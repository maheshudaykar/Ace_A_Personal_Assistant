"""Phase 3A Gate 1.5 - Determinism infrastructure tests."""

import pytest
import threading
from pathlib import Path
from uuid import UUID

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_memory.consolidation_engine import ConsolidationEngine
from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.quality_scorer import QualityScorer
from ace.ace_diagnostics.evaluation_engine import EvaluationEngine

from ace.runtime import (
    DeterminismValidator,
    EventType,
    GlobalEventSequence,
    GoldenTrace,
    MaintenanceScheduler,
)
from ace.runtime import runtime_config


class TestGlobalEventSequence:
    """Test global monotonic ordering under concurrency."""
    
    def test_sequence_id_monotonic(self):
        """Verify sequence IDs are strictly increasing."""
        seq = GlobalEventSequence.get_instance()
        seq.reset()
        
        ids = []
        for _ in range(100):
            ids.append(seq.next())
        
        assert ids == list(range(1, 101))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
