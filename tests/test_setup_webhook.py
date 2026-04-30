"""Testes do subcomando `setup-webhook`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import responses

from bot.__main__ import cmd_setup_webhook
from bot.config import Settings


def make_settings(token: str = "TOKEN_TESTE", secret: str = "the-secret") -> Settings:
    return Settings(
        telegram_bot_token=token, telegram_chat_id="",
        poll_interval_seconds=300, jitter_seconds=30,
        cod_municipio=25300, id_senha=58, log_level="INFO",
        goias_oauth_basic="b", goias_referer="r",
        webhook_port=8080, webhook_path="/telegram/webhook",
        webhook_secret_token=secret,
        verbose_polls=False,
    )


@responses.activate
def test_setup_webhook_calls_telegram_api(capsys):
    settings = make_settings()
    responses.post(
        "https://api.telegram.org/botTOKEN_TESTE/setWebhook",
        json={"ok": True, "result": True, "description": "Webhook was set"},
    )
    rc = cmd_setup_webhook(settings, url="https://abc.trycloudflare.com", delete=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "configurado" in out.lower() or "webhook was set" in out.lower()
    req = responses.calls[0].request
    import json
    payload = json.loads(req.body)
    assert payload["url"] == "https://abc.trycloudflare.com/telegram/webhook"
    assert payload["secret_token"] == "the-secret"


@responses.activate
def test_setup_webhook_delete(capsys):
    settings = make_settings()
    responses.post(
        "https://api.telegram.org/botTOKEN_TESTE/deleteWebhook",
        json={"ok": True, "result": True},
    )
    rc = cmd_setup_webhook(settings, url=None, delete=True)
    assert rc == 0


@responses.activate
def test_setup_webhook_failure_returns_1(capsys):
    settings = make_settings()
    responses.post(
        "https://api.telegram.org/botTOKEN_TESTE/setWebhook",
        json={"ok": False, "description": "Bad webhook URL"},
        status=400,
    )
    rc = cmd_setup_webhook(settings, url="https://bad", delete=False)
    assert rc == 1


def test_setup_webhook_generates_secret_if_empty(tmp_path, monkeypatch):
    """Se webhook_secret_token vazio, gera um e persiste no .env."""
    from bot.__main__ import _ensure_secret_token

    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=t\n")
    monkeypatch.setattr("bot.__main__.ENV_PATH", env)

    secret = _ensure_secret_token("")
    assert len(secret) >= 32
    assert "WEBHOOK_SECRET_TOKEN=" in env.read_text()
    assert secret in env.read_text()


def test_setup_webhook_keeps_secret_if_set(tmp_path, monkeypatch):
    from bot.__main__ import _ensure_secret_token
    secret = _ensure_secret_token("preexisting-secret-12345")
    assert secret == "preexisting-secret-12345"
