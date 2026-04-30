"""Testes do CommandHandler — roteamento de /init, /stop, /status + callback queries."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.command_handler import CommandHandler, TelegramAction
from bot.subscriber_store import SubscriberStore


@pytest.fixture
def store(tmp_path: Path) -> SubscriberStore:
    return SubscriberStore(tmp_path / "subs.json")


def make_update(text: str, chat_id: int = 111, update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": chat_id},
            "text": text,
        },
    }


def make_callback(
    data: str,
    *,
    chat_id: int = 111,
    message_id: int = 42,
    cb_id: str = "cb-1",
) -> dict:
    return {
        "update_id": 1,
        "callback_query": {
            "id": cb_id,
            "data": data,
            "message": {
                "message_id": message_id,
                "chat": {"id": chat_id},
            },
        },
    }


def stub_status() -> dict:
    return {"last_check_at": None, "unidades_com_vagas": 0, "total_polls": 0}


def _first(actions: list[TelegramAction]) -> TelegramAction:
    assert actions, "esperado >=1 ação"
    return actions[0]


def test_init_first_time_envia_keyboard(store):
    """/init NÃO adiciona ao store ainda — só abre o wizard com rascunho vazio."""
    handler = CommandHandler(store, status_provider=stub_status)
    actions = handler.handle_update(make_update("/init"))
    assert len(actions) == 1
    a = actions[0]
    assert a.kind == "send"
    assert a.chat_id == 111
    assert "selecione" in a.text.lower()
    assert a.reply_markup is not None
    assert "inline_keyboard" in a.reply_markup
    assert not store.has_chat(111), "store só é tocado depois do clique em Pronto"


def test_init_duplicate_reabre_wizard(store):
    """/init de novo reabre o wizard — independente de já estar no store ou não."""
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init"))
    actions = handler.handle_update(make_update("/init"))
    a = _first(actions)
    assert a.kind == "send"
    assert "selecione" in a.text.lower()


def test_stop_quando_chat_estava_no_store(store):
    """Após wizard completo, /stop remove o chat do store."""
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init"))
    handler.handle_update(make_callback("tog:25300"))
    handler.handle_update(make_callback("done"))
    assert store.has_chat(111)

    actions = handler.handle_update(make_update("/stop"))
    a = _first(actions)
    assert a.kind == "send"
    assert "pausado" in a.text.lower() or "pausei" in a.text.lower()
    assert not store.has_chat(111)


def test_stop_when_not_subscribed(store):
    handler = CommandHandler(store, status_provider=stub_status)
    actions = handler.handle_update(make_update("/stop"))
    a = _first(actions)
    assert "não estava" in a.text.lower() or "nao estava" in a.text.lower()
    assert not store.has_chat(111)


def test_status_idle(store):
    handler = CommandHandler(store, status_provider=stub_status)
    actions = handler.handle_update(make_update("/status"))
    a = _first(actions)
    assert "idle" in a.text.lower() or "sem subscribers" in a.text.lower()


def test_status_active(store):
    """Status ativo só após chat completar wizard (Pronto)."""
    handler = CommandHandler(store, status_provider=stub_status)
    for cid in (111, 222):
        handler.handle_update(make_update("/init", chat_id=cid))
        handler.handle_update(make_callback("tog:25300", chat_id=cid))
        handler.handle_update(make_callback("done", chat_id=cid))
    actions = handler.handle_update(make_update("/status"))
    a = _first(actions)
    assert "ativo" in a.text.lower()
    assert "2" in a.text


def test_unknown_command_responde(store):
    handler = CommandHandler(store, status_provider=stub_status)
    actions = handler.handle_update(make_update("/foo"))
    if actions:
        a = actions[0]
        assert (
            "não reconheço" in a.text.lower()
            or "comandos" in a.text.lower()
            or "/init" in a.text.lower()
        )


def test_non_command_message_silencioso(store):
    handler = CommandHandler(store, status_provider=stub_status)
    actions = handler.handle_update(make_update("oi tudo bem"))
    assert actions == []


def test_update_sem_message_silencioso(store):
    handler = CommandHandler(store, status_provider=stub_status)
    actions = handler.handle_update({"update_id": 1})
    assert actions == []


def test_command_with_bot_mention_works(store):
    handler = CommandHandler(store, status_provider=stub_status)
    actions = handler.handle_update(make_update("/init@cin_agendamento_expresso_bot"))
    a = _first(actions)
    assert a.kind == "send"
    assert "selecione" in a.text.lower()


# --- Callback queries (botões) -----------------------------------------------


def test_callback_toggle_nao_persiste_ate_done(store):
    """Toggle só altera o rascunho — o store é tocado apenas em 'done'."""
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init"))
    actions = handler.handle_update(make_callback("tog:25300"))
    kinds = [a.kind for a in actions]
    assert "answer_callback" in kinds
    assert "edit" in kinds
    assert not store.has_chat(111), "store ainda intacto antes de Pronto"


def test_callback_toggle_alterna_marcacao_no_keyboard(store):
    """2 cliques no mesmo botão deixam o rascunho vazio (toggle)."""
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init"))
    handler.handle_update(make_callback("tog:25300"))
    actions = handler.handle_update(make_callback("tog:25300"))
    edit = next(a for a in actions if a.kind == "edit")
    rendered = edit.reply_markup["inline_keyboard"]
    flat = [btn["text"] for row in rendered for btn in row]
    # nenhuma linha do município escolhido deve estar marcada (✅) já que voltou pra ⬜️
    assert any("⬜️" in t and "GOIÂNIA" in t for t in flat)
    assert not store.has_chat(111)


def test_callback_done_sem_selecao_alerta(store):
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init"))
    actions = handler.handle_update(make_callback("done"))
    assert len(actions) == 1
    a = actions[0]
    assert a.kind == "answer_callback"
    assert "selecione" in a.text.lower() or "ao menos" in a.text.lower()


def test_callback_done_com_selecao_persiste_e_oferece_pausar(store):
    """Done aplica o rascunho ao store e edita pra mensagem com botão Pausar."""
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init"))
    handler.handle_update(make_callback("tog:25300"))
    actions = handler.handle_update(make_callback("done"))
    kinds = [a.kind for a in actions]
    assert "answer_callback" in kinds
    assert "edit" in kinds
    edit = next(a for a in actions if a.kind == "edit")
    assert "monitoramento iniciado" in edit.text.lower() or "iniciado" in edit.text.lower()
    assert edit.reply_markup is not None
    btns = edit.reply_markup["inline_keyboard"]
    flat = [b for row in btns for b in row]
    assert any(b["callback_data"] == "pause" for b in flat)
    # Estado persistido
    assert store.has_chat(111)
    assert 25300 in store.municipios_de(111)


def test_callback_pause_remove_chat(store):
    """Clique em 'Pausar' remove o chat do store."""
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init"))
    handler.handle_update(make_callback("tog:25300"))
    handler.handle_update(make_callback("done"))
    assert store.has_chat(111)
    actions = handler.handle_update(make_callback("pause"))
    kinds = [a.kind for a in actions]
    assert "answer_callback" in kinds
    assert "edit" in kinds
    assert not store.has_chat(111)


def test_callback_data_invalido_retorna_msg_amigavel(store):
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init"))
    actions = handler.handle_update(make_callback("tog:abc"))
    assert any(a.kind == "answer_callback" for a in actions)


def test_callback_desconhecido_responde(store):
    handler = CommandHandler(store, status_provider=stub_status)
    actions = handler.handle_update(make_callback("foo:bar"))
    assert any(a.kind == "answer_callback" for a in actions)
