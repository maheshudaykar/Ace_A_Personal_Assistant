# Changelog

All notable changes to ACE will be documented in this file.

## [0.1.0] - 2026-02-26 Phase 0 MVP Release

### Added
- **Core Infrastructure**
  - Logging system with RotatingFileHandler (10MB, 5 backups)
  - 4-state state machine (BOOT→IDLE→EXECUTING→SHUTDOWN)
  - Simple pub/sub event bus with event history
  - Deterministic mode for reproducible execution
  
- **Tool System**
  - Tool registry with singleton pattern
  - Read/write/list file operations
  - Mock LLM interface (context-aware responses)
  - Tool execution framework

- **User Interface**
  - Interactive CLI with 8 commands
  - Real-time state display
  - Graceful shutdown support
  
- **Testing & Config**
  - 62 comprehensive unit tests
  - pytest configuration with conftest.py
  - Complete config.yaml with all settings
  - Test coverage for all core modules

- **Documentation**
  - PHASE_0_README.md with setup/usage
  - PHASE_0_COMPLETION.md validation checklist
  - Inline code documentation
  - Architecture overview

### Features
- ✅ Logging to file + console with automatic rotation
- ✅ State machine with transition validation and callbacks
- ✅ Event bus with filtering and history (max 1000 events)
- ✅ Tool registry for managing tool execution
- ✅ Mock LLM for testing before Phase 1 integration
- ✅ CLI with 7 functional commands + help
- ✅ Deterministic mode toggle for reproducibility
- ✅ Pure Python stdlib (no external runtime dependencies)

### Test Coverage
- test_state_machine.py - 15 tests
- test_event_bus.py - 18 tests
- test_tool_registry.py - 14 tests
- test_deterministic_mode.py - 15 tests
- **Total**: 62 tests covering all core functionality

### Known Limitations
- Synchronous only (async support in Phase 1)
- Mock LLM only (real inference in Phase 1)
- Single process (distributed support later)
- Limited tools (50+ in Phase 1)
- No persistence (saved between sessions)

---

## [Unreleased] - Phase 1 Planning

### Planned for Phase 1
- Real LLM integration (llama.cpp)
- Planner & Reasoner for task decomposition
- Reflection engine for self-critique
- Async event bus with priority queue
- 50+ tools (Git, Docker, OS control)
- Episodic and semantic memory systems
- Risk assessment module
- Extended state machine (10 states)
- Model routing and token budgeting

See ACE_MASTER_TASK_ROADMAP.md for complete Phase 1-6 planning.

---

## Installation

```bash
cd c:\Mahi\Jarvis\Ace_A_Personal_Assistant
pip install -r requirements.txt  # Optional (dev tools)
python run_ace.py
```

## Testing

```bash
pytest tests/ -v
```

## License

See LICENSE file.

---

For more details, see PHASE_0_COMPLETION.md
