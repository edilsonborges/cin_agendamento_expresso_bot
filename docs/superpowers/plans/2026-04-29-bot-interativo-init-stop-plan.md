# Bot Interativo (`/init` e `/stop`) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar o bot do Telegram controlável remotamente via `/init` (ligar) e `/stop` (desligar) com webhook, broadcasting para múltiplos chats e estado persistido entre restarts.

**Architecture:** Servidor HTTP single-thread (stdlib `http.server`) compartilha loop com o `Scheduler` existente. Webhook recebe updates do Telegram, roteia comandos para um `CommandHandler` que manipula `SubscriberStore` (set persistido em JSON). O scheduler pula iteração quando o set está vazio, e quando detecta vagas faz broadcast pra todos os subscribers.

**Tech Stack:** Python 3.11+, stdlib (`http.server`, `socket`, `secrets`), `requests` (já existente), `python-dotenv` (já existente). Zero dependência runtime nova.

**Spec:** `docs/superpowers/specs/2026-04-29-bot-interativo-init-stop-design.md`

---

## File map

**Novos arquivos:**

| Arquivo | Responsabilidade |
|---|---|
| `bot/subscriber_store.py` | CRUD persistente do `set[chat_id]` em `subscribers.json` (write atômico) |
| `bot/command_handler.py` | Parsing de updates do Telegram + roteamento `/init` `/stop` `/status` |
| `bot/webhook_server.py` | `HTTPServer` stdlib + roteamento `/telegram/webhook` e `/health` + validação de secret token |
| `tests/test_subscriber_store.py` | Cobertura do SubscriberStore |
| `tests/test_command_handler.py` | Cobertura do CommandHandler |
| `tests/test_webhook_server.py` | Cobertura do WebhookServer |
| `tests/test_serve_integration.py` | Integração end-to-end: HTTP → handler → store |

**Arquivos modificados:**

| Arquivo | Mudança |
|---|---|
| `bot/config.py` | +3 campos no `Settings` (webhook_port, webhook_path, webhook_secret_token); poll_interval default → 300 |
| `bot/telegram_notifier.py` | `chat_id` opcional no construtor; novo `broadcast(chat_ids, text) → list[BroadcastResult]`; `BroadcastResult` dataclass |
| `bot/scheduler.py` | Aceita `subscriber_store` em vez de `notifier`; pula iteração se empty; broadcast em vez de send_text; remove subscribers com HTTP 403 |
| `bot/__main__.py` | Subcomandos `serve` e `setup-webhook` |
| `tests/test_config.py` | Testes dos novos campos + default 300 |
| `tests/test_telegram_notifier.py` | Testes de `broadcast` (3 chats, 1 com 403, 1 com 500) |
| `tests/test_scheduler.py` | Testes de "skip empty subscribers" + "broadcast on diff" + "remove on 403" |
| `.env.example` | +3 envs do webhook + `POLL_INTERVAL_SECONDS=300` |
| `README.md` | Seção "Modo interativo (webhook)" + tabela de comandos atualizada |

---

## Task 1: Estender `Settings` com configs do webhook

**Files:**
- Modify: `bot/config.py`
- Modify: `tests/test_config.py`
- Modify: `.env.example`

**Por que primeiro:** todo o resto consome `Settings`. Sem isso, os testes vão estourar com campos faltando.

- [ ] **Step 1.1: Escrever testes que falham**

Adicionar em `tests/test_config.py` (no final do arquivo, antes do último ` ` ou função):

```python
def test_settings_has_webhook_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from bot.config import load_settings, ENV_PATH
    monkeypatch.setattr("bot.config.ENV_PATH", tmp_path / ".env")
    settings = load_settings()
    assert settings.webhook_port == 8080
    assert settings.webhook_path == "/telegram/webhook"
    assert settings.webhook_secret_token == ""  # vazio = será gerado no boot

def test_settings_reads_webhook_from_env(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "WEBHOOK_PORT=9090\n"
        "WEBHOOK_PATH=/hook\n"
        "WEBHOOK_SECRET_TOKEN=abc123\n"
    )
    monkeypatch.setattr("bot.config.ENV_PATH", env)
    from bot.config import load_settings
    settings = load_settings(env)
    assert settings.webhook_port == 9090
    assert settings.webhook_path == "/hook"
    assert settings.webhook_secret_token == "abc123"

def test_settings_poll_interval_default_is_300(monkeypatch, tmp_path):
    monkeypatch.setattr("bot.config.ENV_PATH", tmp_path / ".env")
    from bot.config import load_settings
    settings = load_settings()
    assert settings.poll_interval_seconds == 300
```

- [ ] **Step 1.2: Rodar testes — verificar que falham**

```bash
pytest tests/test_config.py -v -k "webhook or 300"
```

Esperado: 3 FAIL com `AttributeError: 'Settings' object has no attribute 'webhook_port'` e o de 300 com `AssertionError: assert 180 == 300`.

- [ ] **Step 1.3: Modificar `bot/config.py`**

Mudar `DEFAULT_POLL_INTERVAL = 180` → `DEFAULT_POLL_INTERVAL = 300`.

Adicionar constantes (depois das outras DEFAULT_*):
```python
DEFAULT_WEBHOOK_PORT = 8080
DEFAULT_WEBHOOK_PATH = "/telegram/webhook"
```

Estender o dataclass `Settings` (adicionar três campos no final):
```python
    webhook_port: int
    webhook_path: str
    webhook_secret_token: str
```

Estender `load_settings` (adicionar três linhas no `return Settings(...)`):
```python
        webhook_port=_get_int("WEBHOOK_PORT", DEFAULT_WEBHOOK_PORT),
        webhook_path=os.getenv("WEBHOOK_PATH", DEFAULT_WEBHOOK_PATH).strip(),
        webhook_secret_token=os.getenv("WEBHOOK_SECRET_TOKEN", "").strip(),
```

- [ ] **Step 1.4: Rodar testes — verificar que passam**

```bash
pytest tests/test_config.py -v
```

Esperado: todos os testes passando, incluindo os 3 novos.

- [ ] **Step 1.5: Atualizar `.env.example`**

No final do arquivo, antes da seção de Goiás (ou em nova seção dedicada):
```
# ----- Webhook (modo interativo via /init e /stop) -----
WEBHOOK_PORT=8080
WEBHOOK_PATH=/telegram/webhook
WEBHOOK_SECRET_TOKEN=
# ^ deixar vazio: o `serve` gera automaticamente no primeiro boot e persiste no .env
```

E mudar a linha existente:
```
POLL_INTERVAL_SECONDS=180
```
Para:
```
POLL_INTERVAL_SECONDS=300
```

- [ ] **Step 1.6: Commit**

```bash
git add bot/config.py tests/test_config.py .env.example
git commit -m "feat(config): adiciona settings de webhook e ajusta poll para 5min"
```

---

## Task 2: `SubscriberStore` — persistência do set de chat_ids

**Files:**
- Create: `bot/subscriber_store.py`
- Create: `tests/test_subscriber_store.py`

- [ ] **Step 2.1: Criar `tests/test_subscriber_store.py` com testes que falham**

```python
"""Testes do SubscriberStore — persistência atômica do set[chat_id]."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.subscriber_store import SubscriberStore


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "subscribers.json"


def test_empty_when_file_missing(store_path):
    store = SubscriberStore(store_path)
    assert store.is_empty() is True
    assert store.all() == set()


def test_add_creates_file_atomically(store_path):
    store = SubscriberStore(store_path)
    is_new = store.add(123)
    assert is_new is True
    assert store_path.exists()
    data = json.loads(store_path.read_text())
    assert data["subscribers"] == [123]
    assert "updated_at" in data


def test_add_duplicate_returns_false(store_path):
    store = SubscriberStore(store_path)
    store.add(123)
    is_new = store.add(123)
    assert is_new is False
    assert store.all() == {123}


def test_remove_existing_returns_true(store_path):
    store = SubscriberStore(store_path)
    store.add(123)
    store.add(456)
    assert store.remove(123) is True
    assert store.all() == {456}


def test_remove_missing_returns_false(store_path):
    store = SubscriberStore(store_path)
    store.add(123)
    assert store.remove(999) is False
    assert store.all() == {123}


def test_contains(store_path):
    store = SubscriberStore(store_path)
    store.add(123)
    assert store.contains(123) is True
    assert store.contains(999) is False


def test_persists_across_instances(store_path):
    store1 = SubscriberStore(store_path)
    store1.add(123)
    store1.add(456)

    store2 = SubscriberStore(store_path)
    assert store2.all() == {123, 456}


def test_corrupt_file_starts_empty_with_log(store_path, caplog):
    store_path.write_text("{ this is broken json")
    store = SubscriberStore(store_path)
    assert store.is_empty() is True
    assert any(
        "subscribers" in r.message.lower() and "corrompido" in r.message.lower()
        for r in caplog.records
    )


def test_atomic_write_uses_temp_file(store_path, monkeypatch):
    """Escrita atômica: write em .tmp + rename."""
    store = SubscriberStore(store_path)
    # Captura todos os arquivos criados no diretório durante add
    parent = store_path.parent
    before = set(parent.iterdir())
    store.add(123)
    after = set(parent.iterdir())
    # Após add, deve existir só o arquivo final, sem .tmp residual
    new_files = after - before
    assert store_path in new_files
    for p in new_files:
        assert not p.name.endswith(".tmp"), f"arquivo .tmp residual: {p}"
```

- [ ] **Step 2.2: Rodar — verificar que falham**

```bash
pytest tests/test_subscriber_store.py -v
```

Esperado: todos FAIL com `ModuleNotFoundError: No module named 'bot.subscriber_store'`.

- [ ] **Step 2.3: Criar `bot/subscriber_store.py`**

```python
"""Persistência atômica do set de chat_ids subscritos.

Formato em disco (subscribers.json):
    {
      "subscribers": [123, 456],
      "updated_at": "2026-04-29T14:32:01+00:00"
    }

Escrita: write para `<path>.tmp` + `os.replace` (atômico no POSIX).
Recuperação: arquivo corrompido → start vazio + log warning (não falha).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class SubscriberStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache: set[int] = self._load()

    def add(self, chat_id: int) -> bool:
        """Adiciona chat_id. Retorna True se era novo, False se já existia."""
        if chat_id in self._cache:
            return False
        self._cache.add(chat_id)
        self._persist()
        return True

    def remove(self, chat_id: int) -> bool:
        """Remove chat_id. Retorna True se existia, False caso contrário."""
        if chat_id not in self._cache:
            return False
        self._cache.discard(chat_id)
        self._persist()
        return True

    def contains(self, chat_id: int) -> bool:
        return chat_id in self._cache

    def all(self) -> set[int]:
        return set(self._cache)

    def is_empty(self) -> bool:
        return not self._cache

    def _load(self) -> set[int]:
        if not self._path.exists():
            return set()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            subs = data.get("subscribers", [])
            return {int(x) for x in subs}
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            logger.warning(
                "subscribers.json corrompido (%s) — começando com set vazio", exc
            )
            return set()

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "subscribers": sorted(self._cache),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self._path)
```

- [ ] **Step 2.4: Rodar — verificar que passam**

```bash
pytest tests/test_subscriber_store.py -v
```

Esperado: todos PASS.

- [ ] **Step 2.5: Adicionar `subscribers.json` ao `.gitignore`**

Editar `.gitignore`, adicionar logo abaixo da linha `state-*.lock`:
```
subscribers.json
```

- [ ] **Step 2.6: Commit**

```bash
git add bot/subscriber_store.py tests/test_subscriber_store.py .gitignore
git commit -m "feat: SubscriberStore persistente para chat_ids do Telegram"
```

---

## Task 3: Refatorar `TelegramNotifier` para suportar broadcast

**Files:**
- Modify: `bot/telegram_notifier.py`
- Modify: `tests/test_telegram_notifier.py`

**Mudança de design:** `chat_id` no construtor vira opcional. Adiciona método `broadcast(chat_ids, text) -> list[BroadcastResult]`. Extrai `_send_to(chat_id, text, parse_mode)` privado para evitar duplicação.

- [ ] **Step 3.1: Adicionar testes que falham em `tests/test_telegram_notifier.py`**

Adicionar imports no topo:
```python
from bot.telegram_notifier import BroadcastResult
```

Adicionar testes (no final do arquivo):

```python
@responses.activate
def test_broadcast_three_chats_one_403_one_500_one_ok():
    """Broadcast: ok=200, blocked=403 (com http_status), erro 500 (depois esgota)."""
    notifier = TelegramNotifier("TOKEN_TESTE")  # sem chat_id

    def chat_url(chat_id):
        return "https://api.telegram.org/botTOKEN_TESTE/sendMessage"

    # responses não filtra por payload por default — usamos callback pra discriminar
    def cb(request):
        body = json.loads(request.body)
        cid = body["chat_id"]
        if cid == 111:
            return (200, {}, json.dumps({"ok": True}))
        if cid == 222:
            return (403, {}, json.dumps({"ok": False, "description": "Forbidden: bot was blocked"}))
        # 333 → 500 sempre
        return (500, {}, "boom")

    responses.add_callback(
        responses.POST,
        "https://api.telegram.org/botTOKEN_TESTE/sendMessage",
        callback=cb,
    )

    results = notifier.broadcast([111, 222, 333], "msg")
    by_chat = {r.chat_id: r for r in results}
    assert by_chat[111].ok is True
    assert by_chat[111].http_status == 200
    assert by_chat[222].ok is False
    assert by_chat[222].http_status == 403
    assert by_chat[333].ok is False
    # após esgotar 5xx → 500 vira o último visto
    assert by_chat[333].http_status == 500


def test_send_text_without_chat_id_raises():
    notifier = TelegramNotifier("TOKEN_TESTE")  # chat_id ausente
    import pytest
    with pytest.raises(RuntimeError, match="chat_id"):
        notifier.send_text("hi")


def test_broadcast_empty_returns_empty_list():
    notifier = TelegramNotifier("TOKEN_TESTE")
    assert notifier.broadcast([], "msg") == []
```

Adicionar `import json` no topo do arquivo de teste se ainda não tiver.

- [ ] **Step 3.2: Rodar — verificar que falham**

```bash
pytest tests/test_telegram_notifier.py -v -k "broadcast or without_chat_id"
```

Esperado: ImportError do `BroadcastResult` ou AttributeError do `broadcast`.

- [ ] **Step 3.3: Modificar `bot/telegram_notifier.py`**

Adicionar import e dataclass no topo (depois dos imports):

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class BroadcastResult:
    chat_id: int
    ok: bool
    http_status: int | None  # None = falha de rede / sem resposta HTTP
    error: str | None        # human-readable, vazio se ok
```

Refatorar a classe `TelegramNotifier`:

```python
class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_id: int | str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._timeout = timeout
        self._session = session or requests.Session()

    @property
    def base_url(self) -> str:
        return f"{API_BASE}/bot{self._token}"

    def send_text(self, text: str, *, parse_mode: str = "MarkdownV2") -> bool:
        if self._chat_id is None:
            raise RuntimeError("send_text precisa de chat_id no construtor")
        result = self._send_to(self._chat_id, text, parse_mode)
        return result.ok

    def broadcast(
        self, chat_ids: list[int] | set[int], text: str, *, parse_mode: str = "MarkdownV2"
    ) -> list[BroadcastResult]:
        return [self._send_to(cid, text, parse_mode) for cid in chat_ids]

    def _send_to(
        self, chat_id: int | str, text: str, parse_mode: str
    ) -> BroadcastResult:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        backoff = 2.0
        last_status: int | None = None
        last_error: str | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._session.post(
                    f"{self.base_url}/sendMessage", json=payload, timeout=self._timeout
                )
            except requests.RequestException as exc:
                logger.warning("telegram tentativa=%d falha-rede=%s", attempt, exc)
                last_error = f"network: {exc}"
                time.sleep(backoff)
                backoff *= 2
                continue

            last_status = resp.status_code
            if resp.status_code == 200:
                return BroadcastResult(int(chat_id), True, 200, None)
            if resp.status_code == 429:
                retry_after = self._retry_after(resp)
                logger.warning("telegram 429 retry_after=%ds", retry_after)
                last_error = f"429 retry_after={retry_after}"
                time.sleep(retry_after)
                continue
            if resp.status_code >= 500:
                logger.warning(
                    "telegram tentativa=%d 5xx=%d body=%s",
                    attempt, resp.status_code, resp.text[:200],
                )
                last_error = f"{resp.status_code}: {resp.text[:200]}"
                time.sleep(backoff)
                backoff *= 2
                continue
            # 4xx (não 429) → não adianta retry
            logger.error(
                "telegram 4xx status=%d body=%s — abortando", resp.status_code, resp.text[:200]
            )
            return BroadcastResult(
                int(chat_id), False, resp.status_code, f"{resp.status_code}: {resp.text[:200]}"
            )

        logger.error("telegram esgotou %d tentativas chat_id=%s", MAX_RETRIES, chat_id)
        return BroadcastResult(int(chat_id), False, last_status, last_error or "max retries")

    @staticmethod
    def _retry_after(resp: requests.Response) -> int:
        try:
            return int(resp.json().get("parameters", {}).get("retry_after", 5))
        except (ValueError, AttributeError):
            return 5
```

- [ ] **Step 3.4: Rodar — toda a suíte de telegram_notifier**

```bash
pytest tests/test_telegram_notifier.py -v
```

Esperado: todos PASS, incluindo os 3 novos.

- [ ] **Step 3.5: Commit**

```bash
git add bot/telegram_notifier.py tests/test_telegram_notifier.py
git commit -m "feat(telegram): adiciona broadcast com BroadcastResult"
```

---

## Task 4: `CommandHandler` — parsing e roteamento dos comandos

**Files:**
- Create: `bot/command_handler.py`
- Create: `tests/test_command_handler.py`

- [ ] **Step 4.1: Criar `tests/test_command_handler.py` com testes que falham**

```python
"""Testes do CommandHandler — roteamento de /init, /stop, /status."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.command_handler import CommandHandler, CommandResponse
from bot.subscriber_store import SubscriberStore


@pytest.fixture
def store(tmp_path: Path) -> SubscriberStore:
    return SubscriberStore(tmp_path / "subs.json")


def make_update(text: str, chat_id: int = 111, update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": chat_id},
            "text": text,
        },
    }


def stub_status() -> dict:
    return {"last_check_at": None, "unidades_com_vagas": 0, "total_polls": 0}


def test_init_first_time_adds_chat(store):
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update(make_update("/init"))
    assert isinstance(resp, CommandResponse)
    assert resp.chat_id == 111
    assert "iniciado" in resp.text.lower()
    assert store.contains(111)


def test_init_duplicate_keeps_subscribed(store):
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init"))
    resp = handler.handle_update(make_update("/init"))
    assert "já" in resp.text.lower() or "ja " in resp.text.lower()
    assert store.contains(111)


def test_stop_existing_subscriber(store):
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init"))
    resp = handler.handle_update(make_update("/stop"))
    assert "pausado" in resp.text.lower() or "pausei" in resp.text.lower()
    assert not store.contains(111)


def test_stop_when_not_subscribed(store):
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update(make_update("/stop"))
    assert "não estava" in resp.text.lower() or "nao estava" in resp.text.lower()
    assert not store.contains(111)


def test_status_idle(store):
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update(make_update("/status"))
    assert "idle" in resp.text.lower() or "sem subscribers" in resp.text.lower()


def test_status_active(store):
    handler = CommandHandler(store, status_provider=stub_status)
    handler.handle_update(make_update("/init", chat_id=111))
    handler.handle_update(make_update("/init", chat_id=222))
    resp = handler.handle_update(make_update("/status"))
    assert "ativo" in resp.text.lower()
    assert "2" in resp.text  # 2 subscribers


def test_unknown_command_ignored(store):
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update(make_update("/foo"))
    assert resp is None or "não reconheço" in resp.text.lower() or "comandos" in resp.text.lower()


def test_non_command_message_ignored(store):
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update(make_update("oi tudo bem"))
    assert resp is None


def test_update_without_message_ignored(store):
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update({"update_id": 1})  # sem "message"
    assert resp is None


def test_command_with_bot_mention_works(store):
    """Telegram envia /init@bot_name em grupos — strip do mention."""
    handler = CommandHandler(store, status_provider=stub_status)
    resp = handler.handle_update(make_update("/init@cin_agendamento_expresso_bot"))
    assert resp is not None
    assert "iniciado" in resp.text.lower()
    assert store.contains(111)
```

- [ ] **Step 4.2: Rodar — verificar que falham**

```bash
pytest tests/test_command_handler.py -v
```

Esperado: ModuleNotFoundError de `bot.command_handler`.

- [ ] **Step 4.3: Criar `bot/command_handler.py`**

```python
"""Roteamento de comandos do Telegram (/init, /stop, /status).

Recebe um update completo (formato JSON do Telegram) e devolve
uma CommandResponse (ou None se não há resposta a dar).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from .subscriber_store import SubscriberStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandResponse:
    chat_id: int
    text: str  # plain text — sem MarkdownV2


StatusProvider = Callable[[], dict]


class CommandHandler:
    def __init__(self, store: SubscriberStore, *, status_provider: StatusProvider) -> None:
        self._store = store
        self._status_provider = status_provider

    def handle_update(self, update: dict) -> CommandResponse | None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = (message.get("text") or "").strip()

        if chat_id is None or not text:
            return None

        chat_id_int = int(chat_id)
        # Telegram em grupos manda /comando@nome_bot — pegar só o comando
        cmd = text.split()[0].split("@", 1)[0].lower()

        if cmd == "/init":
            return self._cmd_init(chat_id_int)
        if cmd == "/stop":
            return self._cmd_stop(chat_id_int)
        if cmd == "/status":
            return self._cmd_status(chat_id_int)
        if text.startswith("/"):
            # comando desconhecido — responde com ajuda
            return CommandResponse(
                chat_id_int,
                "Não reconheço esse comando. Use /init, /stop ou /status.",
            )
        # mensagem comum — silêncio
        return None

    def _cmd_init(self, chat_id: int) -> CommandResponse:
        was_new = self._store.add(chat_id)
        if was_new:
            logger.info("subscribe chat_id=***%s", str(chat_id)[-2:])
            return CommandResponse(
                chat_id,
                "✅ Monitoramento iniciado.\n"
                "Verifico Goiânia a cada 5min e te aviso quando aparecer vaga.\n"
                "Mande /stop para pausar.",
            )
        return CommandResponse(
            chat_id,
            "🔄 Você já estava com monitoramento ativo. Tudo certo, fique tranquilo.",
        )

    def _cmd_stop(self, chat_id: int) -> CommandResponse:
        was_present = self._store.remove(chat_id)
        if was_present:
            logger.info("unsubscribe chat_id=***%s", str(chat_id)[-2:])
            return CommandResponse(
                chat_id,
                "⏸ Pausado. Mande /init quando quiser voltar a monitorar.",
            )
        return CommandResponse(
            chat_id,
            "Você não estava monitorando. Mande /init para começar.",
        )

    def _cmd_status(self, chat_id: int) -> CommandResponse:
        snap = self._status_provider()
        n = len(self._store.all())
        if n == 0:
            text = "⚪ Idle — sem subscribers ativos.\nMande /init para começar."
        else:
            last = snap.get("last_check_at") or "(ainda não)"
            unidades = snap.get("unidades_com_vagas", 0)
            polls = snap.get("total_polls", 0)
            text = (
                f"🟢 Ativo — {n} subscriber(s)\n"
                f"Última verificação: {last}\n"
                f"Unidades com vagas: {unidades}\n"
                f"Total de polls: {polls}"
            )
        return CommandResponse(chat_id, text)
```

- [ ] **Step 4.4: Rodar — verificar que passam**

```bash
pytest tests/test_command_handler.py -v
```

Esperado: todos PASS.

- [ ] **Step 4.5: Commit**

```bash
git add bot/command_handler.py tests/test_command_handler.py
git commit -m "feat: CommandHandler para /init, /stop e /status no Telegram"
```

---

## Task 5: `WebhookServer` — servidor HTTP non-blocking

**Files:**
- Create: `bot/webhook_server.py`
- Create: `tests/test_webhook_server.py`

- [ ] **Step 5.1: Criar `tests/test_webhook_server.py` com testes que falham**

```python
"""Testes do WebhookServer — servidor HTTP single-thread, secret token, roteamento."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from typing import Iterator

import pytest
import requests

from bot.command_handler import CommandHandler, CommandResponse
from bot.subscriber_store import SubscriberStore
from bot.webhook_server import WebhookServer


SECRET = "test-secret-token"


@pytest.fixture
def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def handler(tmp_path: Path) -> CommandHandler:
    store = SubscriberStore(tmp_path / "subs.json")
    return CommandHandler(store, status_provider=lambda: {})


@pytest.fixture
def server(free_port: int, handler: CommandHandler) -> Iterator[WebhookServer]:
    srv = WebhookServer(
        host="127.0.0.1",
        port=free_port,
        secret_token=SECRET,
        webhook_path="/telegram/webhook",
        command_handler=handler,
        on_command_response=lambda resp: None,  # no-op em teste
    )
    # roda o loop em thread pra responder durante o teste
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            srv.handle_request_nonblocking()

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    try:
        yield srv
    finally:
        stop.set()
        srv.close()
        t.join(timeout=2)


def url(port: int, path: str = "/telegram/webhook") -> str:
    return f"http://127.0.0.1:{port}{path}"


def test_post_with_valid_secret_returns_200(server, free_port):
    resp = requests.post(
        url(free_port),
        json={"update_id": 1, "message": {"chat": {"id": 111}, "text": "/init"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        timeout=2,
    )
    assert resp.status_code == 200


def test_post_without_secret_returns_401(server, free_port):
    resp = requests.post(
        url(free_port),
        json={"update_id": 1, "message": {"chat": {"id": 111}, "text": "/init"}},
        timeout=2,
    )
    assert resp.status_code == 401


def test_post_wrong_secret_returns_401(server, free_port):
    resp = requests.post(
        url(free_port),
        json={"update_id": 1, "message": {"chat": {"id": 111}, "text": "/init"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        timeout=2,
    )
    assert resp.status_code == 401


def test_get_health_returns_json(server, free_port):
    resp = requests.get(url(free_port, "/health"), timeout=2)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "subscribers" in body


def test_get_unknown_path_returns_404(server, free_port):
    resp = requests.get(url(free_port, "/foo"), timeout=2)
    assert resp.status_code == 404


def test_post_to_health_returns_405(server, free_port):
    resp = requests.post(url(free_port, "/health"), timeout=2)
    assert resp.status_code == 405


def test_get_to_webhook_returns_405(server, free_port):
    resp = requests.get(url(free_port, "/telegram/webhook"), timeout=2)
    assert resp.status_code == 405


def test_post_invalid_json_returns_200_anyway(server, free_port):
    """Telegram retry storm protection: sempre 200 pra POSTs com secret válido."""
    resp = requests.post(
        url(free_port),
        data=b"{ broken",
        headers={
            "X-Telegram-Bot-Api-Secret-Token": SECRET,
            "Content-Type": "application/json",
        },
        timeout=2,
    )
    assert resp.status_code == 200


def test_command_response_callback_invoked(free_port: int, tmp_path: Path):
    """on_command_response recebe a CommandResponse pra envio ao Telegram."""
    store = SubscriberStore(tmp_path / "subs.json")
    cmd_handler = CommandHandler(store, status_provider=lambda: {})

    received: list[CommandResponse] = []

    srv = WebhookServer(
        host="127.0.0.1",
        port=free_port,
        secret_token=SECRET,
        webhook_path="/telegram/webhook",
        command_handler=cmd_handler,
        on_command_response=lambda r: received.append(r),
    )
    stop = threading.Event()
    def loop():
        while not stop.is_set():
            srv.handle_request_nonblocking()
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    try:
        requests.post(
            url(free_port),
            json={"update_id": 1, "message": {"chat": {"id": 111}, "text": "/init"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
            timeout=2,
        )
        # callback pode ser invocado de forma assíncrona; espera curta
        import time
        for _ in range(20):
            if received:
                break
            time.sleep(0.05)
    finally:
        stop.set()
        srv.close()
        t.join(timeout=2)

    assert len(received) == 1
    assert received[0].chat_id == 111
    assert "iniciado" in received[0].text.lower()
```

- [ ] **Step 5.2: Rodar — verificar que falham**

```bash
pytest tests/test_webhook_server.py -v
```

Esperado: ModuleNotFoundError.

- [ ] **Step 5.3: Criar `bot/webhook_server.py`**

```python
"""Servidor HTTP single-thread para receber webhooks do Telegram.

Design:
  - http.server.HTTPServer com socket.settimeout(0.1) → handle_request retorna
    em até 100ms via socket.timeout silencioso quando não há request.
  - Roteamento manual em BaseHTTPRequestHandler:
      POST <webhook_path>  → valida secret token → command_handler
      GET  /health         → status JSON
      tudo mais            → 404
  - Webhook sempre responde 200 OK (mesmo em payload inválido) pra evitar
    retry storm do Telegram.
"""

from __future__ import annotations

import json
import logging
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from .command_handler import CommandHandler, CommandResponse
from .subscriber_store import SubscriberStore

logger = logging.getLogger(__name__)

ResponseCallback = Callable[[CommandResponse], None]


class WebhookServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        secret_token: str,
        webhook_path: str,
        command_handler: CommandHandler,
        on_command_response: ResponseCallback,
        status_provider: Callable[[], dict] | None = None,
        socket_timeout: float = 0.1,
    ) -> None:
        self._secret = secret_token
        self._webhook_path = webhook_path
        self._command_handler = command_handler
        self._on_response = on_command_response
        self._status_provider = status_provider or (lambda: {})

        cls = self  # capturar para o request handler

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                # silencia o log default barulhento do http.server
                logger.debug("http %s", fmt % args)

            def do_POST(self) -> None:
                if self.path != cls._webhook_path:
                    self.send_error(404, "not found")
                    return
                if self.headers.get("X-Telegram-Bot-Api-Secret-Token", "") != cls._secret:
                    logger.warning("webhook POST sem secret válido path=%s", self.path)
                    self.send_error(401, "unauthorized")
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                # sempre 200 — Telegram retentaria caso contrário
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
                try:
                    update = json.loads(raw.decode("utf-8")) if raw else {}
                except json.JSONDecodeError:
                    logger.warning("webhook POST com JSON inválido — descartando")
                    return
                try:
                    response = cls._command_handler.handle_update(update)
                    if response is not None:
                        cls._on_response(response)
                except Exception:
                    logger.exception("erro processando update — ignorado")

            def do_GET(self) -> None:
                if self.path != "/health":
                    if self.path == cls._webhook_path:
                        self.send_error(405, "method not allowed")
                    else:
                        self.send_error(404, "not found")
                    return
                payload = {
                    "status": "ok",
                    "subscribers": len(cls._command_handler._store.all()),
                    **cls._status_provider(),
                }
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_PUT(self) -> None:
                if self.path == "/health":
                    self.send_error(405, "method not allowed")
                else:
                    self.send_error(404, "not found")

            def do_DELETE(self) -> None:
                self.do_PUT()

        self._server = HTTPServer((host, port), _Handler)
        self._server.socket.settimeout(socket_timeout)
        logger.info(
            "webhook listening host=%s port=%d path=%s", host, port, webhook_path
        )

    def handle_request_nonblocking(self) -> None:
        """Processa 1 request se houver; retorna em até socket_timeout segundos se vazio."""
        try:
            self._server.handle_request()
        except socket.timeout:
            return
        except Exception:
            logger.exception("erro no handle_request")

    def close(self) -> None:
        try:
            self._server.server_close()
        except Exception:
            logger.exception("erro fechando servidor")
```

- [ ] **Step 5.4: Rodar — verificar que passam**

```bash
pytest tests/test_webhook_server.py -v
```

Esperado: todos PASS. Se algum teste der flake (timing), aumentar o `time.sleep` para `0.1`.

- [ ] **Step 5.5: Commit**

```bash
git add bot/webhook_server.py tests/test_webhook_server.py
git commit -m "feat: WebhookServer single-thread com secret token e healthcheck"
```

---

## Task 6: Estender `Scheduler` para usar `subscriber_store` + broadcast

**Files:**
- Modify: `bot/scheduler.py`
- Modify: `tests/test_scheduler.py`

**Mudança:** o Scheduler ganha 2 caminhos:
- **Modo legado:** se construído com `notifier`, comporta-se como hoje.
- **Modo broadcast:** se construído com `subscriber_store`, pula iteração quando vazio e faz broadcast quando há diff. Erros 403 removem o subscriber.

- [ ] **Step 6.1: Adicionar testes que falham em `tests/test_scheduler.py`**

Adicionar imports no topo (caso ainda não existam):

```python
from bot.subscriber_store import SubscriberStore
from bot.telegram_notifier import BroadcastResult, TelegramNotifier
```

Adicionar testes (no final do arquivo):

```python
def test_scheduler_skips_when_subscribers_empty(tmp_path, monkeypatch):
    """Sem subscribers → não chama fetch_datas, retorna Diff vazio."""
    from unittest.mock import MagicMock
    from bot.scheduler import Scheduler
    from bot.state_store import StateStore
    from bot.config import Settings

    settings = Settings(
        telegram_bot_token="t", telegram_chat_id="",
        poll_interval_seconds=300, jitter_seconds=30,
        cod_municipio=25300, id_senha=58, log_level="INFO",
        goias_oauth_basic="b", goias_referer="r",
        webhook_port=8080, webhook_path="/h", webhook_secret_token="s",
    )
    client = MagicMock()
    store = StateStore(tmp_path / "state.json")
    subs = SubscriberStore(tmp_path / "subs.json")  # vazio

    notifier = TelegramNotifier("TOKEN")  # sem chat_id, broadcast-ready

    sch = Scheduler(
        settings=settings, client=client, notifier=notifier,
        store=store, subscriber_store=subs,
    )
    diff = sch.run_once()
    assert client.fetch_datas.call_count == 0
    assert diff.has_news is False


def test_scheduler_broadcasts_on_diff(tmp_path, monkeypatch):
    """Com subscribers + vagas novas → broadcast pra cada um."""
    from unittest.mock import MagicMock
    from bot.scheduler import Scheduler
    from bot.state_store import StateStore
    from bot.config import Settings
    from bot.expresso_client import Unidade

    settings = Settings(
        telegram_bot_token="t", telegram_chat_id="",
        poll_interval_seconds=300, jitter_seconds=30,
        cod_municipio=25300, id_senha=58, log_level="INFO",
        goias_oauth_basic="b", goias_referer="r",
        webhook_port=8080, webhook_path="/h", webhook_secret_token="s",
    )
    client = MagicMock()
    client.fetch_datas.return_value = [
        Unidade(nome="Vapt Vupt Anhanguera", datas=["02/05", "03/05"]),
    ]
    store = StateStore(tmp_path / "state.json")
    subs = SubscriberStore(tmp_path / "subs.json")
    subs.add(111)
    subs.add(222)

    notifier = MagicMock(spec=TelegramNotifier)
    notifier.broadcast.return_value = [
        BroadcastResult(111, True, 200, None),
        BroadcastResult(222, True, 200, None),
    ]

    sch = Scheduler(
        settings=settings, client=client, notifier=notifier,
        store=store, subscriber_store=subs,
    )
    sch.run_once()

    assert notifier.broadcast.call_count == 1
    call_args = notifier.broadcast.call_args
    chat_ids = call_args[0][0] if call_args[0] else call_args[1]["chat_ids"]
    assert set(chat_ids) == {111, 222}


def test_scheduler_removes_403_subscribers(tmp_path):
    """Broadcast com 403 → chat removido do subscriber_store."""
    from unittest.mock import MagicMock
    from bot.scheduler import Scheduler
    from bot.state_store import StateStore
    from bot.config import Settings
    from bot.expresso_client import Unidade

    settings = Settings(
        telegram_bot_token="t", telegram_chat_id="",
        poll_interval_seconds=300, jitter_seconds=30,
        cod_municipio=25300, id_senha=58, log_level="INFO",
        goias_oauth_basic="b", goias_referer="r",
        webhook_port=8080, webhook_path="/h", webhook_secret_token="s",
    )
    client = MagicMock()
    client.fetch_datas.return_value = [
        Unidade(nome="Vapt Vupt", datas=["02/05"]),
    ]
    store = StateStore(tmp_path / "state.json")
    subs = SubscriberStore(tmp_path / "subs.json")
    subs.add(111)
    subs.add(222)

    notifier = MagicMock(spec=TelegramNotifier)
    notifier.broadcast.return_value = [
        BroadcastResult(111, True, 200, None),
        BroadcastResult(222, False, 403, "Forbidden"),
    ]

    sch = Scheduler(
        settings=settings, client=client, notifier=notifier,
        store=store, subscriber_store=subs,
    )
    sch.run_once()

    assert subs.contains(111)
    assert not subs.contains(222), "subscriber com 403 deveria ter sido removido"
```

- [ ] **Step 6.2: Rodar — verificar que falham**

```bash
pytest tests/test_scheduler.py -v -k "subscribers or 403"
```

Esperado: TypeError de argumento desconhecido `subscriber_store`.

- [ ] **Step 6.3: Modificar `bot/scheduler.py`**

Adicionar import no topo:
```python
from .subscriber_store import SubscriberStore
from .telegram_notifier import BroadcastResult
```

Estender o construtor de `Scheduler`:
```python
class Scheduler:
    def __init__(
        self,
        *,
        settings: Settings,
        client: ExpressoClient,
        notifier: TelegramNotifier | None,
        store: StateStore,
        subscriber_store: SubscriberStore | None = None,
        municipio_nome: str = DEFAULT_MUNICIPIO_NOME,
        dry_run: bool = False,
    ) -> None:
        self._settings = settings
        self._client = client
        self._notifier = notifier
        self._store = store
        self._subscriber_store = subscriber_store
        self._municipio_nome = municipio_nome
        self._dry_run = dry_run
        self._running = True
        self._backoff = _Backoff()
```

Adicionar método público para snapshot (usado pelo `/status`):

```python
    def snapshot(self) -> dict:
        """Retorna estado leve para o /status do Telegram."""
        state = self._store.load()
        return {
            "last_check_at": state.last_check_at,
            "last_change_at": state.last_change_at,
            "unidades_com_vagas": len(state.datas_por_unidade),
            "total_polls": state.total_polls,
        }
```

Modificar `run_once`. Logo no início (após o `state = self._store.load()`):

```python
    def run_once(self) -> Diff:
        # Modo broadcast: pula se nenhum subscriber
        if self._subscriber_store is not None and self._subscriber_store.is_empty():
            logger.debug("[poll] sem subscribers — skip")
            return compute_diff({}, {})  # diff vazio

        state = self._store.load()
        unidades = self._client.fetch_datas(self._settings.id_senha, self._settings.cod_municipio)
        ...
```

Substituir o bloco que envia notificação. **Antes:**
```python
            else:
                msg = format_message(...)
                if self._notifier.send_text(msg):
                    action = "notified"
                    ...
                else:
                    action = "notify-failed"
```

**Depois:**
```python
            else:
                msg = format_message(
                    self._municipio_nome,
                    diff,
                    is_first_open=is_first_open,
                )
                if self._subscriber_store is not None:
                    chat_ids = list(self._subscriber_store.all())
                    results = self._notifier.broadcast(chat_ids, msg)
                    ok_count = sum(1 for r in results if r.ok)
                    self._handle_broadcast_results(results)
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
```

Adicionar método privado:

```python
    def _handle_broadcast_results(self, results: list[BroadcastResult]) -> None:
        if self._subscriber_store is None:
            return
        for r in results:
            if not r.ok and r.http_status == 403:
                self._subscriber_store.remove(r.chat_id)
                logger.info(
                    "removido subscriber chat_id=***%s status=403",
                    str(r.chat_id)[-2:],
                )
```

- [ ] **Step 6.4: Rodar — toda a suíte do scheduler**

```bash
pytest tests/test_scheduler.py -v
```

Esperado: todos PASS, incluindo os 3 novos.

- [ ] **Step 6.5: Commit**

```bash
git add bot/scheduler.py tests/test_scheduler.py
git commit -m "feat(scheduler): suporta subscriber_store + broadcast + remoção 403"
```

---

## Task 7: Subcomando `setup-webhook`

**Files:**
- Modify: `bot/__main__.py`
- Create: `tests/test_setup_webhook.py`

- [ ] **Step 7.1: Criar `tests/test_setup_webhook.py` com testes que falham**

```python
"""Testes do subcomando `setup-webhook`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import responses

from bot.__main__ import cmd_setup_webhook
from bot.config import Settings


def make_settings(token: str = "TOKEN_TESTE", secret: str = "the-secret") -> Settings:
    return Settings(
        telegram_bot_token=token, telegram_chat_id="",
        poll_interval_seconds=300, jitter_seconds=30,
        cod_municipio=25300, id_senha=58, log_level="INFO",
        goias_oauth_basic="b", goias_referer="r",
        webhook_port=8080, webhook_path="/telegram/webhook",
        webhook_secret_token=secret,
    )


@responses.activate
def test_setup_webhook_calls_telegram_api(capsys):
    settings = make_settings()
    responses.post(
        "https://api.telegram.org/botTOKEN_TESTE/setWebhook",
        json={"ok": True, "result": True, "description": "Webhook was set"},
    )
    rc = cmd_setup_webhook(settings, url="https://abc.trycloudflare.com", delete=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "configurado" in out.lower() or "webhook was set" in out.lower()
    # Verifica payload enviado
    req = responses.calls[0].request
    import json
    payload = json.loads(req.body)
    assert payload["url"] == "https://abc.trycloudflare.com/telegram/webhook"
    assert payload["secret_token"] == "the-secret"


@responses.activate
def test_setup_webhook_delete(capsys):
    settings = make_settings()
    responses.post(
        "https://api.telegram.org/botTOKEN_TESTE/deleteWebhook",
        json={"ok": True, "result": True},
    )
    rc = cmd_setup_webhook(settings, url=None, delete=True)
    assert rc == 0


@responses.activate
def test_setup_webhook_failure_returns_1(capsys):
    settings = make_settings()
    responses.post(
        "https://api.telegram.org/botTOKEN_TESTE/setWebhook",
        json={"ok": False, "description": "Bad webhook URL"},
        status=400,
    )
    rc = cmd_setup_webhook(settings, url="https://bad", delete=False)
    assert rc == 1


def test_setup_webhook_generates_secret_if_empty(tmp_path, monkeypatch):
    """Se webhook_secret_token vazio, gera um e persiste no .env."""
    from bot.__main__ import _ensure_secret_token

    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=t\n")
    monkeypatch.setattr("bot.__main__.ENV_PATH", env)

    secret = _ensure_secret_token("")
    assert len(secret) >= 32
    assert "WEBHOOK_SECRET_TOKEN=" in env.read_text()
    assert secret in env.read_text()


def test_setup_webhook_keeps_secret_if_set(tmp_path, monkeypatch):
    from bot.__main__ import _ensure_secret_token
    secret = _ensure_secret_token("preexisting-secret-12345")
    assert secret == "preexisting-secret-12345"
```

- [ ] **Step 7.2: Rodar — verificar que falham**

```bash
pytest tests/test_setup_webhook.py -v
```

Esperado: ImportError de `cmd_setup_webhook` ou `_ensure_secret_token`.

- [ ] **Step 7.3: Modificar `bot/__main__.py`**

Adicionar imports:
```python
import secrets
import requests
```

Adicionar função antes de `main`:

```python
def _ensure_secret_token(current: str) -> str:
    """Devolve o secret atual ou gera um novo, persistindo no .env."""
    if current and len(current) >= 16:
        return current
    new = secrets.token_urlsafe(32)
    _persist_env_kv("WEBHOOK_SECRET_TOKEN", new)
    return new


def _persist_env_kv(key: str, value: str) -> None:
    """Atualiza/insere KEY=value no .env preservando demais linhas."""
    path = ENV_PATH
    line = f"{key}={value}"
    if not path.exists():
        path.write_text(line + "\n", encoding="utf-8")
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    found = False
    for i, raw in enumerate(lines):
        if raw.strip().startswith(f"{key}="):
            lines[i] = line
            found = True
            break
    if not found:
        lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

Adicionar a função do subcomando:

```python
def cmd_setup_webhook(settings: Settings, *, url: str | None, delete: bool) -> int:
    """Registra/remove URL do webhook na API do Telegram."""
    require_telegram(settings, need_chat_id=False)
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    if delete:
        resp = requests.post(f"{base}/deleteWebhook", timeout=10)
        ok = resp.ok and resp.json().get("ok") is True
        if ok:
            print("webhook removido")
            return 0
        print(f"falha ao remover webhook: {resp.text[:200]}", file=sys.stderr)
        return 1

    if not url:
        print("erro: --url ou --delete obrigatório", file=sys.stderr)
        return 2

    secret = _ensure_secret_token(settings.webhook_secret_token)
    full_url = url.rstrip("/") + settings.webhook_path
    resp = requests.post(
        f"{base}/setWebhook",
        json={"url": full_url, "secret_token": secret},
        timeout=10,
    )
    if not resp.ok or not resp.json().get("ok"):
        print(f"falha: {resp.text[:300]}", file=sys.stderr)
        return 1
    print(f"webhook configurado: {full_url}")
    print(f"(secret token gerado/usado e salvo em {ENV_PATH})")
    return 0
```

Adicionar parser do subcomando dentro de `main`:

Localizar o trecho com os `sub.add_parser(...)` existentes e adicionar:

```python
    setup_p = sub.add_parser("setup-webhook", help="registra ou remove URL do webhook na API Telegram")
    setup_p.add_argument("url", nargs="?", help="URL pública (ex: https://abc.trycloudflare.com)")
    setup_p.add_argument("--delete", action="store_true", help="remove o webhook")
```

E o roteamento dentro do `try:`:

```python
        if args.cmd == "setup-webhook":
            return cmd_setup_webhook(settings, url=args.url, delete=args.delete)
```

- [ ] **Step 7.4: Rodar — verificar que passam**

```bash
pytest tests/test_setup_webhook.py -v
```

Esperado: todos PASS.

- [ ] **Step 7.5: Smoke check (sem rede real)**

```bash
python -m bot setup-webhook 2>&1 | head -5
```

Esperado: erro "URL ou --delete obrigatório" + exit code 2.

- [ ] **Step 7.6: Commit**

```bash
git add bot/__main__.py tests/test_setup_webhook.py
git commit -m "feat: subcomando setup-webhook com geração de secret token"
```

---

## Task 8: Subcomando `serve` — loop unificado

**Files:**
- Modify: `bot/__main__.py`
- Create: `tests/test_serve_integration.py`

- [ ] **Step 8.1: Criar `tests/test_serve_integration.py` com teste end-to-end**

```python
"""Integração: sobe servidor real, manda POST simulando Telegram, verifica side effects."""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest
import requests

from bot.command_handler import CommandHandler
from bot.subscriber_store import SubscriberStore
from bot.telegram_notifier import TelegramNotifier
from bot.webhook_server import WebhookServer


SECRET = "integration-secret"


@pytest.fixture
def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_init_then_stop_via_webhook_persists(tmp_path: Path, free_port: int):
    """POST /init → /stop pelo webhook deve atualizar subscribers.json."""
    subs_path = tmp_path / "subs.json"
    store = SubscriberStore(subs_path)
    handler = CommandHandler(store, status_provider=lambda: {})

    # captura responses pra simulação (sem chamar Telegram real)
    responses_log: list = []

    srv = WebhookServer(
        host="127.0.0.1",
        port=free_port,
        secret_token=SECRET,
        webhook_path="/telegram/webhook",
        command_handler=handler,
        on_command_response=lambda r: responses_log.append(r),
    )

    stop_evt = threading.Event()

    def loop():
        while not stop_evt.is_set():
            srv.handle_request_nonblocking()

    t = threading.Thread(target=loop, daemon=True)
    t.start()

    try:
        url = f"http://127.0.0.1:{free_port}/telegram/webhook"
        h = {"X-Telegram-Bot-Api-Secret-Token": SECRET}

        # /init de chat 555
        r1 = requests.post(
            url,
            json={"update_id": 1, "message": {"chat": {"id": 555}, "text": "/init"}},
            headers=h, timeout=2,
        )
        assert r1.status_code == 200

        # eventual consistency: callback é chamado após response 200
        for _ in range(20):
            if responses_log:
                break
            time.sleep(0.05)
        assert any(r.chat_id == 555 and "iniciado" in r.text.lower() for r in responses_log)

        # subscribers.json deve ter 555 persistido
        data = json.loads(subs_path.read_text())
        assert 555 in data["subscribers"]

        # /stop de chat 555
        r2 = requests.post(
            url,
            json={"update_id": 2, "message": {"chat": {"id": 555}, "text": "/stop"}},
            headers=h, timeout=2,
        )
        assert r2.status_code == 200
        for _ in range(20):
            if len(responses_log) >= 2:
                break
            time.sleep(0.05)

        # subscribers.json deve estar vazio
        data = json.loads(subs_path.read_text())
        assert data["subscribers"] == []
    finally:
        stop_evt.set()
        srv.close()
        t.join(timeout=2)
```

- [ ] **Step 8.2: Rodar — verificar que passa**

```bash
pytest tests/test_serve_integration.py -v
```

Esperado: PASS (com `WebhookServer` e `CommandHandler` da Task 4 e 5 já existentes).

- [ ] **Step 8.3: Adicionar `cmd_serve` em `bot/__main__.py`**

Adicionar função (depois de `cmd_run`):

```python
def cmd_serve(settings: Settings) -> int:
    """Loop unificado: webhook HTTP + scheduler. Modo de produção interativo."""
    require_goias(settings)
    require_telegram(settings, need_chat_id=False)  # chat_ids vêm via webhook

    from .subscriber_store import SubscriberStore
    from .command_handler import CommandHandler
    from .webhook_server import WebhookServer

    secret = _ensure_secret_token(settings.webhook_secret_token)
    if not secret:
        print("erro: WEBHOOK_SECRET_TOKEN não configurado e falha ao gerar", file=sys.stderr)
        return 1

    subs_path = PROJECT_ROOT / "subscribers.json"
    subs = SubscriberStore(subs_path)

    client = ExpressoClient(settings.goias_oauth_basic, settings.goias_referer)
    notifier = TelegramNotifier(settings.telegram_bot_token)  # sem chat_id, broadcast-ready
    store = StateStore(_state_path(settings.cod_municipio))
    scheduler = Scheduler(
        settings=settings, client=client, notifier=notifier,
        store=store, subscriber_store=subs,
    )

    handler = CommandHandler(subs, status_provider=scheduler.snapshot)

    def deliver(resp):
        notifier._send_to(resp.chat_id, resp.text, parse_mode="")

    server = WebhookServer(
        host="0.0.0.0",
        port=settings.webhook_port,
        secret_token=secret,
        webhook_path=settings.webhook_path,
        command_handler=handler,
        on_command_response=deliver,
        status_provider=scheduler.snapshot,
    )

    try:
        with file_lock(_lock_path(settings.cod_municipio)):
            scheduler.install_signal_handlers()
            _serve_loop(server, scheduler, settings)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    finally:
        server.close()
    return 0


def _serve_loop(server, scheduler, settings) -> None:
    """Loop integrado: handle_request_nonblocking + scheduler.run_once a cada intervalo."""
    next_poll = time.monotonic()
    logger.info(
        "serve iniciado port=%d intervalo=%ds",
        settings.webhook_port, settings.poll_interval_seconds,
    )
    while scheduler._running:
        server.handle_request_nonblocking()
        now = time.monotonic()
        if now >= next_poll:
            try:
                scheduler.run_once()
                scheduler._backoff.reset()
                next_poll = now + scheduler._next_interval()
            except Exception:
                logger.exception("erro no scheduler.run_once — backoff")
                wait = scheduler._backoff.next_wait()
                next_poll = now + wait
    logger.info("serve encerrado")
```

Adicionar parser do subcomando dentro de `main` (junto aos outros):
```python
    sub.add_parser("serve", help="loop interativo: webhook HTTP + scheduler com /init e /stop")
```

E o roteamento:
```python
        if args.cmd == "serve":
            return cmd_serve(settings)
```

**Nota técnica:** `notifier._send_to` é privado por convenção mas usado por design — alternativa: criar wrapper público. Decisão: deixar como está, comentar no código que `_send_to` é a unidade de envio (broadcast e respostas de comando ambas usam).

- [ ] **Step 8.4: Smoke manual de `serve` (sem rede real, mata em 5s)**

```bash
# Subir o serve em background, deixar rodar 3s, matar e olhar log
python -m bot serve &
SERVE_PID=$!
sleep 3
kill -INT $SERVE_PID
wait $SERVE_PID 2>/dev/null
tail -20 bot.log
```

Esperado no log: `webhook listening host=0.0.0.0 port=8080 path=/telegram/webhook` + `loop encerrado`.

Se a porta 8080 estiver ocupada, mudar `WEBHOOK_PORT=18080` no `.env` antes do smoke.

- [ ] **Step 8.5: Commit**

```bash
git add bot/__main__.py tests/test_serve_integration.py
git commit -m "feat: subcomando serve unifica webhook + scheduler em um loop"
```

---

## Task 9: Atualizar `README.md` e `.env.example`

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 9.1: Adicionar seção "Modo interativo (webhook)" no README**

Localizar a seção `## Comandos CLI` e adicionar uma nova seção logo depois:

```markdown
---

## Modo interativo (webhook) — `/init` e `/stop` no Telegram

O subcomando `serve` permite controlar o monitoramento direto pelo Telegram:

- `/init` → começa a monitorar Goiânia (5min) e te avisa quando aparecer vaga
- `/stop` → pausa o monitoramento (pra você)
- `/status` → estado atual (ativo/idle, últimas verificações)

### Como rodar localmente (com túnel temporário)

```bash
# Terminal 1 — sobe o bot
python -m bot serve     # escuta em http://localhost:8080

# Terminal 2 — abre um túnel HTTPS público
cloudflared tunnel --url http://localhost:8080
# saída: https://abc-xyz.trycloudflare.com

# Terminal 3 — registra a URL no Telegram
python -m bot setup-webhook https://abc-xyz.trycloudflare.com
# (gera/usa o WEBHOOK_SECRET_TOKEN automaticamente)

# Pronto: mande /init no @cin_agendamento_expresso_bot
```

### Em produção

Use um túnel persistente (Cloudflare Tunnel nomeado, ngrok com domínio fixo, etc.)
e mantenha o `python -m bot serve` rodando via launchd. URL muda? Basta rodar
`python -m bot setup-webhook <nova-url>` de novo — é idempotente.

### Para remover o webhook

```bash
python -m bot setup-webhook --delete
```
```

E atualizar a tabela de comandos CLI já existente (adicionar 2 linhas):

```markdown
| `python -m bot serve`         | Modo interativo: HTTP webhook + scheduler. /init e /stop pelo Telegram. |
| `python -m bot setup-webhook` | Registra URL pública no Telegram (`<URL>` ou `--delete`). Idempotente. |
```

- [ ] **Step 9.2: Verificar `.env.example` (já atualizado na Task 1, mas conferir)**

```bash
grep -E "WEBHOOK|POLL_INTERVAL" .env.example
```

Esperado:
```
POLL_INTERVAL_SECONDS=300
WEBHOOK_PORT=8080
WEBHOOK_PATH=/telegram/webhook
WEBHOOK_SECRET_TOKEN=
```

Se não tiver as 4 linhas, voltar e completar.

- [ ] **Step 9.3: Commit**

```bash
git add README.md
git commit -m "docs: adiciona modo interativo e tabela de comandos atualizada"
```

---

## Task 10: Validação final ponta a ponta

**Files:** nenhum a modificar — só verificações.

- [ ] **Step 10.1: Suite de testes completa**

```bash
pytest -v
```

Esperado: tudo verde, ≥85% de cobertura nos novos arquivos. Anotar contagem total de testes.

- [ ] **Step 10.2: Doctor**

```bash
python -m bot doctor
```

Esperado: 4/4 passes (config, goias auth, listarDatas, telegram getMe).

- [ ] **Step 10.3: Smoke do `serve` por 30s — verifica que sobe sem erro**

```bash
python -m bot serve &
SERVE_PID=$!
sleep 5
# health check local
curl -s http://localhost:8080/health
echo
# matar gracefully
kill -INT $SERVE_PID
wait $SERVE_PID
```

Esperado: `{"status":"ok","subscribers":0,...}` no curl, e log `loop encerrado` após o SIGINT.

- [ ] **Step 10.4: Verificar gitignore — confirmar que `subscribers.json` NÃO é tracked**

```bash
# Cria um subscribers.json fake e confirma que git ignora
echo '{"subscribers":[111],"updated_at":"x"}' > subscribers.json
git status --short subscribers.json   # deve não listar
rm subscribers.json
```

Esperado: nenhuma saída do `git status` (confirmando ignore).

- [ ] **Step 10.5: Push final**

Sob aprovação do usuário (não force, esses são commits novos em cima de `main`):

```bash
git log --oneline -10
git push origin main
```

---

## Self-review

**Cobertura da spec:**

| Spec requirement | Task |
|---|---|
| RF-1 (`/init` adiciona subscriber) | Task 4 (CommandHandler) |
| RF-2 (`/stop` remove + pausa polling) | Task 4 + Task 6 (scheduler skip empty) |
| RF-3 (`/status`) | Task 4 + Scheduler.snapshot (Task 6) |
| RF-4 (broadcast em diff) | Task 6 (scheduler) + Task 3 (broadcast) |
| RF-5 (formato compacto) | já implementado em `format_message`, não muda |
| RF-6 (`serve` CLI) | Task 8 |
| RF-7 (`setup-webhook` CLI) | Task 7 |
| RF-8 (webhook 200 sempre) | Task 5 (WebhookServer) |
| RF-9 (`/health` endpoint) | Task 5 |
| RNF-1 (zero deps novas) | confirmado (só stdlib + requests/dotenv existentes) |
| RNF-2 (single-thread, socket.timeout) | Task 5 |
| RNF-3 (resposta < 2s) | implícito no design (sem bloqueios) |
| RNF-4 (write atômico) | Task 2 |
| RNF-5 (secret token) | Task 5 + Task 7 |
| RNF-6 (broadcast resiliente, remove 403) | Task 3 + Task 6 |
| RNF-7 (logs estruturados) | reuso direto de `logging_setup` |

**Placeholders:** nenhum encontrado.

**Type consistency:** `BroadcastResult` usado consistente em Tasks 3/6. `CommandResponse` em 4/5/8. `Settings` estendido na Task 1 e usado em todas.

**Cuidado conhecido:** Task 8 usa `notifier._send_to` (atributo "privado"). Documentado no plano. Alternativa seria criar `notifier.send_to_chat(chat_id, text)` público — recomendo aceitar como está pra evitar mais um ponto de mudança. Se preferir o método público, adicionar como step extra na Task 3.

---

## Fim
