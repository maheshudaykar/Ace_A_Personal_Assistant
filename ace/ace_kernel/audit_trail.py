"""Append-only audit trail with hash chaining."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional


@dataclass(frozen=True)
class AuditRecord:
    """Single audit record with hash chain fields."""

    timestamp: str
    event: Dict[str, Any]
    prev_hash: str
    hash: str


class AuditTrail:
    """Append-only audit trail backed by JSONL file with hash chaining."""

    def __init__(
        self,
        file_path: str | Path,
        time_fn: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._path = Path(file_path)
        self._time_fn = time_fn or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()

    def append(self, event: Dict[str, Any]) -> AuditRecord:
        """Append an event to the audit trail and return the resulting record."""
        timestamp = self._time_fn().isoformat()
        with self._lock:
            prev_hash = self._get_last_hash_unsafe()
            record_hash = self._compute_hash(timestamp, event, prev_hash)
            record = AuditRecord(
                timestamp=timestamp,
                event=event,
                prev_hash=prev_hash,
                hash=record_hash,
            )
            self._write_record(record)
            return record

    def iter_records(self) -> Iterable[AuditRecord]:
        """Yield records from the audit trail in order."""
        with self._lock:
            yield from self._iter_records_unsafe()

    def _iter_records_unsafe(self) -> Iterable[AuditRecord]:
        """Yield records without acquiring lock (internal use only)."""
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            yield AuditRecord(
                timestamp=payload["timestamp"],
                event=payload["event"],
                prev_hash=payload["prev_hash"],
                hash=payload["hash"],
            )

    def verify_chain(self) -> bool:
        """Verify hash chain integrity for all records."""
        with self._lock:
            prev_hash = "0" * 64
            for record in self._iter_records_unsafe():
                expected = self._compute_hash(record.timestamp, record.event, prev_hash)
                if record.prev_hash != prev_hash or record.hash != expected:
                    return False
                prev_hash = record.hash
            return True

    def _get_last_hash_unsafe(self) -> str:
        """Return hash of last record, or genesis hash if empty (no lock)."""
        last_hash = "0" * 64
        for record in self._iter_records_unsafe():
            last_hash = record.hash
        return last_hash

    def _compute_hash(self, timestamp: str, event: Dict[str, Any], prev_hash: str) -> str:
        payload = json.dumps(
            {
                "timestamp": timestamp,
                "event": event,
                "prev_hash": prev_hash,
            },
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def _write_record(self, record: AuditRecord) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "timestamp": record.timestamp,
                        "event": record.event,
                        "prev_hash": record.prev_hash,
                        "hash": record.hash,
                    },
                    sort_keys=True,
                    ensure_ascii=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
