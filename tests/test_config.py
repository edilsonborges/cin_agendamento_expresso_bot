"""Testes do config: defaults, valores customizados, validações."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.config import (
    DEFAULT_COD_MUNICIPIO,
    DEFAULT_ID_SENHA,
    DEFAULT_JITTER,
    DEFAULT_POLL_INTERVAL,
    Settings,
    load_settings,
    require_goias,
    require_telegram,
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "POLL_INTERVAL_SECONDS",
        "JITTER_SECONDS",
        "COD_MUNICIPIO",
        "ID_SENHA",
        "LOG_LEVEL",
        "GOIAS_OAUTH_BASIC",
        "GOIAS_REFERER",
        "WEBHOOK_PORT",
        "WEBHOOK_PATH",
        "WEBHOOK_SECRET_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_aplicados(monkeypatch, tmp_path: Path):
    _clear_env(monkeypatch)
    settings = load_settings(tmp_path / "no.env")
    assert settings.poll_interval_seconds == DEFAULT_POLL_INTERVAL
    assert settings.jitter_seconds == DEFAULT_JITTER
    assert settings.cod_municipio == DEFAULT_COD_MUNICIPIO
    assert settings.id_senha == DEFAULT_ID_SENHA
    assert settings.log_level == "INFO"


def test_valores_customizados_via_env(monkeypatch, tmp_path: Path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("COD_MUNICIPIO", "23600")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = load_settings(tmp_path / "no.env")
    assert settings.poll_interval_seconds == 60
    assert settings.cod_municipio == 23600
    assert settings.log_level == "DEBUG"


def test_int_invalido_levanta(monkeypatch, tmp_path: Path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "abc")
    with pytest.raises(ValueError):
        load_settings(tmp_path / "no.env")


def test_require_goias_falha_sem_basic():
    s = Settings(
        telegram_bot_token="x",
        telegram_chat_id="",
        poll_interval_seconds=180,
        jitter_seconds=30,
        cod_municipio=25300,
        id_senha=58,
        log_level="INFO",
        goias_oauth_basic="",
        goias_referer="https://x",
        webhook_port=8080,
        webhook_path="/telegram/webhook",
        webhook_secret_token="",
        verbose_polls=False,
    )
    with pytest.raises(RuntimeError, match="GOIAS_OAUTH_BASIC"):
        require_goias(s)


def test_require_telegram_run_precisa_chat_id():
    s = Settings(
        telegram_bot_token="x",
        telegram_chat_id="",
        poll_interval_seconds=180,
        jitter_seconds=30,
        cod_municipio=25300,
        id_senha=58,
        log_level="INFO",
        goias_oauth_basic="x",
        goias_referer="x",
        webhook_port=8080,
        webhook_path="/telegram/webhook",
        webhook_secret_token="",
        verbose_polls=False,
    )
    with pytest.raises(RuntimeError, match="TELEGRAM_CHAT_ID"):
        require_telegram(s, need_chat_id=True)
    require_telegram(s, need_chat_id=False)


def test_require_telegram_falha_sem_token():
    s = Settings(
        telegram_bot_token="",
        telegram_chat_id="",
        poll_interval_seconds=180,
        jitter_seconds=30,
        cod_municipio=25300,
        id_senha=58,
        log_level="INFO",
        goias_oauth_basic="x",
        goias_referer="x",
        webhook_port=8080,
        webhook_path="/telegram/webhook",
        webhook_secret_token="",
        verbose_polls=False,
    )
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        require_telegram(s, need_chat_id=False)


def test_chat_id_int_converte():
    s = Settings(
        telegram_bot_token="x",
        telegram_chat_id="12345",
        poll_interval_seconds=180,
        jitter_seconds=30,
        cod_municipio=25300,
        id_senha=58,
        log_level="INFO",
        goias_oauth_basic="x",
        goias_referer="x",
        webhook_port=8080,
        webhook_path="/telegram/webhook",
        webhook_secret_token="",
        verbose_polls=False,
    )
    assert s.has_chat_id
    assert s.chat_id_int == 12345


def test_settings_has_webhook_defaults(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setattr("bot.config.ENV_PATH", tmp_path / ".env")
    settings = load_settings()
    assert settings.webhook_port == 8080
    assert settings.webhook_path == "/telegram/webhook"
    assert settings.webhook_secret_token == ""  # vazio = será gerado no boot

def test_settings_reads_webhook_from_env(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    env = tmp_path / ".env"
    env.write_text(
        "WEBHOOK_PORT=9090\n"
        "WEBHOOK_PATH=/hook\n"
        "WEBHOOK_SECRET_TOKEN=abc123\n"
    )
    monkeypatch.setattr("bot.config.ENV_PATH", env)
    settings = load_settings(env)
    assert settings.webhook_port == 9090
    assert settings.webhook_path == "/hook"
    assert settings.webhook_secret_token == "abc123"

def test_settings_poll_interval_default_is_300(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setattr("bot.config.ENV_PATH", tmp_path / ".env")
    settings = load_settings()
    assert settings.poll_interval_seconds == 300
