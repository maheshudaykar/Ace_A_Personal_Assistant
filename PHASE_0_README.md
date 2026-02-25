# ACE Phase 0 - Getting Started

## Overview

ACE Phase 0 is the **minimal viable product (MVP)** that establishes the core infrastructure for ACE development. It focuses on getting a working system running quickly without unnecessary complexity.

**Phase 0 Principles**:
- ✅ MVP first - only essentials
- ✅ No distributed nodes yet
- ✅ No nuclear switch
- ✅ No self-modifying code
- ✅ Simple, understandable code
- ✅ Foundation for Phase 1+

## Architecture

Phase 0 consists of:

```
┌─────────────────────────────────────┐
│     Layer 4: Interface (CLI)        │
├─────────────────────────────────────┤
│  Layer 2: Tools (File Ops, LLM)     │
├─────────────────────────────────────┤
│  Layer 1: Memory (Placeholder)      │
├─────────────────────────────────────┤
│  Layer 0: Kernel (State Machine)    │
├─────────────────────────────────────┤
│  Core: Event Bus (Simple Pub/Sub)   │
└─────────────────────────────────────┘
```

## Components

### 1. Logging System (`ace_kernel/logging_setup.py`)
- Simple file and console logging
- Rotating file handler (10MB, 5 backups)
- Deterministic timestamps option

### 2. State Machine (`ace_kernel/state_machine.py`)
- 4 states: BOOT → IDLE → EXECUTING → SHUTDOWN
- Transition validation
- Callbacks on state changes
- State history tracking

### 3. Event Bus (`ace_core/event_bus.py`)
- Minimal pub/sub without async
- Event types: SYSTEM_BOOT, TASK_RECEIVED, TASK_COMPLETED, STATE_CHANGED, etc.
- Simple event history
- Non-blocking subscribers

### 4. Deterministic Mode (`ace_kernel/deterministic_mode.py`)
- Fixed random seed (default: 42)
- Temperature override to 0.0 for LLM
- Reproducible execution for debugging

### 5. Tool Registry (`ace_tools/registry.py`)
- Register and execute tools
- Built-in tools: read_file, list_files, write_file
- Global registry instance

### 6. LLM Interface (`ace_tools/llm_interface.py`)
- Mock LLM for Phase 0 (no real inference)
- Placeholder for llama.cpp integration in Phase 1
- Deterministic mode support

### 7. CLI Interface (`ace_interface/cli.py`)
- Interactive command-line interface
- Commands: help, status, det, read, list, tools, llm, quit
- Real-time state display

## Installation

### Prerequisites
- Python 3.11+
- pip

### Setup

1. **Clone/navigate to ACE directory**:
```bash
cd c:\Mahi\Jarvis\Ace_A_Personal_Assistant
```

2. **(Optional) Create virtual environment**:
```bash
python -m venv venv
venv\Scripts\activate  # Windows
# or: source venv/bin/activate  # Linux/Mac
```

3. **Install development tools** (optional):
```bash
pip install -r requirements.txt
```

## Running ACE Phase 0

### Start ACE (Normal Mode)
```bash
python run_ace.py
```

### Start ACE (Deterministic Mode)
```bash
python run_ace.py --deterministic
# or
python run_ace.py -det
```

## CLI Commands

Once ACE is running, you can use these commands:

| Command | Description | Example |
|---------|-------------|---------|
| `help` | Show help | `help` |
| `status` | Show current status | `status` |
| `det on\|off` | Toggle deterministic mode | `det on` |
| `read <file>` | Read a file | `read README.md` |
| `list <dir>` | List files in directory | `list .` |
| `tools` | List available tools | `tools` |
| `llm <prompt>` | Query LLM (mock) | `llm explain what you do` |
| `quit` | Exit ACE | `quit` |

## Example Session

```
============================================================
  🚀 ACE - Autonomous Cognitive Engine (Phase 0)
  Type 'help' for commands, 'quit' to exit
============================================================

[BOOT] Deterministic: 🔓 OFF
> status

State: BOOT
Deterministic: OFF
Available tools: read_file, list_files, write_file

> det on
✓ Deterministic mode enabled

> list .
--- Files in . ---
  ACE_MASTER_TASK_ROADMAP.md
  README.md
  run_ace.py
  requirements.txt
  ... and more

> read README.md
--- Content of README.md ---
# ACE - Autonomous Cognitive Engine
...

> quit

👋 ACE shutting down...
```

## Log Files

ACE creates logs in the `logs/` directory:

- `logs/system.log` - Main system log with all events
- Rotating logs (5 backups of 10MB each)

## Testing

### Run tests:
```bash
pytest tests/ -v
```

### Run specific test:
```bash
pytest tests/test_state_machine.py -v
```

## Architecture Notes

### Event Bus (Phase 0 vs Phase 1+)

**Phase 0**:
- Simple pub/sub
- Synchronous execution
- No event replay
- No priority queue

**Phase 1+** will add:
- Async support (asyncio)
- Event replay mechanism
- Priority queue (levels 0-4)
- Dead-letter queue
- Backpressure handling

### LLM Interface (Phase 0 vs Phase 1+)

**Phase 0**:
- Mock LLM only
- Simple string matching for responses
- No actual inference

**Phase 1+** will add:
- llama.cpp integration
- Real LLM inference
- Model routing
- Token budgeting

### Tools (Phase 0 vs Phase 1+)

**Phase 0**:
- 3 built-in tools: file operations only
- Simple registry
- Synchronous execution

**Phase 1+** will add:
- 50+ tools (Git, Docker, OS control, etc.)
- Sandboxed execution
- Async support
- Plugin system

## Next Steps (Phase 1)

Phase 1 will add:
1. ✅ Planner & Reasoner (LLM-powered)
2. ✅ Real LLM integration (llama.cpp)
3. ✅ Reflection engine
4. ✅ Memory systems (episodic, semantic)
5. ✅ Risk assessment
6. ✅ 50+ tools
7. ✅ Async event bus
8. ✅ Proper error handling

## Architecture Overview

See `ACE_MASTER_TASK_ROADMAP.md` for complete architecture and Phase 0-6 planning.

## Troubleshooting

### "ModuleNotFoundError" 
- Ensure you're in the correct directory
- Check that all Python files are present

### "Port already in use" (future phases)
- Port conflict with existing service
- Kill process using port or use different port

### Logging not working
- Check `logs/` directory has write permissions
- Check `logs/system.log` for errors

## Development

### Code Style
```bash
# Format code
black ace_* run_ace.py

# Lint
flake8 ace_* run_ace.py

# Type check
mypy ace_* run_ace.py
```

### Running Tests
```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=ace_* -v
```

## License

See LICENSE file in repository root.

## Contributing

See CONTRIBUTING.md for contribution guidelines.

---

**Phase 0 Status**: Ready for development ✅

Start with Phase 1 implementation after validating Phase 0 core components.
