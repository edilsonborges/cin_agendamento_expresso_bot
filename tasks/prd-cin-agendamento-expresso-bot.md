# PRD: cin_agendamento_expresso_bot

> **Versão:** 1.0
> **Data:** 2026-04-29
> **Autor:** edilson
> **Status:** Draft (pronto para implementação)

---

## 1. Introdução / Visão

O serviço de agendamento da **Carteira de Identidade Nacional (CIN)** no portal Goiás Digital
(Vapt Vupt) está com a oferta de vagas para o município de **GOIÂNIA** zerada de forma
recorrente. As vagas são abertas em lotes esporádicos, sem aviso prévio, e desaparecem em
minutos. Ficar acessando manualmente o site é inviável.

O **`cin_agendamento_expresso_bot`** é um cron leve que monitora continuamente a API pública
do portal e dispara uma notificação no Telegram assim que vagas para Goiânia abrem,
listando as datas disponíveis e a unidade do Vapt Vupt onde elas existem.

### O que o bot **é**
- Um worker Python rodando 24/7 em loop, com persistência local de estado.
- Um cliente HTTP autenticado via OAuth2 `client_credentials` (token público do front-end do
  Goiás Digital).
- Um emissor de mensagens via Bot API do Telegram.

### O que o bot **não é**
- Não realiza o agendamento automaticamente — apenas notifica.
- Não armazena dados pessoais do cidadão (CPF, RG, etc.).
- Não substitui o site oficial.

---

## 2. Goals (Objetivos Mensuráveis)

| # | Goal | Métrica |
|---|------|---------|
| G1 | Detectar abertura de vagas em GOIANIA dentro de 5 min da publicação real | Tempo médio entre abertura real e notificação ≤ 5 min |
| G2 | Zero falsos positivos (notificar somente quando há datas inéditas) | 0 mensagens redundantes em 7 dias de operação contínua |
| G3 | Operação 24/7 sem intervenção manual | Uptime ≥ 99% em 7 dias |
| G4 | Não ser bloqueado pelo servidor (rate limit / WAF) | Taxa de respostas HTTP 200 ≥ 99,5% |
| G5 | Configuração e deploy em < 10 min | README com passo-a-passo single-host |

---

## 3. Personas

### P1 — O Cidadão-Dev (você)
- Tem CIN para emitir/atualizar.
- Goiânia é a cidade de interesse — outras cidades têm vaga, mas exigem deslocamento.
- Confortável com terminal, Python, GitHub e Telegram.
- Quer ser notificado **sem ter que fazer nada** depois do setup.

### P2 — Familiar / amigo (extensão futura, fora do MVP)
- Recebe a mesma notificação para reagir mais rápido (provider chat IDs múltiplos).

---

## 4. User Stories

### US-001: Bootstrap do projeto
**Description:** Como dev, quero estrutura mínima do projeto criada (pyproject, requirements, .env.example, README) para poder começar a codar.

**Acceptance Criteria:**
- [ ] `pyproject.toml` com Python 3.11+ definido
- [ ] `requirements.txt` listando: `requests`, `python-dotenv` (Telegram via Bot API direta)
- [ ] `.env.example` com chaves: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `POLL_INTERVAL_SECONDS`, `JITTER_SECONDS`, `COD_MUNICIPIO`, `ID_SENHA`, `LOG_LEVEL`
- [ ] `.gitignore` excluindo `.env`, `state.json`, `*.log`, `__pycache__/`, `.venv/`
- [ ] `README.md` com seção "Setup local" funcional

### US-002: Cliente OAuth2 com cache de token
**Description:** Como bot, preciso de um cliente que obtenha e renove tokens automaticamente para nunca ficar sem credencial válida.

**Acceptance Criteria:**
- [ ] Função `get_access_token()` que retorna token válido, renovando quando faltar < 120s
- [ ] Cache em memória (`_token`, `_expires_at`) — não persiste em disco
- [ ] Em caso de HTTP 401 numa chamada subsequente, força refresh imediato e reta uma vez
- [ ] Logs nunca expõem o token completo (somente os primeiros 20 chars + `...`)
- [ ] Testes: simular expiração e validar que faz novo `POST /token`

### US-003: Cliente da API de datas
**Description:** Como bot, preciso de uma função que retorne o estado atual de vagas para um (idSenha, codgMunicipio).

**Acceptance Criteria:**
- [ ] `fetch_datas(id_senha: int, cod_municipio: int) -> list[Unidade]`
- [ ] Header `Authorization: Bearer <token>`, `Referer` igual ao do front
- [ ] Resposta vazia `[]` é tratada como caso válido (sem vagas)
- [ ] Timeout de 10s; em timeout, levanta `TransientError`
- [ ] HTTP 5xx → `TransientError`; HTTP 4xx (exceto 401) → `PermanentError`

### US-004: Detector de mudança de estado
**Description:** Como bot, preciso comparar estado atual com o anterior persistido em disco e decidir se há novidade que merece notificação.

**Acceptance Criteria:**
- [ ] `state.json` armazena `{ "last_check_at": iso8601, "hash": str, "datas_por_unidade": dict[str, list[str]] }`
- [ ] `compute_diff(prev, curr)` retorna `{ novas_unidades, novas_datas_por_unidade }`
- [ ] Transição vazio → com vagas: notifica todas as datas
- [ ] Transição com vagas → com vagas (datas iguais): NÃO notifica (idempotência por hash)
- [ ] Transição com vagas → com vagas (datas novas adicionadas): notifica somente as novas
- [ ] Transição com vagas → vazio: NÃO notifica (silencioso)
- [ ] Hash baseado em SHA-256 do JSON canonicalizado das datas

### US-005: Notificador Telegram
**Description:** Como dev, quero receber mensagem clara e acionável no Telegram quando vagas abrem.

**Acceptance Criteria:**
- [ ] Função `notify(mensagem: str, chat_id: int)` envia via Bot API
- [ ] Mensagem formatada em MarkdownV2:
  - 🚨 Título com emoji + nome do município
  - Lista de unidades com total de datas e as primeiras 5 (se houver mais, mostrar `...e mais N datas`)
  - Link direto para o portal (botão inline)
  - Timestamp da detecção
- [ ] Erros do Telegram (rate limit, network) são logados mas não derrubam o loop principal
- [ ] Retry automático até 3x com backoff em 5xx do Telegram

### US-006: Discovery automático do chat_id (fluxo /start)
**Description:** Como usuário, quero descobrir meu chat_id sem ter que abrir docs, simplesmente enviando /start ao bot.

**Acceptance Criteria:**
- [ ] Modo `python -m bot init`: bot escuta updates por 5 min ou até receber primeiro /start
- [ ] Quando recebe /start, salva `TELEGRAM_CHAT_ID` em `.env` (cria se não existir, atualiza se existir)
- [ ] Responde no chat: "Chat ID salvo. Pode rodar `python -m bot run`."
- [ ] Modo `python -m bot run`: lê `.env`, falha cedo com mensagem clara se chat_id estiver vazio

### US-007: Loop principal com polling defensivo
**Description:** Como bot, preciso rodar continuamente em loop respeitando rate limits e tratando falhas transientes.

**Acceptance Criteria:**
- [ ] Loop infinito com `POLL_INTERVAL_SECONDS + random.uniform(-JITTER, +JITTER)` entre iterações
- [ ] Default: poll=180s, jitter=30s (range efetivo 150–210s)
- [ ] `TransientError` → backoff exponencial (30s, 60s, 120s, max 600s); reseta ao primeiro 200
- [ ] `PermanentError` (4xx exceto 401) → loga FATAL e mantém loop (chama suporte)
- [ ] `KeyboardInterrupt` (Ctrl+C) → graceful shutdown salvando estado
- [ ] Cada iteração loga: timestamp, status HTTP, count de datas, ação (NOOP|NOTIFY)

### US-008: Logging estruturado
**Description:** Como dev, quero logs em formato fácil de filtrar e entender o que aconteceu.

**Acceptance Criteria:**
- [ ] Formato: `2026-04-29T21:30:00 [INFO] [poll] municipio=25300 datas=0 acao=noop`
- [ ] Nível configurável via `LOG_LEVEL` (default INFO)
- [ ] Arquivo `bot.log` rotativo (max 10 MB, 3 backups)
- [ ] Stdout também recebe logs (para `journalctl`/`launchd`)
- [ ] DEBUG mostra request/response sanitizados (token mascarado)

### US-009: Empacotamento e supervisor (launchd no macOS)
**Description:** Como dev, quero rodar o bot no meu Mac de forma que reinicie sozinho se cair e suba no boot.

**Acceptance Criteria:**
- [ ] `scripts/com.edilson.cin-agendamento-bot.plist` configurado para `RunAtLoad` e `KeepAlive=true`
- [ ] Script `scripts/install.sh` que copia o plist para `~/Library/LaunchAgents/` e roda `launchctl load`
- [ ] Script `scripts/uninstall.sh` para remover
- [ ] README documenta instalação alternativa via `cron` para Linux

### US-010: Verificação manual via CLI (smoke test)
**Description:** Como dev, quero rodar uma única verificação para validar setup sem esperar o loop.

**Acceptance Criteria:**
- [ ] `python -m bot check` executa 1 verificação e imprime estado atual
- [ ] Não envia notificação no Telegram (modo dry-run)
- [ ] Útil para CI / debug rápido

---

## 5. Functional Requirements (numerados)

- **FR-1:** O bot DEVE obter token via `POST https://api.go.gov.br/token` usando `Authorization: Basic <client_id:client_secret>` e `grant_type=client_credentials`.
- **FR-2:** O bot DEVE armazenar o token em memória com TTL e renová-lo quando faltarem menos de 120s.
- **FR-3:** O bot DEVE consultar `GET https://www.go.gov.br/sigac-a-api/agendamento/listarDatasAgendamento?idSenha=58&status=D&codgMunicipio=25300` em cada poll.
- **FR-4:** O bot DEVE persistir em `state.json` o último estado conhecido (hash + datas por unidade + timestamp).
- **FR-5:** O bot DEVE notificar via Telegram somente quando o hash do estado atual for diferente do anterior **E** o estado atual for não-vazio **E** existirem datas que não estavam no estado anterior.
- **FR-6:** O bot DEVE rodar em loop com intervalo de `POLL_INTERVAL_SECONDS ± JITTER_SECONDS`.
- **FR-7:** O bot DEVE tratar HTTP 401 fazendo refresh forçado do token e retentando uma vez.
- **FR-8:** O bot DEVE aplicar backoff exponencial (30s → 60s → 120s → 240s → 600s) em erros 5xx ou timeouts.
- **FR-9:** O bot DEVE expor 3 subcomandos CLI: `init` (descobrir chat_id), `check` (1 verificação dry-run), `run` (loop produção).
- **FR-10:** O bot DEVE registrar logs estruturados em stdout e arquivo rotativo, sem expor tokens.
- **FR-11:** A mensagem do Telegram DEVE conter: emoji + município, lista de unidades com primeiras 5 datas, link para o portal, timestamp.
- **FR-12:** O bot DEVE limitar a frequência de notificações a no máximo 1 a cada 60s (mesmo em mudanças sucessivas, agrupar) — proteção contra spam.

---

## 6. Não-Goals (Out of Scope)

- ❌ Não realiza o agendamento (não preenche formulário, não escolhe horário).
- ❌ Não suporta múltiplos municípios na mesma instância (usuário pode rodar instâncias separadas).
- ❌ Não suporta múltiplos chat_ids no MVP.
- ❌ Não implementa webhook do Telegram (só polling do bot.api).
- ❌ Não tem dashboard web ou histórico visual.
- ❌ Não detecta abertura de vagas para outros tipos de senha (CNH, comprovante, etc.).
- ❌ Não usa Playwright em produção (só foi necessário na fase de reverse engineering).

---

## 7. Arquitetura Proposta

```
┌──────────────────────────────────────────────────────────────────┐
│                    cin_agendamento_expresso_bot                  │
│                                                                  │
│  ┌───────────────┐    ┌────────────────────┐                     │
│  │   CLI entry   │    │      Config        │                     │
│  │  (init|check  ├───►│  (.env / dotenv)   │                     │
│  │   |run)       │    └────────────────────┘                     │
│  └──────┬────────┘                                               │
│         │                                                        │
│         ▼                                                        │
│  ┌───────────────┐    ┌────────────────────┐                     │
│  │   Scheduler   │───►│   ExpressoClient   │── HTTPS ──┐         │
│  │   (loop +     │    │   (auth + datas)   │           │         │
│  │   backoff)    │    └─────────┬──────────┘           │         │
│  └──────┬────────┘              │                      ▼         │
│         │                       │         ┌─────────────────────┐│
│         │                       │         │  api.go.gov.br      ││
│         │                       │         │  www.go.gov.br      ││
│         │                       │         └─────────────────────┘│
│         │                                                        │
│         ▼                                                        │
│  ┌───────────────┐    ┌────────────────────┐                     │
│  │  StateStore   │◄──►│   ChangeDetector   │                     │
│  │ (state.json)  │    │  (diff + hash)     │                     │
│  └───────────────┘    └─────────┬──────────┘                     │
│                                 │                                │
│                                 ▼ (se houver mudança)            │
│                       ┌────────────────────┐                     │
│                       │  TelegramNotifier  │── HTTPS ──┐         │
│                       └────────────────────┘           │         │
│                                                        ▼         │
│                                              ┌────────────────┐  │
│                                              │ api.telegram.org│  │
│                                              └────────────────┘  │
│                                                                  │
│  ┌───────────────┐                                               │
│  │    Logger     │  (stdout + bot.log rotativo)                  │
│  └───────────────┘                                               │
└──────────────────────────────────────────────────────────────────┘
```

### Estrutura de pastas
```
cin_agendamento_expresso_bot/
├── bot/
│   ├── __init__.py
│   ├── __main__.py          # CLI dispatcher (init|check|run)
│   ├── config.py             # Settings via dotenv
│   ├── expresso_client.py    # OAuth2 + listarDatasAgendamento
│   ├── state_store.py        # state.json read/write + hash
│   ├── change_detector.py    # compute_diff
│   ├── telegram_notifier.py  # send_message + format
│   ├── scheduler.py          # loop principal + backoff
│   └── logging_setup.py      # rotativo + format
├── tests/
│   ├── test_change_detector.py
│   ├── test_expresso_client.py  (com mocks)
│   └── test_state_store.py
├── scripts/
│   ├── com.edilson.cin-agendamento-bot.plist
│   ├── install.sh
│   └── uninstall.sh
├── tasks/
│   └── prd-cin-agendamento-expresso-bot.md  ← este arquivo
├── .env.example
├── .gitignore
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 8. Esquema de Dados (estado persistido)

### `state.json`
```json
{
  "last_check_at": "2026-04-29T21:32:00-03:00",
  "last_change_at": "2026-04-29T18:14:23-03:00",
  "last_notification_at": "2026-04-29T18:14:25-03:00",
  "id_senha": 58,
  "cod_municipio": 25300,
  "hash": "f3d2a1...",
  "datas_por_unidade": {
    "Goiânia - Vapt Vupt Centro": ["02/05/2026", "03/05/2026"]
  }
}
```

**Notas de design:**
- Quando o estado é "vazio", `datas_por_unidade = {}` e `hash` é fixo (`hash("")`).
- O `last_change_at` só atualiza quando o `hash` muda — útil para análise post-mortem.
- `last_notification_at` é separado do `last_change_at` para permitir, no futuro, retentativas
  de notificação se o Telegram falhou.

---

## 9. Estratégia de Polling

### Intervalo
- **POLL_INTERVAL_SECONDS = 180s** (3 min) com **JITTER_SECONDS = 30s** → range efetivo 150–210s.
- Justificativa: agressivo o suficiente para pegar vagas (que somem em minutos), mas
  ~20 chamadas/hora é totalmente dentro do que um usuário humano poderia fazer.

### Headers obrigatórios
```
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36
            (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36
Accept: application/json
Accept-Language: pt,en-US;q=0.9,en;q=0.8
Referer: https://www.go.gov.br/servicos-digitais/vapt-vupt/agendamento-atendimento-presencial/novo/origem-rg
Authorization: Bearer <token>
```

### Backoff em erro
| Tentativa | Espera adicional |
|-----------|------------------|
| 1ª falha  | 30s              |
| 2ª falha  | 60s              |
| 3ª falha  | 120s             |
| 4ª falha  | 240s             |
| 5ª+ falha | 600s (cap)       |

Reset ao primeiro HTTP 200.

---

## 10. Formato de Mensagem (Telegram)

### Caso "abertura de vagas"
```
🚨 *Vagas CIN abertas em GOIÂNIA*

📍 *Goiânia \- Vapt Vupt Centro* — 7 datas
   • 02/05/2026
   • 03/05/2026
   • 06/05/2026
   • 07/05/2026
   • 08/05/2026
   _\.\.\.e mais 2 datas_

🔗 [Agendar agora](https://www.go.gov.br/servicos-digitais/vapt-vupt/agendamento-atendimento-presencial/novo/origem-rg)
🕐 _detectado em 29/04/2026 18:14_
```

### Caso "novas datas"
```
✨ *Novas datas CIN em GOIÂNIA*

📍 *Goiânia \- Vapt Vupt Centro*
   *Novas:* 12/05/2026, 13/05/2026
   *Total atual:* 9 datas

🔗 [Agendar agora](...)
```

---

## 11. Plano de Implementação em Fases

### Diretrizes de versionamento e segurança

- **Commits orgânicos, NÃO um commit por fase.** As fases abaixo descrevem
  agrupamentos lógicos de trabalho, não unidades de commit. Faça commits
  pequenos e contextuais sempre que houver uma mudança coerente
  (ex: "feat: ExpressoAuth com cache de token"), mesmo que a fase ainda
  não esteja terminada. Isso facilita revisão e revert.
- **Nunca commitar a chave do bot Telegram** (nem em código, nem em
  documentação, nem em mensagens de commit). A `.env` está no `.gitignore`;
  qualquer outro lugar é proibido. O `.env.example` deve ter sempre valores
  vazios ou placeholders (`<sua-chave-do-bot>`).
- **Pre-commit defensivo:** considerar adicionar [`gitleaks`](https://github.com/gitleaks/gitleaks)
  ou hook simples que rejeite o padrão `[0-9]{9,10}:[A-Za-z0-9_-]{35}` (formato
  do token de bot Telegram).

### Fase 0 — Bootstrap (1 sessão)
- [x] Pasta + git init + remote (público após sanitização de credencial)
- [x] PRD aprovado (este documento)
- [x] README, .env.example, .gitignore, pyproject.toml, requirements.txt

### Fase 1 — Core HTTP (1 sessão)
- [x] US-002: ExpressoAuth (token cache + refresh quando faltar <120s)
- [x] US-003: fetch_datas (retorna `list[Unidade]`, trata 401/4xx/5xx/timeout)
- [x] US-008: logging_setup (stdout + arquivo rotativo, mascara tokens)
- [x] US-010: comando `check` (smoke test dry-run)
- [x] **Critério de saída:** `python -m bot check` imprime `[]` para Goiânia em **0.56s** ✅

### Fase 2 — Estado e diff (1 sessão)
- [x] US-004: state_store (write atômico + hash SHA-256) + change_detector
- [x] Testes unitários do diff (11 casos cobrindo as 4 transições do PRD)
- [x] **Critério de saída:** `pytest -k change_detector` → 11 passed ✅

### Fase 3 — Telegram (1 sessão)
- [x] US-006: comando `init` (polling getUpdates por 5min, escreve chat_id no .env)
- [x] US-005: TelegramNotifier (sendMessage MarkdownV2 + retry 3x + backoff)
- [x] format_message: caso "primeira abertura" e caso "novas datas"
- [x] **Critério de saída:** smoke test do format + send com `responses` mock ✅

### Fase 4 — Loop e supervisor (1 sessão)
- [x] US-007: scheduler com backoff exponencial (30/60/120/240/600s) e signal handlers
- [x] Lockfile via `flock` (R7 — segunda instância falha imediato)
- [x] US-009: launchd plist + install.sh/uninstall.sh
- [x] **Critério de saída:** scheduler testado via mocks (8 testes, todas as transições) ✅

### Fase 5 — Hardening (1 sessão)
- [x] FR-12: rate limit de notificação (60s mínimo entre alertas)
- [x] Fixtures de transição (vazio→vagas, vagas→novas, vagas→vazio, supressão por rate-limit)
- [x] Documentação operacional no README (logs, parar/reiniciar, troubleshooting)
- [ ] **Critério de saída:** rodando 24h sem intervenção (validação manual em campo)

---

## 12. Riscos e Mitigações

| # | Risco | Probabilidade | Impacto | Mitigação |
|---|-------|---------------|---------|-----------|
| R1 | Goiás Digital troca o `client_id`/`client_secret` exposto no front | Média | Alto | Bot detecta 401 mesmo após refresh → loga FATAL com instrução para o dev abrir o site e capturar nova credential. README documenta processo. |
| R2 | API muda formato de resposta | Baixa | Médio | Validação leve do shape (`isinstance(list)`) — em caso de quebra, loga erro detalhado e mantém loop. Não tenta inferir formato. |
| R3 | WAF / rate limit bloqueia o IP | Média | Alto | Jitter aleatório, intervalo conservador (3 min), User-Agent realista, Referer correto. Se 429 ou 403, backoff por 30 min e notifica via Telegram. |
| R4 | Token do Telegram vazado em commit ou no PRD | Média (humano) | Alto | `.gitignore` cobre `.env`; pre-commit hook (gitleaks) bloqueia padrão de token de bot Telegram; PRD/README usam apenas placeholders. **Mitigação se vazar:** revogar imediatamente via @BotFather (`/revoke`) e gerar nova chave — invalidação é instantânea e simples. |
| R5 | Mac dorme / perde conexão | Alta | Médio | `caffeinate -s` opcional; launchd com `KeepAlive` reinicia ao acordar. Loop tolera erros de rede transitórios. |
| R6 | Vaga abre e fecha entre dois polls (perdida) | Média | Médio | 3 min é o melhor compromisso. Se virar problema real, reduzir para 60s (custo: maior risco de bloqueio). |
| R7 | Múltiplas instâncias rodando ao mesmo tempo (spam) | Baixa | Alto | Lockfile em `state.lock`. Segunda instância detecta e aborta. |
| R8 | `state.json` corrompido (Ctrl+C no momento errado) | Baixa | Baixo | Write atômico (write em `.tmp` e `os.rename`). Se falhar parse, reseta para vazio e loga warning. |

---

## 13. Considerações Técnicas

### Stack escolhida
- **Linguagem:** Python 3.11+
- **HTTP:** `requests` (síncrono, simples; volume baixo dispensa async)
- **Telegram:** Bot API direta via `requests` (`/sendMessage`, `/getUpdates`). A dependência
  `python-telegram-bot` foi avaliada e descartada — async/framework não traz ganho para 2 endpoints,
  e síncrono casa melhor com o resto do bot.
- **Config:** `python-dotenv`
- **Logging:** stdlib `logging` com `RotatingFileHandler`
- **Testes:** `pytest` + `responses` (mock de HTTP)

### Variáveis de ambiente

> ⚠️ **Nunca colocar valores reais de `TELEGRAM_BOT_TOKEN` neste documento, no
> README, em commits ou em qualquer arquivo versionado.** A chave do bot fica
> exclusivamente no `.env` local (que está no `.gitignore`). Se a chave for
> exposta acidentalmente, revogar via @BotFather (`/revoke`) e gerar nova.

```env
# Obrigatórias — preencher no .env local, nunca neste PRD
TELEGRAM_BOT_TOKEN=<sua-chave-do-bot>
TELEGRAM_CHAT_ID=<seu-chat-id>

# Opcionais (com defaults)
POLL_INTERVAL_SECONDS=180
JITTER_SECONDS=30
COD_MUNICIPIO=25300
ID_SENHA=58
LOG_LEVEL=INFO

# Credenciais Goiás Digital (públicas, capturadas do front-end — OK estar aqui)
GOIAS_OAUTH_BASIC=<basic-base64-do-front>
GOIAS_REFERER=https://www.go.gov.br/servicos-digitais/vapt-vupt/agendamento-atendimento-presencial/novo/origem-rg
```

### Dependências externas conhecidas
| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `https://api.go.gov.br/token` | POST | OAuth2 client_credentials |
| `https://www.go.gov.br/sigac-a-api/agendamento/listarDatasAgendamento` | GET | Lista datas disponíveis |
| `https://api.telegram.org/bot<token>/sendMessage` | POST | Envia mensagem |
| `https://api.telegram.org/bot<token>/getUpdates` | GET | Polling para descobrir chat_id |

---

## 14. Success Metrics (revisão pós-deploy, 7 dias)

- [ ] **Detection lag:** medir tempo entre publicação real (visualmente confirmada no site)
      e chegada da notificação no Telegram. Meta: < 5 min.
- [ ] **False positive rate:** 0 mensagens redundantes. Verificar via inspeção manual dos logs.
- [ ] **Uptime:** `journalctl -u cin-bot` ou `launchctl list` mostra processo ativo.
- [ ] **Erro rate:** % de iterações que terminaram em status != 200. Meta: ≤ 0,5%.
- [ ] **Auto-recovery:** ao menos 1 erro transiente ocorrido e recuperado sem intervenção.

---

## 15. Decisões registradas (originalmente "Open Questions")

1. ✅ **Frequência de notificação repetida:** Cada transição vazio → com vagas dispara
   notificação. Implementado via diff de hash em `change_detector.compute_diff` + rate-limit
   defensivo de 60s (FR-12) para agrupar mudanças sucessivas.
2. ✅ **Agrupamento por unidade:** Tudo numa mesma mensagem. `format_message` itera todas as
   unidades em `diff.novas_datas_por_unidade` ordenadas por nome.
3. ✅ **Limite de horas para rodar:** Sem pausa. O servidor pode publicar a qualquer hora,
   inclusive madrugada — não vale perder janela.
4. ✅ **Reuso para outros municípios:** Implementado na v1 via state/lock per-município
   (`state-{cod_municipio}.json` e `state-{cod_municipio}.lock`). Instâncias paralelas com
   `.env` distintos não colidem. Para legado, se já existir um `state.json` (sem cod), ele é
   reaproveitado para a migração natural.

---

## 16. Extensões Futuras (não-MVP)

- Suporte a múltiplos municípios numa única instância (loop interno por município)
- Suporte a múltiplos `chat_ids` (broadcast)
- Comando `/status` no bot que retorna estado atual sem esperar próximo poll
- Webhook Telegram em vez de long polling no `init`
- Dashboard web simples (FastAPI + HTMX) com histórico das verificações
- Suporte a outros tipos de senha (CNH, comprovante de residência, etc.)
- Métricas Prometheus + Grafana para análise de padrão de aberturas

---

## Apêndice A — Curls de referência (validados em 2026-04-29)

### Obter token
```bash
curl -s -X POST 'https://api.go.gov.br/token' \
  -H 'Authorization: Basic ak1Rb3lIX1QyR3BXWHdCbEg2Z29XZkJCZHIwYTprOEJPc0lIVEY2c0FSZkhxNHFCUHN2YVlqZjRh' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H 'Referer: https://www.go.gov.br/' \
  --data 'grant_type=client_credentials'
```
Resposta:
```json
{ "access_token": "eyJ4NXQ...", "token_type": "Bearer", "expires_in": 3600 }
```

### Listar datas — GOIÂNIA (vazio)
```bash
curl -s "https://www.go.gov.br/sigac-a-api/agendamento/listarDatasAgendamento?idSenha=58&status=D&codgMunicipio=25300" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Referer: https://www.go.gov.br/servicos-digitais/vapt-vupt/agendamento-atendimento-presencial/novo/origem-rg'
```
Resposta: `[]`

### Listar datas — ANICUNS (com vagas, validação positiva)
Mesmo curl com `codgMunicipio=23600`. Resposta:
```json
[{"idUnidade":45,"nomeUnidade":"Anicuns","idSenha":58,"nomeSenha":"SSP - CARTEIRA DE IDENTIDADE NACIONAL (CIN)",
  "datas":["19/05/2026","20/05/2026", ... 27 datas total]}]
```

## Apêndice B — Mapa completo de municípios (idSenha=58 / CIN)

| Município | codgMunicipio |
|-----------|---------------|
| AGUAS LINDAS DE GOIAS | 149400 |
| ALVORADA DO NORTE | 15300 |
| ANAPOLIS | 23500 |
| ANICUNS | 23600 |
| APARECIDA DE GOIANIA | 33800 |
| BELA VISTA DE GOIAS | 34000 |
| ... | ... |
| **GOIANIA** | **25300** |
| GOIANIRA | 25400 |
| ... | ... |
| TRINDADE | 28800 |
| VALPARAISO DE GOIAS | 148400 |

(Lista completa de 58 municípios obtida via `GET /sigac-a-api/agendamento/listarCidades?idSenha=58`.)
