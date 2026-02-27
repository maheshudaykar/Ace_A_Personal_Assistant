# Contributing to ACE

## Overview

**ACE (Autonomous Cognitive Engine)** is a production-grade autonomous agent framework currently at **Phase 2C** (Memory Hardening & Bounded Growth). This guide covers development practices, architecture constraints, and contribution workflows for the ACE project.

### Current Project Status

- **Phase**: 2C Complete (Memory Hardening & Bounded Growth)
- **Tests**: 268/268 passing (100% success rate)
- **Version**: v0.2.0-phase2c
- **Performance**: O(1) amortized operations with quota governance

## Code Organization

### Module Structure

```
ace_core/          # Event bus infrastructure (Layer - Core)
ace_kernel/        # State machine, logging, deterministic mode (Layer 0)
ace_tools/         # Tool registry, file ops, LLM interface (Layer 2)
ace_interface/     # CLI and user-facing interfaces (Layer 4)
ace_cognitive/     # Planner, reasoner (Layer 1 - placeholder)
ace_memory/        # Memory systems (Phase 2+ - placeholder)
ace_evolution/     # Self-improvement (Phase 3+ - placeholder)
```

### Layer Responsibilities

- **Layer 0 (Kernel)**: Immutable core (logging, state machine, deterministic mode)
- **Core**: Event infrastructure (pub/sub, history)
- **Layer 2 (Tools)**: Tool execution, LLM interface
- **Layer 4 (Interface)**: User interaction (CLI)

## Development Guidelines

### 1. Code Style

```bash
# Format with black
black ace_* run_ace.py

# Lint with flake8
flake8 ace_* run_ace.py

# Type check with mypy
mypy ace_* run_ace.py
```

### 2. Testing

Every module should have corresponding tests:
- `ace_kernel/state_machine.py` → `tests/test_state_machine.py`
- New module → New test file in `tests/`

```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_state_machine.py -v

# Run with coverage
pytest tests/ --cov=ace_* -v
```

### 3. Logging

Use logging throughout:

```python
import logging

logger = logging.getLogger(__name__)

logger.info("Starting operation")
logger.debug("Detailed debug info")
logger.error("An error occurred")
```

### 4. Docstrings

Use Google-style docstrings:

```python
def my_function(param1: str, param2: int) -> bool:
    """Short description.
    
    Longer description if needed.
    
    Args:
        param1: Description of param1
        param2: Description of param2
        
    Returns:
        Description of return value
        
    Raises:
        ValueError: When validation fails
    """
    pass
```

### 5. Error Handling

Always handle errors gracefully:

```python
try:
    result = risky_operation()
except SpecificError as e:
    logger.error(f"Operation failed: {e}")
    raise  # Re-raise or handle appropriately
```

## Phase 0 Scope Constraints

### ✅ Allowed in Phase 0
- Pure Python stdlib modules
- Simple synchronous code
- Mock implementations (for later integration)
- File I/O with safety checks
- Logging and state tracking
- Unit tests with pytest
- Configuration files (YAML)

### ❌ NOT Allowed in Phase 0
- External Python packages (except dev tools)
- Async/await code
- Self-modifying code
- Self-learning implementations
- Distributed communication
- Really anything complex that should wait for Phase 1+

## Adding a New Tool

To add a new tool in Phase 0:

1. **Add tool function** to a file in `ace_tools/`:
```python
def new_tool(param1: str) -> str:
    """Tool description."""
    logger.info(f"Running new_tool with {param1}")
    # Implementation
    return result
```

2. **Register in `run_ace.py`**:
```python
from ace_tools import new_tool, get_tool_registry
registry = get_tool_registry()
registry.register(Tool("new_tool", "Description", new_tool, {"param1": "str"}))
```

3. **Add CLI command** in `ace_interface/cli.py` if needed:
```python
elif command.startswith("new_cmd "):
    param = command[8:].strip()
    result = registry.execute_tool("new_tool", param1=param)
    print(result)
```

4. **Write tests** in `tests/test_new_tool.py`:
```python
def test_new_tool():
    result = new_tool("input")
    assert result == "expected"
```

## Adding a New Event Type

To add a new event type:

1. **Add to EventType enum** in `ace_core/event_bus.py`:
```python
class EventType(Enum):
    # ...existing types...
    NEW_EVENT = "NEW_EVENT"
```

2. **Publish in code**:
```python
event = Event(event_type=EventType.NEW_EVENT, data={"key": "value"})
bus.publish(event)
```

3. **Subscribe** if needed:
```python
def handle_event(event):
    print(f"Got event: {event.data}")

bus.subscribe(EventType.NEW_EVENT, handle_event)
```

## Testing Checklist

Before committing changes:

1. ✅ All tests pass: `pytest tests/ -v`
2. ✅ Code formatted: `black ace_* run_ace.py`
3. ✅ No lint errors: `flake8 ace_* run_ace.py`
4. ✅ Type hints correct: `mypy ace_* run_ace.py`
5. ✅ Logging added to key operations
6. ✅ Docstrings complete
7. ✅ Config updated if needed
8. ✅ README updated if interface changes

## Common Tasks

### Run ACE
```bash
python run_ace.py
python run_ace.py --deterministic
```

### Debug with Logging
```bash
# Edit config/config.yaml, set logging level to DEBUG
# Or check logs/system.log
tail -f logs/system.log
```

### Check Code Quality
```bash
# All checks
black ace_* run_ace.py --check
flake8 ace_* run_ace.py
mypy ace_* run_ace.py
pytest tests/ -v
```

### View Test Coverage
```bash
pytest tests/ --cov=ace_* --cov-report=html
# Open htmlcov/index.html
```

## Phase 0 Principles

1. **Simple over Complex**: Keep it basic
2. **Stdlib Only**: No external deps at runtime
3. **Well-Tested**: High test coverage
4. **Well-Logged**: Audit trail of executions
5. **Well-Documented**: Clear and complete docs
6. **Foundation First**: Build solid foundation for Phase 1+

## Reporting Issues

When reporting issues, include:
- What you were trying to do
- What happened
- What you expected
- Steps to reproduce
- Python version and OS
- Relevant log lines

Example:
```
Title: CLI command "list" fails with unicode filenames

Steps:
1. Create a file with unicode name: "测试.txt"
2. Run: python run_ace.py
3. Type: list .
4. Error occurs

Expected: File list includes "测试.txt"

Actual: Error in list_files() with unicode handling

Environment:
- Python 3.11.0
- Windows 10
- Log excerpt: [error in list_files with encoding]
```

## Questions?

- Check PHASE_0_README.md for usage
- See PHASE_0_COMPLETION.md for architecture
- Review ACE_MASTER_TASK_ROADMAP.md for Phase planning
- Look at existing code for examples

## Phase 0 Timeline

- **Current**: Phase 0 MVP complete
- **Next**: Phase 1 design review
- **Future**: Phase 1 implementation (real LLM, planner, 50+ tools)

---

Thank you for contributing to ACE! 🚀
