"""Testa as 4 transições de estado do PRD §4 / US-004."""

from __future__ import annotations

from bot.change_detector import compute_diff, unidades_to_map
from bot.expresso_client import Unidade


def _u(nome: str, datas: list[str], id_unidade: int = 1) -> Unidade:
    return Unidade(
        id_unidade=id_unidade,
        nome_unidade=nome,
        id_senha=58,
        nome_senha="CIN",
        datas=datas,
    )


def test_vazio_para_vazio_nao_notifica():
    diff = compute_diff({}, {})
    assert diff.has_news is False
    assert diff.novas_datas_por_unidade == {}


def test_vazio_para_com_vagas_notifica_tudo():
    curr = unidades_to_map([_u("Vapt Centro", ["02/05/2026", "03/05/2026"])])
    diff = compute_diff({}, curr)
    assert diff.has_news is True
    assert diff.novas_unidades == ["Vapt Centro"]
    assert diff.novas_datas_por_unidade == {"Vapt Centro": ["02/05/2026", "03/05/2026"]}
    assert diff.total_atual_por_unidade == {"Vapt Centro": 2}


def test_com_vagas_para_vazio_silencioso():
    diff = compute_diff({"Vapt Centro": ["02/05/2026"]}, {})
    assert diff.has_news is False


def test_mesmas_datas_nao_notifica():
    prev = {"Vapt Centro": ["02/05/2026", "03/05/2026"]}
    curr = {"Vapt Centro": ["02/05/2026", "03/05/2026"]}
    diff = compute_diff(prev, curr)
    assert diff.has_news is False


def test_datas_em_ordem_diferente_nao_notifica():
    prev = {"Vapt Centro": ["02/05/2026", "03/05/2026"]}
    curr = {"Vapt Centro": ["03/05/2026", "02/05/2026"]}
    diff = compute_diff(prev, curr)
    assert diff.has_news is False


def test_nova_data_adicionada_notifica_so_a_nova():
    prev = {"Vapt Centro": ["02/05/2026"]}
    curr = {"Vapt Centro": ["02/05/2026", "12/05/2026"]}
    diff = compute_diff(prev, curr)
    assert diff.has_news is True
    assert diff.novas_datas_por_unidade == {"Vapt Centro": ["12/05/2026"]}
    assert diff.total_atual_por_unidade == {"Vapt Centro": 2}


def test_nova_unidade_aparece_notifica():
    prev = {"Vapt Centro": ["02/05/2026"]}
    curr = {
        "Vapt Centro": ["02/05/2026"],
        "Vapt Anhanguera": ["10/05/2026"],
    }
    diff = compute_diff(prev, curr)
    assert diff.has_news is True
    assert "Vapt Anhanguera" in diff.novas_unidades
    assert diff.novas_datas_por_unidade == {"Vapt Anhanguera": ["10/05/2026"]}


def test_data_removida_de_unidade_nao_gera_news():
    prev = {"Vapt Centro": ["02/05/2026", "03/05/2026"]}
    curr = {"Vapt Centro": ["02/05/2026"]}
    diff = compute_diff(prev, curr)
    assert diff.has_news is False


def test_unidades_to_map_ordena_e_deduplica():
    unidades = [
        _u("Vapt Centro", ["03/05/2026", "02/05/2026", "02/05/2026"]),
    ]
    result = unidades_to_map(unidades)
    assert result == {"Vapt Centro": ["02/05/2026", "03/05/2026"]}


def test_unidades_to_map_ignora_unidade_sem_datas():
    unidades = [
        _u("Vapt Centro", []),
        _u("Vapt Anhanguera", ["10/05/2026"]),
    ]
    result = unidades_to_map(unidades)
    assert result == {"Vapt Anhanguera": ["10/05/2026"]}


def test_diff_ordena_datas_cronologicamente():
    prev: dict[str, list[str]] = {}
    curr = {"Vapt Centro": ["10/06/2026", "02/05/2026", "15/05/2026"]}
    diff = compute_diff(prev, curr)
    assert diff.novas_datas_por_unidade["Vapt Centro"] == [
        "02/05/2026",
        "15/05/2026",
        "10/06/2026",
    ]
