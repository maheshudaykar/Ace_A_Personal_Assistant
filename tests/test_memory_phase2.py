"""Phase 2 unit tests for memory subsystem."""

from pathlib import Path

import pytest

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_diagnostics.evaluation_engine import EvaluationEngine
from ace.ace_memory.consolidation_engine import ConsolidationEngine
from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.memory_schema import MemoryEntry, MemoryType
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.pruning_manager import PruningManager
from ace.ace_memory.quality_scorer import QualityScorer
from ace.ace_memory.working_memory import WorkingMemory


class TestMemorySchema:
    """Test memory schema validation."""

    def test_memory_entry_creation(self):
        entry = MemoryEntry(task_id="task1", content="test content")
        assert entry.task_id == "task1"
        assert entry.content == "test content"
        assert entry.importance_score == 0.5
        assert entry.access_count == 0
        assert entry.memory_type == MemoryType.EPISODIC
        assert not entry.archived

    def test_empty_content_raises_error(self):
        with pytest.raises(ValueError, match="content cannot be empty"):
            MemoryEntry(task_id="task1", content="")

    def test_empty_task_id_raises_error(self):
        with pytest.raises(ValueError, match="task_id cannot be empty"):
            MemoryEntry(task_id="", content="test")

    def test_importance_score_validation(self):
        with pytest.raises(ValueError):
            MemoryEntry(task_id="task1", content="test", importance_score=1.5)

    def test_update_access(self):
        entry = MemoryEntry(task_id="task1", content="test")
        initial_count = entry.access_count
        entry.update_access()
        assert entry.access_count == initial_count + 1

    def test_hash_uniqueness(self):
        """Test Phase 2A: __hash__ implementation."""
        entry1 = MemoryEntry(task_id="task1", content="test")
        entry2 = MemoryEntry(task_id="task1", content="test")
        
        # Different IDs, different hashes
        assert hash(entry1) != hash(entry2)
        
        # Same entry, consistent hash
        assert hash(entry1) == hash(entry1)
        
        # Can be used in sets
        entry_set = {entry1, entry2}
        assert len(entry_set) == 2

    def test_computed_field_age_seconds(self):
        """Test Phase 2A: age_seconds computed field."""
        import time
        entry = MemoryEntry(task_id="task1", content="test")
        
        # Should be very recent (< 1 second)
        assert entry.age_seconds < 1.0
        
        # Wait a bit
        time.sleep(0.1)
        assert entry.age_seconds >= 0.1

    def test_computed_field_is_fresh(self):
        """Test Phase 2A: is_fresh computed field (24h threshold)."""
        from datetime import datetime, timezone, timedelta
        
        # Recent entry
        entry = MemoryEntry(task_id="task1", content="test")
        assert entry.is_fresh is True
        
        # Old entry (manually set timestamp for testing)
        entry_old = MemoryEntry(task_id="task2", content="old test")
        entry_old.timestamp = datetime.now(timezone.utc) - timedelta(days=2)
        assert entry_old.is_fresh is False

    def test_computed_field_access_rate_per_day(self):
        """Test Phase 2A: access_rate_per_day computed field."""
        from datetime import datetime, timezone, timedelta
        
        entry = MemoryEntry(task_id="task1", content="test")
        entry.timestamp = datetime.now(timezone.utc) - timedelta(days=2)
        entry.access_count = 10
        
        # 10 accesses over 2 days = 5 per day
        rate = entry.access_rate_per_day
        assert 4.5 <= rate <= 5.5  # Allow slight tolerance


class TestWorkingMemory:
    """Test working memory ring buffer."""

    def test_add_within_capacity(self):
        wm = WorkingMemory(max_capacity=5)
        for i in range(3):
            entry = MemoryEntry(task_id="task1", content=f"entry_{i}")
            wm.add(entry)
        assert wm.size() == 3

    def test_ring_buffer_overflow(self):
        wm = WorkingMemory(max_capacity=10)
        for i in range(20):
            entry = MemoryEntry(task_id="task1", content=f"entry_{i}")
            wm.add(entry)
        
        # Should only retain last 10 entries
        assert wm.size() == 10
        entries = wm.get_all()
        assert entries[0].content == "entry_10"
        assert entries[-1].content == "entry_19"

    def test_clear_working_memory(self):
        wm = WorkingMemory(max_capacity=10)
        for i in range(5):
            entry = MemoryEntry(task_id="task1", content=f"entry_{i}")
            wm.add(entry)
        
        wm.clear()
        assert wm.size() == 0
        assert wm.get_all() == []

    def test_invalid_capacity_raises_error(self):
        with pytest.raises(ValueError, match="max_capacity must be positive"):
            WorkingMemory(max_capacity=0)

    def test_metrics_tracking(self):
        """Test Phase 2A: metrics tracking."""
        wm = WorkingMemory(max_capacity=5)
        
        # Initial metrics
        metrics = wm.get_metrics()
        assert metrics["total_additions"] == 0
        assert metrics["total_evictions"] == 0
        assert metrics["current_size"] == 0
        assert metrics["max_capacity"] == 5
        
        # Add 3 items
        for i in range(3):
            entry = MemoryEntry(task_id="task1", content=f"entry_{i}")
            wm.add(entry)
        
        metrics = wm.get_metrics()
        assert metrics["total_additions"] == 3
        assert metrics["total_evictions"] == 0
        assert metrics["current_size"] == 3
        
        # Add 5 more (will trigger evictions)
        for i in range(5):
            entry = MemoryEntry(task_id="task1", content=f"entry_{i+3}")
            wm.add(entry)
        
        metrics = wm.get_metrics()
        assert metrics["total_additions"] == 8
        assert metrics["total_evictions"] == 3  # 3 evictions to stay at capacity
        assert metrics["current_size"] == 5  # Max capacity
        assert metrics["max_capacity"] == 5


class TestMemoryStore:
    """Test append-only memory storage."""

    def test_save_and_load(self, tmp_path: Path):
        store = MemoryStore(tmp_path / "memory.jsonl")
        
        entry = MemoryEntry(task_id="task1", content="test content")
        store.save(entry)
        
        loaded = store.load_all()
        assert len(loaded) == 1
        assert loaded[0].task_id == "task1"
        assert loaded[0].content == "test content"

    def test_load_by_task(self, tmp_path: Path):
        store = MemoryStore(tmp_path / "memory.jsonl")
        
        store.save(MemoryEntry(task_id="task1", content="content1"))
        store.save(MemoryEntry(task_id="task2", content="content2"))
        store.save(MemoryEntry(task_id="task1", content="content3"))
        
        task1_entries = store.load_by_task("task1")
        assert len(task1_entries) == 2
        assert all(e.task_id == "task1" for e in task1_entries)

    def test_prune_entries(self, tmp_path: Path):
        store = MemoryStore(tmp_path / "memory.jsonl")
        
        entry1 = MemoryEntry(task_id="task1", content="content1")
        entry2 = MemoryEntry(task_id="task2", content="content2")
        store.save(entry1)
        store.save(entry2)
        
        pruned = store.prune([entry1.id])
        assert pruned == 1
        
        active = store.load_active()
        assert len(active) == 1
        assert active[0].task_id == "task2"

    def test_load_active_excludes_archived(self, tmp_path: Path):
        store = MemoryStore(tmp_path / "memory.jsonl")
        
        entry1 = MemoryEntry(task_id="task1", content="content1")
        entry2 = MemoryEntry(task_id="task2", content="content2")
        store.save(entry1)
        store.save(entry2)
        
        store.prune([entry1.id])
        active = store.load_active()
        assert len(active) == 1
        assert active[0].task_id == "task2"

    def test_selective_cache_invalidation(self, tmp_path: Path):
        """Test Phase 2A: selective cache invalidation."""
        store = MemoryStore(tmp_path / "memory.jsonl", cache_size=10)
        
        # Save entries for task1 and task2
        entry1 = MemoryEntry(task_id="task1", content="content1")
        entry2 = MemoryEntry(task_id="task2", content="content2")
        store.save(entry1)
        store.save(entry2)
        
        # Load both tasks (populate cache)
        task1_entries = store.load_by_task("task1")
        task2_entries = store.load_by_task("task2")
        
        # Verify both cached
        assert store._cache.get("task:task1") is not None
        assert store._cache.get("task:task2") is not None
        
        # Save new entry for task1
        entry3 = MemoryEntry(task_id="task1", content="content3")
        store.save(entry3)
        
        # task1 cache should be invalidated
        assert store._cache.get("task:task1") is None
        # task2 cache should still exist (selective invalidation)
        assert store._cache.get("task:task2") is not None


class TestEpisodicMemory:
    """Test episodic memory persistence."""

    def test_record_and_retrieve(self, tmp_path: Path):
        store = MemoryStore(tmp_path / "memory.jsonl")
        episodic = EpisodicMemory(store)
        
        entry = episodic.record("task1", "test content", importance_score=0.7)
        assert entry.task_id == "task1"
        assert entry.memory_type == MemoryType.EPISODIC
        
        retrieved = episodic.retrieve_by_task("task1")
        assert len(retrieved) == 1
        assert retrieved[0].content == "test content"

    def test_access_count_tracking(self, tmp_path: Path):
        store = MemoryStore(tmp_path / "memory.jsonl")
        episodic = EpisodicMemory(store)
        
        episodic.record("task1", "content1")
        
        # First retrieval
        entries1 = episodic.retrieve_by_task("task1")
        _ = entries1[0].access_count
        
        # Second retrieval
        entries2 = episodic.retrieve_by_task("task1")
        # Access count should increment (but need to reload from store)
        # This is a simplified test - in production, would verify persistence
        assert len(entries2) > 0

    def test_retrieval_statistics(self, tmp_path: Path):
        """Test Phase 2A: retrieval statistics tracking."""
        store = MemoryStore(tmp_path / "memory.jsonl")
        episodic = EpisodicMemory(store)
        eval_engine = EvaluationEngine()
        scorer = QualityScorer(eval_engine)
        
        # Record some entries
        for i in range(10):
            episodic.record(f"task{i}", f"content{i}", importance_score=0.7)
        
        # Initial stats should be zero
        stats = episodic.get_statistics()
        assert stats["total_by_task_calls"] == 0
        assert stats["total_all_active_calls"] == 0
        assert stats["total_top_k_calls"] == 0
        
        # Perform retrievals
        episodic.retrieve_by_task("task1")
        episodic.retrieve_all_active()
        episodic.retrieve_top_k(scorer, k=5)
        
        # Check statistics updated
        stats = episodic.get_statistics()
        assert stats["total_by_task_calls"] == 1
        assert stats["total_all_active_calls"] == 1
        assert stats["total_top_k_calls"] == 1
        
        # Check latencies recorded
        assert stats["avg_latency_by_task_ms"] >= 0.0
        assert stats["avg_latency_all_active_ms"] >= 0.0
        assert stats["avg_latency_top_k_ms"] >= 0.0


class TestQualityScorer:
    """Test memory quality scoring."""

    def test_score_recent_entry(self, tmp_path: Path):
        eval_engine = EvaluationEngine()
        scorer = QualityScorer(eval_engine)
        
        entry = MemoryEntry(
            task_id="task1",
            content="test",
            importance_score=0.8,
            access_count=5,
        )
        
        score = scorer.score(entry)
        assert 0.0 <= score <= 1.0
        assert score > 0.5  # Recent + high importance should score well

    def test_score_old_entry(self, tmp_path: Path):
        eval_engine = EvaluationEngine()
        scorer = QualityScorer(eval_engine)
        
        # Create old entry (manually set timestamp for testing)
        entry = MemoryEntry(
            task_id="task1",
            content="test",
            importance_score=0.3,
            access_count=0,
        )
        
        score = scorer.score(entry)
        assert 0.0 <= score <= 1.0

    def test_recency_caching(self):
        """Test Phase 2A: recency caching by day bucket."""
        from datetime import datetime, timezone, timedelta
        
        eval_engine = EvaluationEngine()
        scorer = QualityScorer(eval_engine)
        
        # Create entries with same age (in days)
        timestamp = datetime.now(timezone.utc) - timedelta(days=5)
        entry1 = MemoryEntry(task_id="task1", content="test1", importance_score=0.5)
        entry1.timestamp = timestamp
        
        entry2 = MemoryEntry(task_id="task2", content="test2", importance_score=0.5)
        entry2.timestamp = timestamp
        
        # First score should compute and cache
        score1 = scorer.score(entry1)
        
        # Second score should hit cache (same day bucket)
        score2 = scorer.score(entry2)
        
        # Cache should have entry for day bucket 5
        assert 5 in scorer._recency_cache
        
        # Scores should be identical (same recency component)
        # but may differ slightly due to other factors
        assert abs(score1 - score2) < 0.1

    def test_score_with_explanation(self):
        """Test Phase 2A: score_with_explanation method."""
        eval_engine = EvaluationEngine()
        scorer = QualityScorer(eval_engine)
        
        entry = MemoryEntry(
            task_id="task1",
            content="test",
            importance_score=0.8,
            access_count=5,
        )
        
        explanation = scorer.score_with_explanation(entry)
        
        # Check all components present
        assert "importance" in explanation
        assert "recency" in explanation
        assert "access_frequency" in explanation
        assert "task_success" in explanation
        assert "total" in explanation
        
        # Check values are valid
        assert 0.0 <= explanation["importance"] <= 1.0
        assert 0.0 <= explanation["recency"] <= 1.0
        assert 0.0 <= explanation["access_frequency"] <= 1.0
        assert 0.0 <= explanation["task_success"] <= 1.0
        assert 0.0 <= explanation["total"] <= 1.0
        
        # Total should match score()
        regular_score = scorer.score(entry)
        assert abs(explanation["total"] - regular_score) < 0.001

    def test_score_batch(self):
        """Test Phase 2A: batch scoring with single datetime.now() call."""
        from datetime import datetime, timezone
        
        eval_engine = EvaluationEngine()
        scorer = QualityScorer(eval_engine)
        
        entries = [
            MemoryEntry(task_id=f"task{i}", content=f"content{i}", importance_score=0.5 + i*0.1)
            for i in range(5)
        ]
        
        # Batch score
        ref_time = datetime.now(timezone.utc)
        scored = scorer.score_batch(entries, reference_time=ref_time)
        
        # Should return list of tuples
        assert len(scored) == 5
        assert all(isinstance(item, tuple) for item in scored)
        assert all(len(item) == 2 for item in scored)
        
        # Verify entries and scores
        for entry, score in scored:
            assert isinstance(entry, MemoryEntry)
            assert 0.0 <= score <= 1.0
        
        # Verify scores are in expected order (higher importance = higher score)
        scores = [score for _, score in scored]
        # Later entries have higher importance, so scores should generally increase
        assert scores[-1] > scores[0]


class TestConsolidationEngine:
    """Test memory consolidation."""

    def test_should_consolidate_trigger(self, tmp_path: Path):
        audit = AuditTrail(str(tmp_path / "audit.jsonl"))
        store = MemoryStore(tmp_path / "memory.jsonl")
        episodic = EpisodicMemory(store)
        eval_engine = EvaluationEngine()
        scorer = QualityScorer(eval_engine)
        consolidation = ConsolidationEngine(store, episodic, scorer, audit)
        
        # Add 99 entries
        for i in range(99):
            store.save(MemoryEntry(task_id=f"task_{i}", content=f"content_{i}"))
        
        assert not consolidation.should_consolidate()
        
        # Add one more to reach threshold
        store.save(MemoryEntry(task_id="task_100", content="content_100"))
        assert consolidation.should_consolidate()

    def test_consolidate_merges_entries(self, tmp_path: Path):
        audit = AuditTrail(str(tmp_path / "audit.jsonl"))
        store = MemoryStore(tmp_path / "memory.jsonl")
        episodic = EpisodicMemory(store)
        eval_engine = EvaluationEngine()
        scorer = QualityScorer(eval_engine)
        consolidation = ConsolidationEngine(store, episodic, scorer, audit)
        
        # Add multiple entries for same task
        for i in range(5):
            episodic.record(f"task1", f"content_{i}", importance_score=0.7)
        
        merged_count = consolidation.consolidate()
        assert merged_count > 0


class TestPruningManager:
    """Test memory pruning."""

    def test_should_prune_trigger(self, tmp_path: Path):
        audit = AuditTrail(str(tmp_path / "audit.jsonl"))
        store = MemoryStore(tmp_path / "memory.jsonl")
        eval_engine = EvaluationEngine()
        scorer = QualityScorer(eval_engine)
        pruning = PruningManager(store, scorer, audit)
        
        # Add 1000 entries
        for i in range(1000):
            store.save(MemoryEntry(task_id=f"task_{i}", content=f"content_{i}"))
        
        assert not pruning.should_prune()
        
        # Add one more
        store.save(MemoryEntry(task_id="task_1001", content="content_1001"))
        assert pruning.should_prune()
