"""CLI Interface for ACE"""

import logging
from ace_kernel.state_machine import ACEState, StateMachine
from ace_kernel.deterministic_mode import DeterministicMode
from ace_core.event_bus import EventType, get_event_bus
from ace_tools import get_tool_registry, read_file, list_files
from ace_tools.llm_interface import LLMInterface

logger = logging.getLogger("ACE.CLI")


class CLI:
    """Simple CLI interface for ACE Phase 0"""
    
    def __init__(self, state_machine: StateMachine, llm_interface: LLMInterface, deterministic_mode: DeterministicMode) -> None:
        """
        Initialize CLI.
        
        Args:
            state_machine: ACE state machine
            llm_interface: LLM interface
            deterministic_mode: Deterministic mode controller
        """
        self.state_machine = state_machine
        self.llm = llm_interface
        self.deterministic_mode = deterministic_mode
        self.event_bus = get_event_bus()
        self.tool_registry = get_tool_registry()
        self.running = False
    
    def print_header(self):
        """Print welcome header."""
        print("\n" + "="*60)
        print("  🚀 ACE - Autonomous Cognitive Engine (Phase 0)")
        print("  Type 'help' for commands, 'quit' to exit")
        print("="*60 + "\n")
    
    def print_status(self):
        """Print current status."""
        state = self.state_machine.state_name
        det_mode = "🔒 ON" if self.deterministic_mode.is_deterministic() else "🔓 OFF"
        print(f"\n[{state}] Deterministic: {det_mode}")
        print("> ", end="", flush=True)
    
    def run(self):
        """Run interactive CLI."""
        self.running = True
        self.state_machine.transition(ACEState.IDLE, "CLI startup")
        self.print_header()
        
        while self.running:
            try:
                self.print_status()
                command = input().strip()
                
                if not command:
                    continue
                
                self.process_command(command)
            except KeyboardInterrupt:
                print("\n\nInterrupted by user")
                self.running = False
            except Exception as e:
                logger.error(f"CLI error: {e}")
                print(f"Error: {e}")
        
        self.shutdown()
    
    def process_command(self, command: str):
        """Process CLI command."""
        parts = command.split(maxsplit=1)
        if not parts:
            return
        
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if cmd == "help":
            self.cmd_help()
        elif cmd == "status":
            self.cmd_status()
        elif cmd == "det":
            self.cmd_deterministic(args)
        elif cmd == "read":
            self.cmd_read(args)
        elif cmd == "list":
            self.cmd_list(args)
        elif cmd == "tools":
            self.cmd_tools()
        elif cmd == "llm":
            self.cmd_llm(args)
        elif cmd == "quit":
            self.running = False
        else:
            print(f"Unknown command: {cmd} (type 'help' for commands)")
    
    def cmd_help(self):
        """Print help message."""
        print("\nAvailable commands:")
        print("  help              - Show this help message")
        print("  status            - Show current status")
        print("  det [on|off]      - Toggle deterministic mode")
        print("  read <file>       - Read a file")
        print("  list <dir>        - List files in directory")
        print("  tools             - List available tools")
        print("  llm <prompt>      - Query LLM")
        print("  quit              - Exit ACE\n")
    
    def cmd_status(self):
        """Show status."""
        state = self.state_machine.state_name
        det = "ON" if self.deterministic_mode.is_deterministic() else "OFF"
        print(f"\nState: {state}")
        print(f"Deterministic: {det}")
        print(f"Available tools: {', '.join(self.tool_registry.list_tools())}")
    
    def cmd_deterministic(self, args: str) -> None:
        """Toggle deterministic mode."""
        if args.lower() == "on":
            self.deterministic_mode.activate()
            self.llm.set_deterministic(True)
            print("✓ Deterministic mode enabled")
        elif args.lower() == "off":
            self.deterministic_mode.deactivate()
            self.llm.set_deterministic(False)
            print("✓ Deterministic mode disabled")
        else:
            self.deterministic_mode.toggle()
            self.llm.set_deterministic(self.deterministic_mode.is_deterministic())
            status = "ON" if self.deterministic_mode.is_deterministic() else "OFF"
            print(f"✓ Deterministic mode: {status}")
    
    def cmd_read(self, args: str):
        """Read a file."""
        if not args:
            print("Usage: read <file_path>")
            return
        
        self.state_machine.transition(ACEState.EXECUTING, "File read")
        try:
            content = read_file(args)
            print(f"\n--- Content of {args} ---")
            print(content[:500])  # Limit output
            if len(content) > 500:
                print(f"... ({len(content) - 500} more characters)")
        finally:
            self.state_machine.transition(ACEState.IDLE, "File read complete")
    
    def cmd_list(self, args: str):
        """List files in directory."""
        if not args:
            args = "."
        
        self.state_machine.transition(ACEState.EXECUTING, "Directory listing")
        try:
            files = list_files(args)
            print(f"\n--- Files in {args} ---")
            for f in files[:20]:  # Limit output
                print(f"  {f}")
            if len(files) > 20:
                print(f"  ... and {len(files) - 20} more")
        finally:
            self.state_machine.transition(ACEState.IDLE, "Directory listing complete")
    
    def cmd_tools(self):
        """List available tools."""
        tools = self.tool_registry.list_tools()
        print(f"\nAvailable tools: {', '.join(tools)}")
    
    def cmd_llm(self, args: str):
        """Query LLM."""
        if not args:
            print("Usage: llm <prompt>")
            return
        
        print(f"\nQuerying LLM (deterministic: {self.deterministic_mode.is_deterministic()})...")
        response = self.llm.generate(args)
        print(f"Response: {response}\n")
    
    def shutdown(self):
        """Shutdown CLI."""
        self.state_machine.transition(ACEState.SHUTDOWN, "CLI shutdown")
        self.event_bus.publish_simple(EventType.SYSTEM_SHUTDOWN, {"reason": "CLI exit"})
        print("\n👋 ACE shutting down...")
