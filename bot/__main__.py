"""CLI: `python -m bot {init|check|status|doctor|run}`.

init    → polling getUpdates por até 5 min até receber /start; salva chat_id no `.env`.
check   → 1 fetch dry-run, imprime estado atual (smoke test).
status  → lê state file local e imprime resumo (sem rede).
doctor  → diagnóstico: valida config + testa conectividade Goiás + Telegram (sem enviar msg).
run     → loop infinito de produção com lockfile e signal handlers.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from . import __version__
from .config import (
    ENV_PATH,
    PROJECT_ROOT,
    Settings,
    load_settings,
    require_goias,
    require_telegram,
)
from .expresso_client import ExpressoClient
from .logging_setup import setup_logging
from .scheduler import Scheduler, file_lock
from .state_store import StateStore
from .telegram_notifier import TelegramInit, TelegramNotifier

logger = logging.getLogger(__name__)

LOG_FILE = PROJECT_ROOT / "bot.log"
INIT_TIMEOUT_SECONDS = 5 * 60


def _state_path(cod_municipio: int) -> Path:
    """state-25300.json — permite instâncias paralelas para municípios distintos (PRD §15.4).

    Mantém compatibilidade: se já existe um `state.json` legado, usa-o.
    """
    legacy = PROJECT_ROOT / "state.json"
    if legacy.exists():
        return legacy
    return PROJECT_ROOT / f"state-{cod_municipio}.json"


def _lock_path(cod_municipio: int) -> Path:
    return PROJECT_ROOT / f"state-{cod_municipio}.lock"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bot", description="cin_agendamento_expresso_bot")
    parser.add_argument(
        "--version",
        action="version",
        version=f"cin_agendamento_expresso_bot {__version__}",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="descobrir chat_id via /start no Telegram")
    sub.add_parser("check", help="1 verificação dry-run (smoke test)")
    sub.add_parser("status", help="resumo do state file local (sem rede)")
    sub.add_parser("doctor", help="diagnóstico de config + conectividade")
    run_p = sub.add_parser("run", help="loop principal (produção)")
    run_p.add_argument(
        "--once",
        action="store_true",
        help="executa 1 iteração e sai (útil para cron externo em vez do loop interno)",
    )

    args = parser.parse_args(argv)
    settings = load_settings()
    setup_logging(settings.log_level, LOG_FILE)

    try:
        if args.cmd == "init":
            return cmd_init(settings)
        if args.cmd == "check":
            return cmd_check(settings)
        if args.cmd == "status":
            return cmd_status(settings)
        if args.cmd == "doctor":
            return cmd_doctor(settings)
        if args.cmd == "run":
            return cmd_run(settings, once=getattr(args, "once", False))
    except RuntimeError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    parser.error(f"comando desconhecido: {args.cmd}")
    return 2


def cmd_check(settings: Settings) -> int:
    """Smoke test: faz 1 fetch e imprime resultado, sem notificar."""
    require_goias(settings)
    client = ExpressoClient(settings.goias_oauth_basic, settings.goias_referer)
    store = StateStore(_state_path(settings.cod_municipio))
    scheduler = Scheduler(
        settings=settings,
        client=client,
        notifier=None,
        store=store,
        dry_run=True,
    )
    started = time.monotonic()
    diff = scheduler.run_once()
    elapsed = time.monotonic() - started

    state = store.load()
    print(f"--- check completo em {elapsed:.2f}s ---")
    print(f"municipio={settings.cod_municipio} id_senha={settings.id_senha}")
    print(f"unidades_com_vagas={len(state.datas_por_unidade)}")
    if state.datas_por_unidade:
        for nome, datas in state.datas_por_unidade.items():
            print(f"  • {nome}: {len(datas)} datas → {datas[:5]}{'...' if len(datas) > 5 else ''}")
    else:
        print("  (vazio — sem vagas no momento)")
    if diff.has_news:
        print("→ teria notificado (dry-run)")
    return 0


def cmd_status(settings: Settings) -> int:
    """Resumo offline do state file. Útil para inspeção rápida sem hit na API."""
    path = _state_path(settings.cod_municipio)
    print("--- status ---")
    print(f"municipio={settings.cod_municipio} id_senha={settings.id_senha}")
    print(f"state_file={path}")
    if not path.exists():
        print("  (nenhum state ainda — rode `python -m bot check` ou `run` primeiro)")
        return 0
    state = StateStore(path).load()
    print(f"last_check_at={state.last_check_at or '(nunca)'}")
    print(f"last_change_at={state.last_change_at or '(nunca)'}")
    print(f"last_notification_at={state.last_notification_at or '(nunca)'}")
    print(f"hash={state.hash[:16]}{'…' if state.hash else '(vazio)'}")
    print(
        f"contadores: polls={state.total_polls} "
        f"notificações={state.total_notifications} "
        f"erros={state.total_errors}"
    )
    print(f"unidades_com_vagas={len(state.datas_por_unidade)}")
    if state.datas_por_unidade:
        for nome, datas in state.datas_por_unidade.items():
            print(f"  • {nome}: {len(datas)} datas")
    else:
        print("  (vazio)")
    return 0


def cmd_doctor(settings: Settings) -> int:
    """Diagnóstico: valida config, testa auth Goiás, valida Telegram via /getMe.

    Não envia mensagem. Retorna 0 se tudo OK, 1 se algum teste falhou.
    """
    import requests

    failures = 0
    print("--- doctor ---")

    # 1. Configuração obrigatória
    print("[1/4] config:")
    issues = _doctor_check_config(settings)
    for line in issues:
        print(f"      ✗ {line}")
        failures += 1
    if not issues:
        print("      ✓ todas as variáveis obrigatórias presentes")

    # 2. Auth Goiás (POST /token)
    print("[2/4] goias auth (POST /token):")
    if not settings.goias_oauth_basic:
        print("      - skip (GOIAS_OAUTH_BASIC ausente)")
        failures += 1
    else:
        try:
            client = ExpressoClient(settings.goias_oauth_basic, settings.goias_referer, timeout=5)
            token = client.get_access_token()
            print(f"      ✓ token obtido ({len(token)} chars)")
        except Exception as exc:  # noqa: BLE001
            print(f"      ✗ falhou: {exc}")
            failures += 1

    # 3. Goiás listarDatas (sanity)
    print("[3/4] goias listarDatas:")
    if not settings.goias_oauth_basic:
        print("      - skip (sem token)")
    else:
        try:
            client = ExpressoClient(settings.goias_oauth_basic, settings.goias_referer, timeout=5)
            unidades = client.fetch_datas(settings.id_senha, settings.cod_municipio)
            total = sum(len(u.datas) for u in unidades)
            print(f"      ✓ resposta OK — {len(unidades)} unidade(s), {total} data(s) total")
        except Exception as exc:  # noqa: BLE001
            print(f"      ✗ falhou: {exc}")
            failures += 1

    # 4. Telegram /getMe
    print("[4/4] telegram (/getMe):")
    if not settings.telegram_bot_token:
        print("      - skip (TELEGRAM_BOT_TOKEN ausente)")
        failures += 1
    else:
        try:
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200 and resp.json().get("ok"):
                username = resp.json().get("result", {}).get("username", "?")
                print(f"      ✓ bot @{username} responde")
            else:
                print(f"      ✗ status={resp.status_code} body={resp.text[:100]}")
                failures += 1
        except Exception as exc:  # noqa: BLE001
            print(f"      ✗ falhou: {exc}")
            failures += 1

    print()
    if failures == 0:
        print("✓ tudo OK")
        return 0
    print(f"✗ {failures} problema(s)")
    return 1


def _doctor_check_config(settings: Settings) -> list[str]:
    """Lista os problemas de configuração — vazia se tudo OK."""
    issues = []
    if not settings.goias_oauth_basic:
        issues.append("GOIAS_OAUTH_BASIC ausente")
    if not settings.goias_referer:
        issues.append("GOIAS_REFERER ausente")
    if not settings.telegram_bot_token:
        issues.append("TELEGRAM_BOT_TOKEN ausente (necessário para run/init)")
    if not settings.has_chat_id:
        issues.append("TELEGRAM_CHAT_ID ausente (necessário para run; rode `bot init` antes)")
    if settings.poll_interval_seconds < 60:
        issues.append(
            f"POLL_INTERVAL_SECONDS={settings.poll_interval_seconds} < 60 (agressivo demais)"
        )
    return issues


def cmd_run(settings: Settings, *, once: bool = False) -> int:
    require_goias(settings)
    require_telegram(settings, need_chat_id=True)

    client = ExpressoClient(settings.goias_oauth_basic, settings.goias_referer)
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.chat_id_int)
    store = StateStore(_state_path(settings.cod_municipio))
    scheduler = Scheduler(
        settings=settings,
        client=client,
        notifier=notifier,
        store=store,
    )

    try:
        with file_lock(_lock_path(settings.cod_municipio)):
            if once:
                scheduler.run_once()
            else:
                scheduler.install_signal_handlers()
                scheduler.run_forever()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    return 0


def cmd_init(settings: Settings) -> int:
    require_telegram(settings, need_chat_id=False)

    init = TelegramInit(settings.telegram_bot_token)
    print(f"Aguardando /start no Telegram (timeout {INIT_TIMEOUT_SECONDS // 60} min)...")
    print("Abra o bot e mande /start.")

    last_update_id: int | None = None
    deadline = time.monotonic() + INIT_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        try:
            updates = init.get_updates(
                offset=last_update_id + 1 if last_update_id is not None else None
            )
        except Exception as exc:
            logger.error("getUpdates falhou: %s", exc)
            time.sleep(3)
            continue

        for update in updates:
            update_id = int(update.get("update_id", 0))
            if last_update_id is None or update_id > last_update_id:
                last_update_id = update_id
            message = update.get("message") or {}
            text = (message.get("text") or "").strip()
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            if text.startswith("/start") and chat_id is not None:
                _persist_chat_id(int(chat_id))
                init.reply(int(chat_id), "Chat ID salvo. Pode rodar `python -m bot run`.")
                print(f"chat_id={chat_id} salvo em {ENV_PATH}")
                return 0

        time.sleep(2)

    print("Timeout — nenhum /start recebido. Tente de novo.")
    return 1


def _persist_chat_id(chat_id: int) -> None:
    """Atualiza/insere TELEGRAM_CHAT_ID no .env preservando demais linhas."""
    path = ENV_PATH
    line_to_write = f"TELEGRAM_CHAT_ID={chat_id}"

    if not path.exists():
        path.write_text(line_to_write + "\n", encoding="utf-8")
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("TELEGRAM_CHAT_ID="):
            lines[i] = line_to_write
            found = True
            break
    if not found:
        lines.append(line_to_write)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
