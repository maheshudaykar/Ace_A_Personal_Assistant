<div align="center">

![ACE Logo](ace-logo.png)

# ACE - Autonomous Cognitive Engine

**Production-Grade Autonomous Agent Framework with Advanced Memory Architecture**

[![Tests](https://img.shields.io/badge/tests-268%20passed-success)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Phase](https://img.shields.io/badge/phase-2C%20complete-green)](PHASE_2C_COMPLETION_REPORT.md)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

[Features](#-features) • [Architecture](#-architecture) • [Installation](#-installation) • [Usage](#-usage) • [Performance](#-performance) • [Contributing](#-contributing)

</div>

---

## 📖 Overview

**ACE (Autonomous Cognitive Engine)** is a research-grade autonomous agent framework designed for production environments. Built with rigorous engineering principles, ACE provides a complete cognitive architecture featuring deterministic behavior, bounded resource management, and enterprise-ready memory systems.

### Current Status: **Phase 2C Complete** ✅

- **268 tests passing** (100% success rate)
- **O(1) amortized performance** with incremental state tracking
- **Production-validated** memory governance and quota enforcement
- **Research-backed** architecture integrating patterns from AIOS, KAOS, Mnemosyne, H-MEM, and CogMem

---

## ✨ Features

### Phase 0 - Core Infrastructure
- **Immutable Kernel**: State machine, deterministic mode, audit logging
- **Event Bus**: Publish/subscribe with event history
- **Tool Registry**: Extensible tool execution framework
- **CLI Interface**: Interactive command-line interface

### Phase 1 - Cognitive Architecture
- **Working Memory**: Fast in-memory storage with configurable capacity
- **Episodic Memory**: Persistent task-based memory with hierarchical indexing
- **Quality Scoring**: Multi-dimensional evaluation (clarity, relevance, confidence, utility)
- **Semantic Search**: Embedding-based retrieval with TF-IDF fallback

### Phase 2A - Micro-Optimizations ([Report](PHASE_2A_COMPLETION_REPORT.md))
- **32.6% latency reduction** vs Phase 1 baseline
- **Batch quality scoring** eliminating redundant evaluations
- **LRU caching** for episodic memory store
- **Optimized embeddings** with length-aware scoring
- **237 tests** validating deterministic behavior

### Phase 2B - Advanced Memory ([Report](PHASE_2B_COMPLETION_REPORT.md))
- **Deterministic Similarity Consolidation**: Merges duplicate memories via cosine similarity
- **Hierarchical Indexing**: Hot/warm/cold tiers for efficient retrieval
- **Archive Management**: Quality-based archiving preserving active memory
- **259 tests** including consolidation and indexing validation

### Phase 2C - Memory Hardening & Bounded Growth ([Tag: v0.2.0-phase2c](https://github.com/yourusername/ace/releases/tag/v0.2.0-phase2c))
- **Global Quota Enforcement**: 10k total, 5k active, 1k per-task hard caps
- **Consolidation Guard**: Comparison budget preventing unbounded complexity
- **Atomic Compaction**: Deterministic archived entry reduction (30% → 20%)
- **O(1) Performance**: Incremental counters eliminate full-store scans
- **468x-1,031x speedup** from performance remediation
- **268 tests** with comprehensive governance coverage

---

## 🏗️ Architecture

ACE is built on a **layered architecture** with strict immutability guarantees:

```
┌─────────────────────────────────────────────────────────┐
│  Layer 4: Interface (CLI, API)                          │
├─────────────────────────────────────────────────────────┤
│  Layer 3: Diagnostics (Evaluation, Benchmarking)        │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Tools (Registry, File Ops, LLM Interface)     │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Cognitive (Planner, Reasoner - Future)        │
├─────────────────────────────────────────────────────────┤
│  Core: Memory (Working, Episodic, Consolidation)        │
│        Event Bus (Pub/Sub, History)                     │
├─────────────────────────────────────────────────────────┤
│  Layer 0: Kernel (State Machine, Audit, Deterministic)  │
│           🔒 IMMUTABLE - Never Modified                 │
└─────────────────────────────────────────────────────────┘
```

### Memory System Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Working Memory (Fast, In-Memory, Capacity-Limited)      │
├──────────────────────────────────────────────────────────┤
│  Episodic Memory (Persistent, Task-Indexed)              │
│  ├─ Hot Tier (< 7 days)                                 │
│  ├─ Warm Tier (7-30 days)                               │
│  └─ Cold Tier (> 30 days)                               │
├──────────────────────────────────────────────────────────┤
│  Memory Store (JSONL, LRU Cached, Atomic Operations)    │
├──────────────────────────────────────────────────────────┤
│  Consolidation Engine (Similarity-Based Deduplication)   │
├──────────────────────────────────────────────────────────┤
│  Governance Layer (Quotas, Guards, Compaction)          │
│  ├─ Per-Task Cap: 1,000 entries (quality-based archive) │
│  ├─ Active Cap: 5,000 entries (triggers consolidation)  │
│  ├─ Total Cap: 10,000 entries (prunes oldest archived)  │
│  └─ Comparison Guard: 50k comparisons/pass              │
└──────────────────────────────────────────────────────────┘
```

### Key Design Principles

- ✅ **Deterministic Execution**: Reproducible behavior for testing and debugging
- ✅ **Synchronous Operations**: No async/await complexity, predictable flow
- ✅ **Archive-First Policy**: Never delete active memories, always archive first
- ✅ **Atomic Operations**: Full-store rewrites for consistency guarantees
- ✅ **Bounded Growth**: Hard caps at all levels preventing unbounded resource consumption
- ✅ **Audit Trail**: Complete logging of all quota enforcement and governance actions

---

## 🚀 Installation

### Prerequisites

- Python 3.11+ (tested with Python 3.14.2)
- Virtual environment recommended

### Setup

**Windows (PowerShell):**
```powershell
# Clone repository
git clone https://github.com/yourusername/ace.git
cd ace

# Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies
python -m pip install -U pip
python -m pip install -r requirements.txt

# Verify installation
python -m pytest tests/ -v
```

**Linux/macOS:**
```bash
# Clone repository
git clone https://github.com/yourusername/ace.git
cd ace

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -U pip
pip install -r requirements.txt

# Verify installation
python -m pytest tests/ -v
```

---

## 💻 Usage

### Running Tests

```bash
# Run all tests (268 tests)
python -m pytest tests/ -v

# Run specific test suite
python -m pytest tests/test_phase2c_governance.py -v

# Run with coverage
python -m pytest tests/ --cov=ace --cov-report=html
```

### Memory System Example

```python
from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.consolidation_engine import ConsolidationEngine

# Initialize memory system
store = MemoryStore(store_path="memory.db")
memory = EpisodicMemory(store=store)

# Record experiences
entry_id = memory.record(
    task_id="task-001",
    content="User requested weather information",
    context={"location": "New York", "intent": "weather_query"}
)

# Retrieve relevant memories
results = memory.retrieve_top_k(
    task_id="task-001",
    query="weather",
    k=5
)

# Consolidate similar memories
consolidator = ConsolidationEngine(episodic=memory)
merged_count = consolidator.consolidate(merge_threshold=0.85)
print(f"Merged {merged_count} duplicate memories")
```

### Quota Enforcement

```python
from ace.ace_memory import memory_config

# Current quota configuration (memory_config.py)
MAX_TOTAL_ENTRIES = 10_000        # Hard cap on total entries
MAX_ACTIVE_ENTRIES = 5_000        # Triggers consolidation
MAX_ENTRIES_PER_TASK = 1_000      # Per-task hard cap
MAX_COMPARISONS_PER_PASS = 50_000 # Consolidation complexity guard

# Quotas are enforced automatically:
# - Per-task cap: Archives lowest-quality entries when exceeded
# - Total cap: Prunes oldest archived entries deterministically
# - Active cap: Triggers consolidation to merge duplicates
# - Comparison guard: Prevents unbounded consolidation complexity
```

---

## ⚡ Performance

### Benchmark Results (Phase 2C vs Phase 2B Baseline)

| Benchmark | Phase 2B Baseline | Phase 2C Optimized | Improvement |
|-----------|------------------:|-------------------:|------------:|
| **1k entries - record()** | 40.46 ms | 38.53 ms | **-4.8%** ✅ |
| **5k entries - record()** | N/A | 201.90 ms | **1,031x** vs pre-optimization |
| **Memory overhead (1k)** | +5.38 MB | +6.08 MB | +13% (acceptable) |
| **Memory overhead (5k)** | +23.82 MB | +17.14 MB | **-36%** ✅ |

### Performance Characteristics

- **O(1) amortized record()**: Incremental counters eliminate full-store scans
- **Threshold-triggered enforcement**: Governance only activates when quotas exceeded
- **Atomic compaction**: Full-store rewrite reduces archived ratio from 30% → 20%
- **LRU caching**: Frequently accessed entries served from memory
- **Deterministic behavior**: Reproducible performance across runs

---

## 🧪 Testing

### Test Coverage: 268/268 Passing (100%)

- **Phase 0 Tests**: Kernel, event bus, state machine
- **Phase 1 Tests**: Working memory, episodic memory, quality scoring
- **Phase 2A Tests**: Batch scoring, LRU cache, optimizations (30 tests)
- **Phase 2B Tests**: Consolidation, hierarchical indexing (12 tests)
- **Phase 2C Tests**: Quota enforcement, governance, compaction (9 tests)

### Running Specific Test Suites

```bash
# Phase 2C governance tests
python -m pytest tests/test_phase2c_governance.py -v

# Memory system tests
python -m pytest tests/test_episodic_memory.py tests/test_memory_store.py -v

# Consolidation tests
python -m pytest tests/test_consolidation_engine.py -v

# Full suite with detailed output
python -m pytest tests/ -v --tb=short
```

---

## 🗺️ Roadmap

### ✅ Completed Phases

- **Phase 0**: Core infrastructure (kernel, event bus, CLI)
- **Phase 1**: Cognitive architecture (memory systems, quality scoring)
- **Phase 2A**: Micro-optimizations (32.6% latency reduction)
- **Phase 2B**: Advanced memory (consolidation, hierarchical indexing)
- **Phase 2C**: Memory hardening (quota enforcement, bounded growth)

### 🔮 Future Phases

- **Phase 3**: Background maintenance and async optimizations
- **Phase 4**: Advanced cognitive features (planner, reasoner)
- **Phase 5**: Distributed architecture and scaling
- **Phase 6**: Self-improvement and evolution mechanisms

---

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for:

- Development setup and guidelines
- Code style and testing requirements
- Architecture constraints and design principles
- How to add new features or fix bugs

### Quick Start for Contributors

```bash
# Fork and clone
git clone https://github.com/yourfork/ace.git
cd ace

# Create feature branch
git checkout -b feature/your-feature-name

# Make changes and test
python -m pytest tests/ -v

# Commit with conventional commits
git commit -m "feat: add new feature"

# Push and create PR
git push origin feature/your-feature-name
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

ACE's architecture is informed by research from:

- **AIOS/KAOS**: Explicit resource governance without async complexity
- **AgentOps**: High-signal telemetry and observability patterns
- **Mnemosyne/H-MEM/CogMem**: Bounded memory with archive tiers and consolidation
- **Production Systems Design**: Hard caps, deterministic behavior, atomic operations

---

<div align="center">

**Built with ❤️ for autonomous agent research and production deployment**

[Documentation](docs/) • [Issue Tracker](issues/) • [Discussions](discussions/)

</div>

