"""Persistência atômica de subscribers.

Cada chat guarda:
  - `municipios`: set de cod_municipio que ele quer monitorar
  - `msg_id`: id da mensagem do "dashboard" editável (None se nunca foi enviada)

Formato em disco (subscribers.json):
    {
      "subscribers": {
        "123": {"municipios": [25300, 23600], "msg_id": 99},
        "456": {"municipios": [148400], "msg_id": null}
      },
      "updated_at": "2026-04-30T..."
    }

Migração:
  - Formato muito antigo `[123, 456]` (lista de chats) → cada chat sem municípios e sem msg_id
  - Formato intermediário `{"123": [25300]}` (dict de listas) → dict completo com msg_id null

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
        # Estrutura paralela em memória pra simplicidade de acesso.
        self._municipios: dict[int, set[int]] = {}
        self._msg_ids: dict[int, int | None] = {}
        self._load()

    # --- Consultas -----------------------------------------------------------

    def has_chat(self, chat_id: int) -> bool:
        return chat_id in self._municipios

    def municipios_de(self, chat_id: int) -> set[int]:
        return set(self._municipios.get(chat_id, set()))

    def all_chats(self) -> set[int]:
        return set(self._municipios.keys())

    def municipios_distintos(self) -> set[int]:
        out: set[int] = set()
        for codigos in self._municipios.values():
            out.update(codigos)
        return out

    def chats_para(self, cod_municipio: int) -> set[int]:
        return {cid for cid, codigos in self._municipios.items() if cod_municipio in codigos}

    def is_empty(self) -> bool:
        return not any(self._municipios.values())

    def get_dashboard_msg_id(self, chat_id: int) -> int | None:
        return self._msg_ids.get(chat_id)

    # --- Mutadores -----------------------------------------------------------

    def add_chat(self, chat_id: int) -> bool:
        if chat_id in self._municipios:
            return False
        self._municipios[chat_id] = set()
        self._msg_ids.setdefault(chat_id, None)
        self._persist()
        return True

    def remove_chat(self, chat_id: int) -> bool:
        if chat_id not in self._municipios:
            return False
        del self._municipios[chat_id]
        self._msg_ids.pop(chat_id, None)
        self._persist()
        return True

    def add_municipio(self, chat_id: int, cod: int) -> bool:
        codigos = self._municipios.setdefault(chat_id, set())
        self._msg_ids.setdefault(chat_id, None)
        if cod in codigos:
            return False
        codigos.add(cod)
        self._persist()
        return True

    def remove_municipio(self, chat_id: int, cod: int) -> bool:
        codigos = self._municipios.get(chat_id)
        if not codigos or cod not in codigos:
            return False
        codigos.discard(cod)
        self._persist()
        return True

    def toggle_municipio(self, chat_id: int, cod: int) -> bool:
        codigos = self._municipios.setdefault(chat_id, set())
        self._msg_ids.setdefault(chat_id, None)
        if cod in codigos:
            codigos.discard(cod)
            self._persist()
            return False
        codigos.add(cod)
        self._persist()
        return True

    def set_dashboard_msg_id(self, chat_id: int, msg_id: int | None) -> None:
        """Salva o message_id do dashboard editável do chat."""
        self._municipios.setdefault(chat_id, set())
        self._msg_ids[chat_id] = msg_id
        self._persist()

    # --- Persistência --------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "subscribers.json corrompido (%s) — começando vazio", exc
            )
            return
        subs = data.get("subscribers")
        if subs is None:
            return

        # Formato muito antigo: list[int]
        if isinstance(subs, list):
            try:
                for x in subs:
                    cid = int(x)
                    self._municipios[cid] = set()
                    self._msg_ids[cid] = None
                logger.info(
                    "subscribers.json migrado de formato lista legado (%d chats)",
                    len(self._municipios),
                )
            except (ValueError, TypeError) as exc:
                logger.warning("subscribers.json (lista) inválido (%s) — vazio", exc)
            return

        if not isinstance(subs, dict):
            logger.warning(
                "subscribers.json: 'subscribers' tem tipo inesperado %s — vazio",
                type(subs).__name__,
            )
            return

        for k, v in subs.items():
            try:
                chat_id = int(k)
            except (ValueError, TypeError):
                logger.warning("chat_id inválido %r — pulando", k)
                continue

            # Formato intermediário: lista direta
            if isinstance(v, list):
                self._municipios[chat_id] = self._coerce_codigos(v, chat_id)
                self._msg_ids[chat_id] = None
                continue

            # Formato novo: dict com municipios + msg_id
            if isinstance(v, dict):
                codigos_raw = v.get("municipios", [])
                self._municipios[chat_id] = self._coerce_codigos(codigos_raw, chat_id)
                msg_id = v.get("msg_id")
                if msg_id is None:
                    self._msg_ids[chat_id] = None
                else:
                    try:
                        self._msg_ids[chat_id] = int(msg_id)
                    except (ValueError, TypeError):
                        logger.warning(
                            "msg_id inválido %r para chat %s — null", msg_id, chat_id
                        )
                        self._msg_ids[chat_id] = None
                continue

            logger.warning(
                "valor de %s tem tipo %s — pulando", chat_id, type(v).__name__
            )

    @staticmethod
    def _coerce_codigos(raw: object, chat_id: int) -> set[int]:
        out: set[int] = set()
        if not isinstance(raw, list):
            return out
        for item in raw:
            try:
                out.add(int(item))
            except (ValueError, TypeError):
                logger.warning("codigo inválido %r para chat %s — pulando", item, chat_id)
        return out

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "subscribers": {
                str(cid): {
                    "municipios": sorted(self._municipios[cid]),
                    "msg_id": self._msg_ids.get(cid),
                }
                for cid in sorted(self._municipios)
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self._path)
