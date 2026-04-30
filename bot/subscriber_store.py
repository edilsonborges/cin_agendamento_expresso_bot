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
