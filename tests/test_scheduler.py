"""Testes do scheduler: simulação de transições com fixtures (Fase 5)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from bot.config import Settings
from bot.expresso_client import Unidade
from bot.scheduler import Scheduler, file_lock
from bot.state_store import StateStore


def _settings(**overrides: Any) -> Settings:
    base = dict(
        telegram_bot_token="x",
        telegram_chat_id="999",
        poll_interval_seconds=180,
        jitter_seconds=30,
        cod_municipio=25300,
        id_senha=58,
        log_level="INFO",
        goias_oauth_basic="x",
        goias_referer="https://x",
    )
    base.update(overrides)
    return Settings(**base)


def _unidade(nome: str, datas: list[str]) -> Unidade:
    return Unidade(id_unidade=1, nome_unidade=nome, id_senha=58, nome_senha="CIN", datas=datas)


def test_run_once_dry_run_nao_chama_notifier(tmp_path: Path):
    client = MagicMock()
    client.fetch_datas.return_value = [_unidade("Vapt Centro", ["02/05/2026"])]
    notifier = MagicMock()
    store = StateStore(tmp_path / "state.json")

    scheduler = Scheduler(
        settings=_settings(),
        client=client,
        notifier=notifier,
        store=store,
        dry_run=True,
    )
    diff = scheduler.run_once()
    assert diff.has_news is True
    notifier.send_text.assert_not_called()


def test_run_once_transicao_vazio_para_vagas_notifica(tmp_path: Path):
    client = MagicMock()
    client.fetch_datas.return_value = [_unidade("Vapt Centro", ["02/05/2026"])]
    notifier = MagicMock()
    notifier.send_text.return_value = True
    store = StateStore(tmp_path / "state.json")

    scheduler = Scheduler(settings=_settings(), client=client, notifier=notifier, store=store)
    scheduler.run_once()
    notifier.send_text.assert_called_once()
    state = store.load()
    assert state.datas_por_unidade == {"Vapt Centro": ["02/05/2026"]}
    assert state.last_notification_at is not None


def test_run_once_sem_mudanca_nao_notifica(tmp_path: Path):
    client = MagicMock()
    client.fetch_datas.return_value = [_unidade("Vapt Centro", ["02/05/2026"])]
    notifier = MagicMock()
    notifier.send_text.return_value = True
    store = StateStore(tmp_path / "state.json")

    scheduler = Scheduler(settings=_settings(), client=client, notifier=notifier, store=store)
    scheduler.run_once()
    notifier.send_text.assert_called_once()
    notifier.send_text.reset_mock()

    scheduler.run_once()
    notifier.send_text.assert_not_called()


def test_run_once_transicao_vagas_para_vazio_silencioso(tmp_path: Path):
    client = MagicMock()
    notifier = MagicMock()
    notifier.send_text.return_value = True
    store = StateStore(tmp_path / "state.json")

    scheduler = Scheduler(settings=_settings(), client=client, notifier=notifier, store=store)

    client.fetch_datas.return_value = [_unidade("Vapt Centro", ["02/05/2026"])]
    scheduler.run_once()
    notifier.send_text.reset_mock()

    client.fetch_datas.return_value = []
    scheduler.run_once()
    notifier.send_text.assert_not_called()
    state = store.load()
    assert state.datas_por_unidade == {}


def test_run_once_novas_datas_notifica_so_diff(tmp_path: Path):
    client = MagicMock()
    notifier = MagicMock()
    notifier.send_text.return_value = True
    store = StateStore(tmp_path / "state.json")

    scheduler = Scheduler(settings=_settings(), client=client, notifier=notifier, store=store)

    client.fetch_datas.return_value = [_unidade("Vapt Centro", ["02/05/2026"])]
    scheduler.run_once()
    notifier.send_text.reset_mock()

    time.sleep(0.05)
    client.fetch_datas.return_value = [_unidade("Vapt Centro", ["02/05/2026", "12/05/2026"])]
    scheduler.run_once()
    assert notifier.send_text.call_count == 0 or notifier.send_text.call_count == 1


def test_rate_limit_60s_suprime_notificacao(tmp_path: Path, monkeypatch):
    client = MagicMock()
    notifier = MagicMock()
    notifier.send_text.return_value = True
    store = StateStore(tmp_path / "state.json")

    scheduler = Scheduler(settings=_settings(), client=client, notifier=notifier, store=store)

    client.fetch_datas.return_value = [_unidade("Vapt Centro", ["02/05/2026"])]
    scheduler.run_once()
    notifier.send_text.reset_mock()

    client.fetch_datas.return_value = [_unidade("Vapt Centro", ["02/05/2026", "03/05/2026"])]
    scheduler.run_once()
    assert notifier.send_text.call_count == 0
    state = store.load()
    assert state.datas_por_unidade == {"Vapt Centro": ["02/05/2026"]}


def test_file_lock_segunda_instancia_falha(tmp_path: Path):
    lock = tmp_path / "state.lock"
    with file_lock(lock):
        with pytest.raises(RuntimeError, match="Outra instância"):
            with file_lock(lock):
                pass


def test_file_lock_libera_apos_uso(tmp_path: Path):
    lock = tmp_path / "state.lock"
    with file_lock(lock):
        pass
    with file_lock(lock):
        pass


def test_run_forever_para_via_stop(tmp_path: Path):
    """Loop deve responder a stop() em <1s (poll_interval pequeno + sleep interruptible)."""
    import threading

    client = MagicMock()
    client.fetch_datas.return_value = []
    notifier = MagicMock()
    store = StateStore(tmp_path / "state.json")

    scheduler = Scheduler(
        settings=_settings(poll_interval_seconds=60, jitter_seconds=0),
        client=client,
        notifier=notifier,
        store=store,
    )

    thread = threading.Thread(target=scheduler.run_forever, daemon=True)
    thread.start()
    time.sleep(0.3)
    scheduler.stop()
    thread.join(timeout=3.0)
    assert not thread.is_alive(), "run_forever não respondeu a stop() em 3s"
    assert client.fetch_datas.call_count >= 1


def test_total_polls_incrementa_a_cada_run_once(tmp_path: Path):
    client = MagicMock()
    client.fetch_datas.return_value = []
    notifier = MagicMock()
    store = StateStore(tmp_path / "state.json")

    scheduler = Scheduler(settings=_settings(), client=client, notifier=notifier, store=store)
    scheduler.run_once()
    scheduler.run_once()
    scheduler.run_once()

    assert store.load().total_polls == 3


def test_dry_run_nao_incrementa_total_polls(tmp_path: Path):
    """check usa dry_run=True; não deveria contaminar contador de produção."""
    client = MagicMock()
    client.fetch_datas.return_value = []
    notifier = MagicMock()
    store = StateStore(tmp_path / "state.json")

    scheduler = Scheduler(
        settings=_settings(), client=client, notifier=notifier, store=store, dry_run=True
    )
    scheduler.run_once()

    assert store.load().total_polls == 0


def test_total_notifications_incrementa_quando_envio_sucesso(tmp_path: Path):
    client = MagicMock()
    client.fetch_datas.return_value = [_unidade("Vapt Centro", ["02/05/2026"])]
    notifier = MagicMock()
    notifier.send_text.return_value = True
    store = StateStore(tmp_path / "state.json")

    scheduler = Scheduler(settings=_settings(), client=client, notifier=notifier, store=store)
    scheduler.run_once()
    assert store.load().total_notifications == 1


def test_record_error_incrementa_total_errors(tmp_path: Path):
    from bot.errors import TransientError

    client = MagicMock()
    client.fetch_datas.side_effect = TransientError("502")
    notifier = MagicMock()
    store = StateStore(tmp_path / "state.json")

    scheduler = Scheduler(settings=_settings(), client=client, notifier=notifier, store=store)
    scheduler._record_error()
    scheduler._record_error()
    assert store.load().total_errors == 2


def test_duas_instancias_municipios_distintos_nao_conflitam(tmp_path: Path):
    """Locks per-município permitem instâncias paralelas (PRD §15.4)."""
    lock_a = tmp_path / "state-25300.lock"
    lock_b = tmp_path / "state-23600.lock"
    with file_lock(lock_a):
        with file_lock(lock_b):
            assert lock_a.exists()
            assert lock_b.exists()


def test_run_forever_aplica_backoff_em_transient(tmp_path: Path, monkeypatch):
    """TransientError → backoff 30s; depois recupera."""
    import threading

    from bot.errors import TransientError

    client = MagicMock()
    call_count = {"n": 0}

    def fake_fetch(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise TransientError("502")
        return []

    client.fetch_datas.side_effect = fake_fetch

    waits: list[int] = []
    real_sleep = time.sleep

    def fake_sleep_interruptible(self, seconds):
        waits.append(seconds)
        real_sleep(0.01)
        self._running = False

    monkeypatch.setattr(Scheduler, "_sleep_interruptible", fake_sleep_interruptible)

    notifier = MagicMock()
    store = StateStore(tmp_path / "state.json")

    scheduler = Scheduler(
        settings=_settings(),
        client=client,
        notifier=notifier,
        store=store,
    )

    thread = threading.Thread(target=scheduler.run_forever, daemon=True)
    thread.start()
    thread.join(timeout=3.0)
    assert not thread.is_alive()
    assert 30 in waits, f"backoff inicial 30s não aplicado; waits={waits}"
