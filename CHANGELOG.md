# Changelog

All notable changes to ACE are documented in this file.

This project follows a phased release model focused on deterministic behavior, governance safety, and production stability.

## [Unreleased]

### Documentation
- README refreshed to focus on project purpose, architecture, runtime flow, and practical usage
- CONTRIBUTING guide modernized with current governance constraints, workflow, and validation expectations

### Phase 3 Readiness Status (as of 2026-03-01)

#### Validation Gates
- ✅ Full regression suite: 268/268 passing
- ✅ Determinism preserved across Phase 0-2C workflows
- ✅ Memory governance active (total/active/per-task quotas + consolidation guard + compaction)
- ✅ No kernel modifications required for current hardening scope

#### Current Performance Snapshot
- 1,000-entry benchmark:
  - Record: 39.69 ms
  - Consolidate: 95.93 ms
  - Retrieve avg: 2.82 ms
  - Memory increase: 6.18 MB (~6.32 KB/entry)
- 5,000-entry benchmark:
  - Record: 200.48 ms
  - Consolidate: 395.67 ms
  - Retrieve avg: 13.28 ms
  - Memory increase: 17.07 MB (~3.50 KB/entry)

#### Pre-Phase 3 Checklist
- ✅ Phase 2C governance complete and stable
- ✅ Stress validation (1k + 5k) completed
- ✅ Test suite green on current main
- ⚠️ Working tree must be clean before Phase 3 branching/release cut

---

## [v0.2.0-phase2c] - 2026-02-28

### Added
- Phase 2C memory governance configuration in `ace/ace_memory/memory_config.py`
- Hard caps:
  - `MAX_TOTAL_ENTRIES = 10_000`
  - `MAX_ACTIVE_ENTRIES = 5_000`
  - `MAX_ENTRIES_PER_TASK = 1_000`
  - `MAX_COMPARISONS_PER_PASS = 50_000`
- Growth observability threshold (`GROWTH_SPIKE_ENTRIES_PER_MINUTE`)

### Changed
- `EpisodicMemory.record()` hardened with deterministic enforcement order:
  1) per-task cap,
  2) total quota,
  3) active quota,
  4) growth monitoring
- Incremental state accounting added for performance stabilization:
  - `_total_count`, `_active_count`, `_archived_count`, `_task_counts`
  - threshold-crossing enforcement instead of continuous re-enforcement
- Consolidation complexity guard added to cap comparisons per pass
- Deterministic compaction retained with atomic rewrite semantics

### Fixed
- Record-path performance regression from repeated full-store scans
- Excessive trigger frequency for governance checks under high write load

### Tests
- New governance test module: `tests/test_phase2c_governance.py` (9 tests)
- Full suite status at release: 268/268 passing

---

## [v0.2.0-phase2b] - 2026-02-27

### Added
- Deterministic similarity consolidation (no clustering libraries)
- Hierarchical retrieval indexing (task index + hot/warm/cold tiers)

### Guarantees
- Synchronous execution only
- Stable deterministic ordering for merge/retrieval paths

### Validation
- 259/259 tests passing at Phase 2B completion

---

## [v0.2.0-phase2a] - 2026-02-27

### Added
- Memory micro-optimizations and observability improvements:
  - computed schema fields
  - recency caching
  - selective cache invalidation
  - retrieval statistics

### Validation
- 30/30 Phase 2A tests passing
- No regressions in existing suite

---

## [v0.2.0-phase2] - 2026-02-27

### Added
- Core memory architecture foundations (working, episodic, scoring, consolidation/pruning scaffolding)

### Notes
- Established Phase 2 baseline for later 2A/2B/2C hardening and scaling work

---

## [ace_phase1_stable] - 2026-02-26

### Added
- Phase 1 kernel and governance foundation finalized
- Safety-critical infrastructure stabilized and tagged as Phase 1 stable

---

## [Phase 0] - 2026-02-26

### Added
- Initial MVP core:
  - deterministic mode
  - state machine + event bus
  - tool registry + CLI shell
  - baseline tests and docs

---

## Notes

- Phase tags in git are authoritative release anchors.
- Reports under project root (`PHASE_2A_COMPLETION_REPORT.md`, `PHASE_2B_COMPLETION_REPORT.md`) contain deeper implementation and benchmark detail.
