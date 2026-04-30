"""Comandos do bot: /init, /stop, /status + callback queries dos botões.

Cada update do Telegram (mensagem ou callback de botão) é despachado em
`handle_update`, que devolve uma lista de `TelegramAction` — descrições
declarativas do que enviar/editar/responder. Quem realmente bate na API é o
caller (cmd_serve), o que mantém o handler puro e testável.

Wizard de seleção de municípios:
  - O `/init` carrega a seleção atual do chat para uma área de "rascunho"
    em memória (`_pending`).
  - Cada toque em município mexe SÓ no rascunho (não persiste no store).
  - Só ao clicar "Pronto" o rascunho é gravado no SubscriberStore e o
    monitoramento começa de fato.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from .subscriber_store import SubscriberStore

logger = logging.getLogger(__name__)


# Municípios oferecidos no menu de /init. Tupla: (codigo, nome_exibicao).
# O nome_exibicao é encurtado quando muito longo, pra caber bem em 2 colunas.
MUNICIPIOS_OFERECIDOS: tuple[tuple[int, str], ...] = (
    (25300, "GOIÂNIA"),
    (33800, "AP. GOIÂNIA"),
    (23500, "ANÁPOLIS"),
    (23600, "ANICUNS"),
    (28800, "TRINDADE"),
    (34000, "BELA VISTA"),
    (19500, "LUZIÂNIA"),
    (32800, "RIO VERDE"),
    (32500, "JATAÍ"),
    (148400, "VALPARAÍSO"),
    (19400, "FORMOSA"),
)

# Quantas colunas no inline keyboard.
KEYBOARD_COLS = 2

PROMPT_TEXT = (
    "🎯 Selecione os municípios que quer monitorar.\n"
    "Toque para marcar/desmarcar. Quando terminar, toque em ✅ Pronto."
)


@dataclass(frozen=True)
class TelegramAction:
    """Ação a executar no Telegram. kind = send | edit | answer_callback."""

    kind: str
    chat_id: int = 0
    text: str = ""
    reply_markup: dict | None = None
    message_id: int | None = None
    callback_query_id: str = ""


StatusProvider = Callable[[], dict]


def _build_keyboard(selected: set[int]) -> dict:
    """Monta inline_keyboard em N colunas. Marcados ganham ✅."""
    rows: list[list[dict]] = []
    line: list[dict] = []
    for cod, nome in MUNICIPIOS_OFERECIDOS:
        prefix = "✅" if cod in selected else "⬜️"
        line.append(
            {
                "text": f"{prefix} {nome}",
                "callback_data": f"tog:{cod}",
            }
        )
        if len(line) == KEYBOARD_COLS:
            rows.append(line)
            line = []
    if line:
        rows.append(line)
    rows.append([{"text": "✅ Pronto", "callback_data": "done"}])
    return {"inline_keyboard": rows}


def _build_paused_keyboard() -> dict:
    """Botão único 'Pausar' que aparece após o monitoramento iniciar."""
    return {
        "inline_keyboard": [
            [{"text": "⏸ Pausar", "callback_data": "pause"}],
        ]
    }


class CommandHandler:
    def __init__(self, store: SubscriberStore, *, status_provider: StatusProvider) -> None:
        self._store = store
        self._status_provider = status_provider
        # Estado em memória do wizard. chat_id → set[cod_municipio] em rascunho.
        # Reinício do bot perde esses rascunhos (só perde quem está no meio do wizard).
        self._pending: dict[int, set[int]] = {}

    def handle_update(self, update: dict) -> list[TelegramAction]:
        """Despacha update do Telegram. Retorna lista de ações (pode ser vazia)."""
        if "callback_query" in update:
            return self._handle_callback(update["callback_query"])
        msg = update.get("message")
        if msg:
            return self._handle_message(msg)
        return []

    # --- mensagens (/init, /stop, /status) -----------------------------------

    def _handle_message(self, msg: dict) -> list[TelegramAction]:
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        text = (msg.get("text") or "").strip()
        if chat_id is None or not text:
            return []
        chat_id_int = int(chat_id)
        cmd = text.split()[0].split("@", 1)[0].lower()
        if cmd == "/init":
            return self._cmd_init(chat_id_int)
        if cmd == "/stop":
            return self._cmd_stop(chat_id_int)
        if cmd == "/status":
            return self._cmd_status(chat_id_int)
        if text.startswith("/"):
            return [
                TelegramAction(
                    kind="send",
                    chat_id=chat_id_int,
                    text="Não reconheço esse comando. Use /init, /stop ou /status.",
                )
            ]
        return []

    def _cmd_init(self, chat_id: int) -> list[TelegramAction]:
        # Rascunho do wizard: começa com a seleção atual (vazio se chat novo).
        self._pending[chat_id] = set(self._store.municipios_de(chat_id))
        logger.info(
            "init chat_id=***%s rascunho=%d",
            str(chat_id)[-2:],
            len(self._pending[chat_id]),
        )
        return [
            TelegramAction(
                kind="send",
                chat_id=chat_id,
                text=PROMPT_TEXT,
                reply_markup=_build_keyboard(self._pending[chat_id]),
            )
        ]

    def _cmd_stop(self, chat_id: int) -> list[TelegramAction]:
        self._pending.pop(chat_id, None)
        was = self._store.remove_chat(chat_id)
        text = (
            "⏸ Pausado. Mande /init quando quiser voltar a monitorar."
            if was
            else "Você não estava monitorando. Mande /init para começar."
        )
        return [TelegramAction(kind="send", chat_id=chat_id, text=text)]

    def _cmd_status(self, chat_id: int) -> list[TelegramAction]:
        snap = self._status_provider()
        n_chats = len(self._store.all_chats())
        meus = self._store.municipios_de(chat_id)
        if n_chats == 0:
            text = "⚪ Idle — sem subscribers ativos.\nMande /init para começar."
        else:
            text = f"🟢 Ativo — {n_chats} chat(s)\n"
            text += f"Seus municípios: {len(meus)}\n"
            if meus:
                from .municipios import por_codigo

                nomes = sorted(
                    por_codigo(c).nome if por_codigo(c) else str(c) for c in meus
                )
                for nome in nomes:
                    text += f"  • {nome}\n"
            text += f"Última verificação: {snap.get('last_check_at') or '(ainda não)'}"
        return [TelegramAction(kind="send", chat_id=chat_id, text=text)]

    # --- callback queries (cliques nos botões) -------------------------------

    def _handle_callback(self, cb: dict) -> list[TelegramAction]:
        cb_id = cb.get("id", "")
        data = cb.get("data", "")
        msg = cb.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = int(chat.get("id", 0))
        message_id = msg.get("message_id")
        actions: list[TelegramAction] = []

        if data.startswith("tog:"):
            return self._cb_toggle(chat_id, cb_id, message_id, data)
        if data == "done":
            return self._cb_done(chat_id, cb_id, message_id)
        if data == "pause":
            return self._cb_pause(chat_id, cb_id, message_id)

        actions.append(
            TelegramAction(
                kind="answer_callback",
                callback_query_id=cb_id,
                text="Comando desconhecido",
            )
        )
        return actions

    def _cb_toggle(
        self, chat_id: int, cb_id: str, message_id: int | None, data: str
    ) -> list[TelegramAction]:
        try:
            cod = int(data.split(":", 1)[1])
        except ValueError:
            return [
                TelegramAction(
                    kind="answer_callback",
                    callback_query_id=cb_id,
                    text="Código inválido",
                )
            ]

        # Garante que o rascunho existe (caso o user clique sem ter dado /init,
        # ex: depois de um restart do bot que perdeu o pending).
        rascunho = self._pending.setdefault(
            chat_id, set(self._store.municipios_de(chat_id))
        )

        if cod in rascunho:
            rascunho.discard(cod)
            ack = "⬜️ removido"
        else:
            rascunho.add(cod)
            ack = "✅ adicionado"

        return [
            TelegramAction(
                kind="answer_callback",
                callback_query_id=cb_id,
                text=ack,
            ),
            TelegramAction(
                kind="edit",
                chat_id=chat_id,
                message_id=message_id,
                text=PROMPT_TEXT,
                reply_markup=_build_keyboard(rascunho),
            ),
        ]

    def _cb_done(
        self, chat_id: int, cb_id: str, message_id: int | None
    ) -> list[TelegramAction]:
        rascunho = self._pending.get(chat_id, set())
        if not rascunho:
            return [
                TelegramAction(
                    kind="answer_callback",
                    callback_query_id=cb_id,
                    text="Selecione ao menos 1 município",
                )
            ]

        # Aplica o rascunho: sincroniza o store com o que foi selecionado.
        self._sync_store(chat_id, rascunho)
        self._pending.pop(chat_id, None)

        # Salva o message_id como dashboard editável: todos os updates futuros
        # vão editar essa mesma mensagem em vez de criar mensagens novas.
        if message_id is not None:
            self._store.set_dashboard_msg_id(chat_id, message_id)

        from .municipios import por_codigo

        nomes = sorted(
            por_codigo(c).nome if por_codigo(c) else str(c) for c in rascunho
        )
        confirmation = "✅ Monitoramento iniciado para:\n"
        for nome in nomes:
            confirmation += f"  • {nome}\n"
        confirmation += (
            "\nAguardando primeira verificação..."
        )

        logger.info(
            "done chat_id=***%s municipios=%d",
            str(chat_id)[-2:],
            len(rascunho),
        )

        return [
            TelegramAction(
                kind="answer_callback",
                callback_query_id=cb_id,
                text=f"{len(rascunho)} município(s) ativos",
            ),
            TelegramAction(
                kind="edit",
                chat_id=chat_id,
                message_id=message_id,
                text=confirmation,
                reply_markup=_build_paused_keyboard(),
            ),
        ]

    def _cb_pause(
        self, chat_id: int, cb_id: str, message_id: int | None
    ) -> list[TelegramAction]:
        self._pending.pop(chat_id, None)
        had = self._store.remove_chat(chat_id)
        logger.info("pause chat_id=***%s had=%s", str(chat_id)[-2:], had)
        text = (
            "⏸ Pausado. Mande /init quando quiser voltar a monitorar."
            if had
            else "Você já estava pausado. Mande /init para começar."
        )
        return [
            TelegramAction(
                kind="answer_callback",
                callback_query_id=cb_id,
                text="Pausado",
            ),
            TelegramAction(
                kind="edit",
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=None,
            ),
        ]

    def _sync_store(self, chat_id: int, alvo: set[int]) -> None:
        """Faz o store refletir exatamente `alvo` para o chat dado."""
        self._store.add_chat(chat_id)
        atual = self._store.municipios_de(chat_id)
        for cod in atual - alvo:
            self._store.remove_municipio(chat_id, cod)
        for cod in alvo - atual:
            self._store.add_municipio(chat_id, cod)
