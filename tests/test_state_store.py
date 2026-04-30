"""Testes do state_store: roundtrip, write atômico, hash determinístico."""

from __future__ import annotations

from pathlib import Path

from bot.state_store import State, StateStore, hash_datas


def test_load_inexistente_retorna_state_default(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    state = store.load()
    assert state.is_empty
    assert state.hash == ""
    assert state.datas_por_unidade == {}


def test_save_e_load_roundtrip(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    s = State(
        last_check_at="2026-04-29T21:00:00-03:00",
        id_senha=58,
        cod_municipio=25300,
        hash="abc",
        datas_por_unidade={"Vapt Centro": ["02/05/2026", "03/05/2026"]},
    )
    store.save(s)
    loaded = store.load()
    assert loaded.id_senha == 58
    assert loaded.cod_municipio == 25300
    assert loaded.datas_por_unidade == {"Vapt Centro": ["02/05/2026", "03/05/2026"]}


def test_save_e_atomico(tmp_path: Path):
    """Após save, .tmp não fica perdido."""
    store = StateStore(tmp_path / "state.json")
    store.save(State(hash="x"))
    files = list(tmp_path.iterdir())
    assert {f.name for f in files} == {"state.json"}


def test_load_corrompido_reseta(tmp_path: Path):
    p = tmp_path / "state.json"
    p.write_text("{nao-eh-json", encoding="utf-8")
    store = StateStore(p)
    state = store.load()
    assert state.is_empty


def test_hash_determinismo():
    a = {"X": ["02/05/2026", "03/05/2026"]}
    b = {"X": ["03/05/2026", "02/05/2026"]}
    assert hash_datas(a) == hash_datas(b)


def test_hash_muda_quando_datas_mudam():
    a = {"X": ["02/05/2026"]}
    b = {"X": ["02/05/2026", "03/05/2026"]}
    assert hash_datas(a) != hash_datas(b)


def test_hash_estado_vazio_e_estavel():
    h1 = hash_datas({})
    h2 = hash_datas({})
    assert h1 == h2


def test_is_empty_true_quando_dict_vazio():
    assert State().is_empty
    assert not State(datas_por_unidade={"X": ["02/05"]}).is_empty
