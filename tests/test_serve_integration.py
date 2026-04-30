"""Integração: sobe servidor real, manda POST simulando Telegram, verifica side effects."""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest
import requests

from bot.command_handler import CommandHandler, TelegramAction
from bot.subscriber_store import SubscriberStore
from bot.webhook_server import WebhookServer


SECRET = "integration-secret"


@pytest.fixture
def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_wizard_completo_via_webhook_persiste(tmp_path: Path, free_port: int):
    """Wizard /init → toggle → done deve persistir chat+município no subscribers.json."""
    subs_path = tmp_path / "subs.json"
    store = SubscriberStore(subs_path)
    handler = CommandHandler(store, status_provider=lambda: {})

    actions_log: list[list[TelegramAction]] = []

    srv = WebhookServer(
        host="127.0.0.1",
        port=free_port,
        secret_token=SECRET,
        webhook_path="/telegram/webhook",
        command_handler=handler,
        on_actions=lambda a: actions_log.append(a),
    )

    stop_evt = threading.Event()

    def loop():
        while not stop_evt.is_set():
            srv.handle_request_nonblocking()

    t = threading.Thread(target=loop, daemon=True)
    t.start()

    def post(body):
        return requests.post(
            f"http://127.0.0.1:{free_port}/telegram/webhook",
            json=body,
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
            timeout=2,
        )

    def wait_actions(min_count: int) -> None:
        for _ in range(40):
            if len(actions_log) >= min_count:
                return
            time.sleep(0.05)

    try:
        # /init
        assert post({
            "update_id": 1,
            "message": {"chat": {"id": 555}, "text": "/init"},
        }).status_code == 200
        wait_actions(1)
        # store ainda intacto após /init (rascunho em memória)
        assert not subs_path.exists() or store.has_chat(555) is False

        # toggle de Goiânia (25300)
        assert post({
            "update_id": 2,
            "callback_query": {
                "id": "cb1",
                "data": "tog:25300",
                "message": {"message_id": 10, "chat": {"id": 555}},
            },
        }).status_code == 200
        wait_actions(2)

        # done — agora persiste
        assert post({
            "update_id": 3,
            "callback_query": {
                "id": "cb2",
                "data": "done",
                "message": {"message_id": 10, "chat": {"id": 555}},
            },
        }).status_code == 200
        wait_actions(3)

        data = json.loads(subs_path.read_text())
        assert "555" in data["subscribers"]
        assert 25300 in data["subscribers"]["555"]["municipios"]

        # pause via callback — limpa o chat
        assert post({
            "update_id": 4,
            "callback_query": {
                "id": "cb3",
                "data": "pause",
                "message": {"message_id": 10, "chat": {"id": 555}},
            },
        }).status_code == 200
        wait_actions(4)

        data = json.loads(subs_path.read_text())
        assert data["subscribers"] == {}
    finally:
        stop_evt.set()
        srv.close()
        t.join(timeout=2)
