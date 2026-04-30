"""Hierarquia de erros do bot.

Distingue erros transientes (que justificam retry/backoff) dos permanentes
(que indicam contrato quebrado e precisam intervenção humana).
"""


class BotError(Exception):
    """Base de todos os erros do bot."""


class TransientError(BotError):
    """Erro recuperável: timeout, 5xx, rede instável. Aplica backoff e segue."""


class PermanentError(BotError):
    """Erro de contrato: 4xx (exceto 401), shape inesperado, config inválida."""


class AuthError(TransientError):
    """401 — força refresh de token. É transiente porque pode ser token expirado."""
