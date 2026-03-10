# ACE Review: Issue Quick Reference & File Locations

## 🗂️ FILE-BY-FILE ISSUES FOUND

### ace/distributed/byzantine_detector.py
**Issue:** Score decay vulnerability - attackers alternate good/bad votes to stay low  
**Lines:** 140-160  
**Severity:** 🔴 CRITICAL  
**Fix:** Require N consecutive good votes, not just one good vote to offset bad

---

### ace/distributed/memory_sync.py
**Issue:** Quota bypass - concurrent proposals can exceed quota  
**Lines:** 135-185  
**Severity:** 🔴 CRITICAL  
**Fix:** Implement reserve-then-confirm protocol, count in-flight proposals

---

### ace/runtime/agent_scheduler.py
**Issue:** Active count race condition under high concurrency  
**Lines:** 175-185  
**Severity:** 🟠 HIGH  
**Fix:** Add atomic compare-and-swap, invariant checking

---

### ace/distributed/consensus_engine.py
**Issue:** Election timeout vulnerable to clock skew (NTP adjustments break timing)  
**Lines:** 150-200  
**Severity:** 🟠 HIGH  
**Fix:** Use time.monotonic() for timeouts instead of hash-based

---

### ace/runtime/maintenance_scheduler.py
**Issue:** _run_cycle() never calls consolidate() - memory grows unbounded  
**Lines:** 100-130  
**Severity:** 🟡 MEDIUM  
**Fix:** Actually call `self._consolidation.consolidate(merge_threshold=0.85)`

---

### ace/ace_memory/episodic_memory.py
**Issue:** RWLock nesting risk - quota enforcement might deadlock  
**Lines:** 160-175  
**Severity:** 🟡 MEDIUM  
**Fix:** Make quota enforcement atomic with record(), separate locks or check nesting

---

### ace/runtime/task_graph_engine.py
**Issue:** Deadlock detection incomplete - misses circular dependencies in running state  
**Lines:** 60-75  
**Severity:** 🟡 MEDIUM  
**Fix:** Add timeout-based secondary detection, log all in-flight tasks

---

### ace/ace_memory/consolidation_engine.py
**Issue:** O(n²) similarity algorithm - becomes bottleneck with 1000+ entries  
**Lines:** 60-100  
**Severity:** 🟡 MEDIUM (but important for scalability)  
**Fix:** Implement LSH-based nearest neighbor search instead of all-pairs

---

### ace/ace_cognitive/coordinator_agent.py
**Issue:** Subscription efficiency - creates many handlers for concurrent steps  
**Lines:** 140-155  
**Severity:** 🟡 MEDIUM  
**Fix:** Use correlation ID routing instead of bus-wide handlers

---

### ace/ace_kernel/snapshot_engine.py
**Issue:** Missing validation - non-serializable objects crash save  
**Lines:** 37-50  
**Severity:** 🟡 MEDIUM  
**Fix:** Validate serializable before I/O, use atomic file operations

---

### ace/ace_memory/memory_store.py
**Issue:** Selective cache invalidation race - stale reads between write/invalidate  
**Lines:** 78-87  
**Severity:** 🟡 MEDIUM  
**Fix:** Invalidate BEFORE releasing lock, implement versioning

---

### ace/distributed/memory_federation.py
**Issues:** 
1. Floating-point equality checks (lines 156)
2. Unstable rank vulnerable to payload mutation (lines 183-190)

**Severity:** 🟡 MEDIUM  
**Fix:** Use math.isclose() for floats, immutable rank calculation

---

### ace/runtime/experiment_engine.py
**Issues:**
1. Floating-point equality checks (lines 192, 215)
2. Unused imports: threading, GoldenTrace, etc.

**Severity:** 🟡-⚪ LOW/MEDIUM  
**Fix:** Use math.isclose(), remove unused imports

---

### ace/distributed/distributed_planner.py
**Issues:**
1. Unnecessary isinstance check (line 104)
2. Unused imports: hashlib, logging, dataclass, field, type hints
3. Unused variables: step, required, target, reason, etc.

**Severity:** ⚪ LOW (code quality)  
**Fix:** Simplify isinstance, remove unused elements

---

### ace/distributed/higher_level_orchestrator.py
**Issues:**
1. Unused imports: logging, time, dataclass, field, type hints

**Severity:** ⚪ LOW  
**Fix:** Remove unused imports

---

### ace/ace_memory/project_memory.py
**Issues:**
1. Partially unknown types (List[str], Dict[str, Any] without factories)

**Severity:** ⚪ LOW (typing)  
**Fix:** Add typed default_factory functions like done in planning_engine.py

---

---

## 🎯 QUICK LOOKUP BY SYMPTOM

### "Application hangs under high volume"
→ Check `ace/runtime/agent_scheduler.py` (race condition)  
→ Check `ace/runtime/task_graph_engine.py` (incomplete deadlock detection)

### "Untrusted node stays in cluster despite bad behavior"
→ Check `ace/distributed/byzantine_detector.py` (score decay)

### "Memory grows unbounded"
→ Check `ace/runtime/maintenance_scheduler.py` (no consolidation)  
→ Check `ace/ace_memory/consolidation_engine.py` (slow algorithm)

### "Multiple leaders elected simultaneously"
→ Check `ace/distributed/consensus_engine.py` (clock skew)

### "Memory quota exceeded despite enforcement"
→ Check `ace/distributed/memory_sync.py` (concurrent proposal race)

---

## 📊 COMPLEXITY MATRIX

| File | Issue Count | Total LOC | Severity | Complexity |
|------|-------------|-----------|----------|------------|
| consensus_engine.py | 1 | ~400 | HIGH | HIGH |
| byzantine_detector.py | 1 | ~300 | CRITICAL | MEDIUM |
| memory_sync.py | 1 | ~400 | CRITICAL | HIGH |
| agent_scheduler.py | 1 | ~250 | HIGH | MEDIUM |
| consolidation_engine.py | 1 | ~200 | MEDIUM | MEDIUM |
| maintenance_scheduler.py | 1 | ~150 | MEDIUM | LOW |
| episodic_memory.py | 1 | ~300 | MEDIUM | HIGH |
| distributed_planner.py | 3 | ~120 | LOW | LOW |
| coordinator_agent.py | 1 | ~320 | MEDIUM | MEDIUM |
| task_graph_engine.py | 1 | ~120 | MEDIUM | LOW |
| memory_federation.py | 2 | ~170 | MEDIUM | MEDIUM |
| experiment_engine.py | 2 | ~240 | LOW | MEDIUM |

---

## 🚀 QUICK START: WHAT TO FIX FIRST

### TODAY (Critical - Production Safety)
```python
# File: ace/distributed/byzantine_detector.py
# Line: 140-160
# Action: Change score decrease to require N consecutive good votes

# File: ace/distributed/memory_sync.py
# Line: 135-185
# Action: Implement reserve-then-confirm for quota checking
```

### THIS WEEK (High - System Stability)
```python
# File: ace/runtime/agent_scheduler.py
# Line: 175-185
# Action: Add atomic compare-and-swap guard

# File: ace/distributed/consensus_engine.py
# Line: 150-200
# Action: Use time.monotonic() instead of hash

# File: ace/runtime/maintenance_scheduler.py
# Line: 100-130
# Action: Call self._consolidation.consolidate()
```

### NEXT WEEK (Medium - Performance & Robustness)
```python
# File: ace/ace_memory/episodic_memory.py
# Line: 160-175
# Action: Check lock nesting, make quota atomic

# File: ace/runtime/task_graph_engine.py
# Line: 60-75
# Action: Add timeout-based deadlock detection

# File: ace/ace_memory/consolidation_engine.py
# Line: 60-100
# Action: (Medium-term) Implement LSH-based similarity
```

---

## 📋 TESTING REQUIREMENTS

### New Tests Needed
- Byzantine detection: Alternating good/bad vote pattern
- Memory quota: Concurrent proposals from multiple followers
- Consolidation: Verify _run_cycle actually calls consolidate()
- Deadlock: Circular task dependency with all running
- Clock skew: Simulate NTP adjustment during election

### Test Files to Update
- `tests/test_byzantine_detector.py` - Add attack scenario
- `tests/test_consensus_engine.py` - Add clock skew test
- `tests/test_memory_sync.py` - Add quota bypass test
- `tests/test_task_graph_engine.py` - Add circular dependency test

---

## 🔗 CROSS-DEPENDENCIES

```
Fix Byzantine → Improves: Cluster trustworthiness
Fix Memory Quota → Improves: Consistency guarantees
Fix AgentScheduler → Improves: Throughput under load
Fix Consensus ← Depends on: Clock skew fix
Fix Consolidation ← Depends on: MaintenanceScheduler
```

---

## ✅ SIGN-OFF CHECKLIST

- [ ] All 7 issues understood by team
- [ ] Priority P0 (2 critical issues) assigned to senior dev
- [ ] Priority P1 (2 high issues) assigned and estimated
- [ ] Test plans created for 5 new test scenarios
- [ ] Code review process updated to catch these patterns
- [ ] Risk communication sent to stakeholders

---

*Quick Reference Version: March 10, 2026*  
*Print this page or bookmark for during fixes*
