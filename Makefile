# Atalhos de dev. Usa explicitamente .venv/bin/* para não depender de
# `source .venv/bin/activate` (cada target make roda em shell novo).

PY := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff
MYPY := .venv/bin/mypy

.PHONY: help install test cov lint format type ci clean run check status init doctor

help:
	@echo "Targets:"
	@echo "  install   - cria venv e instala deps (run + dev)"
	@echo "  test      - roda pytest"
	@echo "  cov       - pytest com cobertura (terminal + htmlcov/)"
	@echo "  lint      - ruff check"
	@echo "  format    - ruff format (escreve)"
	@echo "  type      - mypy"
	@echo "  ci        - lint + format-check + type + test (todos os checks do CI)"
	@echo "  check     - smoke test ao vivo (1 fetch dry-run)"
	@echo "  status    - resumo offline do state file"
	@echo "  doctor    - diagnóstico de config + conectividade"
	@echo "  init      - polling getUpdates pra capturar chat_id"
	@echo "  run       - loop de produção"
	@echo "  clean     - remove caches/build/state local"

install:
	python3 -m venv .venv
	$(PIP) install -U pip
	$(PIP) install -r requirements-dev.txt

test:
	$(PYTEST) -q

cov:
	$(PYTEST) --cov=bot --cov-report=term-missing --cov-report=html

lint:
	$(RUFF) check bot tests

format:
	$(RUFF) format bot tests

type:
	$(MYPY)

ci:
	$(RUFF) check bot tests
	$(RUFF) format --check bot tests
	$(MYPY)
	$(PYTEST) -q

check:
	$(PY) -m bot check

status:
	$(PY) -m bot status

doctor:
	$(PY) -m bot doctor

init:
	$(PY) -m bot init

run:
	$(PY) -m bot run

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
	rm -f state.json state-*.json state.lock state-*.lock bot.log bot.log.*
