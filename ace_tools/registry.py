"""ACE Tools - Tool registry and execution"""

from dataclasses import dataclass
from typing import Callable, Any, Optional
import logging

logger = logging.getLogger("ACE.Tools")


@dataclass
class Tool:
    """Simple tool definition"""
    name: str
    description: str
    func: Callable[..., Any]
    parameters: Optional[dict[str, str]] = None  # param_name -> description
    
    def execute(self, **kwargs: Any) -> Any:
        """Execute the tool with given parameters."""
        logger.info(f"Executing tool: {self.name}")
        try:
            result = self.func(**kwargs)
            logger.info(f"Tool {self.name} completed successfully")
            return result
        except Exception as e:
            logger.error(f"Tool {self.name} failed: {e}")
            raise


class ToolRegistry:
    """Registry for ACE tools"""
    
    def __init__(self):
        self.tools: dict[str, Tool] = {}
        logger.info("ToolRegistry initialized")
    
    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self.tools[tool.name] = tool
        logger.info(f"Tool registered: {tool.name}")
    
    def get_tool(self, name: str) -> Tool:
        """Get tool by name."""
        if name not in self.tools:
            raise ValueError(f"Tool not found: {name}")
        return self.tools[name]
    
    def list_tools(self) -> list[str]:
        """List all available tools."""
        return list(self.tools.keys())
    
    def execute_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Execute a tool by name with given parameters."""
        tool = self.get_tool(tool_name)
        return tool.execute(**kwargs)


# Global tool registry instance
_global_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get or create global tool registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def reset_tool_registry():
    """Reset global tool registry (for testing)."""
    global _global_registry
    _global_registry = ToolRegistry()
