"""Persistência do estado em `state.json`.

Write atômico (write em `.tmp` + `os.replace`) para resistir a Ctrl+C.
Hash SHA-256 do conteúdo canonical para idempotência (FR-4 / US-004).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class State:
    last_check_at: str | None = None
    last_change_at: str | None = None
    last_notification_at: str | None = None
    id_senha: int = 0
    cod_municipio: int = 0
    hash: str = ""
    datas_por_unidade: dict[str, list[str]] = field(default_factory=dict)
    total_polls: int = 0
    total_notifications: int = 0
    total_errors: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> State:
        data = json.loads(raw)
        return cls(
            last_check_at=data.get("last_check_at"),
            last_change_at=data.get("last_change_at"),
            last_notification_at=data.get("last_notification_at"),
            id_senha=int(data.get("id_senha", 0)),
            cod_municipio=int(data.get("cod_municipio", 0)),
            hash=str(data.get("hash", "")),
            datas_por_unidade=dict(data.get("datas_por_unidade", {})),
            total_polls=int(data.get("total_polls", 0)),
            total_notifications=int(data.get("total_notifications", 0)),
            total_errors=int(data.get("total_errors", 0)),
        )

    @property
    def is_empty(self) -> bool:
        return not self.datas_por_unidade


def hash_datas(datas_por_unidade: dict[str, list[str]]) -> str:
    """Hash determinístico do mapeamento unidade → datas."""
    canonical = json.dumps(
        {k: sorted(v) for k, v in sorted(datas_por_unidade.items())},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class StateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> State:
        if not self._path.exists():
            return State()
        try:
            return State.from_json(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("state.json corrompido (%s) — resetando", exc)
            return State()

    def save(self, state: State) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(state.to_json(), encoding="utf-8")
        tmp.replace(self._path)
