#!/usr/bin/env bash
# Roda todos os checks que o CI roda. Útil antes de abrir PR.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
    echo "ERRO: .venv não encontrado. Rode primeiro: make install"
    exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ ruff check"
ruff check bot tests

echo "→ ruff format --check"
ruff format --check bot tests

echo "→ mypy"
mypy

echo "→ pytest"
pytest -q

echo
echo "✓ todos os checks passaram"
