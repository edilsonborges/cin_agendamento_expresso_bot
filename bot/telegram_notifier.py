r"""Notificador via Telegram Bot API (sendMessage / getUpdates).

Usa `requests` direto — basta um POST para enviar e um GET para descobrir chat_id.
Nada de async/framework.

Formatação MarkdownV2: caracteres _*[]()~`>#+-=|{}.! precisam de escape com \.
Erros de rede são logados e retornados — `False` indica falha, mas NÃO levanta
para não derrubar o loop principal (FR-12 / US-005).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import requests

from .change_detector import Diff

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
PORTAL_LINK = (
    "https://www.go.gov.br/servicos-digitais/vapt-vupt/"
    "agendamento-atendimento-presencial/novo/origem-rg"
)
MAX_DATAS_INLINE = 5

_MD_V2_SPECIALS = r"_*[]()~`>#+-=|{}.!\\"


def escape_md_v2(text: str) -> str:
    out = []
    for ch in text:
        if ch in _MD_V2_SPECIALS:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_id: int | str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._timeout = timeout
        self._session = session or requests.Session()

    @property
    def base_url(self) -> str:
        return f"{API_BASE}/bot{self._token}"

    def send_text(self, text: str, *, parse_mode: str = "MarkdownV2") -> bool:
        """Envia mensagem com retry. Devolve True se entregue, False caso falhe."""
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        backoff = 2.0
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._session.post(
                    f"{self.base_url}/sendMessage", json=payload, timeout=self._timeout
                )
            except requests.RequestException as exc:
                logger.warning("telegram tentativa=%d falha-rede=%s", attempt, exc)
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                retry_after = self._retry_after(resp)
                logger.warning("telegram 429 retry_after=%ds", retry_after)
                time.sleep(retry_after)
                continue
            if resp.status_code >= 500:
                logger.warning(
                    "telegram tentativa=%d 5xx=%d body=%s",
                    attempt,
                    resp.status_code,
                    resp.text[:200],
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            logger.error(
                "telegram 4xx status=%d body=%s — abortando", resp.status_code, resp.text[:200]
            )
            return False

        logger.error("telegram esgotou %d tentativas", MAX_RETRIES)
        return False

    @staticmethod
    def _retry_after(resp: requests.Response) -> int:
        try:
            return int(resp.json().get("parameters", {}).get("retry_after", 5))
        except (ValueError, AttributeError):
            return 5


def format_message(
    municipio_nome: str,
    diff: Diff,
    *,
    is_first_open: bool,
    detected_at: datetime | None = None,
) -> str:
    """Monta MarkdownV2 — `is_first_open=True` quando saímos de vazio para com vagas."""
    detected_at = detected_at or datetime.now().astimezone()
    title = (
        f"🚨 *Vagas CIN abertas em {escape_md_v2(municipio_nome.upper())}*"
        if is_first_open
        else f"✨ *Novas datas CIN em {escape_md_v2(municipio_nome.upper())}*"
    )
    lines = [title, ""]

    for unidade in sorted(diff.novas_datas_por_unidade.keys()):
        novas = diff.novas_datas_por_unidade[unidade]
        total = diff.total_atual_por_unidade.get(unidade, len(novas))
        nome_esc = escape_md_v2(unidade)

        if is_first_open:
            lines.append(f"📍 *{nome_esc}* — {total} datas")
            mostradas = novas[:MAX_DATAS_INLINE]
            for d in mostradas:
                lines.append(f"   • {escape_md_v2(d)}")
            if len(novas) > MAX_DATAS_INLINE:
                restante = len(novas) - MAX_DATAS_INLINE
                lines.append(escape_md_v2(f"   ...e mais {restante} datas"))
        else:
            lines.append(f"📍 *{nome_esc}*")
            datas_str = ", ".join(novas[:MAX_DATAS_INLINE])
            if len(novas) > MAX_DATAS_INLINE:
                datas_str += f" (+{len(novas) - MAX_DATAS_INLINE})"
            lines.append(f"   *Novas:* {escape_md_v2(datas_str)}")
            lines.append(f"   *Total atual:* {total} datas")
        lines.append("")

    portal_label = escape_md_v2("Agendar agora")
    portal_url = PORTAL_LINK
    lines.append(f"🔗 [{portal_label}]({portal_url})")

    ts = detected_at.strftime("%d/%m/%Y %H:%M")
    lines.append(f"🕐 _detectado em {escape_md_v2(ts)}_")

    return "\n".join(lines)


class TelegramInit:
    """Modo `init` — descobre chat_id via getUpdates."""

    def __init__(
        self,
        token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        self._token = token
        self._timeout = timeout
        self._session = session or requests.Session()

    @property
    def base_url(self) -> str:
        return f"{API_BASE}/bot{self._token}"

    def get_updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": 0}
        if offset is not None:
            params["offset"] = offset
        resp = self._session.get(
            f"{self.base_url}/getUpdates", params=params, timeout=self._timeout
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates falhou: {data}")
        return list(data.get("result", []))

    def reply(self, chat_id: int, text: str) -> None:
        try:
            self._session.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logger.warning("init reply falhou: %s", exc)
