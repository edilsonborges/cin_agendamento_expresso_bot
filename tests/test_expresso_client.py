"""Testes do ExpressoClient com mock de HTTP via responses.

Cobre:
  - Token cache (não refaz POST /token enquanto válido)
  - Refresh forçado
  - 401 → refresh + retry uma vez
  - 5xx → TransientError, 4xx → PermanentError
  - parsing de Unidade
"""

from __future__ import annotations

import time

import pytest
import responses

from bot.errors import PermanentError, TransientError
from bot.expresso_client import DATAS_URL, TOKEN_URL, ExpressoClient


def _client() -> ExpressoClient:
    return ExpressoClient(oauth_basic="dummy-basic", referer="https://www.go.gov.br/x", timeout=2.0)


@responses.activate
def test_get_access_token_faz_post_e_cacheia():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "tok-1", "expires_in": 3600},
        status=200,
    )
    client = _client()
    t1 = client.get_access_token()
    t2 = client.get_access_token()
    assert t1 == "tok-1"
    assert t2 == "tok-1"
    assert len(responses.calls) == 1


@responses.activate
def test_get_access_token_refresh_quando_quase_expira():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "tok-1", "expires_in": 60},
        status=200,
    )
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "tok-2", "expires_in": 3600},
        status=200,
    )
    client = _client()
    client.get_access_token()
    client._expires_at = time.monotonic() + 30
    assert client.get_access_token() == "tok-2"


@responses.activate
def test_token_oauth_4xx_levanta_permanent():
    responses.add(responses.POST, TOKEN_URL, status=403, body="forbidden")
    client = _client()
    with pytest.raises(PermanentError):
        client.get_access_token()


@responses.activate
def test_token_oauth_5xx_levanta_transient():
    responses.add(responses.POST, TOKEN_URL, status=502)
    client = _client()
    with pytest.raises(TransientError):
        client.get_access_token()


@responses.activate
def test_fetch_datas_lista_vazia():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "tok", "expires_in": 3600},
        status=200,
    )
    responses.add(responses.GET, DATAS_URL, json=[], status=200)
    client = _client()
    result = client.fetch_datas(58, 25300)
    assert result == []


@responses.activate
def test_fetch_datas_parses_unidade():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "tok", "expires_in": 3600},
        status=200,
    )
    responses.add(
        responses.GET,
        DATAS_URL,
        json=[
            {
                "idUnidade": 45,
                "nomeUnidade": "Anicuns",
                "idSenha": 58,
                "nomeSenha": "CIN",
                "datas": ["19/05/2026", "20/05/2026"],
            }
        ],
        status=200,
    )
    client = _client()
    [unidade] = client.fetch_datas(58, 23600)
    assert unidade.id_unidade == 45
    assert unidade.nome_unidade == "Anicuns"
    assert unidade.datas == ["19/05/2026", "20/05/2026"]


@responses.activate
def test_fetch_datas_401_refresh_e_retry():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "tok-old", "expires_in": 3600},
        status=200,
    )
    responses.add(responses.GET, DATAS_URL, status=401, body="unauthorized")
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "tok-new", "expires_in": 3600},
        status=200,
    )
    responses.add(responses.GET, DATAS_URL, json=[], status=200)
    client = _client()
    result = client.fetch_datas(58, 25300)
    assert result == []


@responses.activate
def test_fetch_datas_401_persistente_levanta_permanent():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "tok", "expires_in": 3600},
        status=200,
    )
    responses.add(responses.GET, DATAS_URL, status=401)
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "tok-2", "expires_in": 3600},
        status=200,
    )
    responses.add(responses.GET, DATAS_URL, status=401)
    client = _client()
    with pytest.raises(PermanentError):
        client.fetch_datas(58, 25300)


@responses.activate
def test_fetch_datas_5xx_levanta_transient():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "tok", "expires_in": 3600},
        status=200,
    )
    responses.add(responses.GET, DATAS_URL, status=503)
    client = _client()
    with pytest.raises(TransientError):
        client.fetch_datas(58, 25300)


@responses.activate
def test_fetch_datas_429_levanta_transient():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "tok", "expires_in": 3600},
        status=200,
    )
    responses.add(responses.GET, DATAS_URL, status=429)
    client = _client()
    with pytest.raises(TransientError):
        client.fetch_datas(58, 25300)


@responses.activate
def test_fetch_datas_shape_invalido_levanta_permanent():
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "tok", "expires_in": 3600},
        status=200,
    )
    responses.add(responses.GET, DATAS_URL, json={"erro": "x"}, status=200)
    client = _client()
    with pytest.raises(PermanentError):
        client.fetch_datas(58, 25300)
