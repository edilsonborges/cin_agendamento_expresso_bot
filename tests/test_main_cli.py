"""Testes do dispatcher CLI (`python -m bot ...`).

Cobre: argparse, _persist_chat_id, e o caminho de erro quando faltam env vars.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.__main__ import _lock_path, _persist_chat_id, _state_path, main


def test_main_sem_argumento_aborta():
    with pytest.raises(SystemExit):
        main([])


def test_main_subcomando_invalido_aborta():
    with pytest.raises(SystemExit):
        main(["xyz"])


def test_main_run_once_passa_flag(monkeypatch, tmp_path: Path):
    """`run --once` deve executar 1 iteração e retornar — não rodar o loop infinito."""
    from unittest.mock import MagicMock, patch

    monkeypatch.setattr("bot.__main__.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("bot.__main__.ENV_PATH", tmp_path / "no.env")
    monkeypatch.setattr("bot.config.ENV_PATH", tmp_path / "no.env")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("GOIAS_OAUTH_BASIC", "x")

    fake_scheduler = MagicMock()
    fake_scheduler.run_once.return_value = MagicMock(has_news=False)

    with patch("bot.__main__.Scheduler", return_value=fake_scheduler):
        with patch("bot.__main__.ExpressoClient"):
            with patch("bot.__main__.TelegramNotifier"):
                rc = main(["run", "--once"])
    assert rc == 0
    fake_scheduler.run_once.assert_called_once()
    fake_scheduler.run_forever.assert_not_called()
    fake_scheduler.install_signal_handlers.assert_not_called()


def test_main_run_sem_once_chama_run_forever(monkeypatch, tmp_path: Path):
    from unittest.mock import MagicMock, patch

    monkeypatch.setattr("bot.__main__.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("bot.__main__.ENV_PATH", tmp_path / "no.env")
    monkeypatch.setattr("bot.config.ENV_PATH", tmp_path / "no.env")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("GOIAS_OAUTH_BASIC", "x")

    fake_scheduler = MagicMock()

    with patch("bot.__main__.Scheduler", return_value=fake_scheduler):
        with patch("bot.__main__.ExpressoClient"):
            with patch("bot.__main__.TelegramNotifier"):
                rc = main(["run"])
    assert rc == 0
    fake_scheduler.run_forever.assert_called_once()
    fake_scheduler.install_signal_handlers.assert_called_once()


def test_main_version_imprime_versao(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "cin_agendamento_expresso_bot" in out
    assert "0.1.0" in out


def test_main_run_sem_env_imprime_erro_amigavel(capsys, monkeypatch, tmp_path):
    for var in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "GOIAS_OAUTH_BASIC",
        "GOIAS_REFERER",
    ):
        monkeypatch.delenv(var, raising=False)
    fake_env = tmp_path / "no.env"
    monkeypatch.setattr("bot.__main__.ENV_PATH", fake_env)
    monkeypatch.setattr("bot.config.ENV_PATH", fake_env)
    rc = main(["run"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "erro:" in err


def test_persist_chat_id_cria_arquivo(tmp_path: Path, monkeypatch):
    fake_env = tmp_path / ".env"
    monkeypatch.setattr("bot.__main__.ENV_PATH", fake_env)
    _persist_chat_id(12345)
    assert fake_env.read_text(encoding="utf-8") == "TELEGRAM_CHAT_ID=12345\n"


def test_persist_chat_id_atualiza_linha_existente(tmp_path: Path, monkeypatch):
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "TELEGRAM_BOT_TOKEN=abc\nTELEGRAM_CHAT_ID=999\nLOG_LEVEL=INFO\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("bot.__main__.ENV_PATH", fake_env)
    _persist_chat_id(12345)
    content = fake_env.read_text(encoding="utf-8")
    assert "TELEGRAM_CHAT_ID=12345" in content
    assert "TELEGRAM_CHAT_ID=999" not in content
    assert "TELEGRAM_BOT_TOKEN=abc" in content
    assert "LOG_LEVEL=INFO" in content


def test_persist_chat_id_acrescenta_se_ausente(tmp_path: Path, monkeypatch):
    fake_env = tmp_path / ".env"
    fake_env.write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
    monkeypatch.setattr("bot.__main__.ENV_PATH", fake_env)
    _persist_chat_id(12345)
    content = fake_env.read_text(encoding="utf-8")
    assert "LOG_LEVEL=INFO" in content
    assert "TELEGRAM_CHAT_ID=12345" in content


def test_state_path_per_municipio_quando_nao_ha_legacy(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("bot.__main__.PROJECT_ROOT", tmp_path)
    p = _state_path(25300)
    assert p == tmp_path / "state-25300.json"


def test_state_path_usa_legacy_se_existir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("bot.__main__.PROJECT_ROOT", tmp_path)
    legacy = tmp_path / "state.json"
    legacy.write_text("{}", encoding="utf-8")
    assert _state_path(25300) == legacy
    assert _state_path(99999) == legacy


def test_lock_path_sempre_per_municipio(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("bot.__main__.PROJECT_ROOT", tmp_path)
    assert _lock_path(25300) == tmp_path / "state-25300.lock"
    assert _lock_path(23600) == tmp_path / "state-23600.lock"
    assert _lock_path(25300) != _lock_path(23600)


def test_cmd_status_sem_state_imprime_aviso(capsys, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("bot.__main__.PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("COD_MUNICIPIO", "25300")
    monkeypatch.setattr("bot.__main__.ENV_PATH", tmp_path / "no.env")
    monkeypatch.setattr("bot.config.ENV_PATH", tmp_path / "no.env")
    rc = main(["status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "nenhum state" in out
    assert "municipio=25300" in out


def test_cmd_doctor_tudo_ok(capsys, tmp_path: Path, monkeypatch):
    import responses

    from bot.expresso_client import DATAS_URL, TOKEN_URL

    monkeypatch.setattr("bot.__main__.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("bot.__main__.ENV_PATH", tmp_path / "no.env")
    monkeypatch.setattr("bot.config.ENV_PATH", tmp_path / "no.env")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "111:fake")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("GOIAS_OAUTH_BASIC", "basic-fake")

    with responses.RequestsMock() as rsps:
        rsps.add(rsps.POST, TOKEN_URL, json={"access_token": "tok", "expires_in": 3600})
        rsps.add(rsps.GET, DATAS_URL, json=[])
        rsps.add(
            rsps.GET,
            "https://api.telegram.org/bot111:fake/getMe",
            json={"ok": True, "result": {"username": "fakebot"}},
        )
        rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "tudo OK" in out
    assert "@fakebot" in out


def test_cmd_doctor_detecta_falta_de_config(capsys, tmp_path: Path, monkeypatch):
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GOIAS_OAUTH_BASIC"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("bot.__main__.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("bot.__main__.ENV_PATH", tmp_path / "no.env")
    monkeypatch.setattr("bot.config.ENV_PATH", tmp_path / "no.env")

    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "GOIAS_OAUTH_BASIC ausente" in out
    assert "TELEGRAM_BOT_TOKEN ausente" in out


def test_cmd_status_com_state_existente_imprime_resumo(capsys, tmp_path: Path, monkeypatch):
    import json

    monkeypatch.setattr("bot.__main__.PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("COD_MUNICIPIO", "25300")
    monkeypatch.setattr("bot.__main__.ENV_PATH", tmp_path / "no.env")
    monkeypatch.setattr("bot.config.ENV_PATH", tmp_path / "no.env")

    state_file = tmp_path / "state-25300.json"
    state_file.write_text(
        json.dumps(
            {
                "last_check_at": "2026-04-29T21:00:00-03:00",
                "last_change_at": "2026-04-29T20:00:00-03:00",
                "last_notification_at": "2026-04-29T20:01:00-03:00",
                "id_senha": 58,
                "cod_municipio": 25300,
                "hash": "abc1234567890def0123456789abc",
                "datas_por_unidade": {"Vapt Centro": ["02/05/2026", "03/05/2026"]},
            }
        ),
        encoding="utf-8",
    )

    rc = main(["status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Vapt Centro" in out
    assert "2 datas" in out
    assert "abc1234567890de" in out
    assert "2026-04-29T20:01:00" in out
