"""Testes do SubscriberStore — persistência atômica do set[chat_id]."""

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
    assert store.all() == set()


def test_add_creates_file_atomically(store_path):
    store = SubscriberStore(store_path)
    is_new = store.add(123)
    assert is_new is True
    assert store_path.exists()
    data = json.loads(store_path.read_text())
    assert data["subscribers"] == [123]
    assert "updated_at" in data


def test_add_duplicate_returns_false(store_path):
    store = SubscriberStore(store_path)
    store.add(123)
    is_new = store.add(123)
    assert is_new is False
    assert store.all() == {123}


def test_remove_existing_returns_true(store_path):
    store = SubscriberStore(store_path)
    store.add(123)
    store.add(456)
    assert store.remove(123) is True
    assert store.all() == {456}


def test_remove_missing_returns_false(store_path):
    store = SubscriberStore(store_path)
    store.add(123)
    assert store.remove(999) is False
    assert store.all() == {123}


def test_contains(store_path):
    store = SubscriberStore(store_path)
    store.add(123)
    assert store.contains(123) is True
    assert store.contains(999) is False


def test_persists_across_instances(store_path):
    store1 = SubscriberStore(store_path)
    store1.add(123)
    store1.add(456)

    store2 = SubscriberStore(store_path)
    assert store2.all() == {123, 456}


def test_corrupt_file_starts_empty_with_log(store_path, caplog):
    store_path.write_text("{ this is broken json")
    store = SubscriberStore(store_path)
    assert store.is_empty() is True
    assert any(
        "subscribers" in r.message.lower() and "corrompido" in r.message.lower()
        for r in caplog.records
    )


def test_atomic_write_uses_temp_file(store_path, monkeypatch):
    """Escrita atômica: write em .tmp + rename."""
    store = SubscriberStore(store_path)
    # Captura todos os arquivos criados no diretório durante add
    parent = store_path.parent
    before = set(parent.iterdir())
    store.add(123)
    after = set(parent.iterdir())
    # Após add, deve existir só o arquivo final, sem .tmp residual
    new_files = after - before
    assert store_path in new_files
    for p in new_files:
        assert not p.name.endswith(".tmp"), f"arquivo .tmp residual: {p}"
