# cin_agendamento_expresso_bot

Bot de Telegram que monitora vagas para a **Carteira de Identidade Nacional (CIN)** no portal
[Vapt Vupt — Goiás Digital](https://www.go.gov.br/servicos-digitais/vapt-vupt/agendamento-atendimento-presencial/novo/origem-rg)
e notifica quando datas abrem para um município de interesse (default: **Goiânia**).

> Status: **MVP implementado.** PRD em [`tasks/prd-cin-agendamento-expresso-bot.md`](tasks/prd-cin-agendamento-expresso-bot.md).

---

## Como funciona

1. A cada ~3 minutos (jitter ±30s), o bot autentica via OAuth2 (`client_credentials`) na API
   pública do Goiás Digital e consulta `listarDatasAgendamento`.
2. Compara a resposta com o último estado salvo em `state.json`.
3. Se houver datas novas, envia mensagem formatada no Telegram.
4. Se a resposta for vazia ou repetida, apenas registra log e dorme.

Sem login, sem cookies de sessão, sem captcha — duas chamadas HTTP por ciclo.

---

## Setup local

```bash
# 1. Clonar
git clone git@github.com:edilsonborges/cin_agendamento_expresso_bot.git
cd cin_agendamento_expresso_bot

# 2. Ambiente Python (3.11+)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configurar .env (a partir do exemplo)
cp .env.example .env
chmod 600 .env
$EDITOR .env       # cole TELEGRAM_BOT_TOKEN do @BotFather

# 4. Smoke test (sem Telegram, dry-run)
python -m bot check
# saída esperada: "vazio — sem vagas no momento" ou unidades + datas

# 5. Descobrir chat_id (mande /start no @cin_agendamento_expresso_bot)
python -m bot init

# 6. Rodar em loop em primeiro plano
python -m bot run
```

---

## Comandos CLI

| Comando | Descrição |
|---------|-----------|
| `python -m bot check`   | 1 verificação dry-run; nunca envia notificação. Rápido (<5s). |
| `python -m bot init`    | Polling do Telegram por até 5min. Salva `TELEGRAM_CHAT_ID` no `.env` ao receber `/start`. |
| `python -m bot status`  | Imprime resumo do state file local. Sem rede — útil para inspeção rápida. |
| `python -m bot doctor`  | Diagnóstico: config + auth Goiás + Telegram `/getMe`. Não envia msg. Exit 1 se falha. |
| `python -m bot run`     | Loop de produção com lockfile, signal handlers, backoff e rate-limit. |
| `python -m bot run --once` | Executa **1 iteração** e sai (útil para cron externo em vez de loop interno). |
| `python -m bot serve`         | Modo interativo: HTTP webhook + scheduler. /init e /stop pelo Telegram. |
| `python -m bot setup-webhook` | Registra URL pública no Telegram (`<URL>` ou `--delete`). Idempotente. |
| `python -m bot --version` | Versão atual. |

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

---

## Rodando 24/7 no macOS via launchd

```bash
./scripts/install.sh                                    # instala o LaunchAgent e inicia
launchctl list | grep com.edilson.cin-agendamento-bot   # confirma que está rodando
tail -f bot.log                                         # acompanha logs estruturados
./scripts/uninstall.sh                                  # desinstala
```

Detalhes:
- O `install.sh` substitui `__PROJECT_DIR__` no template `.plist` pelo caminho absoluto do
  projeto e copia para `~/Library/LaunchAgents/`.
- `KeepAlive=true` reinicia o bot se ele cair; `ThrottleInterval=30` evita restart loop.
- Stdout/stderr vão para `bot.stdout.log` e `bot.stderr.log` (raros — quase tudo
  passa pelo `logging` em `bot.log`).

### Linux (systemd) — alternativa

Crie `/etc/systemd/system/cin-agendamento-bot.service` com `ExecStart=$PWD/.venv/bin/python -m bot run`,
`Restart=always`, e ative com `systemctl enable --now cin-agendamento-bot`.

---

## Operação e troubleshooting

### Logs

Formato fixo, fácil de grep:
```
2026-04-29T21:30:00 [INFO] [poll] municipio=25300 datas=0 unidades=0 acao=noop
```

| Ação | Significado |
|------|-------------|
| `noop` | Estado igual ao anterior; nada a fazer. |
| `notified` | Mensagem enviada com sucesso ao Telegram. |
| `notify-failed` | Telegram rejeitou (4xx) ou esgotou retry; próximo loop tenta de novo. |
| `suppressed(rate-limit)` | Há novidade mas última notificação foi há <60s; espera. |
| `would-notify(dry-run)` | Modo `check` detectou novidade mas não enviou. |

```bash
tail -f bot.log                           # tempo real
grep ERROR bot.log                        # só erros
grep "acao=notified" bot.log              # quando o bot notificou
```

### Parar / reiniciar

```bash
# Foreground: Ctrl+C (graceful — salva estado antes de sair)

# LaunchAgent:
launchctl unload ~/Library/LaunchAgents/com.edilson.cin-agendamento-bot.plist
launchctl load   ~/Library/LaunchAgents/com.edilson.cin-agendamento-bot.plist
```

### Estado persistente

O bot grava em `state-{cod_municipio}.json` (ex: `state-25300.json` para Goiânia). Se quiser
forçar "reset" (próxima notificação será como primeira abertura):

```bash
rm state-25300.json     # Goiânia
```

Lockfile `state-{cod_municipio}.lock` impede dupla instância **para o mesmo município**. Se
travar (raro, e.g. processo morto sem cleanup), delete e reinicie:

```bash
rm state-25300.lock
```

### Múltiplas instâncias (vários municípios)

Como state e lock são por município, dá pra rodar dois bots em paralelo, um por município —
basta um `.env` separado pra cada e invocar com diretórios distintos ou variáveis distintas.
Exemplo simples:

```bash
COD_MUNICIPIO=25300 python -m bot run   # Goiânia
COD_MUNICIPIO=33800 python -m bot run   # Aparecida (em outro shell)
```

Cada instância terá seu próprio `state-25300.json` e `state-33800.json` sem colisão.

### Token vazado

Se o `TELEGRAM_BOT_TOKEN` cair no público (commit, screenshot, log), revogue **imediatamente**:

1. Abra `@BotFather` no Telegram → `/revoke` → escolha `cin_agendamento_expresso_bot`.
2. Receberá novo token; substitua no `.env`.
3. Reinicie o bot.

---

## Arquitetura

Ver [PRD §7](tasks/prd-cin-agendamento-expresso-bot.md#7-arquitetura-proposta) para o
diagrama completo. Resumo dos módulos:

| Módulo | Responsabilidade |
|--------|------------------|
| `bot/config.py` | Carrega `.env`, valida campos obrigatórios. |
| `bot/expresso_client.py` | OAuth2 + `listarDatasAgendamento`, cache de Bearer. |
| `bot/state_store.py` | Persistência atômica de `state.json` + hash SHA-256. |
| `bot/change_detector.py` | Diff entre estado anterior e atual. |
| `bot/telegram_notifier.py` | sendMessage MarkdownV2 com retry; `getUpdates` no `init`. |
| `bot/scheduler.py` | Loop, backoff exponencial, lockfile, rate-limit, sinais. |
| `bot/logging_setup.py` | stdout + arquivo rotativo, mascara tokens. |
| `bot/__main__.py` | Dispatcher CLI (init/check/run). |

---

## Testes e qualidade

Atalhos via Makefile:

```bash
make install                          # cria venv e instala deps
make test                             # pytest (85 testes, ~1.3s)
make cov                              # pytest com cobertura (terminal + htmlcov/)
make lint                             # ruff check
make format                           # ruff format (escreve)
make type                             # mypy
make ci                               # tudo acima (replica do CI)
make help                             # lista todos os targets
```

Ou diretamente:

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt

pytest                                # toda a suite
pytest -k change_detector             # só os testes do diff
pytest -v                             # output detalhado

ruff check bot tests                  # lint
ruff format --check bot tests         # formatação consistente
mypy                                  # type checking (configurado em pyproject)

./scripts/validate.sh                 # equivalente a `make ci`
```

Dependências de dev: `pytest`, `responses` (mock HTTP), `ruff`, `mypy`, `types-requests`.

CI no GitHub Actions roda lint + format + mypy + pytest em Python 3.11/3.12 e gitleaks-action
em todo PR (`.github/workflows/ci.yml`).

### Versão

```bash
python -m bot --version               # cin_agendamento_expresso_bot 0.1.0
```

---

## Roadmap

- [x] Reverse engineering dos endpoints (validação ao vivo)
- [x] PRD aprovado
- [x] Fase 0 — Bootstrap (pyproject, requirements, .env.example, .gitignore, README)
- [x] Fase 1 — Core HTTP (auth + fetch_datas + comando `check`)
- [x] Fase 2 — Estado e diff (state_store + change_detector + 11 testes verdes)
- [x] Fase 3 — Notificação Telegram (`init`, `notifier`, format MarkdownV2)
- [x] Fase 4 — Loop + supervisor (scheduler com backoff, lockfile, launchd plist)
- [x] Fase 5 — Hardening (rate-limit FR-12, fixtures de transição, docs operacionais)

Extensões previstas no PRD §16 (não-MVP): múltiplos municípios numa instância, broadcast para
múltiplos chat_ids, comando `/status`, dashboard web, métricas Prometheus.

---

## Contato

Bot Telegram: [@cin_agendamento_expresso_bot](https://t.me/cin_agendamento_expresso_bot)
