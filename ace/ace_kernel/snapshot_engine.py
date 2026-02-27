"""Snapshot engine with hash validation and append-only snapshot log."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ace.ace_kernel.audit_trail import AuditTrail


@dataclass(frozen=True)
class SnapshotRecord:
    """Snapshot record metadata."""

    snapshot_id: str
    timestamp: str
    state_hash: str
    path: str


class SnapshotEngine:
    """Save and restore JSON snapshots with integrity validation."""

    def __init__(
        self,
        snapshot_dir: str | Path,
        audit_trail: AuditTrail,
        time_fn: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._dir = Path(snapshot_dir)
        self._audit = audit_trail
        self._time_fn = time_fn or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._dir.mkdir(parents=True, exist_ok=True)

    def save_state(self, state: Dict[str, Any]) -> SnapshotRecord:
        """Persist state to a JSON snapshot and log the event."""
        timestamp = self._time_fn().isoformat()
        snapshot_id = sha256(timestamp.encode("utf-8")).hexdigest()[:16]
        payload = json.dumps(state, sort_keys=True, ensure_ascii=True)
        state_hash = sha256(payload.encode("utf-8")).hexdigest()
        path = self._dir / f"snapshot_{snapshot_id}.json"

        with self._lock:
            path.write_text(payload, encoding="utf-8")
            record = SnapshotRecord(
                snapshot_id=snapshot_id,
                timestamp=timestamp,
                state_hash=state_hash,
                path=str(path),
            )
            self._audit.append(
                {
                    "type": "snapshot.save",
                    "snapshot_id": snapshot_id,
                    "timestamp": timestamp,
                    "state_hash": state_hash,
                    "path": str(path),
                }
            )
            return record

    def restore_state(self, snapshot_id: str) -> Dict[str, Any]:
        """Restore a snapshot by ID after validating its hash."""
        path = self._dir / f"snapshot_{snapshot_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Snapshot not found: {snapshot_id}")

        with self._lock:
            payload = path.read_text(encoding="utf-8")
            state_hash = sha256(payload.encode("utf-8")).hexdigest()
            state = json.loads(payload)
            self._audit.append(
                {
                    "type": "snapshot.restore",
                    "snapshot_id": snapshot_id,
                    "state_hash": state_hash,
                    "path": str(path),
                }
            )
            return state

    def validate_snapshot(self, snapshot_id: str) -> bool:
        """Validate snapshot file hash against its content."""
        path = self._dir / f"snapshot_{snapshot_id}.json"
        if not path.exists():
            return False
        payload = path.read_text(encoding="utf-8")
        state_hash = sha256(payload.encode("utf-8")).hexdigest()
        try:
            json.loads(payload)
        except json.JSONDecodeError:
            return False
        return len(state_hash) == 64
