"""Integração: sobe servidor real, manda POST simulando Telegram, verifica side effects."""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest
import requests

from bot.command_handler import CommandHandler
from bot.subscriber_store import SubscriberStore
from bot.telegram_notifier import TelegramNotifier
from bot.webhook_server import WebhookServer


SECRET = "integration-secret"


@pytest.fixture
def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_init_then_stop_via_webhook_persists(tmp_path: Path, free_port: int):
    """POST /init → /stop pelo webhook deve atualizar subscribers.json."""
    subs_path = tmp_path / "subs.json"
    store = SubscriberStore(subs_path)
    handler = CommandHandler(store, status_provider=lambda: {})

    responses_log: list = []

    srv = WebhookServer(
        host="127.0.0.1",
        port=free_port,
        secret_token=SECRET,
        webhook_path="/telegram/webhook",
        command_handler=handler,
        on_command_response=lambda r: responses_log.append(r),
    )

    stop_evt = threading.Event()

    def loop():
        while not stop_evt.is_set():
            srv.handle_request_nonblocking()

    t = threading.Thread(target=loop, daemon=True)
    t.start()

    try:
        url = f"http://127.0.0.1:{free_port}/telegram/webhook"
        h = {"X-Telegram-Bot-Api-Secret-Token": SECRET}

        # /init de chat 555
        r1 = requests.post(
            url,
            json={"update_id": 1, "message": {"chat": {"id": 555}, "text": "/init"}},
            headers=h, timeout=2,
        )
        assert r1.status_code == 200

        for _ in range(20):
            if responses_log:
                break
            time.sleep(0.05)
        assert any(r.chat_id == 555 and "iniciado" in r.text.lower() for r in responses_log)

        data = json.loads(subs_path.read_text())
        assert 555 in data["subscribers"]

        # /stop de chat 555
        r2 = requests.post(
            url,
            json={"update_id": 2, "message": {"chat": {"id": 555}, "text": "/stop"}},
            headers=h, timeout=2,
        )
        assert r2.status_code == 200
        for _ in range(20):
            if len(responses_log) >= 2:
                break
            time.sleep(0.05)

        data = json.loads(subs_path.read_text())
        assert data["subscribers"] == []
    finally:
        stop_evt.set()
        srv.close()
        t.join(timeout=2)
