"""Loop principal: poll → diff → notify → sleep com jitter.

Desenho:
  - Cada iteração trata erros transientes localmente (backoff exponencial).
  - PermanentError loga FATAL e mantém loop (humano precisa intervir).
  - SIGINT/SIGTERM → graceful shutdown salvando estado.
  - Lockfile (`state.lock`) impede dupla instância (R7).
  - Rate limit de notificação: 60s mínimo entre alertas (FR-12).
"""

from __future__ import annotations

import fcntl
import logging
import os
import random
import signal
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .change_detector import Diff, compute_diff, unidades_to_map
from .config import Settings
from .errors import PermanentError, TransientError
from .expresso_client import ExpressoClient
from .state_store import State, StateStore, hash_datas, now_iso
from .telegram_notifier import TelegramNotifier, format_message

logger = logging.getLogger(__name__)

BACKOFF_WAITS = [30, 60, 120, 240, 600]
NOTIFICATION_RATE_LIMIT_SECONDS = 60
DEFAULT_MUNICIPIO_NOME = "GOIÂNIA"


class _Backoff:
    def __init__(self) -> None:
        self._tries = 0

    def next_wait(self) -> int:
        idx = min(self._tries, len(BACKOFF_WAITS) - 1)
        self._tries += 1
        return BACKOFF_WAITS[idx]

    def reset(self) -> None:
        self._tries = 0


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Lock exclusivo via flock — segunda instância falha imediatamente."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fp = open(path, "w", encoding="utf-8")
    try:
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                f"Outra instância já está rodando (lock em {path}). "
                "Verifique com `ps aux | grep cin_agendamento`."
            ) from exc
        fp.write(str(os.getpid()))
        fp.flush()
        try:
            yield
        finally:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
    finally:
        fp.close()
        try:
            path.unlink()
        except OSError:
            pass


class Scheduler:
    def __init__(
        self,
        *,
        settings: Settings,
        client: ExpressoClient,
        notifier: TelegramNotifier | None,
        store: StateStore,
        municipio_nome: str = DEFAULT_MUNICIPIO_NOME,
        dry_run: bool = False,
    ) -> None:
        self._settings = settings
        self._client = client
        self._notifier = notifier
        self._store = store
        self._municipio_nome = municipio_nome
        self._dry_run = dry_run
        self._running = True
        self._backoff = _Backoff()

    def stop(self, *_args: object) -> None:
        if self._running:
            logger.info("shutdown sinalizado — encerrando após iteração corrente")
        self._running = False

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

    def run_forever(self) -> None:
        logger.info(
            "loop iniciado municipio=%d id_senha=%d intervalo=%ds±%ds",
            self._settings.cod_municipio,
            self._settings.id_senha,
            self._settings.poll_interval_seconds,
            self._settings.jitter_seconds,
        )
        while self._running:
            try:
                self.run_once()
                self._backoff.reset()
            except TransientError as exc:
                self._record_error()
                wait = self._backoff.next_wait()
                logger.warning("transient=%s — backoff=%ds", exc, wait)
                self._sleep_interruptible(wait)
                continue
            except PermanentError as exc:
                self._record_error()
                logger.error("FATAL permanent=%s — mantendo loop, intervenção necessária", exc)
            except Exception:
                self._record_error()
                logger.exception("erro inesperado — mantendo loop")

            self._sleep_interruptible(self._next_interval())

        logger.info("loop encerrado")

    def run_once(self) -> Diff:
        state = self._store.load()
        unidades = self._client.fetch_datas(self._settings.id_senha, self._settings.cod_municipio)
        curr_map = unidades_to_map(unidades)
        curr_hash = hash_datas(curr_map)

        diff = compute_diff(state.datas_por_unidade, curr_map)
        total_curr = sum(len(v) for v in curr_map.values())
        is_first_open = state.is_empty and bool(curr_map)

        action = "noop"
        if diff.has_news:
            if self._dry_run or self._notifier is None:
                action = "would-notify(dry-run)"
            elif self._too_soon_since_last_notification(state):
                action = "suppressed(rate-limit)"
            else:
                msg = format_message(
                    self._municipio_nome,
                    diff,
                    is_first_open=is_first_open,
                )
                if self._notifier.send_text(msg):
                    action = "notified"
                    state.last_notification_at = now_iso()
                    state.total_notifications += 1
                else:
                    action = "notify-failed"

        if not self._dry_run:
            state.total_polls += 1
        state.last_check_at = now_iso()
        state.id_senha = self._settings.id_senha
        state.cod_municipio = self._settings.cod_municipio

        if action in ("notified", "noop", "would-notify(dry-run)"):
            if state.hash != curr_hash:
                state.last_change_at = now_iso()
            state.datas_por_unidade = curr_map
            state.hash = curr_hash

        self._store.save(state)

        logger.info(
            "[poll] municipio=%d datas=%d unidades=%d acao=%s",
            self._settings.cod_municipio,
            total_curr,
            len(curr_map),
            action,
        )
        return diff

    def _record_error(self) -> None:
        """Incrementa contador de erros, defensivo a falhas de I/O."""
        try:
            state = self._store.load()
            state.total_errors += 1
            self._store.save(state)
        except Exception:
            logger.exception("não foi possível persistir total_errors")

    def _too_soon_since_last_notification(self, state: State) -> bool:
        if not state.last_notification_at:
            return False
        try:
            last = datetime.fromisoformat(state.last_notification_at)
        except ValueError:
            return False
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        delta = (datetime.now(timezone.utc) - last.astimezone(timezone.utc)).total_seconds()
        return delta < NOTIFICATION_RATE_LIMIT_SECONDS

    def _next_interval(self) -> int:
        base = self._settings.poll_interval_seconds
        jitter = self._settings.jitter_seconds
        return max(60, int(base + random.uniform(-jitter, jitter)))

    def _sleep_interruptible(self, seconds: int) -> None:
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            time.sleep(min(1.0, end - time.monotonic()))
