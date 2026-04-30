# cin_agendamento_expresso_bot

Bot de Telegram que monitora vagas para a **Carteira de Identidade Nacional (CIN)** no portal
[Vapt Vupt — Goiás Digital](https://www.go.gov.br/servicos-digitais/vapt-vupt/agendamento-atendimento-presencial/novo/origem-rg)
e notifica quando datas abrem para um município de interesse (default: **Goiânia**).

> Status atual: **Especificação concluída.** PRD em [`tasks/prd-cin-agendamento-expresso-bot.md`](tasks/prd-cin-agendamento-expresso-bot.md). Implementação a iniciar.

---

## Como funciona

1. A cada ~3 minutos, o bot autentica via OAuth2 (`client_credentials`) na API pública do
   Goiás Digital e consulta o endpoint `listarDatasAgendamento`.
2. Compara a resposta com o último estado salvo em `state.json`.
3. Se houver datas novas, envia uma mensagem formatada no Telegram.
4. Se a resposta for vazia (estado normal hoje), apenas registra log e dorme.

Sem login, sem cookies de sessão, sem captcha. Tudo via 2 chamadas HTTP por ciclo.

---

## Setup local (rascunho — implementação pendente)

```bash
# 1. Clonar
git clone git@github.com:edilsonborges/cin_agendamento_expresso_bot.git
cd cin_agendamento_expresso_bot

# 2. Ambiente
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configurar
cp .env.example .env
# editar TELEGRAM_BOT_TOKEN

# 4. Descobrir o chat_id automaticamente
python -m bot init
# (no Telegram, abra @cin_agendamento_expresso_bot e mande /start)

# 5. Smoke test
python -m bot check

# 6. Rodar em loop
python -m bot run
```

### Rodando 24/7 no macOS via launchd
```bash
./scripts/install.sh
launchctl list | grep cin-agendamento
tail -f bot.log
```

---

## Arquitetura

Ver [PRD § 7 — Arquitetura Proposta](tasks/prd-cin-agendamento-expresso-bot.md#7-arquitetura-proposta).

---

## Roadmap

- [x] Reverse engineering dos endpoints (validação ao vivo)
- [x] PRD aprovado
- [ ] Fase 1 — Core HTTP (auth + fetch_datas)
- [ ] Fase 2 — Estado e diff
- [ ] Fase 3 — Notificação Telegram
- [ ] Fase 4 — Loop + supervisor
- [ ] Fase 5 — Hardening

---

## Contato

Bot Telegram: [@cin_agendamento_expresso_bot](https://t.me/cin_agendamento_expresso_bot)
