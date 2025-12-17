"""Tools package for LLM tool calling."""

from .base import Tool, ToolExecutor, ToolRegistry
from .calendar import CalendarTool
from .reminders import (
    CompleteReminderTool,
    CreateReminderTool,
    EditReminderTool,
    RemindersTool,
)

__all__ = [
    "Tool",
    "ToolRegistry",
    "ToolExecutor",
    "CalendarTool",
    "RemindersTool",
    "CreateReminderTool",
    "EditReminderTool",
    "CompleteReminderTool",
]


def create_default_registry() -> ToolRegistry:
    """Create a registry with all default tools."""
    registry = ToolRegistry()
    registry.register(CalendarTool())
    registry.register(RemindersTool())
    registry.register(CreateReminderTool())
    registry.register(EditReminderTool())
    registry.register(CompleteReminderTool())
    return registry
