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
                logger.debug("http %s", fmt % args)

            def do_POST(self) -> None:
                if self.path != cls._webhook_path:
                    if self.path == "/health":
                        self.send_error(405, "method not allowed")
                    else:
                        self.send_error(404, "not found")
                    return
                if self.headers.get("X-Telegram-Bot-Api-Secret-Token", "") != cls._secret:
                    logger.warning("webhook POST sem secret válido path=%s", self.path)
                    self.send_error(401, "unauthorized")
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
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
