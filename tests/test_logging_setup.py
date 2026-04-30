"""Testes do logging_setup.

O TokenMaskFilter é segurança crítica — US-002 AC4 exige que tokens nunca
apareçam completos em logs. Testes cobrem Bearer e padrão de bot Telegram.
"""

from __future__ import annotations

import logging

from bot.logging_setup import TokenMaskFilter, setup_logging


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname="x.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


def test_filter_mascara_bearer_em_msg():
    f = TokenMaskFilter()
    r = _record("Authorization: Bearer abcdefghijklmnopqrstuvwxyz1234567890")
    f.filter(r)
    assert "abcdefghijklmnopqrst" in r.msg
    assert "1234567890" not in r.msg
    assert "(masked)" in r.msg


def test_filter_mascara_token_telegram():
    f = TokenMaskFilter()
    r = _record("token=8625551703:AAFdt4Z5fYaz9x0J6e3ZRA5qMDa90CxNQig usado")
    f.filter(r)
    assert "AAFdt4Z5fYaz9x0J6e3ZRA5qMDa90CxNQig" not in r.msg
    assert "(masked)" in r.msg or "…" in r.msg


def test_filter_preserva_msg_sem_token():
    f = TokenMaskFilter()
    r = _record("[poll] municipio=25300 datas=0 acao=noop")
    f.filter(r)
    assert r.msg == "[poll] municipio=25300 datas=0 acao=noop"


def test_setup_logging_cria_handler_stdout():
    root = setup_logging("DEBUG")
    assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
    assert root.level == logging.DEBUG


def test_setup_logging_cria_arquivo_rotativo(tmp_path):
    log_file = tmp_path / "bot.log"
    setup_logging("INFO", log_file)
    logger = logging.getLogger("test_setup_logging")
    logger.info("uma linha de teste")
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "uma linha de teste" in content


def test_setup_logging_idempotente_nao_duplica_handlers(tmp_path):
    log_file = tmp_path / "bot.log"
    setup_logging("INFO", log_file)
    n1 = len(logging.getLogger().handlers)
    setup_logging("INFO", log_file)
    n2 = len(logging.getLogger().handlers)
    assert n1 == n2


def test_setup_logging_arquivo_recebe_token_mascarado(tmp_path):
    log_file = tmp_path / "bot.log"
    setup_logging("DEBUG", log_file)
    logger = logging.getLogger("test_token_mask_file")
    logger.info("usando Bearer eyJ4NXQiOmZha2V0b2tlbnZlcnlsb25nMTIzNDU2Nzg5MA")
    content = log_file.read_text(encoding="utf-8")
    assert "eyJ4NXQiOmZha2V0b2tlbnZlcnlsb25nMTIzNDU2Nzg5MA" not in content
    assert "(masked)" in content
