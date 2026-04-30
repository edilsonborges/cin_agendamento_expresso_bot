#!/usr/bin/env bash
# Remove o LaunchAgent. Idempotente.
set -euo pipefail

PLIST_DEST="$HOME/Library/LaunchAgents/com.edilson.cin-agendamento-bot.plist"

if [ -f "$PLIST_DEST" ]; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    rm -f "$PLIST_DEST"
    echo "Removido: $PLIST_DEST"
else
    echo "Nada para remover (não estava instalado)."
fi
