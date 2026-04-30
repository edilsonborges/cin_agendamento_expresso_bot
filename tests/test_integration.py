"""Testes integrados: Scheduler real + ExpressoClient real + TelegramNotifier real,
com HTTP mockado em ambos os boundaries.

Este nível de teste pega regressões entre módulos — ex: parser do Unidade
quebrar com payload realista, format_message gerar markdown que não chega
limpo, etc. Usa payload de resposta real validado no PRD apêndice A.
"""

from __future__ import annotations

from pathlib import Path

import responses

from bot.config import Settings
from bot.expresso_client import DATAS_URL, TOKEN_URL, ExpressoClient
from bot.scheduler import Scheduler
from bot.state_store import StateStore
from bot.telegram_notifier import API_BASE, TelegramNotifier

TELEGRAM_TOKEN = "111:AAFakeTokenForTests1234567890"
TELEGRAM_CHAT = 12345
TELEGRAM_SEND_URL = f"{API_BASE}/bot{TELEGRAM_TOKEN}/sendMessage"


def _make_settings(cod: int = 25300) -> Settings:
    return Settings(
        telegram_bot_token=TELEGRAM_TOKEN,
        telegram_chat_id=str(TELEGRAM_CHAT),
        poll_interval_seconds=180,
        jitter_seconds=30,
        cod_municipio=cod,
        id_senha=58,
        log_level="INFO",
        goias_oauth_basic="dummy-basic",
        goias_referer="https://www.go.gov.br/x",
    )


def _scheduler(tmp_path: Path, cod: int = 25300) -> Scheduler:
    return Scheduler(
        settings=_make_settings(cod=cod),
        client=ExpressoClient(
            oauth_basic="dummy-basic", referer="https://www.go.gov.br/x", timeout=2.0
        ),
        notifier=TelegramNotifier(TELEGRAM_TOKEN, TELEGRAM_CHAT, timeout=2.0),
        store=StateStore(tmp_path / "state.json"),
    )


@responses.activate
def test_e2e_goiania_vazio_nao_notifica(tmp_path: Path):
    responses.add(
        responses.POST, TOKEN_URL, json={"access_token": "tok", "expires_in": 3600}, status=200
    )
    responses.add(responses.GET, DATAS_URL, json=[], status=200)

    scheduler = _scheduler(tmp_path)
    diff = scheduler.run_once()
    assert diff.has_news is False

    telegram_calls = [c for c in responses.calls if API_BASE in c.request.url]
    assert telegram_calls == []


@responses.activate
def test_e2e_payload_realista_anicuns_notifica_e_persiste(tmp_path: Path):
    """Payload exato como documentado no PRD apêndice A."""
    responses.add(
        responses.POST, TOKEN_URL, json={"access_token": "tok", "expires_in": 3600}, status=200
    )
    responses.add(
        responses.GET,
        DATAS_URL,
        json=[
            {
                "idUnidade": 45,
                "nomeUnidade": "Anicuns",
                "idSenha": 58,
                "nomeSenha": "SSP - CARTEIRA DE IDENTIDADE NACIONAL (CIN)",
                "datas": [
                    "19/05/2026",
                    "20/05/2026",
                    "21/05/2026",
                    "22/05/2026",
                    "23/05/2026",
                    "26/05/2026",
                ],
            }
        ],
        status=200,
    )
    responses.add(responses.POST, TELEGRAM_SEND_URL, json={"ok": True}, status=200)

    scheduler = _scheduler(tmp_path, cod=23600)
    diff = scheduler.run_once()
    assert diff.has_news is True

    telegram_calls = [c for c in responses.calls if API_BASE in c.request.url]
    assert len(telegram_calls) == 1
    body = telegram_calls[0].request.body
    assert body is not None
    body_text = body.decode("utf-8") if isinstance(body, bytes) else body
    assert "Anicuns" in body_text
    assert "MarkdownV2" in body_text

    state = StateStore(tmp_path / "state.json").load()
    assert state.datas_por_unidade["Anicuns"][0] == "19/05/2026"
    assert state.last_notification_at is not None
    assert state.hash != ""


@responses.activate
def test_e2e_segundo_poll_mesmas_datas_nao_renotifica(tmp_path: Path):
    responses.add(
        responses.POST, TOKEN_URL, json={"access_token": "tok", "expires_in": 3600}, status=200
    )
    payload = [
        {
            "idUnidade": 45,
            "nomeUnidade": "Anicuns",
            "idSenha": 58,
            "nomeSenha": "CIN",
            "datas": ["19/05/2026"],
        }
    ]
    responses.add(responses.GET, DATAS_URL, json=payload, status=200)
    responses.add(responses.GET, DATAS_URL, json=payload, status=200)
    responses.add(responses.POST, TELEGRAM_SEND_URL, json={"ok": True}, status=200)

    scheduler = _scheduler(tmp_path, cod=23600)
    scheduler.run_once()
    scheduler.run_once()

    telegram_calls = [c for c in responses.calls if API_BASE in c.request.url]
    assert len(telegram_calls) == 1


@responses.activate
def test_e2e_token_401_dispara_refresh(tmp_path: Path):
    responses.add(
        responses.POST, TOKEN_URL, json={"access_token": "tok-old", "expires_in": 3600}, status=200
    )
    responses.add(responses.GET, DATAS_URL, status=401)
    responses.add(
        responses.POST, TOKEN_URL, json={"access_token": "tok-new", "expires_in": 3600}, status=200
    )
    responses.add(responses.GET, DATAS_URL, json=[], status=200)

    scheduler = _scheduler(tmp_path)
    diff = scheduler.run_once()
    assert diff.has_news is False

    token_calls = [c for c in responses.calls if c.request.url == TOKEN_URL]
    assert len(token_calls) == 2


@responses.activate
def test_e2e_telegram_5xx_loga_falha_mas_nao_quebra(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("bot.telegram_notifier.time.sleep", lambda _s: None)
    responses.add(
        responses.POST, TOKEN_URL, json={"access_token": "tok", "expires_in": 3600}, status=200
    )
    responses.add(
        responses.GET,
        DATAS_URL,
        json=[
            {
                "idUnidade": 45,
                "nomeUnidade": "Vapt",
                "idSenha": 58,
                "nomeSenha": "CIN",
                "datas": ["02/05/2026"],
            }
        ],
        status=200,
    )
    responses.add(responses.POST, TELEGRAM_SEND_URL, status=502)
    responses.add(responses.POST, TELEGRAM_SEND_URL, status=502)
    responses.add(responses.POST, TELEGRAM_SEND_URL, status=502)

    scheduler = _scheduler(tmp_path)
    diff = scheduler.run_once()
    assert diff.has_news is True

    state = StateStore(tmp_path / "state.json").load()
    assert state.last_notification_at is None
