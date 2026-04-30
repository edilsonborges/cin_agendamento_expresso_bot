#!/usr/bin/env bash
# Instala o LaunchAgent do bot. Idempotente — pode rodar várias vezes.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_TEMPLATE="$PROJECT_DIR/scripts/com.edilson.cin-agendamento-bot.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_DEST="$LAUNCH_AGENTS_DIR/com.edilson.cin-agendamento-bot.plist"
LABEL="com.edilson.cin-agendamento-bot"

if [ ! -d "$PROJECT_DIR/.venv" ]; then
    echo "ERRO: .venv não encontrado em $PROJECT_DIR. Rode primeiro:"
    echo "  python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "ERRO: .env não encontrado. Copie .env.example e preencha:"
    echo "  cp .env.example .env && \$EDITOR .env"
    exit 1
fi

mkdir -p "$LAUNCH_AGENTS_DIR"

# Substitui placeholder pelo path real do projeto e instala.
sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$PLIST_TEMPLATE" > "$PLIST_DEST"
chmod 644 "$PLIST_DEST"

# Recarrega: unload defensivo (ignora erro), depois load.
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "Instalado: $PLIST_DEST"
echo
echo "Comandos úteis:"
echo "  launchctl list | grep $LABEL"
echo "  tail -f $PROJECT_DIR/bot.log"
echo "  ./scripts/uninstall.sh"
