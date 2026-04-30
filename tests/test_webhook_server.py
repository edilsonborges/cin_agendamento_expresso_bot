"""Testes do WebhookServer — servidor HTTP single-thread, secret token, roteamento."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from typing import Iterator

import pytest
import requests

from bot.command_handler import CommandHandler, CommandResponse
from bot.subscriber_store import SubscriberStore
from bot.webhook_server import WebhookServer


SECRET = "test-secret-token"


@pytest.fixture
def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def handler(tmp_path: Path) -> CommandHandler:
    store = SubscriberStore(tmp_path / "subs.json")
    return CommandHandler(store, status_provider=lambda: {})


@pytest.fixture
def server(free_port: int, handler: CommandHandler) -> Iterator[WebhookServer]:
    srv = WebhookServer(
        host="127.0.0.1",
        port=free_port,
        secret_token=SECRET,
        webhook_path="/telegram/webhook",
        command_handler=handler,
        on_command_response=lambda resp: None,
    )
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            srv.handle_request_nonblocking()

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    try:
        yield srv
    finally:
        stop.set()
        srv.close()
        t.join(timeout=2)


def url(port: int, path: str = "/telegram/webhook") -> str:
    return f"http://127.0.0.1:{port}{path}"


def test_post_with_valid_secret_returns_200(server, free_port):
    resp = requests.post(
        url(free_port),
        json={"update_id": 1, "message": {"chat": {"id": 111}, "text": "/init"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        timeout=2,
    )
    assert resp.status_code == 200


def test_post_without_secret_returns_401(server, free_port):
    resp = requests.post(
        url(free_port),
        json={"update_id": 1, "message": {"chat": {"id": 111}, "text": "/init"}},
        timeout=2,
    )
    assert resp.status_code == 401


def test_post_wrong_secret_returns_401(server, free_port):
    resp = requests.post(
        url(free_port),
        json={"update_id": 1, "message": {"chat": {"id": 111}, "text": "/init"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        timeout=2,
    )
    assert resp.status_code == 401


def test_get_health_returns_json(server, free_port):
    resp = requests.get(url(free_port, "/health"), timeout=2)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "subscribers" in body


def test_get_unknown_path_returns_404(server, free_port):
    resp = requests.get(url(free_port, "/foo"), timeout=2)
    assert resp.status_code == 404


def test_post_to_health_returns_405(server, free_port):
    resp = requests.post(url(free_port, "/health"), timeout=2)
    assert resp.status_code == 405


def test_get_to_webhook_returns_405(server, free_port):
    resp = requests.get(url(free_port, "/telegram/webhook"), timeout=2)
    assert resp.status_code == 405


def test_post_invalid_json_returns_200_anyway(server, free_port):
    """Telegram retry storm protection: sempre 200 pra POSTs com secret válido."""
    resp = requests.post(
        url(free_port),
        data=b"{ broken",
        headers={
            "X-Telegram-Bot-Api-Secret-Token": SECRET,
            "Content-Type": "application/json",
        },
        timeout=2,
    )
    assert resp.status_code == 200


def test_command_response_callback_invoked(free_port: int, tmp_path: Path):
    """on_command_response recebe a CommandResponse pra envio ao Telegram."""
    store = SubscriberStore(tmp_path / "subs.json")
    cmd_handler = CommandHandler(store, status_provider=lambda: {})

    received: list[CommandResponse] = []

    srv = WebhookServer(
        host="127.0.0.1",
        port=free_port,
        secret_token=SECRET,
        webhook_path="/telegram/webhook",
        command_handler=cmd_handler,
        on_command_response=lambda r: received.append(r),
    )
    stop = threading.Event()
    def loop():
        while not stop.is_set():
            srv.handle_request_nonblocking()
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    try:
        requests.post(
            url(free_port),
            json={"update_id": 1, "message": {"chat": {"id": 111}, "text": "/init"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
            timeout=2,
        )
        import time
        for _ in range(20):
            if received:
                break
            time.sleep(0.05)
    finally:
        stop.set()
        srv.close()
        t.join(timeout=2)

    assert len(received) == 1
    assert received[0].chat_id == 111
    assert "iniciado" in received[0].text.lower()
