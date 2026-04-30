"""Roteamento de comandos do Telegram (/init, /stop, /status).

Recebe um update completo (formato JSON do Telegram) e devolve
uma CommandResponse (ou None se não há resposta a dar).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from .subscriber_store import SubscriberStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandResponse:
    chat_id: int
    text: str  # plain text — sem MarkdownV2


StatusProvider = Callable[[], dict]


class CommandHandler:
    def __init__(self, store: SubscriberStore, *, status_provider: StatusProvider) -> None:
        self._store = store
        self._status_provider = status_provider

    def handle_update(self, update: dict) -> CommandResponse | None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = (message.get("text") or "").strip()

        if chat_id is None or not text:
            return None

        chat_id_int = int(chat_id)
        # Telegram em grupos manda /comando@nome_bot — pegar só o comando
        cmd = text.split()[0].split("@", 1)[0].lower()

        if cmd == "/init":
            return self._cmd_init(chat_id_int)
        if cmd == "/stop":
            return self._cmd_stop(chat_id_int)
        if cmd == "/status":
            return self._cmd_status(chat_id_int)
        if text.startswith("/"):
            # comando desconhecido — responde com ajuda
            return CommandResponse(
                chat_id_int,
                "Não reconheço esse comando. Use /init, /stop ou /status.",
            )
        # mensagem comum — silêncio
        return None

    def _cmd_init(self, chat_id: int) -> CommandResponse:
        was_new = self._store.add(chat_id)
        if was_new:
            logger.info("subscribe chat_id=***%s", str(chat_id)[-2:])
            return CommandResponse(
                chat_id,
                "✅ Monitoramento iniciado.\n"
                "Verifico Goiânia a cada 5min e te aviso quando aparecer vaga.\n"
                "Mande /stop para pausar.",
            )
        return CommandResponse(
            chat_id,
            "🔄 Você já estava com monitoramento ativo. Tudo certo, fique tranquilo.",
        )

    def _cmd_stop(self, chat_id: int) -> CommandResponse:
        was_present = self._store.remove(chat_id)
        if was_present:
            logger.info("unsubscribe chat_id=***%s", str(chat_id)[-2:])
            return CommandResponse(
                chat_id,
                "⏸ Pausado. Mande /init quando quiser voltar a monitorar.",
            )
        return CommandResponse(
            chat_id,
            "Você não estava monitorando. Mande /init para começar.",
        )

    def _cmd_status(self, chat_id: int) -> CommandResponse:
        snap = self._status_provider()
        n = len(self._store.all())
        if n == 0:
            text = "⚪ Idle — sem subscribers ativos.\nMande /init para começar."
        else:
            last = snap.get("last_check_at") or "(ainda não)"
            unidades = snap.get("unidades_com_vagas", 0)
            polls = snap.get("total_polls", 0)
            text = (
                f"🟢 Ativo — {n} subscriber(s)\n"
                f"Última verificação: {last}\n"
                f"Unidades com vagas: {unidades}\n"
                f"Total de polls: {polls}"
            )
        return CommandResponse(chat_id, text)
