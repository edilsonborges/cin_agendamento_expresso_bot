"""Diff entre estado anterior (em disco) e atual (acabou de chegar da API).

Regras (PRD §5 / US-004):
  - vazio → com vagas      ⇒ notifica todas as datas
  - com vagas → vazio      ⇒ NÃO notifica (silencioso)
  - mesmas datas (hash =)  ⇒ NÃO notifica (idempotência)
  - datas novas adicionadas⇒ notifica SOMENTE as novas
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .expresso_client import Unidade


@dataclass
class Diff:
    has_news: bool
    novas_unidades: list[str] = field(default_factory=list)
    novas_datas_por_unidade: dict[str, list[str]] = field(default_factory=dict)
    total_atual_por_unidade: dict[str, int] = field(default_factory=dict)


def unidades_to_map(unidades: list[Unidade]) -> dict[str, list[str]]:
    """Achata `[Unidade]` em `{nome_unidade: [datas]}` (ordenadas)."""
    out: dict[str, list[str]] = {}
    for u in unidades:
        if not u.datas:
            continue
        out[u.nome_unidade] = sorted(set(u.datas))
    return out


def compute_diff(prev: dict[str, list[str]], curr: dict[str, list[str]]) -> Diff:
    """Compara datas anteriores vs atuais. `prev` vazio implica todas as `curr` são novas."""
    if not curr:
        return Diff(has_news=False)

    novas_unidades: list[str] = []
    novas_datas: dict[str, list[str]] = {}
    total: dict[str, int] = {}

    for nome, datas in curr.items():
        datas_set = set(datas)
        prev_set = set(prev.get(nome, []))
        diff_datas = sorted(datas_set - prev_set, key=_data_sort_key)
        total[nome] = len(datas)
        if nome not in prev:
            novas_unidades.append(nome)
        if diff_datas:
            novas_datas[nome] = diff_datas

    has_news = bool(novas_datas)
    return Diff(
        has_news=has_news,
        novas_unidades=sorted(novas_unidades),
        novas_datas_por_unidade=novas_datas,
        total_atual_por_unidade=total,
    )


def _data_sort_key(s: str) -> tuple[int, int, int]:
    """Datas vêm como dd/mm/yyyy — ordenar como tupla numérica."""
    try:
        d, m, y = s.split("/")
        return (int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return (0, 0, 0)
