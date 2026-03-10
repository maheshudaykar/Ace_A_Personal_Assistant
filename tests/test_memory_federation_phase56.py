from ace.distributed.memory_federation import FederatedRecord, MemoryFederation
from ace.distributed.memory_sync import DistributedMemorySync


def test_memory_federation_conflict_resolution_uses_confidence_and_timestamp() -> None:
    sync = DistributedMemorySync(node_id="leader", is_leader=True)
    federation = MemoryFederation(sync)

    record_old = FederatedRecord(
        record_id="r1",
        memory_type="semantic",
        payload={"v": 1},
        timestamp=1.0,
        confidence=0.2,
        source_node="a",
    )
    record_new = FederatedRecord(
        record_id="r1",
        memory_type="semantic",
        payload={"v": 2},
        timestamp=2.0,
        confidence=0.1,
        source_node="b",
    )

    federation.upsert_record(record_old)
    winner = federation.upsert_record(record_new)

    assert winner.payload["v"] == 2
    assert len(federation.get_conflict_history()) == 1


def test_memory_federation_sync_submits_to_memory_sync() -> None:
    sync = DistributedMemorySync(node_id="leader", is_leader=True)
    federation = MemoryFederation(sync)
    federation.upsert_record(
        FederatedRecord(
            record_id="r2",
            memory_type="episodic",
            payload={"event": "x"},
            timestamp=1.0,
            confidence=0.8,
            source_node="a",
        )
    )

    accepted = federation.synchronize_to_cluster("episodic")
    assert accepted == 1
