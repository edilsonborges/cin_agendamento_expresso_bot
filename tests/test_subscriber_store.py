"""Testes do SubscriberStore — persistência atômica do dict[chat_id, set[cod_municipio]]."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.subscriber_store import SubscriberStore


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "subscribers.json"


def test_empty_when_file_missing(store_path):
    store = SubscriberStore(store_path)
    assert store.is_empty() is True
    assert store.all_chats() == set()
    assert store.municipios_distintos() == set()


def test_add_chat_creates_file_atomically(store_path):
    store = SubscriberStore(store_path)
    is_new = store.add_chat(123)
    assert is_new is True
    assert store_path.exists()
    data = json.loads(store_path.read_text())
    assert data["subscribers"] == {"123": {"municipios": [], "msg_id": None}}
    assert "updated_at" in data


def test_add_chat_duplicate_returns_false(store_path):
    store = SubscriberStore(store_path)
    store.add_chat(123)
    assert store.add_chat(123) is False
    assert store.all_chats() == {123}


def test_remove_chat_existing_returns_true(store_path):
    store = SubscriberStore(store_path)
    store.add_chat(123)
    store.add_chat(456)
    assert store.remove_chat(123) is True
    assert store.all_chats() == {456}


def test_remove_chat_missing_returns_false(store_path):
    store = SubscriberStore(store_path)
    store.add_chat(123)
    assert store.remove_chat(999) is False
    assert store.all_chats() == {123}


def test_has_chat(store_path):
    store = SubscriberStore(store_path)
    store.add_chat(123)
    assert store.has_chat(123) is True
    assert store.has_chat(999) is False


def test_persists_across_instances(store_path):
    store1 = SubscriberStore(store_path)
    store1.add_chat(123)
    store1.add_municipio(123, 25300)
    store1.add_chat(456)

    store2 = SubscriberStore(store_path)
    assert store2.all_chats() == {123, 456}
    assert store2.municipios_de(123) == {25300}
    assert store2.municipios_de(456) == set()


def test_corrupt_file_starts_empty_with_log(store_path, caplog):
    store_path.write_text("{ this is broken json")
    store = SubscriberStore(store_path)
    assert store.is_empty() is True
    assert any(
        "subscribers" in r.message.lower() and "corrompido" in r.message.lower()
        for r in caplog.records
    )


def test_atomic_write_uses_temp_file(store_path):
    """Escrita atômica: write em .tmp + rename — sem .tmp residual."""
    store = SubscriberStore(store_path)
    parent = store_path.parent
    before = set(parent.iterdir())
    store.add_chat(123)
    after = set(parent.iterdir())
    new_files = after - before
    assert store_path in new_files
    for p in new_files:
        assert not p.name.endswith(".tmp"), f"arquivo .tmp residual: {p}"


# --- Phase 2: Multi-município --------------------------------------------------


def test_add_municipio_cria_chat_se_necessario(store_path):
    store = SubscriberStore(store_path)
    is_new = store.add_municipio(111, 25300)
    assert is_new is True
    assert store.has_chat(111)
    assert store.municipios_de(111) == {25300}


def test_add_municipio_idempotente(store_path):
    store = SubscriberStore(store_path)
    store.add_municipio(111, 25300)
    assert store.add_municipio(111, 25300) is False


def test_remove_municipio_existente(store_path):
    store = SubscriberStore(store_path)
    store.add_municipio(111, 25300)
    store.add_municipio(111, 23600)
    assert store.remove_municipio(111, 25300) is True
    assert store.municipios_de(111) == {23600}


def test_remove_municipio_inexistente_retorna_false(store_path):
    store = SubscriberStore(store_path)
    store.add_chat(111)
    assert store.remove_municipio(111, 25300) is False


def test_toggle_municipio_alterna(store_path):
    store = SubscriberStore(store_path)
    store.add_chat(111)
    assert store.toggle_municipio(111, 25300) is True   # ativa
    assert 25300 in store.municipios_de(111)
    assert store.toggle_municipio(111, 25300) is False  # desativa
    assert 25300 not in store.municipios_de(111)


def test_chats_para_filtra_corretamente(store_path):
    store = SubscriberStore(store_path)
    store.add_municipio(111, 25300)
    store.add_municipio(111, 23600)
    store.add_municipio(222, 25300)
    store.add_municipio(333, 33800)
    assert store.chats_para(25300) == {111, 222}
    assert store.chats_para(23600) == {111}
    assert store.chats_para(33800) == {333}
    assert store.chats_para(99999) == set()


def test_municipios_distintos_uniao_dos_chats(store_path):
    store = SubscriberStore(store_path)
    store.add_municipio(111, 25300)
    store.add_municipio(111, 23600)
    store.add_municipio(222, 33800)
    assert store.municipios_distintos() == {25300, 23600, 33800}


def test_is_empty_quando_nenhum_municipio_ativo(store_path):
    store = SubscriberStore(store_path)
    store.add_chat(111)
    assert store.is_empty() is True
    store.add_municipio(111, 25300)
    assert store.is_empty() is False


def test_remove_chat_zera_municipios(store_path):
    store = SubscriberStore(store_path)
    store.add_municipio(111, 25300)
    store.add_municipio(111, 23600)
    assert store.remove_chat(111) is True
    assert store.municipios_distintos() == set()


def test_persist_dict_format_em_json(store_path):
    store = SubscriberStore(store_path)
    store.add_municipio(111, 25300)
    store.add_municipio(111, 23600)
    store.add_municipio(222, 33800)

    data = json.loads(store_path.read_text())
    assert data["subscribers"]["111"]["municipios"] == [23600, 25300]
    assert data["subscribers"]["222"]["municipios"] == [33800]
    assert data["subscribers"]["111"]["msg_id"] is None


def test_migracao_formato_legado_list_para_dict(store_path):
    """Formato antigo `[123, 456]` deve virar `{123: set(), 456: set()}`."""
    store_path.write_text(
        json.dumps({"subscribers": [123, 456], "updated_at": "2026-04-29T00:00:00Z"}),
        encoding="utf-8",
    )
    store = SubscriberStore(store_path)
    assert store.all_chats() == {123, 456}
    assert store.municipios_de(123) == set()
    assert store.is_empty() is True


def test_migracao_legado_continua_persistindo_no_formato_novo(store_path):
    store_path.write_text(
        json.dumps({"subscribers": [123]}),
        encoding="utf-8",
    )
    store = SubscriberStore(store_path)
    store.add_municipio(123, 25300)
    data = json.loads(store_path.read_text())
    assert data["subscribers"] == {"123": {"municipios": [25300], "msg_id": None}}


def test_dashboard_msg_id_persiste(store_path):
    store = SubscriberStore(store_path)
    store.add_chat(111)
    assert store.get_dashboard_msg_id(111) is None
    store.set_dashboard_msg_id(111, 42)
    assert store.get_dashboard_msg_id(111) == 42

    # Reabre: persiste cross-instance
    store2 = SubscriberStore(store_path)
    assert store2.get_dashboard_msg_id(111) == 42

    # Limpa
    store2.set_dashboard_msg_id(111, None)
    assert store2.get_dashboard_msg_id(111) is None


def test_remove_chat_limpa_msg_id(store_path):
    store = SubscriberStore(store_path)
    store.add_chat(111)
    store.set_dashboard_msg_id(111, 42)
    store.remove_chat(111)
    assert store.get_dashboard_msg_id(111) is None
