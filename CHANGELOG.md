# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Added
- Comando `python -m bot status` — resumo offline do state file (sem rede).
- Comando `python -m bot doctor` — diagnóstico de config + auth Goiás + Telegram `/getMe`.
- Flag `--once` em `python -m bot run` — 1 iteração e sai (útil para cron externo).
- Comando `python -m bot --version` exibindo a versão atual.
- Contadores persistentes em `state.json`: `total_polls`, `total_notifications`, `total_errors`
  (visíveis via `bot status`).
- State e lockfile per-município (`state-{cod}.json` e `state-{cod}.lock`) — permite rodar
  instâncias paralelas para municípios distintos sem colisão (resolve PRD §15.4).
  Compatibilidade: se já existe `state.json` legado, ele é reaproveitado.
- `Makefile` com targets `install/test/cov/lint/format/type/ci/check/status/doctor/init/run/clean`.
- `scripts/validate.sh` — réplica local do CI.
- `tests/conftest.py` com fixture `reset_logging` autouse para isolamento absoluto.
- Suite de testes com 89 casos e cobertura de 84%.
- CI no GitHub Actions (Python 3.11/3.12) com lint + format-check + mypy + pytest + gitleaks.
- Pre-commit hooks (`gitleaks`, `ruff`, `detect-private-key`).
- Testes de integração end-to-end com payload realista do PRD §A (Anicuns).

### Changed
- Removida dependência `python-telegram-bot` em favor de chamadas diretas via `requests`
  à Bot API (justificativa registrada no PRD §13).
- Erros de configuração no CLI viram mensagem amigável em stderr (sem stacktrace) com exit 1.

### Security
- `TokenMaskFilter` em todos os handlers de logging — Bearer e tokens de bot Telegram são
  mascarados mesmo em `LOG_LEVEL=DEBUG`.
- `urllib3`/`httpx` configurados em `WARNING` para evitar leak de headers em logs.

## [0.1.0] — 2026-04-29

### Added
- PRD inicial em `tasks/prd-cin-agendamento-expresso-bot.md`.
- Implementação completa das fases 0–5 do PRD: bootstrap, core HTTP (auth + listarDatas),
  estado e diff, Telegram notifier, scheduler com backoff/lockfile/sinais, hardening.
- LaunchAgent para macOS (`scripts/com.edilson.cin-agendamento-bot.plist` + `install.sh`/`uninstall.sh`).
