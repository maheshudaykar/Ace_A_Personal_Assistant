"""ACE - Autonomous Cognitive Engine - Main Entry Point"""

import sys
from pathlib import Path
from typing import Any

# Setup path for imports
sys.path.insert(0, str(Path(__file__).parent))

from ace_kernel import setup_logging, StateMachine, DeterministicMode
from ace_core import get_event_bus, EventType
from ace_interface import CLI
from ace_tools import get_tool_registry, Tool, get_llm
from ace_tools import read_file, list_files, write_file


def initialize_ace(deterministic: bool = False) -> dict[str, Any]:
    """
    Initialize ACE components for Phase 0.
    
    Args:
        deterministic: Whether to enable deterministic mode
    
    Returns:
        Dictionary of initialized components
    """
    # Setup logging
    logger = setup_logging(deterministic_mode=deterministic)
    logger.info("="*60)
    logger.info("ACE Phase 0 Initialization Starting")
    logger.info("="*60)
    
    # Initialize core components
    state_machine = StateMachine()
    deterministic_mode = DeterministicMode(enabled=deterministic)
    event_bus = get_event_bus()
    llm = get_llm(model_name="mock", deterministic=deterministic)
    
    # Initialize tools
    tool_registry = get_tool_registry()
    
    # Register built-in tools
    read_file_tool = Tool(
        name="read_file",
        description="Read contents from a file",
        func=read_file,
        parameters={"file_path": "Path to file", "encoding": "Optional: file encoding (default: utf-8)"}
    )
    tool_registry.register(read_file_tool)
    
    list_files_tool = Tool(
        name="list_files",
        description="List files in a directory",
        func=list_files,
        parameters={"directory": "Directory path"}
    )
    tool_registry.register(list_files_tool)
    
    write_file_tool = Tool(
        name="write_file",
        description="Write content to a file",
        func=write_file,
        parameters={"file_path": "Path to file", "content": "Content to write"}
    )
    tool_registry.register(write_file_tool)
    
    # Publish startup event
    event_bus.publish_simple(EventType.SYSTEM_BOOT, {
        "version": "0.1.0-alpha",
        "deterministic": deterministic,
        "phase": "Phase 0"
    })
    
    logger.info("ACE initialization complete")
    
    return {
        "state_machine": state_machine,
        "deterministic_mode": deterministic_mode,
        "event_bus": event_bus,
        "llm": llm,
        "tool_registry": tool_registry,
        "logger": logger,
    }


def main(deterministic: bool = False):
    """
    Main entry point for ACE.
    
    Args:
        deterministic: Whether to enable deterministic mode
    """
    # Initialize
    components = initialize_ace(deterministic=deterministic)
    
    # Start CLI
    cli = CLI(
        state_machine=components["state_machine"],
        llm_interface=components["llm"],
        deterministic_mode=components["deterministic_mode"],
    )
    
    cli.run()


if __name__ == "__main__":
    # Check for deterministic flag
    deterministic = "--deterministic" in sys.argv or "-det" in sys.argv
    
    try:
        main(deterministic=deterministic)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
