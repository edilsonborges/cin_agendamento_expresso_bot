"""Cliente HTTP para Goiás Digital (Vapt Vupt).

Apenas dois endpoints públicos:
  1. POST https://api.go.gov.br/token              (OAuth2 client_credentials)
  2. GET  https://www.go.gov.br/sigac-a-api/agendamento/listarDatasAgendamento

Cache do Bearer em memória (renova quando faltar <120s).
401 → refresh forçado + 1 retry (token pode ter sido revogado server-side).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from .errors import AuthError, PermanentError, TransientError

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.go.gov.br/token"
DATAS_URL = "https://www.go.gov.br/sigac-a-api/agendamento/listarDatasAgendamento"
TOKEN_REFRESH_THRESHOLD_SECONDS = 120
DEFAULT_TIMEOUT = 10.0

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class Unidade:
    """Resultado de uma unidade do Vapt Vupt com vagas para a senha consultada."""

    id_unidade: int
    nome_unidade: str
    id_senha: int
    nome_senha: str
    datas: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Unidade:
        return cls(
            id_unidade=int(raw.get("idUnidade", 0)),
            nome_unidade=str(raw.get("nomeUnidade", "")).strip(),
            id_senha=int(raw.get("idSenha", 0)),
            nome_senha=str(raw.get("nomeSenha", "")).strip(),
            datas=list(raw.get("datas") or []),
        )


class ExpressoClient:
    def __init__(
        self,
        oauth_basic: str,
        referer: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        self._oauth_basic = oauth_basic
        self._referer = referer
        self._timeout = timeout
        self._session = session or requests.Session()
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        """Retorna token válido. Faz refresh se faltar <120s ou se force_refresh=True."""
        now = time.monotonic()
        if (
            not force_refresh
            and self._token
            and (self._expires_at - now) > TOKEN_REFRESH_THRESHOLD_SECONDS
        ):
            return self._token
        return self._refresh_token()

    def _refresh_token(self) -> str:
        headers = {
            "Authorization": f"Basic {self._oauth_basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Referer": "https://www.go.gov.br/",
        }
        try:
            resp = self._session.post(
                TOKEN_URL,
                headers=headers,
                data={"grant_type": "client_credentials"},
                timeout=self._timeout,
            )
        except requests.Timeout as exc:
            raise TransientError(f"Timeout ao obter token: {exc}") from exc
        except requests.RequestException as exc:
            raise TransientError(f"Falha de rede ao obter token: {exc}") from exc

        if resp.status_code in (401, 403):
            raise PermanentError(
                f"OAuth2 rejeitou credenciais (status={resp.status_code}). "
                "Provavelmente o portal renovou o client. Capture novo Basic via DevTools."
            )
        if resp.status_code >= 500:
            raise TransientError(f"Auth server 5xx: {resp.status_code}")
        if resp.status_code >= 400:
            raise PermanentError(f"Auth server 4xx: {resp.status_code} body={resp.text[:200]}")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise PermanentError(f"Auth respondeu não-JSON: {resp.text[:200]}") from exc

        token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 3600))
        if not token:
            raise PermanentError(f"Auth payload sem access_token: {payload}")

        self._token = token
        self._expires_at = time.monotonic() + expires_in
        logger.info("token renovado expires_in=%ds", expires_in)
        return token

    def fetch_datas(self, id_senha: int, cod_municipio: int) -> list[Unidade]:
        """Consulta datas disponíveis. Lista vazia = sem vagas (caso normal)."""
        try:
            return self._fetch_with_token(id_senha, cod_municipio, retry_on_401=True)
        except AuthError:
            logger.warning("auth=401 forcando refresh e retry")
            self.get_access_token(force_refresh=True)
            return self._fetch_with_token(id_senha, cod_municipio, retry_on_401=False)

    def _fetch_with_token(
        self, id_senha: int, cod_municipio: int, *, retry_on_401: bool
    ) -> list[Unidade]:
        token = self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Accept-Language": "pt,en-US;q=0.9,en;q=0.8",
            "User-Agent": USER_AGENT,
            "Referer": self._referer,
        }
        params: dict[str, str | int] = {
            "idSenha": id_senha,
            "status": "D",
            "codgMunicipio": cod_municipio,
        }
        try:
            resp = self._session.get(
                DATAS_URL, headers=headers, params=params, timeout=self._timeout
            )
        except requests.Timeout as exc:
            raise TransientError(f"Timeout em listarDatas: {exc}") from exc
        except requests.RequestException as exc:
            raise TransientError(f"Falha de rede em listarDatas: {exc}") from exc

        if resp.status_code == 401:
            if retry_on_401:
                raise AuthError("Bearer rejeitado (401)")
            raise PermanentError("401 persistente após refresh — credenciais inválidas")
        if resp.status_code >= 500:
            raise TransientError(f"listarDatas 5xx: {resp.status_code}")
        if resp.status_code == 429:
            raise TransientError("listarDatas 429 — rate limit")
        if resp.status_code >= 400:
            raise PermanentError(f"listarDatas 4xx: {resp.status_code} body={resp.text[:200]}")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise PermanentError(f"listarDatas não-JSON: {resp.text[:200]}") from exc

        if not isinstance(payload, list):
            raise PermanentError(f"listarDatas shape inesperado: {type(payload).__name__}")

        return [Unidade.from_api(item) for item in payload if isinstance(item, dict)]
