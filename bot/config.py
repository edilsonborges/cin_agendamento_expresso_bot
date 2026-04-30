"""Configuração lida via dotenv.

Variáveis obrigatórias para `run`/`init`: TELEGRAM_BOT_TOKEN, GOIAS_OAUTH_BASIC, GOIAS_REFERER.
TELEGRAM_CHAT_ID é obrigatória só no `run` — `init` é justamente quem descobre.
Para `check` (smoke test dry-run), basta GOIAS_OAUTH_BASIC e GOIAS_REFERER.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

DEFAULT_POLL_INTERVAL = 300
DEFAULT_JITTER = 30
DEFAULT_COD_MUNICIPIO = 25300
DEFAULT_ID_SENHA = 58
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_REFERER = (
    "https://www.go.gov.br/servicos-digitais/vapt-vupt/"
    "agendamento-atendimento-presencial/novo/origem-rg"
)
DEFAULT_WEBHOOK_PORT = 8080
DEFAULT_WEBHOOK_PATH = "/telegram/webhook"


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    poll_interval_seconds: int
    jitter_seconds: int
    cod_municipio: int
    id_senha: int
    log_level: str
    goias_oauth_basic: str
    goias_referer: str
    webhook_port: int
    webhook_path: str
    webhook_secret_token: str
    verbose_polls: bool

    @property
    def has_chat_id(self) -> bool:
        return bool(self.telegram_chat_id.strip())

    @property
    def chat_id_int(self) -> int:
        return int(self.telegram_chat_id)


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Variável {name} deve ser inteiro, recebido: {raw!r}") from exc


def load_settings(env_path: Path | None = None) -> Settings:
    """Carrega `.env` (se existir) e devolve Settings.

    Validação adiada: o caller decide quais campos são obrigatórios para o seu uso.
    """
    target = env_path or ENV_PATH
    if target.exists():
        load_dotenv(target, override=False)

    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        poll_interval_seconds=_get_int("POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL),
        jitter_seconds=_get_int("JITTER_SECONDS", DEFAULT_JITTER),
        cod_municipio=_get_int("COD_MUNICIPIO", DEFAULT_COD_MUNICIPIO),
        id_senha=_get_int("ID_SENHA", DEFAULT_ID_SENHA),
        log_level=os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper(),
        goias_oauth_basic=os.getenv("GOIAS_OAUTH_BASIC", "").strip(),
        goias_referer=os.getenv("GOIAS_REFERER", DEFAULT_REFERER).strip(),
        webhook_port=_get_int("WEBHOOK_PORT", DEFAULT_WEBHOOK_PORT),
        webhook_path=os.getenv("WEBHOOK_PATH", DEFAULT_WEBHOOK_PATH).strip(),
        webhook_secret_token=os.getenv("WEBHOOK_SECRET_TOKEN", "").strip(),
        verbose_polls=os.getenv("VERBOSE_POLLS", "").strip().lower() in ("1", "true", "yes"),
    )


def require_goias(settings: Settings) -> None:
    if not settings.goias_oauth_basic:
        raise RuntimeError("GOIAS_OAUTH_BASIC ausente. Capture do front-end e cole no .env.")
    if not settings.goias_referer:
        raise RuntimeError("GOIAS_REFERER ausente. Use o default do .env.example.")


def require_telegram(settings: Settings, *, need_chat_id: bool) -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ausente. Obtenha em @BotFather.")
    if need_chat_id and not settings.has_chat_id:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID ausente. Rode `python -m bot init` e mande /start no Telegram."
        )
