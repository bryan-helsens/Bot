"""Tamper-evident audit logging.

Every security- or trading-significant action is recorded as an immutable audit
entry. Entries are **hash-chained**: each record's hash includes the previous
record's hash, so any retroactive modification or deletion breaks the chain and
is detectable via :meth:`AuditLogger.verify`. Entries are emitted to the
structured logger and, optionally, handed to a sink (e.g. a database repository)
for durable storage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from quantbot.core.logging import get_logger
from quantbot.core.models import utcnow

_log = get_logger("audit")

#: Optional async sink invoked for each entry (e.g. persist to DB).
AuditSink = Callable[["AuditEntry"], Awaitable[None]]


@dataclass(slots=True)
class AuditEntry:
    """A single, hash-chained audit record."""

    sequence: int
    actor: str
    action: str
    resource: str
    payload: dict[str, object]
    timestamp: datetime
    prev_hash: str
    hash: str = ""

    def compute_hash(self) -> str:
        """Deterministic SHA-256 over the entry's content + previous hash."""
        body = json.dumps(
            {
                "sequence": self.sequence,
                "actor": self.actor,
                "action": self.action,
                "resource": self.resource,
                "payload": self.payload,
                "timestamp": self.timestamp.isoformat(),
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(body.encode()).hexdigest()


class AuditLogger:
    """Append-only, hash-chained audit trail."""

    _GENESIS = "0" * 64

    def __init__(self, *, enabled: bool = True, sink: AuditSink | None = None) -> None:
        self._enabled = enabled
        self._sink = sink
        self._entries: list[AuditEntry] = []
        self._last_hash = self._GENESIS

    async def record(
        self, *, actor: str, action: str, resource: str, **payload: object
    ) -> AuditEntry | None:
        """Append an audit entry for *actor* performing *action* on *resource*."""
        if not self._enabled:
            return None
        entry = AuditEntry(
            sequence=len(self._entries),
            actor=actor,
            action=action,
            resource=resource,
            payload=payload,
            timestamp=utcnow(),
            prev_hash=self._last_hash,
        )
        entry.hash = entry.compute_hash()
        self._entries.append(entry)
        self._last_hash = entry.hash
        _log.info(
            "audit", actor=actor, action=action, resource=resource,
            sequence=entry.sequence, hash=entry.hash[:12], **payload,
        )
        if self._sink is not None:
            try:
                await self._sink(entry)
            except Exception as exc:  # noqa: BLE001 - sink failure must not lose the trail
                _log.error("audit_sink_failed", error=str(exc))
        return entry

    def verify(self) -> bool:
        """Verify the integrity of the entire chain (no tampering)."""
        prev = self._GENESIS
        for entry in self._entries:
            if entry.prev_hash != prev:
                _log.error("audit_chain_broken", sequence=entry.sequence, reason="prev_hash")
                return False
            if entry.compute_hash() != entry.hash:
                _log.error("audit_chain_broken", sequence=entry.sequence, reason="hash")
                return False
            prev = entry.hash
        return True

    @property
    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


__all__ = ["AuditEntry", "AuditLogger", "AuditSink"]
