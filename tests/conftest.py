"""Fixtures e setup compartilhado entre todos os testes.

`reset_logging` (autouse): cada teste começa com root logger limpo. Evita acumular
handlers do `setup_logging` chamado em testes anteriores, o que corromperia o
output e poderia escrever em arquivos de outros testes.
"""

from __future__ import annotations

import logging

import pytest


@pytest.fixture(autouse=True)
def reset_logging():
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    root.setLevel(logging.WARNING)
