"""Testes do CommandHandler — roteamento de /init, /stop, /status."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.command_handler import CommandHandler, CommandResponse
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


def stub_status() -> dict:
    return {"last_check_at": None, "unidades_com_vagas": 0, "total_polls": 0}


def test_init_first_time_adds_chat(store):
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update(make_update("/init"))
    assert isinstance(resp, CommandResponse)
    assert resp.chat_id == 111
    assert "iniciado" in resp.text.lower()
    assert store.contains(111)


def test_init_duplicate_keeps_subscribed(store):
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init"))
    resp = handler.handle_update(make_update("/init"))
    assert "já" in resp.text.lower() or "ja " in resp.text.lower()
    assert store.contains(111)


def test_stop_existing_subscriber(store):
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init"))
    resp = handler.handle_update(make_update("/stop"))
    assert "pausado" in resp.text.lower() or "pausei" in resp.text.lower()
    assert not store.contains(111)


def test_stop_when_not_subscribed(store):
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update(make_update("/stop"))
    assert "não estava" in resp.text.lower() or "nao estava" in resp.text.lower()
    assert not store.contains(111)


def test_status_idle(store):
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update(make_update("/status"))
    assert "idle" in resp.text.lower() or "sem subscribers" in resp.text.lower()


def test_status_active(store):
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init", chat_id=111))
    handler.handle_update(make_update("/init", chat_id=222))
    resp = handler.handle_update(make_update("/status"))
    assert "ativo" in resp.text.lower()
    assert "2" in resp.text  # 2 subscribers


def test_unknown_command_ignored(store):
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update(make_update("/foo"))
    assert resp is None or "não reconheço" in resp.text.lower() or "comandos" in resp.text.lower()


def test_non_command_message_ignored(store):
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update(make_update("oi tudo bem"))
    assert resp is None


def test_update_without_message_ignored(store):
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update({"update_id": 1})  # sem "message"
    assert resp is None


def test_command_with_bot_mention_works(store):
    """Telegram envia /init@bot_name em grupos — strip do mention."""
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update(make_update("/init@cin_agendamento_expresso_bot"))
    assert resp is not None
    assert "iniciado" in resp.text.lower()
    assert store.contains(111)
