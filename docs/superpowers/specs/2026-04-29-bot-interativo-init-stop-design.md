# Bot Telegram Interativo — Comandos `/init` e `/stop`

**Data:** 2026-04-29
**Status:** Aprovado, pronto pra plano de implementação
**Escopo:** Adicionar interatividade ao bot existente — começar/parar monitoramento via Telegram em vez de só via CLI/launchd.

---

## Contexto

Hoje o bot é **passivo**: recebe mensagens só no comando CLI `python -m bot init` (que descobre `chat_id`). Durante o `run`, ele só *envia* — nunca lê. O monitoramento começa quando o processo sobe (manualmente ou via launchd) e roda até ser morto.

O usuário quer controle dinâmico: ligar e desligar o polling do Goiás Digital via comandos `/init` e `/stop` no Telegram, com o processo principal rodando 24/7 via launchd.

## Decisões já tomadas (brainstorming)

| Decisão | Escolha |
|---|---|
| Modelo de execução | Processo always-on via launchd; comandos só ligam/desligam o polling do Goiás |
| Persistência entre restarts | Retoma o último estado (`monitoring on/off` = `subscribers != ∅`) |
| Formato da notificação | Compacto: emoji + unidade + datas + link (item (b) na conversa) |
| Restrição de chats | Sem restrição — qualquer chat que mandar `/init` vira subscriber |
| Modo de input do Telegram | Webhook (HTTP server local + setWebhook) |
| Modo de teste local | Túnel temporário (cloudflared `--url http://localhost:8080`) |
| Polling de fallback | **Não implementar** — só webhook |

## Requisitos funcionais

**RF-1.** Comando `/init` no Telegram registra o `chat_id` como subscriber e inicia (ou mantém) o polling do Goiás a cada 5min.

**RF-2.** Comando `/stop` no Telegram remove o `chat_id` da lista de subscribers. Se não restar nenhum, o polling do Goiás pausa (não consome a API).

**RF-3.** Comando `/status` no Telegram retorna estado atual: ativo/idle, número de subscribers, última verificação, vagas atuais.

**RF-4.** Quando o polling detectar vagas novas, **broadcast** da mensagem para todos os subscribers ativos.

**RF-5.** Mensagem de notificação no formato:
```
🟢 Vaga CIN aberta — Goiânia
📍 <Nome da unidade>
📅 <até 5 datas, formato dd/mm> (+N se >5)
👉 <link Vapt Vupt>
```
Se múltiplas unidades têm vagas novas, listar uma por vez na mesma mensagem (separadas por linha em branco).

**RF-6.** Subcomando CLI `python -m bot serve` é o ponto de entrada de produção. Sobe o servidor HTTP + scheduler num único processo.

**RF-7.** Subcomando CLI `python -m bot setup-webhook <URL>` registra a URL no Telegram via `POST /setWebhook` (idempotente). Aceita também `--delete` para limpar.

**RF-8.** Endpoint `POST /telegram/webhook` recebe updates do Telegram e responde `200 OK` mesmo em erro de processamento (evita retry storm).

**RF-9.** Endpoint `GET /health` retorna 200 + JSON com `{status, subscribers, last_check_at, monitoring_active}`. Útil para debug e healthcheck do túnel.

## Requisitos não-funcionais

**RNF-1.** **Zero novas dependências em runtime.** Servidor HTTP usando `http.server` da stdlib. Sem Flask/FastAPI/aiohttp.

**RNF-2.** Single-thread, sem `threading`/`asyncio`. Loop unificado: usa `HTTPServer` com `socket.settimeout(0.1)`. A cada iteração chama `handle_request()` (que retorna em até 100ms via `socket.timeout` silencioso se não há request) e depois decide se já é hora do próximo poll do Goiás. Custo: ~100ms de latência adicionada ao polling do Goiás, irrelevante para janela de 5min.

**RNF-3.** Resposta a comandos `/init` `/stop` `/status` em < 2s no caminho feliz.

**RNF-4.** Persistência atômica do `subscribers.json` (write-temp + rename), mesmo padrão do `state.json` atual.

**RNF-5.** Webhook secret token configurado no `setWebhook` (header `X-Telegram-Bot-Api-Secret-Token`). Requests sem secret válido são descartados — proteção gratuita do Telegram contra spoofing.

**RNF-6.** Broadcast resiliente: erro ao mandar para um chat individual (ex: usuário bloqueou o bot) não bloqueia o broadcast. Erro 403 (bot blocked) → remove o chat do subscribers automaticamente.

**RNF-7.** Logs estruturados existentes (`logging_setup.py`) reutilizados. Toda interação tem log com `chat_id` (mascarado nas últimas 2 dígitos).

## Arquitetura

```
┌──────────────────────────────────────────────────────────────┐
│  python -m bot serve  (processo único, single-thread)        │
│                                                               │
│  Loop principal (300ms tick):                                 │
│    1. http_server.handle_request_nonblocking()                │
│       └─ se houver request:                                   │
│             POST /telegram/webhook → command_handler          │
│             GET  /health           → status_handler           │
│    2. if time_to_poll() and subscribers:                      │
│         scheduler.run_once() → broadcast se diff              │
│                                                               │
│  Estado em disco:                                             │
│    state-25300.json    (já existe)                            │
│    subscribers.json    (NOVO — persiste set[chat_id])         │
└──────────────────────────────────────────────────────────────┘
```

### Componentes novos

| Arquivo | Responsabilidade |
|---|---|
| `bot/webhook_server.py` | Servidor HTTP `http.server`, roteamento simples (`/telegram/webhook`, `/health`), validação de secret token, parsing JSON do update |
| `bot/command_handler.py` | Recebe payload do update, identifica comando (`/init`, `/stop`, `/status`), chama `subscriber_store` e responde no Telegram |
| `bot/subscriber_store.py` | CRUD do `subscribers.json` com write atômico. API: `add(chat_id)`, `remove(chat_id)`, `all() -> set[int]`, `is_empty() -> bool` |

### Componentes modificados

| Arquivo | Mudança |
|---|---|
| `bot/scheduler.py` | (1) Aceita `subscriber_store` em vez de `notifier` único. (2) Pula iteração se `subscribers.is_empty()`. (3) Broadcast: itera `subscribers.all()` chamando notifier para cada |
| `bot/telegram_notifier.py` | Adiciona `broadcast(chat_ids, msg) -> dict[chat_id, ok]`. Remove subscribers em erro 403 |
| `bot/__main__.py` | Adiciona subcomandos `serve`, `setup-webhook` |
| `bot/config.py` | Novas envs: `WEBHOOK_PORT` (8080), `WEBHOOK_PATH` (`/telegram/webhook`), `WEBHOOK_SECRET_TOKEN` (gerado se ausente) |

### Componentes preservados (sem mudança)

- `bot/expresso_client.py` — cliente Goiás
- `bot/change_detector.py` — diff de datas
- `bot/state_store.py` — state do Goiás
- `bot/logging_setup.py`, `bot/errors.py`, `bot/__init__.py`

## Fluxos

### Fluxo: `/init`

```
1. Telegram → POST {chat_id, text: "/init"}
2. webhook_server valida secret token; se ok, dispatcha
3. command_handler:
   - chat_id já existe em subscribers? → responde "🔄 já estava ativo"
   - senão: subscribers.add(chat_id) + responde "✅ Monitoramento iniciado"
4. Próximo tick do scheduler verá subscribers != ∅ e iniciará polling
```

### Fluxo: `/stop`

```
1. Telegram → POST {chat_id, text: "/stop"}
2. command_handler:
   - chat_id existe? subscribers.remove(chat_id) + responde "⏸ Pausado pra você"
   - não existia? → responde "Você não estava monitorando"
3. Se subscribers.is_empty() agora, scheduler pulará próximas iterações
```

### Fluxo: detecção de vaga

```
A cada 5min (jitter ±30s):
  if subscribers.is_empty(): skip iteração (sem hit no Goiás)
  resultado = expresso.fetch_datas(Goiânia)
  diff = change_detector(resultado, state_anterior)
  state_store.save(resultado)
  if diff.has_news:
    msg = format_message(diff)
    notifier.broadcast(subscribers.all(), msg)
    # erros 403 removem o chat de subscribers
```

### Fluxo: setup do webhook

```
1. Usuário sobe túnel: cloudflared tunnel --url http://localhost:8080
2. cloudflared retorna URL: https://xxx.trycloudflare.com
3. Usuário roda: python -m bot setup-webhook https://xxx.trycloudflare.com
4. Bot chama POST https://api.telegram.org/bot<TOKEN>/setWebhook
   com {url, secret_token}
5. Telegram passa a entregar updates via POST naquele URL
```

## Estado e persistência

### subscribers.json

```json
{
  "subscribers": [123456789, 987654321],
  "updated_at": "2026-04-29T14:32:01Z"
}
```

### Restart behavior

- Boot: `subscribers.json` carregado para `set` em memória.
- Se há subscribers → scheduler entra em modo ativo automaticamente.
- Se vazio → scheduler em modo idle.

### Idempotência

- `/init` em quem já é subscriber: noop + msg de confirmação.
- `/stop` em quem não é subscriber: noop + msg neutra.
- `setup-webhook` chamado várias vezes: noop se URL idêntico, atualiza se diferente.

## Segurança

- **Secret token:** gerado no primeiro boot (`secrets.token_urlsafe(32)`), salvo no `.env`. Validado em todo POST do webhook.
- **HTTPS:** garantido pelo túnel (cloudflared/serveo dão TLS terminado). O servidor local pode ser HTTP simples — o túnel cuida do TLS.
- **Sem auth de chat:** decisão consciente — qualquer um pode mandar `/init`. Mitigação: o nome do bot (`@cin_agendamento_expresso_bot`) é privado entre amigos. Se virar problema, adicionar allowlist depois (não escopo agora).
- **Sem rate limit no webhook:** Telegram já faz rate limit no envio de updates (~30/s); ataque DDoS é mitigado pelo cloudflared.

## Modo de teste local (sem deploy)

```bash
# 1. Subir o bot
python -m bot serve   # escuta em http://localhost:8080

# 2. Em outro terminal, abrir túnel
cloudflared tunnel --url http://localhost:8080
# saída: 2026-04-29 14:00:00 INF | https://xxx-yyy-zzz.trycloudflare.com

# 3. Configurar webhook
python -m bot setup-webhook https://xxx-yyy-zzz.trycloudflare.com

# 4. Testar no Telegram
#    /init   → deve responder "Monitoramento iniciado"
#    /status → "🟢 Ativo"
#    aguardar 5min para primeiro poll
#    /stop   → "Pausado"
```

## Plano de testes

### Unitários (`tests/`)

- `test_subscriber_store.py` — add, remove, is_empty, persistência atômica, recuperação de arquivo corrompido (json malformado → start vazio + log)
- `test_command_handler.py` — todos os comandos × estados (já é subscriber, não é, primeiro `/init`, `/stop` quando vazio, comando desconhecido, `/status` em vazio/ativo)
- `test_webhook_server.py` — secret token válido/inválido, payload malformado, métodos HTTP errados (405), path desconhecido (404), `/health`
- `test_telegram_notifier.py` — adicionar testes para `broadcast` (3 chats, 1 falha 403 → removido; 1 falha 500 → mantido)
- `test_scheduler.py` — adicionar testes para "skip quando subscribers vazio" e "broadcast ao detectar diff"

### Integração

- `test_serve_integration.py` — sobe servidor HTTP em porta efêmera, manda POST simulando Telegram, verifica side effects em `subscribers.json`
- Reaproveita fixtures realistas existentes (`listar_datas_anicuns.json`)

### Smoke manual (não automatizado)

- Túnel + setup-webhook + `/init` + aguardar poll + `/stop` documentado no README.

## O que fica fora deste spec (YAGNI)

- ❌ Modo polling de fallback (`getUpdates`) — só webhook
- ❌ Allowlist/restrição de chats — sem restrição agora
- ❌ Comandos administrativos (`/restart`, `/clearstate`)
- ❌ Suporte a múltiplos municípios via Telegram — segue só Goiânia (config no `.env`)
- ❌ Migração de `python -m bot run` para usar webhook — `run` segue funcional como CLI legado, sem mudança
- ❌ Webhook signature usando IP allowlist — secret token é suficiente

## Mudanças no .env.example

Adicionar:
```bash
# ----- Webhook (opcional, com defaults) -----
WEBHOOK_PORT=8080
WEBHOOK_PATH=/telegram/webhook
WEBHOOK_SECRET_TOKEN=<gerado-no-primeiro-boot-se-vazio>
```

**Importante — atualizar o intervalo de polling:**
```bash
POLL_INTERVAL_SECONDS=300   # de 180 para 300 (5min, conforme combinado)
```

## Atualizações no README

- Seção "Como funciona" — adicionar parágrafo sobre `/init` e `/stop`
- Nova seção "Modo interativo (webhook)" com exemplo de cloudflared
- Atualizar tabela de comandos CLI com `serve` e `setup-webhook`

## Critério de aceite

- [ ] `python -m bot serve` sobe sem erro com `.env` válido
- [ ] `python -m bot setup-webhook <URL>` registra com sucesso e o Telegram passa a entregar updates
- [ ] `/init` em chat novo: bot responde + `subscribers.json` ganha o chat_id
- [ ] `/stop` em subscriber: bot responde + chat_id removido
- [ ] `/status`: respostas corretas em ambos estados
- [ ] Diff detectado → broadcast pra todos os subscribers
- [ ] Subscribers != ∅ → polling roda; ∅ → polling pula
- [ ] Restart preserva subscribers.json
- [ ] Erro 403 (bot bloqueado) remove o chat automaticamente
- [ ] Cobertura de testes ≥ 85% para os novos arquivos
