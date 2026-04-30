"""Loop principal: poll → diff → notify → sleep com jitter.

Modelo multi-município (Phase 2):
  - O Scheduler descobre dinamicamente quais municípios pollar a partir do
    `subscriber_store.municipios_distintos()`.
  - Pra cada município ativo, mantém um `StateStore` independente (criado
    sob demanda via `state_factory(cod) -> StateStore`).
  - Cada município é processado em sequência dentro de `run_once()`.

Tratamento de erros:
  - Erros transientes em UM município não derrubam os outros: são logados
    como `total_errors` no state daquele município e a iteração continua.
  - Apenas erros catastróficos (ex: subscriber_store ilegível) sobem.
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
from typing import Callable, Iterator

from .change_detector import Diff, compute_diff, unidades_to_map
from .config import Settings
from .errors import PermanentError, TransientError
from .expresso_client import ExpressoClient
from .municipios import por_codigo
from .state_store import State, StateStore, hash_datas, now_iso
from .subscriber_store import SubscriberStore
from .telegram_notifier import BroadcastResult, TelegramNotifier, format_message

logger = logging.getLogger(__name__)

BACKOFF_WAITS = [30, 60, 120, 240, 600]
NOTIFICATION_RATE_LIMIT_SECONDS = 60


StateFactory = Callable[[int], StateStore]


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
        store: StateStore | None = None,
        state_factory: StateFactory | None = None,
        subscriber_store: SubscriberStore | None = None,
        municipio_nome: str | None = None,
        dry_run: bool = False,
    ) -> None:
        self._settings = settings
        self._client = client
        self._notifier = notifier
        self._dry_run = dry_run
        self._running = True
        self._backoff = _Backoff()
        self._subscriber_store = subscriber_store

        # Estado por município. `store` (legado) atende ao caminho mono-municipio.
        # `state_factory` é o caminho multi-município novo.
        self._legacy_store: StateStore | None = store
        self._state_factory: StateFactory | None = state_factory
        self._state_cache: dict[int, StateStore] = {}
        self._municipio_nome_legacy = municipio_nome or _resolve_municipio_nome(
            settings.cod_municipio
        )
        # Cronograma por município (modo multi): próximo tempo monotonic em que
        # cada cod deve ser processado. Valor 0 = nunca processado, processa
        # imediatamente (com pequeno stagger pra não bater todos no mesmo tick).
        self._next_per_municipio: dict[int, float] = {}
        # Por chat, conjunto de códigos cujos polls já completaram desde a
        # última mensagem enviada. Quando o set cobre todos os municípios do
        # chat, mandamos UMA mensagem agregada e resetamos.
        self._polled_since_last: dict[int, set[int]] = {}

    # ---------- snapshot agregado ----------

    def snapshot(self) -> dict:
        """Retorna estado leve para o /status do Telegram. Agrega múltiplos municípios."""
        if self._subscriber_store is not None and self._state_factory is not None:
            municipios = sorted(self._subscriber_store.municipios_distintos())
            last_check = ""
            total_polls = 0
            unidades = 0
            for cod in municipios:
                store = self._get_state_store(cod)
                if store is None:
                    continue
                state = store.load()
                total_polls += state.total_polls
                unidades += len(state.datas_por_unidade)
                if state.last_check_at and state.last_check_at > last_check:
                    last_check = state.last_check_at
            return {
                "last_check_at": last_check or None,
                "municipios_ativos": len(municipios),
                "unidades_com_vagas": unidades,
                "total_polls": total_polls,
            }
        # Caminho legado (mono-municipio).
        if self._legacy_store is None:
            return {
                "last_check_at": None,
                "municipios_ativos": 0,
                "unidades_com_vagas": 0,
                "total_polls": 0,
            }
        state = self._legacy_store.load()
        return {
            "last_check_at": state.last_check_at,
            "last_change_at": state.last_change_at,
            "unidades_com_vagas": len(state.datas_por_unidade),
            "total_polls": state.total_polls,
        }

    # ---------- ciclo de vida ----------

    def stop(self, *_args: object) -> None:
        if self._running:
            logger.info("shutdown sinalizado — encerrando após iteração corrente")
        self._running = False

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

    def run_forever(self) -> None:
        logger.info(
            "loop iniciado id_senha=%d intervalo=%ds±%ds",
            self._settings.id_senha,
            self._settings.poll_interval_seconds,
            self._settings.jitter_seconds,
        )
        while self._running:
            try:
                self.run_once()
                self._backoff.reset()
            except TransientError as exc:
                self._record_error_legacy()
                wait = self._backoff.next_wait()
                logger.warning("transient=%s — backoff=%ds", exc, wait)
                self._sleep_interruptible(wait)
                continue
            except PermanentError as exc:
                self._record_error_legacy()
                logger.error(
                    "FATAL permanent=%s — mantendo loop, intervenção necessária", exc
                )
            except Exception:
                self._record_error_legacy()
                logger.exception("erro inesperado — mantendo loop")

            self._sleep_interruptible(self._next_interval())

        logger.info("loop encerrado")

    # ---------- run_once ----------

    def run_once(self) -> Diff:
        """Itera todos os municípios ativos. Devolve um Diff agregado (com_news se algum teve)."""
        # Modo multi-município (Phase 2): só ativa quando temos state_factory + subscribers.
        if self._state_factory is not None and self._subscriber_store is not None:
            return self._run_once_multi()
        # Modo legado (mono-municipio): mantém compatibilidade com testes/old run.
        return self._run_once_legacy()

    def _run_once_multi(self) -> Diff:
        """Processa apenas os municípios cujo agendamento já venceu.

        Cada município tem um `next_per_municipio[cod]` independente, atualizado
        após cada processamento com `_next_interval()` aleatório. Isso evita
        que vários municípios batam a API ao mesmo tempo (anti-banimento).
        """
        assert self._subscriber_store is not None
        if self._subscriber_store.is_empty():
            logger.debug("[poll] sem municípios ativos — skip")
            return compute_diff({}, {})
        now = time.monotonic()
        codigos = sorted(self._subscriber_store.municipios_distintos())
        # Limpa cronogramas de municípios que ninguém quer mais.
        for cod_orfao in [c for c in self._next_per_municipio if c not in codigos]:
            self._next_per_municipio.pop(cod_orfao, None)

        agg_has_news = False
        for cod in codigos:
            # Primeira vez que vemos esse cod: processa imediatamente.
            # Polls subsequentes seguem o intervalo aleatório.
            if cod not in self._next_per_municipio:
                self._next_per_municipio[cod] = now
            if now < self._next_per_municipio[cod]:
                continue  # ainda não venceu
            try:
                d = self._handle_municipio(cod)
                if d.has_news:
                    agg_has_news = True
                self._next_per_municipio[cod] = time.monotonic() + self._next_interval()
            except TransientError as exc:
                logger.warning("[poll] municipio=%d transient=%s", cod, exc)
                self._record_error_for(cod)
                self._next_per_municipio[cod] = time.monotonic() + self._backoff.next_wait()
            except PermanentError as exc:
                logger.error("[poll] municipio=%d permanent=%s — mantendo loop", cod, exc)
                self._record_error_for(cod)
                self._next_per_municipio[cod] = time.monotonic() + self._next_interval()
            except Exception:
                logger.exception("[poll] municipio=%d erro inesperado", cod)
                self._record_error_for(cod)
                self._next_per_municipio[cod] = time.monotonic() + self._next_interval()
        return compute_diff({"_": []}, {"_": []}) if not agg_has_news else Diff(has_news=True)

    def _handle_municipio(self, cod: int) -> Diff:
        """Processa um único município: fetch, diff, broadcast, persist."""
        assert self._subscriber_store is not None
        state_store = self._get_state_store(cod)
        if state_store is None:
            logger.warning("[poll] municipio=%d sem state_factory — skip", cod)
            return compute_diff({}, {})

        nome = _resolve_municipio_nome(cod)
        state = state_store.load()
        unidades = self._client.fetch_datas(self._settings.id_senha, cod)
        curr_map = unidades_to_map(unidades)
        curr_hash = hash_datas(curr_map)

        diff = compute_diff(state.datas_por_unidade, curr_map)
        total_curr = sum(len(v) for v in curr_map.values())
        is_first_open = state.is_empty and bool(curr_map)
        chat_ids = list(self._subscriber_store.chats_para(cod))

        # Persiste estado novo ANTES de renderizar dashboard, para que ele
        # reflita o resultado deste poll.
        if not self._dry_run:
            state.total_polls += 1
        state.last_check_at = now_iso()
        state.id_senha = self._settings.id_senha
        state.cod_municipio = cod
        if state.hash != curr_hash:
            state.last_change_at = now_iso()
            if diff.has_news and not self._dry_run:
                state.last_notification_at = now_iso()
                state.total_notifications += 1
        state.datas_por_unidade = curr_map
        state.hash = curr_hash
        state_store.save(state)

        # Acumula este município no "set já pollado" de cada chat afetado.
        # Só manda mensagem quando TODOS os municípios do chat completaram
        # um poll desde a última mensagem — assim o user recebe um update
        # consolidado por ciclo, não 1 por município.
        action = "noop"
        if self._dry_run or self._notifier is None:
            action = "would-send(dry-run)"
        elif not chat_ids:
            action = "no-subs"
        else:
            sent_count = 0
            partial_count = 0
            pause_kb = {
                "inline_keyboard": [
                    [{"text": "⏸ Pausar busca", "callback_data": "pause"}]
                ]
            }
            for chat_id in chat_ids:
                polled = self._polled_since_last.setdefault(chat_id, set())
                polled.add(cod)
                desejados = self._subscriber_store.municipios_de(chat_id)
                if not desejados.issubset(polled):
                    partial_count += 1
                    continue
                text = self._render_dashboard_for(chat_id)
                result = self._notifier.send_to(
                    chat_id, text, parse_mode="", reply_markup=pause_kb
                )
                if result.ok:
                    sent_count += 1
                self._polled_since_last[chat_id] = set()  # reset após enviar
            action = f"sent={sent_count} partial={partial_count}"
        logger.info(
            "[poll] municipio=%d datas=%d unidades=%d acao=%s subs=%d",
            cod,
            total_curr,
            len(curr_map),
            action,
            len(chat_ids),
        )
        return diff

    def _run_once_legacy(self) -> Diff:
        """Comportamento Phase 1: 1 município (vindo de settings) + broadcast unificado."""
        assert self._legacy_store is not None or self._notifier is None or self._dry_run
        if self._subscriber_store is not None and self._subscriber_store.is_empty():
            logger.debug("[poll] sem subscribers — skip")
            return compute_diff({}, {})

        if self._legacy_store is None:
            # Sem store, mas chamado em dry_run → ainda fetch para devolver Diff.
            unidades = self._client.fetch_datas(
                self._settings.id_senha, self._settings.cod_municipio
            )
            curr_map = unidades_to_map(unidades)
            return compute_diff({}, curr_map)

        state = self._legacy_store.load()
        unidades = self._client.fetch_datas(
            self._settings.id_senha, self._settings.cod_municipio
        )
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
                    self._municipio_nome_legacy,
                    diff,
                    is_first_open=is_first_open,
                )
                if self._subscriber_store is not None:
                    chat_ids = list(self._subscriber_store.all_chats())
                    results = self._notifier.broadcast(chat_ids, msg)
                    ok_count = sum(1 for r in results if r.ok)
                    self._handle_broadcast_results_legacy(results)
                    if ok_count > 0:
                        action = f"broadcast({ok_count}/{len(results)})"
                        state.last_notification_at = now_iso()
                        state.total_notifications += 1
                    else:
                        action = "broadcast-all-failed"
                else:
                    if self._notifier.send_text(msg):
                        action = "notified"
                        state.last_notification_at = now_iso()
                        state.total_notifications += 1
                    else:
                        action = "notify-failed"
        elif (
            self._settings.verbose_polls
            and self._subscriber_store is not None
            and not self._dry_run
            and self._notifier is not None
        ):
            verbose_msg = _format_verbose_status(
                self._municipio_nome_legacy, curr_map, total_curr, state.total_polls + 1
            )
            chat_ids = list(self._subscriber_store.all_chats())
            results = self._notifier.broadcast(chat_ids, verbose_msg, parse_mode="")
            ok_count = sum(1 for r in results if r.ok)
            self._handle_broadcast_results_legacy(results)
            action = f"verbose-broadcast({ok_count}/{len(results)})"

        if not self._dry_run:
            state.total_polls += 1
        state.last_check_at = now_iso()
        state.id_senha = self._settings.id_senha
        state.cod_municipio = self._settings.cod_municipio

        if (
            action in ("notified", "noop", "would-notify(dry-run)")
            or action.startswith("broadcast(")
            or action.startswith("verbose-broadcast(")
        ):
            if state.hash != curr_hash:
                state.last_change_at = now_iso()
            state.datas_por_unidade = curr_map
            state.hash = curr_hash

        self._legacy_store.save(state)

        logger.info(
            "[poll] municipio=%d datas=%d unidades=%d acao=%s",
            self._settings.cod_municipio,
            total_curr,
            len(curr_map),
            action,
        )
        return diff

    # ---------- helpers ----------

    def _get_state_store(self, cod: int) -> StateStore | None:
        if self._state_factory is None:
            return None
        if cod not in self._state_cache:
            self._state_cache[cod] = self._state_factory(cod)
        return self._state_cache[cod]

    def _handle_broadcast_results(
        self, cod: int, results: list[BroadcastResult]
    ) -> None:
        """Remove apenas o município (não o chat inteiro) quando 403."""
        if self._subscriber_store is None:
            return
        for r in results:
            if not r.ok and r.http_status == 403:
                self._subscriber_store.remove_municipio(r.chat_id, cod)
                logger.info(
                    "removido municipio=%d do chat_id=***%s status=403",
                    cod,
                    str(r.chat_id)[-2:],
                )

    def _handle_broadcast_results_legacy(self, results: list[BroadcastResult]) -> None:
        """Comportamento legado: 403 remove o chat inteiro."""
        if self._subscriber_store is None:
            return
        for r in results:
            if not r.ok and r.http_status == 403:
                self._subscriber_store.remove_chat(r.chat_id)
                logger.info(
                    "removido subscriber chat_id=***%s status=403",
                    str(r.chat_id)[-2:],
                )

    def _record_error_for(self, cod: int) -> None:
        store = self._get_state_store(cod)
        if store is None:
            return
        try:
            state = store.load()
            state.total_errors += 1
            store.save(state)
        except Exception:
            logger.exception("não foi possível persistir total_errors municipio=%d", cod)

    def _record_error_legacy(self) -> None:
        """Incrementa contador de erros no store legado, defensivo."""
        if self._legacy_store is None:
            return
        try:
            state = self._legacy_store.load()
            state.total_errors += 1
            self._legacy_store.save(state)
        except Exception:
            logger.exception("não foi possível persistir total_errors")

    # Aliases mantidos por compat com testes existentes.
    def _record_error(self) -> None:
        self._record_error_legacy()

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

    def _render_dashboard_for(self, chat_id: int) -> str:
        """Texto agregado pra um chat — estado de TODOS os municípios que ele assinou."""
        assert self._subscriber_store is not None
        municipios = sorted(self._subscriber_store.municipios_de(chat_id))
        agora = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S")
        lines = [f"🤖 Monitor CIN ({len(municipios)} cidade(s)) — {agora}"]
        lines.append("")
        link_needed = False
        for cod in municipios:
            nome = _resolve_municipio_nome(cod)
            store = self._get_state_store(cod)
            if store is None:
                lines.append(f"⏳ {nome} — aguardando")
                continue
            state = store.load()
            if not state.datas_por_unidade:
                lines.append(f"⏰ {nome} — sem vagas")
                continue
            link_needed = True
            for unidade in sorted(state.datas_por_unidade.keys()):
                datas = state.datas_por_unidade[unidade]
                amostra = ", ".join(datas[:3])
                if len(datas) > 3:
                    amostra += f" (+{len(datas) - 3})"
                lines.append(f"🟢 {nome} — {len(datas)} datas: {amostra}")
        if link_needed:
            lines.append("")
            lines.append(
                "👉 https://www.go.gov.br/servicos-digitais/vapt-vupt/"
                "agendamento-atendimento-presencial/novo/origem-rg"
            )
        return "\n".join(lines)

    def _next_interval(self) -> int:
        base = self._settings.poll_interval_seconds
        jitter = self._settings.jitter_seconds
        return max(60, int(base + random.uniform(-jitter, jitter)))

    def _sleep_interruptible(self, seconds: int) -> None:
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            time.sleep(min(1.0, end - time.monotonic()))


def _resolve_municipio_nome(cod: int) -> str:
    """Lookup do nome no enum de municípios; fallback para o código bruto."""
    m = por_codigo(cod)
    return m.nome if m else f"municipio-{cod}"


def _format_verbose_status(
    municipio_nome: str, curr_map: dict, total_datas: int, poll_n: int
) -> str:
    """Plain text compacto pro modo verbose/teste.

    Sem vagas: linha única com ⏰.
    Com vagas: linha única com 🟢 + amostra (+N outras) + link na linha de baixo.
    """
    if not curr_map:
        return f"⏰ Poll #{poll_n} {municipio_nome} — sem vagas"

    if len(curr_map) == 1:
        # Caso comum (1 unidade): condensa tudo numa linha.
        unidade = next(iter(curr_map))
        datas = curr_map[unidade]
        amostra = ", ".join(datas[:3])
        if len(datas) > 3:
            amostra += f" (+{len(datas) - 3} outras)"
        head = f"🟢 {municipio_nome} — {len(datas)} datas: {amostra}"
        return f"{head}\n👉 https://www.go.gov.br/servicos-digitais/vapt-vupt/agendamento-atendimento-presencial/novo/origem-rg"

    # Múltiplas unidades: 1 linha de header + 1 linha por unidade.
    lines = [f"🟢 {municipio_nome} — {len(curr_map)} unidades, {total_datas} datas"]
    for unidade in sorted(curr_map.keys()):
        datas = curr_map[unidade]
        amostra = ", ".join(datas[:3])
        if len(datas) > 3:
            amostra += f" (+{len(datas) - 3})"
        lines.append(f"  {unidade}: {amostra}")
    lines.append(
        "👉 https://www.go.gov.br/servicos-digitais/vapt-vupt/"
        "agendamento-atendimento-presencial/novo/origem-rg"
    )
    return "\n".join(lines)
