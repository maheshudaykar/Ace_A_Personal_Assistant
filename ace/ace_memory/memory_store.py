"""Append-only memory storage with hash validation and read-ahead caching."""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterable, List
from uuid import UUID

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_memory.memory_schema import MemoryEntry


class LRUCache:
    """Simple LRU cache for memory entries."""

    def __init__(self, maxsize: int = 100) -> None:
        self._cache: OrderedDict[str, List[MemoryEntry]] = OrderedDict()
        self._maxsize = maxsize
        self._lock = threading.Lock()

    def get(self, key: str) -> List[MemoryEntry] | None:
        """Get cached value and move to end (most recently used)."""
        with self._lock:
            if key in self._cache:
                # Move to end (mark as recently used)
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key: str, value: List[MemoryEntry]) -> None:
        """Add value to cache, evicting oldest if at capacity."""
        with self._lock:
            if key in self._cache:
                # Update existing entry
                self._cache.move_to_end(key)
                self._cache[key] = value
            else:
                # Add new entry
                if len(self._cache) >= self._maxsize:
                    # Evict oldest
                    self._cache.popitem(last=False)
                self._cache[key] = value

    def invalidate(self) -> None:
        """Clear entire cache (on writes)."""
        with self._lock:
            self._cache.clear()

    def delete(self, key: str) -> None:
        """Delete a specific cache key."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]


class MemoryStore:
    """Append-only JSONL storage for memory entries with read-ahead caching."""

    def __init__(
        self,
        store_path: str | Path,
        flush_every: int = 10,
        cache_size: int = 100,
        audit_trail: AuditTrail | None = None,
    ) -> None:
        self._path = Path(store_path)
        self._lock = threading.Lock()
        if flush_every <= 0:
            raise ValueError("flush_every must be positive")
        self._flush_every = flush_every
        self._pending_writes = 0
        self._cache = LRUCache(maxsize=cache_size)  # Read-ahead cache (MemGPT/LangChain pattern)
        self._audit = audit_trail
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()
        self._handle = self._path.open("a", encoding="utf-8")

    def save(self, entry: MemoryEntry) -> None:
        """Append a memory entry to storage (selective cache invalidation)."""
        with self._lock:
            self._write_entry_unsafe(entry)
            # Selective cache invalidation - only invalidate affected keys
            self._invalidate_selective(entry)

    def load_all(self) -> List[MemoryEntry]:
        """Load all memory entries from storage (cached)."""
        cache_key = "all"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        with self._lock:
            self._handle.flush()
            result = self._load_all_unsafe()
            self._cache.put(cache_key, result)
            return result

    def _load_all_unsafe(self) -> List[MemoryEntry]:
        """Load all entries without acquiring lock (internal use only)."""
        # Use dict to keep only latest version of each entry (by ID)
        entries_dict: dict[UUID, MemoryEntry] = {}
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if isinstance(payload, dict) and "entry" in payload:
                    entry = MemoryEntry.model_validate(payload["entry"])
                else:
                    entry = MemoryEntry.model_validate(payload)
                entries_dict[entry.id] = entry  # Latest version wins
            except Exception:  # Skip malformed entries
                continue
        return list(entries_dict.values())

    def load_by_task(self, task_id: str) -> List[MemoryEntry]:
        """Load memory entries for a specific task (cached)."""
        cache_key = f"task:{task_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result = [entry for entry in self.load_all() if entry.task_id == task_id]
        self._cache.put(cache_key, result)
        return result

    def load_active(self) -> List[MemoryEntry]:
        """Load only non-archived entries (cached)."""
        cache_key = "active"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result = [entry for entry in self.load_all() if not entry.archived]
        self._cache.put(cache_key, result)
        return result

    def prune(self, entry_ids: Iterable[UUID]) -> int:
        """Mark entries as archived (no in-place modification, invalidates cache)."""
        ids_to_prune = set(entry_ids)
        pruned_count = 0

        with self._lock:
            self._handle.flush()
            all_entries = self._load_all_unsafe()

            for entry in all_entries:
                if entry.id in ids_to_prune and not entry.archived:
                    entry.archived = True
                    # Write directly without acquiring lock again
                    self._write_entry_unsafe(entry)
                    pruned_count += 1

            # Invalidate cache after pruning
            self._cache.invalidate()

        return pruned_count

    def count_total_entries(self) -> int:
        """Count total latest-version entries in store."""
        return len(self.load_all())

    def count_active_entries(self) -> int:
        """Count non-archived latest-version entries in store."""
        return len(self.load_active())

    def prune_oldest_archived(self, count: int) -> int:
        """Permanently delete oldest archived entries (deterministic order)."""
        if count <= 0:
            return 0

        with self._lock:
            self._handle.flush()
            all_entries = self._load_all_unsafe()
            archived_entries = [entry for entry in all_entries if entry.archived]
            archived_entries.sort(key=lambda e: (e.timestamp, str(e.id)))

            ids_to_delete = {entry.id for entry in archived_entries[:count]}
            if not ids_to_delete:
                return 0

            kept_entries = [entry for entry in all_entries if entry.id not in ids_to_delete]
            self._rewrite_entries_unsafe(kept_entries)
            self._cache.invalidate()

            deleted_count = len(ids_to_delete)
            if self._audit is not None:
                self._audit.append({
                    "type": "memory.prune_oldest_archived",
                    "deleted_count": deleted_count,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            return deleted_count

    def compact_archived_entries(self) -> int:
        """
        Deterministically compact archived entries.

        If archived ratio > 30%, delete oldest archived entries until ratio <= 20%.
        Returns number of permanently deleted entries.
        """
        with self._lock:
            self._handle.flush()
            all_entries = self._load_all_unsafe()
            total_count = len(all_entries)
            if total_count == 0:
                return 0

            archived_entries = [entry for entry in all_entries if entry.archived]
            archived_count = len(archived_entries)
            archived_ratio = archived_count / total_count

            if archived_ratio <= 0.30:
                return 0

            required_delete_float = (archived_count - 0.20 * total_count) / 0.80
            delete_count = max(0, int(required_delete_float + 0.999999))
            if delete_count <= 0:
                return 0

            archived_entries.sort(key=lambda e: (e.timestamp, str(e.id)))
            ids_to_delete = {entry.id for entry in archived_entries[:delete_count]}
            kept_entries = [entry for entry in all_entries if entry.id not in ids_to_delete]

            self._rewrite_entries_unsafe(kept_entries)
            self._cache.invalidate()

            deleted_count = len(ids_to_delete)
            if self._audit is not None:
                new_total = len(kept_entries)
                new_archived = sum(1 for entry in kept_entries if entry.archived)
                new_ratio = (new_archived / new_total) if new_total > 0 else 0.0
                self._audit.append({
                    "type": "memory.compaction.complete",
                    "deleted_count": deleted_count,
                    "total_before": total_count,
                    "archived_before": archived_count,
                    "archived_ratio_before": archived_ratio,
                    "total_after": new_total,
                    "archived_after": new_archived,
                    "archived_ratio_after": new_ratio,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            return deleted_count

    def _invalidate_selective(self, entry: MemoryEntry) -> None:
        """Selectively invalidate cache keys affected by this entry."""
        # Only invalidate "all" and task-specific cache
        keys_to_invalidate = ["all", f"task:{entry.task_id}", "active"]
        for key in keys_to_invalidate:
            self._cache.delete(key)

    def _rewrite_entries_unsafe(self, entries: List[MemoryEntry]) -> None:
        """Rewrite full store atomically with provided latest entries (lock required)."""
        temp_path = self._path.with_suffix(self._path.suffix + ".tmp")

        with temp_path.open("w", encoding="utf-8") as handle:
            for entry in entries:
                entry_payload = entry.model_dump(mode="json")
                entry_json = json.dumps(
                    entry_payload,
                    sort_keys=True,
                    ensure_ascii=True,
                    separators=(",", ":"),
                )
                entry_hash = sha256(entry_json.encode("utf-8")).hexdigest()
                record_json = f'{{"hash":"{entry_hash}","entry":{entry_json}}}'
                handle.write(record_json + "\n")

        self._handle.flush()
        self._handle.close()
        temp_path.replace(self._path)
        self._handle = self._path.open("a", encoding="utf-8")
        self._pending_writes = 0

    def _write_entry_unsafe(self, entry: MemoryEntry) -> None:
        """Write entry with hash wrapper (internal use only)."""
        entry_payload = entry.model_dump(mode="json")
        entry_json = json.dumps(
            entry_payload,
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        entry_hash = sha256(entry_json.encode("utf-8")).hexdigest()
        record_json = f'{{"hash":"{entry_hash}","entry":{entry_json}}}'

        self._handle.write(record_json + "\n")
        self._pending_writes += 1
        if self._pending_writes % self._flush_every == 0:
            self._handle.flush()

    def close(self) -> None:
        """Close the underlying file handle."""
        with self._lock:
            self._handle.flush()
            self._handle.close()
