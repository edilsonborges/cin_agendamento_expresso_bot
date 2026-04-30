"""Testes do TelegramNotifier: escape MarkdownV2, formatação e retry."""

from __future__ import annotations

import json
from datetime import datetime

import responses

from bot.change_detector import Diff
from bot.telegram_notifier import (
    API_BASE,
    BroadcastResult,
    TelegramNotifier,
    escape_md_v2,
    format_message,
)


def test_escape_md_v2_escapa_specials():
    assert escape_md_v2("Vapt - Centro") == r"Vapt \- Centro"
    assert escape_md_v2(".") == r"\."
    assert escape_md_v2("(test)") == r"\(test\)"
    assert escape_md_v2("a.b!c") == r"a\.b\!c"


def test_escape_md_v2_preserva_texto_normal():
    assert escape_md_v2("Goiania") == "Goiania"
    assert escape_md_v2("CIN") == "CIN"


def test_format_message_first_open_inclui_emoji_alerta():
    diff = Diff(
        has_news=True,
        novas_unidades=["Vapt Centro"],
        novas_datas_por_unidade={"Vapt Centro": ["02/05/2026", "03/05/2026"]},
        total_atual_por_unidade={"Vapt Centro": 2},
    )
    detected = datetime(2026, 4, 29, 18, 14)
    msg = format_message("Goiânia", diff, is_first_open=True, detected_at=detected)
    assert "🚨" in msg
    assert "GOIÂNIA" in msg
    assert "Vapt Centro" in msg
    assert "2 datas" in msg
    assert r"02/05/2026" in msg
    assert "Agendar agora" in msg


def test_format_message_novas_datas_inclui_emoji_sparkles():
    diff = Diff(
        has_news=True,
        novas_unidades=[],
        novas_datas_por_unidade={"Vapt Centro": ["12/05/2026"]},
        total_atual_por_unidade={"Vapt Centro": 9},
    )
    msg = format_message("Goiânia", diff, is_first_open=False)
    assert "✨" in msg
    assert "Total atual" in msg
    assert "9 datas" in msg


def test_format_message_truncamento_apos_5_datas():
    datas = [f"{i:02d}/05/2026" for i in range(1, 11)]
    diff = Diff(
        has_news=True,
        novas_unidades=["Vapt Centro"],
        novas_datas_por_unidade={"Vapt Centro": datas},
        total_atual_por_unidade={"Vapt Centro": 10},
    )
    msg = format_message("Goiânia", diff, is_first_open=True)
    assert "10 datas" in msg
    assert "e mais 5 datas" in msg


@responses.activate
def test_send_text_200_retorna_true():
    token = "123:ABC"
    responses.add(
        responses.POST,
        f"{API_BASE}/bot{token}/sendMessage",
        json={"ok": True},
        status=200,
    )
    notifier = TelegramNotifier(token, 999)
    assert notifier.send_text("ola") is True


@responses.activate
def test_send_text_4xx_retorna_false():
    token = "123:ABC"
    responses.add(
        responses.POST,
        f"{API_BASE}/bot{token}/sendMessage",
        json={"ok": False, "description": "bad request"},
        status=400,
    )
    notifier = TelegramNotifier(token, 999)
    assert notifier.send_text("ola") is False


@responses.activate
def test_send_text_5xx_retry_e_recupera(monkeypatch):
    monkeypatch.setattr("bot.telegram_notifier.time.sleep", lambda _s: None)
    token = "123:ABC"
    responses.add(
        responses.POST,
        f"{API_BASE}/bot{token}/sendMessage",
        json={"ok": False},
        status=502,
    )
    responses.add(
        responses.POST,
        f"{API_BASE}/bot{token}/sendMessage",
        json={"ok": True},
        status=200,
    )
    notifier = TelegramNotifier(token, 999)
    assert notifier.send_text("ola") is True
    assert len(responses.calls) == 2


@responses.activate
def test_send_text_429_respeita_retry_after(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr("bot.telegram_notifier.time.sleep", lambda s: waits.append(s))
    token = "123:ABC"
    responses.add(
        responses.POST,
        f"{API_BASE}/bot{token}/sendMessage",
        json={"ok": False, "parameters": {"retry_after": 7}},
        status=429,
    )
    responses.add(
        responses.POST,
        f"{API_BASE}/bot{token}/sendMessage",
        json={"ok": True},
        status=200,
    )
    notifier = TelegramNotifier(token, 999)
    assert notifier.send_text("ola") is True
    assert 7 in waits


@responses.activate
def test_broadcast_three_chats_one_403_one_500_one_ok():
    """Broadcast: ok=200, blocked=403 (com http_status), erro 500 (depois esgota)."""
    notifier = TelegramNotifier("TOKEN_TESTE")  # sem chat_id

    def chat_url(chat_id):
        return "https://api.telegram.org/botTOKEN_TESTE/sendMessage"

    # responses não filtra por payload por default — usamos callback pra discriminar
    def cb(request):
        body = json.loads(request.body)
        cid = body["chat_id"]
        if cid == 111:
            return (200, {}, json.dumps({"ok": True}))
        if cid == 222:
            return (403, {}, json.dumps({"ok": False, "description": "Forbidden: bot was blocked"}))
        # 333 → 500 sempre
        return (500, {}, "boom")

    responses.add_callback(
        responses.POST,
        "https://api.telegram.org/botTOKEN_TESTE/sendMessage",
        callback=cb,
    )

    results = notifier.broadcast([111, 222, 333], "msg")
    by_chat = {r.chat_id: r for r in results}
    assert by_chat[111].ok is True
    assert by_chat[111].http_status == 200
    assert by_chat[222].ok is False
    assert by_chat[222].http_status == 403
    assert by_chat[333].ok is False
    # após esgotar 5xx → 500 vira o último visto
    assert by_chat[333].http_status == 500


def test_send_text_without_chat_id_raises():
    notifier = TelegramNotifier("TOKEN_TESTE")  # chat_id ausente
    import pytest
    with pytest.raises(RuntimeError, match="chat_id"):
        notifier.send_text("hi")


def test_broadcast_empty_returns_empty_list():
    notifier = TelegramNotifier("TOKEN_TESTE")
    assert notifier.broadcast([], "msg") == []
