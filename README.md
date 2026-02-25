ACE - Autonomous Cognitive Engine (Phase 0)
===========================================

Phase 0 provides a minimal, fully typed core for ACE with a CLI, state machine,
event bus, tool registry, and deterministic mode. It is a local-only mock that
uses standard library components and a stubbed LLM interface.

Highlights
----------
- Kernel: state machine, deterministic mode, logging
- Core: event bus (publish/subscribe with history)
- Tools: registry plus file and LLM mock tools
- Interface: simple CLI for basic commands

Project Layout
--------------
- ace_kernel/       Kernel primitives (state machine, deterministic mode)
- ace_core/         Core services (event bus)
- ace_tools/        Tool registry and built-in tools
- ace_interface/    CLI entry points
- tests/            Pytest suite for Phase 0

Requirements
------------
- Python 3.11+ (tested with 3.14)

Setup
-----
Create and activate a virtual environment, then install test dependencies.

Windows (PowerShell):
	python -m venv .venv
	.venv\Scripts\Activate.ps1
	python -m pip install -U pip
	python -m pip install pytest

Run
---
Start the CLI:
	python run_ace.py

Useful commands:
- help
- status
- det on|off
- read <file>
- list <dir>
- tools
- llm <prompt>
- quit

Deterministic Mode
------------------
Deterministic mode fixes the random seed and forces LLM temperature to 0.0.
Use the CLI command:
	det on

Testing
-------
Run the tests:
	python -m pytest tests/ -v

Notes
-----
- Logs are written to logs/system.log
- The mock LLM returns a deterministic canned response

