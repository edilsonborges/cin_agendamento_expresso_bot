#!/usr/bin/env bash
# Sobe tudo num comando: cloudflared + bot serve + setup-webhook.
# Uso: ./scripts/run.sh {start|stop|restart|status|logs}
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PIDS_DIR="$ROOT/.run"
mkdir -p "$PIDS_DIR"

BOT_PID_FILE="$PIDS_DIR/bot.pid"
TUNNEL_PID_FILE="$PIDS_DIR/tunnel.pid"
TUNNEL_URL_FILE="$PIDS_DIR/tunnel.url"
BOT_LOG="$ROOT/bot.log"
TUNNEL_LOG="$ROOT/cloudflared.log"

PYTHON="$ROOT/.venv/bin/python"

die() {
  echo "ERRO: $*" >&2
  exit 1
}

is_running() {
  local pidfile="$1"
  [[ -f "$pidfile" ]] || return 1
  local pid
  pid="$(cat "$pidfile")"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

require() {
  command -v "$1" >/dev/null 2>&1 || die "$1 não instalado. ${2:-}"
}

cmd_start() {
  [[ -x "$PYTHON" ]] || die "venv ausente em .venv/. Rode: make install"
  require cloudflared "Instale com: brew install cloudflared"
  [[ -f "$ROOT/.env" ]] || die ".env ausente. Copie de .env.example e preencha."

  if is_running "$BOT_PID_FILE"; then
    echo "✓ bot já está rodando (PID $(cat "$BOT_PID_FILE"))"
    if [[ -f "$TUNNEL_URL_FILE" ]]; then
      echo "  túnel: $(cat "$TUNNEL_URL_FILE")"
    fi
    return 0
  fi

  rm -f "$ROOT"/state-*.lock

  echo "→ subindo cloudflared..."
  : > "$TUNNEL_LOG"
  nohup cloudflared tunnel --url http://localhost:8080 > "$TUNNEL_LOG" 2>&1 &
  echo $! > "$TUNNEL_PID_FILE"

  local tunnel_url=""
  for _ in $(seq 1 30); do
    sleep 1
    tunnel_url="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -1 || true)"
    [[ -n "$tunnel_url" ]] && break
  done
  [[ -n "$tunnel_url" ]] || { cat "$TUNNEL_LOG"; die "túnel não subiu em 30s"; }
  echo "$tunnel_url" > "$TUNNEL_URL_FILE"
  echo "✓ túnel: $tunnel_url"

  echo "→ subindo bot serve..."
  : > "$BOT_LOG"
  nohup "$PYTHON" -m bot serve > "$BOT_LOG" 2>&1 &
  echo $! > "$BOT_PID_FILE"
  sleep 3
  if ! is_running "$BOT_PID_FILE"; then
    cat "$BOT_LOG"
    rm -f "$BOT_PID_FILE"
    cmd_stop_tunnel
    die "bot não subiu — veja log acima"
  fi
  echo "✓ bot serve rodando (PID $(cat "$BOT_PID_FILE"))"

  echo "→ registrando webhook..."
  "$PYTHON" -m bot setup-webhook "$tunnel_url"

  echo
  echo "Tudo no ar. Mande /init no Telegram."
  echo "  logs:    $0 logs"
  echo "  parar:   $0 stop"
  echo "  status:  $0 status"
}

cmd_stop_tunnel() {
  if is_running "$TUNNEL_PID_FILE"; then
    kill "$(cat "$TUNNEL_PID_FILE")" 2>/dev/null || true
    echo "✓ cloudflared parado"
  fi
  rm -f "$TUNNEL_PID_FILE" "$TUNNEL_URL_FILE"
}

cmd_stop() {
  if is_running "$BOT_PID_FILE"; then
    kill "$(cat "$BOT_PID_FILE")" 2>/dev/null || true
    echo "✓ bot serve parado"
  fi
  rm -f "$BOT_PID_FILE"
  cmd_stop_tunnel
  rm -f "$ROOT"/state-*.lock
}

cmd_status() {
  if is_running "$BOT_PID_FILE"; then
    echo "✓ bot serve   — PID $(cat "$BOT_PID_FILE")"
  else
    echo "✗ bot serve   — parado"
  fi
  if is_running "$TUNNEL_PID_FILE"; then
    echo "✓ cloudflared — PID $(cat "$TUNNEL_PID_FILE")"
    [[ -f "$TUNNEL_URL_FILE" ]] && echo "  URL: $(cat "$TUNNEL_URL_FILE")"
  else
    echo "✗ cloudflared — parado"
  fi
}

cmd_logs() {
  [[ -f "$BOT_LOG" ]] || die "sem log ainda — rode '$0 start' primeiro"
  exec tail -f "$BOT_LOG"
}

case "${1:-start}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; sleep 1; cmd_start ;;
  status)  cmd_status ;;
  logs)    cmd_logs ;;
  *)
    echo "uso: $0 {start|stop|restart|status|logs}" >&2
    exit 2
    ;;
esac
