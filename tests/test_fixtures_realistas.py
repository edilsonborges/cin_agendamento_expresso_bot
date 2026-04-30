"""Testes que carregam fixtures JSON capturadas do servidor real (PRD §A).

Garantem que mudanças no parser/format quebram explicitamente quando o shape
do servidor muda — em vez de silenciosamente aceitar dados malformados.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.change_detector import compute_diff, unidades_to_map
from bot.expresso_client import Unidade
from bot.telegram_notifier import format_message

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_payload_anicuns_parseado_corretamente():
    raw = _load("listar_datas_anicuns.json")
    unidades = [Unidade.from_api(item) for item in raw]
    assert len(unidades) == 1
    u = unidades[0]
    assert u.id_unidade == 45
    assert u.nome_unidade == "Anicuns"
    assert u.id_senha == 58
    assert u.nome_senha == "SSP - CARTEIRA DE IDENTIDADE NACIONAL (CIN)"
    assert len(u.datas) == 27
    assert u.datas[0] == "19/05/2026"
    assert u.datas[-1] == "24/06/2026"


def test_payload_anicuns_gera_diff_com_27_datas():
    raw = _load("listar_datas_anicuns.json")
    unidades = [Unidade.from_api(item) for item in raw]
    curr = unidades_to_map(unidades)
    diff = compute_diff({}, curr)
    assert diff.has_news
    assert "Anicuns" in diff.novas_unidades
    assert len(diff.novas_datas_por_unidade["Anicuns"]) == 27
    assert diff.total_atual_por_unidade["Anicuns"] == 27


def test_payload_anicuns_format_message_truncamento_correto():
    raw = _load("listar_datas_anicuns.json")
    unidades = [Unidade.from_api(item) for item in raw]
    curr = unidades_to_map(unidades)
    diff = compute_diff({}, curr)
    msg = format_message("Anicuns", diff, is_first_open=True)

    assert "🟢" in msg
    assert "ANICUNS" in msg
    assert "27 datas" in msg
    assert "19/05/2026" in msg
    assert "23/05/2026" in msg
    assert "24/06/2026" not in msg
    assert "e mais 22 datas" in msg
    assert "Agendar agora" in msg


def test_payload_goiania_vazio():
    raw = _load("listar_datas_goiania_vazio.json")
    assert raw == []
    unidades = [Unidade.from_api(item) for item in raw]
    assert unidades == []
    diff = compute_diff({}, unidades_to_map(unidades))
    assert diff.has_news is False


def test_diff_anicuns_acrescimo_de_datas_notifica_so_novas():
    """Simula servidor adicionando 2 datas além do payload realista — diff deve isolar só o novo."""
    raw = _load("listar_datas_anicuns.json")
    unidades_anteriores = [Unidade.from_api(item) for item in raw]
    prev = unidades_to_map(unidades_anteriores)

    raw_atual = json.loads(json.dumps(raw))
    raw_atual[0]["datas"].extend(["25/06/2026", "26/06/2026"])
    unidades_atuais = [Unidade.from_api(item) for item in raw_atual]
    curr = unidades_to_map(unidades_atuais)

    diff = compute_diff(prev, curr)
    assert diff.has_news is True
    assert diff.novas_datas_por_unidade == {"Anicuns": ["25/06/2026", "26/06/2026"]}
    assert diff.total_atual_por_unidade == {"Anicuns": 29}


@pytest.mark.parametrize(
    "fixture", ["listar_datas_anicuns.json", "listar_datas_goiania_vazio.json"]
)
def test_fixtures_sao_json_validos(fixture):
    """Defesa contra commits que quebrem fixtures."""
    raw = (FIXTURES / fixture).read_text(encoding="utf-8")
    json.loads(raw)
