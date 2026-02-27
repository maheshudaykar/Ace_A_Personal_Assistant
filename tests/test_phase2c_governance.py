"""Phase 2C tests - hardening, quotas, and bounded-growth governance."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from ace.ace_diagnostics.evaluation_engine import EvaluationEngine
from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_memory import memory_config
from ace.ace_memory.consolidation_engine import ConsolidationEngine
from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.memory_schema import MemoryEntry, MemoryType
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.quality_scorer import QualityScorer


@pytest.fixture
def audit_trail(tmp_path: Path) -> AuditTrail:
    return AuditTrail(tmp_path / "audit.jsonl")


@pytest.fixture
def memory_store(tmp_path: Path, audit_trail: AuditTrail) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.jsonl", audit_trail=audit_trail)


@pytest.fixture
def quality_scorer() -> QualityScorer:
    return QualityScorer(EvaluationEngine())


@pytest.fixture
def episodic(memory_store: MemoryStore, quality_scorer: QualityScorer, audit_trail: AuditTrail) -> EpisodicMemory:
    return EpisodicMemory(memory_store, quality_scorer=quality_scorer, audit_trail=audit_trail)


def _event_types(audit: AuditTrail) -> list[str]:
    return [record.event.get("type", "") for record in audit.iter_records()]


def test_total_quota_enforced(monkeypatch: pytest.MonkeyPatch, episodic: EpisodicMemory, memory_store: MemoryStore, audit_trail: AuditTrail) -> None:
    monkeypatch.setattr(memory_config, "MAX_TOTAL_ENTRIES", 3)
    monkeypatch.setattr(memory_config, "MAX_ACTIVE_ENTRIES", 100)
    monkeypatch.setattr(memory_config, "MAX_ENTRIES_PER_TASK", 100)

    e1 = episodic.record("task-a", "a1", importance_score=0.9)
    e2 = episodic.record("task-a", "a2", importance_score=0.9)
    _e3 = episodic.record("task-a", "a3", importance_score=0.9)
    assert e1 is not None and e2 is not None

    episodic.archive_entries([e1.id, e2.id])
    _e4 = episodic.record("task-a", "a4", importance_score=0.9)

    assert memory_store.count_total_entries() <= 3
    assert "memory.total_quota_enforced" in _event_types(audit_trail)


def test_active_quota_enforced(monkeypatch: pytest.MonkeyPatch, episodic: EpisodicMemory, memory_store: MemoryStore, quality_scorer: QualityScorer, audit_trail: AuditTrail) -> None:
    monkeypatch.setattr(memory_config, "MAX_TOTAL_ENTRIES", 10_000)
    monkeypatch.setattr(memory_config, "MAX_ACTIVE_ENTRIES", 2)
    monkeypatch.setattr(memory_config, "MAX_ENTRIES_PER_TASK", 100)

    _engine = ConsolidationEngine(memory_store, episodic, quality_scorer, audit_trail)

    episodic.record("task-b", "same-content", importance_score=0.9)
    episodic.record("task-b", "same-content", importance_score=0.8)
    episodic.record("task-b", "same-content", importance_score=0.7)

    assert memory_store.count_active_entries() <= 2
    event_types = _event_types(audit_trail)
    assert "memory.active_quota_enforced" in event_types
    assert "consolidation.complete" in event_types


def test_per_task_quota_enforced(monkeypatch: pytest.MonkeyPatch, episodic: EpisodicMemory, memory_store: MemoryStore, audit_trail: AuditTrail) -> None:
    monkeypatch.setattr(memory_config, "MAX_TOTAL_ENTRIES", 10_000)
    monkeypatch.setattr(memory_config, "MAX_ACTIVE_ENTRIES", 10_000)
    monkeypatch.setattr(memory_config, "MAX_ENTRIES_PER_TASK", 2)

    episodic.record("task-cap", "content-1", importance_score=0.9)
    episodic.record("task-cap", "content-2", importance_score=0.8)
    episodic.record("task-cap", "content-3", importance_score=0.7)

    task_active = [e for e in memory_store.load_by_task("task-cap") if not e.archived]
    task_archived = [e for e in memory_store.load_by_task("task-cap") if e.archived]

    assert len(task_active) == 2
    assert len(task_archived) >= 1
    assert "memory.per_task_quota_enforced" in _event_types(audit_trail)


def test_per_task_cap_archives_lowest_quality(monkeypatch: pytest.MonkeyPatch, episodic: EpisodicMemory, memory_store: MemoryStore) -> None:
    monkeypatch.setattr(memory_config, "MAX_TOTAL_ENTRIES", 10_000)
    monkeypatch.setattr(memory_config, "MAX_ACTIVE_ENTRIES", 10_000)
    monkeypatch.setattr(memory_config, "MAX_ENTRIES_PER_TASK", 2)

    episodic.record("task-quality", "low", importance_score=0.51)
    episodic.record("task-quality", "mid", importance_score=0.75)
    episodic.record("task-quality", "high", importance_score=0.95)

    by_task = memory_store.load_by_task("task-quality")
    status = {entry.content: entry.archived for entry in by_task}

    assert status["low"] is True
    assert status["mid"] is False
    assert status["high"] is False


def test_archived_entries_removed_from_indices(monkeypatch: pytest.MonkeyPatch, episodic: EpisodicMemory, memory_store: MemoryStore) -> None:
    monkeypatch.setattr(memory_config, "MAX_TOTAL_ENTRIES", 10_000)
    monkeypatch.setattr(memory_config, "MAX_ACTIVE_ENTRIES", 10_000)
    monkeypatch.setattr(memory_config, "MAX_ENTRIES_PER_TASK", 1)

    first = episodic.record("task-index", "old", importance_score=0.6)
    second = episodic.record("task-index", "new", importance_score=0.9)

    assert first is not None and second is not None

    assert first.id not in episodic._task_index.get("task-index", set())  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert second.id in episodic._task_index.get("task-index", set())  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    for tier in ("hot", "warm", "cold"):
        assert first.id not in episodic._recency_tiers[tier]  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    archived = [entry for entry in memory_store.load_by_task("task-index") if entry.archived]
    assert any(entry.id == first.id for entry in archived)


def test_consolidation_guard_triggers(monkeypatch: pytest.MonkeyPatch, episodic: EpisodicMemory, memory_store: MemoryStore, quality_scorer: QualityScorer, audit_trail: AuditTrail) -> None:
    monkeypatch.setattr(memory_config, "MAX_COMPARISONS_PER_PASS", 3)

    engine = ConsolidationEngine(memory_store, episodic, quality_scorer, audit_trail)

    for idx in range(8):
        memory_store.save(
            MemoryEntry(
                id=UUID(int=idx + 1),
                task_id="task-guard",
                content=f"content-{idx}",
                importance_score=0.6,
                memory_type=MemoryType.EPISODIC,
            )
        )

    _merged = engine.consolidate(max_comparisons_per_pass=3)

    assert "consolidation_guard_triggered" in _event_types(audit_trail)


def test_deterministic_behavior_with_guard(tmp_path: Path) -> None:
    def run_once(base_path: Path) -> set[UUID]:
        audit = AuditTrail(base_path / "audit.jsonl")
        store = MemoryStore(base_path / "memory.jsonl", audit_trail=audit)
        scorer = QualityScorer(EvaluationEngine())
        epi = EpisodicMemory(store, quality_scorer=scorer, audit_trail=audit)
        engine = ConsolidationEngine(store, epi, scorer, audit)

        for idx in range(6):
            store.save(
                MemoryEntry(
                    id=UUID(int=idx + 1),
                    task_id="task-deterministic",
                    content="same-content",
                    importance_score=0.8,
                    memory_type=MemoryType.EPISODIC,
                )
            )

        engine.consolidate(max_comparisons_per_pass=2)
        return {entry.id for entry in store.load_all() if entry.archived}

    archived_run_1 = run_once(tmp_path / "run1")
    archived_run_2 = run_once(tmp_path / "run2")

    assert archived_run_1 == archived_run_2


def test_compaction_reduces_archived_ratio(memory_store: MemoryStore) -> None:
    entries = [MemoryEntry(task_id="task-comp", content=f"entry-{i}", importance_score=0.8) for i in range(10)]
    for entry in entries:
        memory_store.save(entry)

    _archived = memory_store.prune([entry.id for entry in entries[:5]])
    before = memory_store.load_all()
    before_ratio = sum(1 for e in before if e.archived) / len(before)
    assert before_ratio > 0.30

    deleted = memory_store.compact_archived_entries()
    after = memory_store.load_all()
    after_ratio = sum(1 for e in after if e.archived) / len(after)

    assert deleted > 0
    assert after_ratio <= 0.20


def test_compaction_preserves_active_entries(memory_store: MemoryStore) -> None:
    active_entries = [MemoryEntry(task_id="task-live", content=f"active-{i}", importance_score=0.9) for i in range(5)]
    archived_entries = [MemoryEntry(task_id="task-old", content=f"archived-{i}", importance_score=0.5) for i in range(5)]

    for entry in active_entries + archived_entries:
        memory_store.save(entry)

    memory_store.prune([entry.id for entry in archived_entries])
    active_ids_before = {entry.id for entry in memory_store.load_active()}

    _deleted = memory_store.compact_archived_entries()
    active_ids_after = {entry.id for entry in memory_store.load_active()}

    assert active_ids_before == active_ids_after
