"""Lista de municípios atendidos pelo Vapt Vupt para o serviço de CIN.

Capturados do dropdown do portal Goiás Digital em 2026-04-30. São apenas os
58 municípios que têm unidade Vapt Vupt para CIN — não todos os municípios
de Goiás (a tabela completa do estado tem ~250 municípios).

Código = `codgMunicipio` interno do Goiás Digital (não é IBGE).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Municipio:
    nome: str
    codigo: int


# Ordem alfabética conforme dropdown do portal.
MUNICIPIOS: tuple[Municipio, ...] = (
    Municipio("AGUAS LINDAS DE GOIAS", 149400),
    Municipio("ALVORADA DO NORTE", 15300),
    Municipio("ANAPOLIS", 23500),
    Municipio("ANICUNS", 23600),
    Municipio("APARECIDA DE GOIANIA", 33800),
    Municipio("BELA VISTA DE GOIAS", 34000),
    Municipio("BOM JESUS DE GOIAS", 39200),
    Municipio("BURITI ALEGRE", 39300),
    Municipio("CALDAS NOVAS", 34100),
    Municipio("CAMPOS BELOS", 9400),
    Municipio("CATALAO", 36500),
    Municipio("CERES", 24600),
    Municipio("CRISTALINA", 19300),
    Municipio("CRIXAS", 11800),
    Municipio("FORMOSA", 19400),
    Municipio("GOIANESIA", 25200),
    Municipio("GOIANIA", 25300),
    Municipio("GOIANIRA", 25400),
    Municipio("GOIAS", 17000),
    Municipio("GOIATUBA", 39700),
    Municipio("HIDROLANDIA", 34600),
    Municipio("IPAMERI", 37000),
    Municipio("IPORA", 25800),
    Municipio("ITABERAI", 26000),
    Municipio("ITAPACI", 26200),
    Municipio("ITAPURANGA", 26300),
    Municipio("ITUMBIARA", 40000),
    Municipio("JARAGUA", 26600),
    Municipio("JATAI", 32500),
    Municipio("JUSSARA", 17200),
    Municipio("LUZIANIA", 19500),
    Municipio("MARA ROSA", 12100),
    Municipio("MINACU", 12200),
    Municipio("MINEIROS", 21600),
    Municipio("MORRINHOS", 40300),
    Municipio("MOZARLANDIA", 17300),
    Municipio("NEROPOLIS", 27100),
    Municipio("NOVO GAMA", 148500),
    Municipio("PADRE BERNARDO", 19600),
    Municipio("PALMEIRAS DE GOIAS", 34900),
    Municipio("PARAUNA", 32700),
    Municipio("PIRACANJUBA", 35000),
    Municipio("PIRENOPOLIS", 19700),
    Municipio("PIRES DO RIO", 37600),
    Municipio("PLANALTINA", 19800),
    Municipio("PORANGATU", 12700),
    Municipio("POSSE", 16000),
    Municipio("QUIRINOPOLIS", 40600),
    Municipio("RIALMA", 27800),
    Municipio("RIO VERDE", 32800),
    Municipio("RUBIATABA", 28000),
    Municipio("SANTA HELENA DE GOIAS", 40700),
    Municipio("SANTO ANTONIO DO DESCOBERTO", 19900),
    Municipio("SAO LUIS DE MONTES BELOS", 28600),
    Municipio("SAO MIGUEL DO ARAGUAIA", 13000),
    Municipio("SENADOR CANEDO", 29500),
    Municipio("TRINDADE", 28800),
    Municipio("VALPARAISO DE GOIAS", 148400),
)


def por_nome(nome: str) -> Municipio | None:
    """Busca case-insensitive sem acentos. None se não encontrado."""
    alvo = nome.strip().upper()
    for m in MUNICIPIOS:
        if m.nome == alvo:
            return m
    return None


def por_codigo(codigo: int) -> Municipio | None:
    for m in MUNICIPIOS:
        if m.codigo == codigo:
            return m
    return None
