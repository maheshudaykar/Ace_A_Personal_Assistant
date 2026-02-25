"""Unit tests for ace_tools.registry module."""

import pytest  # type: ignore[import-not-found]
from ace_tools.registry import Tool, ToolRegistry, get_tool_registry, reset_tool_registry


class TestTool:
    """Test Tool dataclass."""
    
    def test_tool_creation(self):
        """Test tool creation."""
        def dummy_func(x: int) -> int:
            return x * 2
        
        tool = Tool(
            name="double",
            description="Double a number",
            func=dummy_func,
            parameters={"x": "int"}
        )
        
        assert tool.name == "double"
        assert tool.description == "Double a number"
        assert tool.func == dummy_func
        assert tool.parameters == {"x": "int"}
    
    def test_tool_execute(self):
        """Test tool execution."""
        def add(a: int, b: int) -> int:
            return a + b
        
        tool = Tool(
            name="add",
            description="Add two numbers",
            func=add,
            parameters={"a": "int", "b": "int"}
        )
        
        result = tool.execute(a=5, b=3)
        assert result == 8
    
    def test_tool_execute_with_exception(self):
        """Test tool execution with exception."""
        def bad_func() -> None:
            raise ValueError("Bad function")
        
        tool = Tool(
            name="bad",
            description="Bad function",
            func=bad_func,
            parameters={}
        )
        
        with pytest.raises(ValueError, match="Bad function"):  # type: ignore[attr-defined]
            tool.execute()
    
    def test_tool_execute_with_no_params(self):
        """Test tool execution with no parameters."""
        def greet() -> str:
            return "Hello"
        
        tool = Tool(
            name="greet",
            description="Greet",
            func=greet,
            parameters={}
        )
        
        result = tool.execute()
        assert result == "Hello"


class TestToolRegistry:
    """Test ToolRegistry class."""
    
    def test_registry_creation(self):
        """Test registry creation."""
        registry = ToolRegistry()
        assert registry.tools == {}
    
    def test_register_tool(self):
        """Test registering a tool."""
        registry = ToolRegistry()
        
        def dummy() -> str:
            return "dummy"
        
        tool = Tool(
            name="dummy",
            description="Dummy tool",
            func=dummy,
            parameters={}
        )
        
        registry.register(tool)
        
        assert "dummy" in registry.tools
        assert registry.tools["dummy"] == tool
    
    def test_register_duplicate_tool(self):
        """Test registering duplicate tool overwrites."""
        registry = ToolRegistry()
        
        def func1() -> int:
            return 1
        
        def func2() -> int:
            return 2
        
        tool1 = Tool("test", "Test 1", func1, {})
        tool2 = Tool("test", "Test 2", func2, {})
        
        registry.register(tool1)
        registry.register(tool2)
        
        result = registry.get_tool("test").execute()
        assert result == 2  # Second function
    
    def test_get_tool(self):
        """Test getting a tool."""
        registry = ToolRegistry()
        
        def dummy() -> str:
            return "result"
        
        tool = Tool("dummy", "Dummy tool", dummy, {})
        registry.register(tool)
        
        retrieved = registry.get_tool("dummy")
        assert retrieved == tool
    
    def test_get_nonexistent_tool(self):
        """Test getting non-existent tool raises error."""
        registry = ToolRegistry()

        with pytest.raises(ValueError, match="Tool not found"):
            registry.get_tool("nonexistent")
    
    def test_list_tools(self):
        """Test listing all tools."""
        registry = ToolRegistry()
        
        tool1 = Tool("tool1", "Tool 1", lambda: None, {})  # type: ignore
        tool2 = Tool("tool2", "Tool 2", lambda: None, {})  # type: ignore
        
        registry.register(tool1)
        registry.register(tool2)
        
        tools = registry.list_tools()
        assert len(tools) == 2
        assert "tool1" in tools
        assert "tool2" in tools
    
    def test_execute_tool(self):
        """Test executing a tool through registry."""
        registry = ToolRegistry()
        
        def add(a: int, b: int) -> int:
            return a + b
        
        tool = Tool("add", "Add", add, {"a": "int", "b": "int"})
        registry.register(tool)
        
        result = registry.execute_tool("add", a=5, b=3)
        assert result == 8
    
    def test_execute_nonexistent_tool(self):
        """Test executing non-existent tool raises error."""
        registry = ToolRegistry()

        with pytest.raises(ValueError, match="Tool not found"):
            registry.execute_tool("nonexistent")
    
    def test_execute_tool_with_error(self):
        """Test executing tool that raises error."""
        registry = ToolRegistry()
        
        def bad_func() -> None:
            raise ValueError("Bad")
        
        tool = Tool("bad", "Bad", bad_func, {})
        registry.register(tool)
        
        with pytest.raises(ValueError, match="Bad"):  # type: ignore[attr-defined]
            registry.execute_tool("bad")


class TestToolRegistrySingleton:
    """Test singleton pattern for ToolRegistry."""
    
    def test_get_registry_returns_same_instance(self):
        """Test get_tool_registry returns same instance."""
        reset_tool_registry()
        
        reg1 = get_tool_registry()
        reg2 = get_tool_registry()
        
        assert reg1 is reg2
    
    def test_reset_registry(self):
        """Test resetting registry."""
        reg1 = get_tool_registry()
        
        def dummy() -> str:
            return "test"
        
        tool = Tool("test", "Test", dummy, {})
        reg1.register(tool)
        
        assert len(reg1.list_tools()) == 1
        
        reset_tool_registry()
        reg2 = get_tool_registry()
        
        assert reg1 is not reg2
        assert len(reg2.list_tools()) == 0
    
    def test_registered_tools_persist(self):
        """Test tools registered to global registry persist."""
        reset_tool_registry()
        
        def dummy() -> str:
            return "dummy"
        
        reg = get_tool_registry()
        tool = Tool("dummy", "Dummy", dummy, {})
        reg.register(tool)
        
        # Get registry again
        reg2 = get_tool_registry()
        assert len(reg2.list_tools()) == 1
        assert "dummy" in reg2.list_tools()
