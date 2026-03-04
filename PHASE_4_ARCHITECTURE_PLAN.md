# Phase 4: Cognitive Agents - Architecture Plan

**Status**: Ready to implement  
**Predecessor**: Phase 3B (✅ 127/127 tests passing)  
**Duration Estimate**: 3-4 weeks  
**Team Size**: 2-3 developers

---

## Executive Summary

Phase 4 implements **6 specialized cognitive agents** that work together to enable:

1. **Proactive Intelligence** - Predict user actions, pre-execute safely, learn from feedback
2. **Code Architecture Analysis** - Extract, analyze, and suggest improvements for large codebases

The system operates as a **distributed multi-agent system** leveraging Phase 3B's:
- ConsensusEngine (coordination across agents)
- TaskDelegator (parallelize analysis on follower nodes)
- DistributedMemorySync (share learned patterns across cluster)
- HealthMonitor (track agent resource usage)

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│                  PHASE 4 COGNITIVE AGENTS                      │
│                                                                │
│  PROACTIVE INTELLIGENCE                                        │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Predictor   │  │ Validator    │  │ Executor     │          │
│  │ Agent       │→ │ Agent        │→ │ Agent        │          │
│  └─────────────┘  └──────────────┘  └──────────────┘          │
│       ↓                  ↓                   ↓                 │
│  Observe patterns  Score safety      Sandbox execution        │
│  Generate predictions  Risk assessment  Approval gate         │
│                                                                │
│  CODE ARCHITECTURE ANALYSIS                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Transformer │  │ Analyzer     │  │ Simulator    │          │
│  │ Agent       │→ │ Agent        │→ │ Agent        │          │
│  └─────────────┘  └──────────────┘  └──────────────┘          │
│       ↓                  ↓                   ↓                 │
│  Extract architecture  Quality scoring  Refactor simulation   │
│  Parallelize parsing   SOLID analysis   Validate safety       │
│                                                                │
│  SHARED INFRASTRUCTURE (Phase 3B)                             │
│  ├─ ConsensusEngine (agent coordination)                      │
│  ├─ DistributedMemorySync (share patterns)                   │
│  ├─ TaskDelegator (parallelize expensive operations)         │
│  └─ HealthMonitor (track agent performance)                  │
└────────────────────────────────────────────────────────────────┘
```

---

## Agent Specifications

### 1. PredictorAgent (Proactive Intelligence)

**Purpose**: Observe user action patterns and predict next 5 likely actions

**Location**: `ace/ace_cognitive/predictor_agent.py`

**Responsibilities**:
- Collect action sequences from episodic memory
- Cluster sequences using deterministic k-means
- Learn action patterns with confidence scoring
- Generate predictions for upcoming user actions
- Track prediction accuracy for learning

**Key Data Structures**:

```python
@dataclass
class ActionSequence:
    """Recorded user action sequence."""
    sequence_id: str
    actions: List[str]  # ['open_file', 'run_test', 'refactor']
    timestamp: float
    project_context: dict  # {'language': 'python', 'project': 'ace'}
    outcome: str  # 'success' or 'failure'
    duration_ms: float

@dataclass
class PredictionPattern:
    """Learned pattern of action sequences."""
    pattern_id: str
    sequence_prefix: List[str]  # First N actions
    predicted_next_actions: List[str]  # Ordered by probability
    confidence_score: float  # 0.0-1.0
    frequency: int  # Times observed
    last_observed: float
    feedback_positive: int
    feedback_negative: int

@dataclass
class Prediction:
    """Single prediction with explanation."""
    prediction_id: str
    predicted_actions: List[str]
    confidence: float
    reason: str  # "User typically refactors after 2 test runs"
    estimated_duration_ms: int
    estimated_value: str  # 'high', 'medium', 'low'
```

**Algorithm**:

1. **Collection Phase** (continuous):
   - Collect action events from EventBus
   - Store as ActionSequence in episodic memory

2. **Clustering Phase** (nightly or 100+ actions):
   - Vectorize sequences using deterministic embedding
   - K-means clustering (k=10-20, deterministic seed)
   - Extract frequent prefixes per cluster

3. **Pattern Learning** (per cluster):
   - For each prefix, calculate next-action frequencies
   - Score confidence = frequency / cluster_size
   - Store as PredictionPattern

4. **Prediction Generation** (on user action):
   - Match current action sequence to patterns
   - Find top-3 matching patterns
   - Generate 5 predictions with confidence scores
   - Reject if confidence <0.6 (too uncertain)

**Integration Points**:
- **Input**: EventBus (user actions), EpisodicMemory (historical sequences)
- **Output**: PredictionAgent → ValidatorAgent
- **Storage**: PredictionPatterns in DistributedMemorySync (tag: `prediction_pattern`)

**Tests** (8 tests):
- `test_action_sequence_collection` - Collect actions correctly
- `test_deterministic_clustering` - Same seed → identical clusters
- `test_pattern_extraction` - Extract frequent prefixes
- `test_confidence_scoring` - Calibrated 0.0-1.0 scores
- `test_prediction_generation` - Generate 5 diverse predictions
- `test_low_confidence_rejection` - Skip uncertain predictions
- `test_feedback_improves_model` - User feedback retrains
- `test_anti_oscillation` - Stop predicting after N rejections

---

### 2. ValidatorAgent (Safety Gate)

**Purpose**: Assess safety and risk of predicted actions before execution

**Location**: `ace/ace_cognitive/validator_agent.py`

**Responsibilities**:
- Evaluate predicted action safety
- Score risk (0.0-1.0) based on system state
- Apply governance policies
- Reject actions exceeding risk threshold

**Safety Scoring Formula**:

```python
risk_score = (
    risk_from_action_type * 0.3 +      # File delete = high risk
    risk_from_system_state * 0.2 +     # RAM >80% = risky
    risk_from_user_history * 0.2 +     # User disabled similar prediction = risky
    risk_from_current_load * 0.15 +     # CPU >70% = risky
    risk_from_unpredictability * 0.15   # Action involves random elements = risky
)

# Decision:
if risk_score > 0.8:
    REJECT (too risky, wait for user)
elif risk_score > 0.5:
    WARN (executor may get user approval)
else:
    APPROVE (executor can proceed)
```

**Policies Enforced**:

```yaml
policies:
  - file_operations:
      delete: risk=0.9
      write: risk=0.6 (if outside workspace=0.95)
      read: risk=0.1
  
  - code_generation:
      with_tests: risk=0.5 (tests validate safety)
      without_tests: risk=0.85 (no validation)
      requires_approval: true
  
  - external_calls:
      http_request: risk=0.7
      shell_command: risk=0.8 (depends on command)
      package_install: risk=0.9
  
  - memory_operations:
      read: risk=0.1
      write: risk=0.3 (governance enforced)
      delete: risk=0.85
```

**Tests** (6 tests):
- `test_risk_scoring_accurate` - Scores match expectations
- `test_policy_enforcement` - Policies applied correctly
- `test_system_state_factors` - High load increases risk
- `test_user_history_factors` - User rejections increase risk
- `test_rejection_threshold` - Rejects >0.8 risk
- `test_approval_logging` - All decisions logged to audit trail

---

### 3. ExecutorAgent (Safe Execution)

**Purpose**: Execute validated predictions in isolated sandbox

**Location**: `ace/ace_cognitive/executor_agent.py`

**Responsibilities**:
- Execute approved predictions safely
- Sandbox execution (no side effects)
- Capture results and resource usage
- Present results to user for approval
- Handle execution failures gracefully

**Sandbox Isolation**:

```yaml
sandbox_policy:
  filesystem:
    mode: read_only  # Cannot write to user files
    working_dir: /tmp/proactive_exec_XXXXX
  network:
    allowed: localhost_only  # Cannot reach external APIs
  process:
    timeout: 30_seconds
    memory_limit: 512_MB
    cpu_cores: 1
  execution:
    as: separate_process  # Isolated from main ACE
    capture_stdout: true
    capture_stderr: true
    fallback_safe: true  # If sandbox fails, don't execute
```

**Execution Workflow**:

```
1. Receive approved prediction
2. Create sandbox environment
3. Execute predicted action
4. Capture output + resource usage
5. On success: Present results to user
6. User decision: Accept | Reject | Learn
7. (Optional) Apply side effects if user accepts
```

**Example Execution**:

```
Prediction: "Generate unit tests for user's open Python file"

Execution:
1. Copy file to sandbox (read-only)
2. Run: test_generator.generate_tests(file_content)
3. Capture: test_code.py (in sandbox)
4. Measure: 2.3s runtime, 45MB peak memory
5. Present: "Generated 15 tests with 92% coverage. Accept?"
6. User: "Yes"
7. Apply: Write test_code.py to user's workspace
```

**Tests** (6 tests):
- `test_sandbox_isolation_prevents_side_effects` - Changes don't escape
- `test_timeout_enforcement` - Kills runaway predictions
- `test_memory_limit_enforcement` - Respects 512MB quota
- `test_resource_usage_tracking` - Reports CPU/memory/time
- `test_failure_handling` - Gracefully handles exceptions
- `test_result_presentation` - Formats output for user

---

### 4. TransformerAgent (Code Architecture Extraction)

**Purpose**: Extract code architecture from large repositories (100K+ LOC)

**Location**: `ace/ace_cognitive/transformer_agent.py`

**Responsibilities**:
- Parse source code (AST-based for Python)
- Extract components: classes, functions, imports
- Build dependency graph: nodes=artifacts, edges=dependencies
- Handle large repos via TaskDelegator parallelization
- Aggregate partial graphs into unified view

**Extraction Algorithm**:

```
1. Discover all source files (recursively)
2. For each file:
   a. Parse with AST
   b. Extract classes, functions, imports
   c. Build local dependency graph
   d. Delegate to follower if file >5000 LOC
3. Aggregate local graphs into unified graph:
   a. Merge nodes (dedup)
   b. Merge edges (union dependency sets)
   c. Detect circular dependencies
4. Output: dependency graph (JSON/GraphML)
```

**Data Structures**:

```python
@dataclass
class CodeArtifact:
    """Code component (class, function, etc)."""
    artifact_id: str
    name: str
    type: str  # 'class', 'function', 'module'
    file_path: str
    line_range: tuple  # (start, end)
    source_code: str
    docstring: Optional[str]
    complexity: int  # McCabe complexity

@dataclass
class DependencyEdge:
    """Dependency from one artifact to another."""
    source_id: str
    target_id: str
    edge_type: str  # 'calls', 'inherits', 'imports', 'instantiates'
    frequency: int  # How many times called
    strength: float  # 0.0-1.0 (how important)

@dataclass
class DependencyGraph:
    """Complete architecture graph."""
    artifacts: Dict[str, CodeArtifact]
    edges: List[DependencyEdge]
    circular_dependencies: List[List[str]]  # Cycles detected
    metrics: dict  # Coupling, cohesion, etc.
```

**Parallelization** (via TaskDelegator):
- Files <5000 LOC: Parse locally
- Files >5000 LOC: Delegate to follower node
- Pool results from followers
- Aggregate into unified graph

**Tests** (7 tests):
- `test_extract_small_project` - 10 files, correct extraction
- `test_extract_large_project` - 1000+ files
- `test_circular_dependency_detection` - Finds cycles
- `test_parallelization_correctness` - Distributed = local
- `test_metrics_computation` - Coupling, cohesion accurate
- `test_ast_parsing_edge_cases` - Complex Python syntax
- `test_incremental_update` - Only re-parse changed files

---

### 5. AnalyzerAgent (Quality Scoring & Recommendations)

**Purpose**: Analyze architecture and propose refactoring improvements

**Location**: `ace/ace_cognitive/analyzer_agent.py`

**Responsibilities**:
- Score code quality (SOLID principles)
- Identify anti-patterns
- Propose refactoring improvements
- Rank proposals by impact × effort

**Quality Metrics**:

```python
@dataclass
class QualityMetrics:
    """Code architecture quality scores."""
    modularity: float  # Lower coupling = higher
    cohesion: float  # Higher = artifacts related
    cyclomatic_complexity: float  # Lower function complexity
    maintainability_index: float  # Overall maintainability
    solid_score: float  # SOLID principles compliance
    
    # SOLID Breakdown
    single_responsibility: float  # Classes <500 LOC?
    open_closed: float  # Extendable without modification?
    liskov_substitution: float  # Substitutable implementations?
    interface_segregation: float  # Segregated interfaces?
    dependency_inversion: float  # Depends on abstractions?

@dataclass
class RefactoringProposal:
    """Suggested refactoring."""
    proposal_id: str
    title: str  # "Extract UserService class"
    description: str
    affected_artifacts: List[str]
    estimated_complexity_reduction: float  # 0.0-1.0
    estimated_effort_hours: float
    impact_score: float  # Complexity reduction / effort
    risk_level: str  # 'low', 'medium', 'high'
    steps: List[str]  # Ordered refactoring steps
```

**Proposal Generation**:

1. **Extract Module** - Very large class (>1000 LOC) split into 2
2. **Merge Modules** - Tightly coupled classes (>3 shared dependencies) consolidated
3. **Break Cycle** - Circular dependency resolved via inversion
4. **Extract Interface** - Multiple implementations share common pattern
5. **Move Method** - Method used more by other class
6. **Remove God Object** - Class with 20+ public methods

**Scoring Formula**:

```python
proposal_quality_score = (
    (complexity_reduction * 0.4) +
    (coupling_improvement * 0.3) +
    (maintainability_gain * 0.2) +
    (risk_level_inverse * 0.1)
)

# Only propose if score > 0.7
```

**Tests** (7 tests):
- `test_modularity_scoring` - Scores match expectations
- `test_cohesion_calculation` - Intra-module density
- `test_solid_compliance_checking` - SRP, OCP, etc. validated
- `test_proposal_generation` - Generates 3-5 proposals per repo
- `test_proposal_ranking` - Higher-impact proposals ranked higher
- `test_anti_pattern_detection` - Catches god objects, cycles
- `test_effort_estimation_accuracy` - Effort estimates within 30%

---

### 6. SimulatorAgent (Refactoring Validation)

**Purpose**: Simulate refactoring changes and validate safety

**Location**: `ace/ace_cognitive/simulator_agent.py`

**Responsibilities**:
- Clone codebase to sandbox
- Apply refactoring changes
- Run test suite (if exists)
- Report safety and impact
- Generate detailed diff

**Simulation Workflow**:

```
1. Receive refactoring proposal
2. Clone repo to sandbox
3. Apply refactoring (code transformation)
4. Run existing tests:
   a. Parse test framework
   b. Identify test files
   c. Execute tests
   d. Capture results
5. Analyze impact:
   a. Check for import errors
   b. Verify method signatures
   c. Scan for broken references
6. Generate report:
   - ✅ Tests passing: X/Y
   - ⚠️ Warnings: Z (unused imports, etc.)
   - 📊 Impact: +50 lines, -30 lines
   - 🎯 Recommendation: SAFE | RISKY | BLOCKED
```

**Tests** (6 tests):
- `test_code_transformation_correctness` - Refactored code is valid
- `test_test_execution_in_simulation` - Tests run correctly
- `test_import_validation` - No broken imports
- `test_method_signature_compatibility` - Signatures preserved
- `test_impact_calculation` - Lines added/removed accurate
- `test_safety_recommendation_accuracy` - Correctly flags risky changes

---

## Integration with Phase 3B

### ConsensusEngine Usage
- **Agent Voting**: High-risk decisions require consensus from 2+ agents
- **Pattern Agreement**: Prediction patterns must match across nodes for promotion
- **Coordination**: Agents communicate via Raft-ordered events

### TaskDelegator Usage
- **Code Extraction**: Parallelize large file parsing to follower nodes
- **Architecture Analysis**: Distribute analysis across capable nodes
- **Simulation**: Massive test suite execution delegated to powerful nodes

### DistributedMemorySync Usage
- **Prediction Patterns**: Learned patterns replicated to all nodes
- **Architecture Snapshots**: Latest codebase analysis cached
- **Analysis Results**: De-duplicated across cluster

### HealthMonitor Usage
- **Agent Resource Tracking**: Monitor each agent's CPU/memory usage
- **Load-Balanced Delegation**: Route heavy tasks to underutilized nodes
- **Recovery Actions**: Restart crashed agents, handle timeouts

---

## Data Flow

```
User Action
    ↓
EventBus (Phase 0)
    ↓
┌─────────────────────────────────────┐
│ PredictorAgent                      │
│ - Observe patterns                  │
│ - Generate predictions              │
│ (confidence, reason, duration)      │
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│ ValidatorAgent                      │
│ - Score risk                        │
│ - Apply policies                    │
│ - Reject if unsafe                  │
└──────────────┬──────────────────────┘
               ↓
           DECISION
        /    |    \
    REJECT  WARN  APPROVE
      |      |      |
      └──────┴──────┘
             ↓
┌─────────────────────────────────────┐
│ ExecutorAgent                       │
│ - Sandbox execution                 │
│ - Capture results                   │
│ - Present to user                   │
└──────────────┬──────────────────────┘
               ↓
         User Decision
        /    |        \
    REJECT  ACCEPT   LEARN
      |      |         |
      └──────┴─────────┘
             ↓
    Update Prediction Model
    (feedback loop)
```

---

## Implementation Phases

### Phase 4.1: Core Agents (1 week)
- [ ] PredictorAgent (clustering + pattern learning)
- [ ] ValidatorAgent (risk scoring + policy enforcement)
- [ ] ExecutorAgent (sandbox execution)
- [ ] Full integration tests

### Phase 4.2: Code Analysis Agents (1 week)
- [ ] TransformerAgent (AST parsing + extraction)
- [ ] AnalyzerAgent (quality scoring + proposal generation)
- [ ] SimulatorAgent (refactoring validation)
- [ ] Full integration tests

### Phase 4.3: Integration & Optimization (1 week)
- [ ] Phase 3B integration (TaskDelegator, DistributedMemorySync)
- [ ] Distributed execution testing
- [ ] Performance optimization
- [ ] Production hardening

---

## Test Strategy

**Unit Tests**: 40+ tests (one per major function)
- PredictorAgent: 8 tests
- ValidatorAgent: 6 tests
- ExecutorAgent: 6 tests
- TransformerAgent: 7 tests
- AnalyzerAgent: 7 tests
- SimulatorAgent: 6 tests

**Integration Tests**: 10+ tests
- End-to-end proactive prediction workflow
- End-to-end code analysis workflow
- Phase 3B integration (delegation, memory sync)
- Multi-agent coordination

**Stress Tests**: 5+ tests
- 100 proactive predictions under load
- 1000+ LOC code analysis
- Concurrent agent execution
- Memory pressure (>80% RAM)

**Target Coverage**: >90% line coverage per module

---

## Safety & Governance

### Preserves Phase 0-3 Guarantees

1. **Determinism** ✅
   - Clustering uses deterministic seed
   - Predictions recorded in GoldenTrace
   - Replay produces identical predictions

2. **Memory Governance** ✅
   - Prediction patterns subject to Phase 2C quotas
   - Code analysis results archived properly
   - No quota violations

3. **Kernel Isolation** ✅
   - Cannot modify Layer 0 modules
   - All actions logged to AuditTrail
   - NuclearMode preserves approval gate

4. **Safety-First** ✅
   - Predictions execute in sandbox (no side effects)
   - ValidatorAgent rejects high-risk actions
   - User approval required before real execution

5. **Anti-Oscillation** ✅
   - Track rejection frequency per pattern
   - Disable pattern if rejected >3 times
   - User explicitly re-enable disabled patterns

---

## Dependencies & Prerequisites

**Must Have** (Phases 0-3B complete):
- ✅ DeterministicMode (Phase 0)
- ✅ AuditTrail (Phase 0)
- ✅ SnapshotEngine (Phase 0)
- ✅ EvaluationEngine (Phase 1)
- ✅ MemoryGovernance (Phase 2C)
- ✅ ConsensusEngine (Phase 3B)
- ✅ TaskDelegator (Phase 3B)
- ✅ DistributedMemorySync (Phase 3B)
- ✅ HealthMonitor (Phase 3B)

**Optional** (Beneficial but not required):
- AgentScheduler (Phase 3A) - Better load balancing
- ByzantineDetector (Phase 3B) - Defense against anomalous agents

---

## Success Metrics

| Metric | Target | How Measured |
|--------|--------|--------------|
| **Prediction Accuracy** | >70% | % of predictions user accepts |
| **Safety** | >99% | Zero unintended side effects |
| **Coverage** | >90% | Code coverage per module |
| **Code Analysis Speed** | <60s for 100K LOC | Wall-clock time on follower nodes |
| **Determinism** | 100% | Replay produces identical results |
| **Anti-oscillation** | 100% | No repeated rejected patterns |

---

## References

- **Phase 3B Architecture**: PHASE_3B_ARCHITECTURE.md
- **Phase 3B Completion**: PHASE_3B_COMPLETION_REPORT.md
- **Master Roadmap**: ACE_MASTER_TASK_ROADMAP.md (Phase 4 section)
- **Test Files**: `tests/test_phase4_*.py`
- **Implementation**: `ace/ace_cognitive/` (agent modules)

---

## Approval & Sign-Off

**Phase 4 Architecture**: ✅ APPROVED FOR IMPLEMENTATION

- **3-4 week estimated duration**
- **2-3 developer team recommended**
- **40+ tests to validate**
- **Dependent on Phase 3B completion (127/127 tests passing)**

**Ready to proceed with implementation** 🚀
