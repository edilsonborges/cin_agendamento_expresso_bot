"""Configuração de logging estruturado.

Formato fixo, fácil de grep:
    2026-04-29T21:30:00 [INFO] [poll] municipio=25300 datas=0 acao=noop

Stdout sempre ativo (para journalctl/launchd) + arquivo rotativo `bot.log` (10MB x 3).
Tokens Bearer e Telegram são mascarados via filtro defensivo — nunca logamos cred completa.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_BEARER_PATTERN = re.compile(r"(Bearer\s+)([A-Za-z0-9\-_.]+)")
_BOT_TOKEN_PATTERN = re.compile(r"\b(\d{8,12}:[A-Za-z0-9_-]{30,})\b")


def _mask(token: str) -> str:
    if len(token) <= 24:
        return token[:4] + "…"
    return token[:20] + "…(masked)"


class TokenMaskFilter(logging.Filter):
    """Mascara qualquer token Bearer/Telegram que possa aparecer no log."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "Bearer " in msg:
            msg = _BEARER_PATTERN.sub(lambda m: m.group(1) + _mask(m.group(2)), msg)
        if ":" in msg:
            msg = _BOT_TOKEN_PATTERN.sub(lambda m: _mask(m.group(1)), msg)
        record.msg = msg
        record.args = ()
        return True


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> logging.Logger:
    """Configura root logger. Idempotente — chamadas repetidas não duplicam handlers."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    mask = TokenMaskFilter()

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(formatter)
    stdout.addFilter(mask)
    root.addHandler(stdout)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        rot = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        rot.setFormatter(formatter)
        rot.addFilter(mask)
        root.addHandler(rot)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    return root
