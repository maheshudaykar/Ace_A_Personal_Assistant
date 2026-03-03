<div align="center">

![ACE Logo](ace-logo.png)

# ACE — Autonomous Cognitive Engine

Deterministic, governance-first autonomous agent architecture for production-oriented systems.

[![Tests](https://img.shields.io/badge/tests-268%20passing-success)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Current Phase](https://img.shields.io/badge/phase-2C-green)](CHANGELOG.md)

</div>

---

## What ACE Is

ACE is a layered autonomous-agent framework designed around two priorities:

1. **Deterministic behavior** for repeatability, debugging, and reliability
2. **Governance and safety controls** for bounded runtime and memory growth

ACE is built as a strong systems foundation first, then expanded with higher-level cognitive capabilities over time.

> Current phase (short): **Phase 2C complete**. Full release and phase details are maintained in `CHANGELOG.md`.

---

## Core Design Principles

- **Deterministic by default**: stable ordering and predictable outcomes
- **Synchronous execution model**: no background daemons required for core guarantees
- **Governance-first architecture**: quotas, guardrails, and auditable actions
- **Archive-before-delete memory policy**: active memory is preserved; archival and compaction are controlled
- **Layer isolation**: kernel responsibilities remain separated from cognitive/runtime layers

---

## Architecture Overview

ACE is organized as composable layers and subsystems:

```text
┌────────────────────────────────────────────────────────────┐
│ Interface Layer                                            │
│ - CLI, operator entry points                               │
├────────────────────────────────────────────────────────────┤
│ Tooling + Diagnostics Layer                                │
│ - tool registry, executors, profiling, evaluation          │
├────────────────────────────────────────────────────────────┤
│ Cognitive + Runtime Layer                                  │
│ - scheduling/runtime orchestration, future reasoning stack │
├────────────────────────────────────────────────────────────┤
│ Memory Layer                                               │
│ - working memory, episodic store, consolidation, governance│
├────────────────────────────────────────────────────────────┤
│ Kernel Layer (governed core)                               │
│ - state machine, audit trail, deterministic controls       │
└────────────────────────────────────────────────────────────┘
```

### Directory Layout

```text
ace/
  ace_kernel/        # state, safety, audit primitives
  ace_core/          # event infrastructure
  ace_tools/         # tool interfaces and executors
  ace_memory/        # memory system and governance
  ace_diagnostics/   # evaluation and profiling utilities
  ace_cognitive/     # cognitive modules (expanding)
  runtime/           # runtime orchestration helpers

tests/               # full validation suite
run_ace.py           # main entrypoint
CHANGELOG.md         # release and phase history
```

---

## How ACE Works

At a high level, ACE operates in a deterministic control loop:

1. **Initialize core systems**
   - state machine
   - deterministic mode
   - event bus
   - tool registry
2. **Accept and process tasks/commands**
3. **Execute tools through governed interfaces**
4. **Record outcomes and telemetry in memory + audit trail**
5. **Apply memory governance when thresholds are crossed**
6. **Return deterministic, auditable results**

This keeps behavior explainable and bounded as workload scales.

---

## Memory Architecture (Practical)

ACE memory combines fast operational context with persistent task history:

- **Working Memory**
  - short-lived in-memory buffer for current task context
- **Episodic Memory**
  - persistent task-linked records
  - indexed retrieval paths
- **Consolidation Engine**
  - deterministic merge logic for similar memory records
- **Governance Controls**
  - total/active/per-task hard caps
  - consolidation complexity guard
  - deterministic archival compaction

### Why this matters

This design gives you:
- bounded growth under sustained load
- predictable latency characteristics
- low operational surprise in production

---

## Determinism, Safety, and Governance

ACE emphasizes systems reliability rather than best-effort behavior:

- deterministic tie-breaking and stable ordering
- auditable governance events
- no hidden mutation paths
- bounded-memory policies to prevent uncontained growth
- clear separation of responsibilities across layers

For detailed release-by-release behavior changes, use `CHANGELOG.md` and tagged milestones.

---

## Getting Started

### Requirements

- Python 3.11+
- Windows/Linux/macOS

### Setup

```bash
git clone <your-repo-url>
cd Ace_A_Personal_Assistant
python -m venv .venv
```

**Windows (PowerShell)**
```powershell
.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
```

**Linux/macOS**
```bash
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

### Run ACE

```bash
python run_ace.py
```

Deterministic mode:

```bash
python run_ace.py --deterministic
```

---

## Testing and Validation

Run full suite:

```bash
python -m pytest tests/ -v
```

Quick run:

```bash
python -m pytest tests/ -q
```

The test suite is the primary source of behavioral verification for architecture and governance guarantees.

---

## Contributing

Contributions are welcome.

Please read `CONTRIBUTING.md` for:
- coding standards
- architecture constraints
- test requirements
- contribution workflow

---

## Documentation Map

- `CHANGELOG.md` — release notes and phase progression
- `CONTRIBUTING.md` — contributor workflow and rules
- `PHASE_2A_COMPLETION_REPORT.md` — 2A technical completion details
- `PHASE_2B_COMPLETION_REPORT.md` — 2B technical completion details
- `ACE_RESEARCH_INTEGRATION_REPORT.md` — research synthesis and architectural rationale

---

## License

Use the repository license terms for all usage and contributions.
