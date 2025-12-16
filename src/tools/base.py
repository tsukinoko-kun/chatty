"""Base tool class and registry for tool calling."""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class Tool(ABC):
    """Base class for all tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for the tool."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does (shown to LLM)."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema for the tool's parameters."""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """
        Execute the tool with the given parameters.

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            String result to feed back to the LLM
        """
        pass

    def to_ollama_tool(self) -> dict:
        """Convert to Ollama tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry for managing available tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' already registered, overwriting")
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all(self) -> list[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_ollama_tools(self) -> list[dict]:
        """Get all tools in Ollama format."""
        return [tool.to_ollama_tool() for tool in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


class ToolExecutor:
    """Executes tools and handles errors."""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """
        Execute a tool by name with the given arguments.

        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments to pass to the tool

        Returns:
            Tool result as string, or error message
        """
        tool = self.registry.get(tool_name)

        if tool is None:
            error_msg = f"Unknown tool: {tool_name}"
            logger.error(error_msg)
            return f"Error: {error_msg}"

        try:
            logger.info(f"Executing tool '{tool_name}' with args: {arguments}")
            result = tool.execute(**arguments)
            logger.info(f"Tool '{tool_name}' returned: {result[:200]}...")
            return result
        except Exception as e:
            error_msg = f"Tool '{tool_name}' failed: {e}"
            logger.error(error_msg, exc_info=True)
            return f"Error: {error_msg}"
