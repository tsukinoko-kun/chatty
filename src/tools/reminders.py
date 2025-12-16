"""Reminders tool using macOS EventKit."""

import logging
import sys
from datetime import datetime
from typing import Any

from .base import Tool

logger = logging.getLogger(__name__)

# Check if we're on macOS and can use EventKit
IS_MACOS = sys.platform == "darwin"

if IS_MACOS:
    try:
        import EventKit
        import Foundation

        EVENTKIT_AVAILABLE = True
    except ImportError:
        EVENTKIT_AVAILABLE = False
        logger.warning(
            "pyobjc-framework-EventKit not installed. "
            "Reminders tool will be unavailable. "
            "Install with: pip install pyobjc-framework-EventKit"
        )
else:
    EVENTKIT_AVAILABLE = False


class RemindersTool(Tool):
    """Tool for reading reminders from the system Reminders app."""

    def __init__(self):
        self._store = None
        if EVENTKIT_AVAILABLE:
            self._init_event_store()

    def _init_event_store(self) -> None:
        """Initialize the EventKit event store."""
        try:
            self._store = EventKit.EKEventStore.alloc().init()
            # Request access (this will prompt user on first run)
            self._request_access()
        except Exception as e:
            logger.error(f"Failed to initialize EventKit store: {e}")
            self._store = None

    def _request_access(self) -> bool:
        """Request reminders access from the user."""
        if not self._store:
            return False

        # For macOS 14+, use the new API
        try:
            # Try the newer API first (macOS 14+)
            granted = [False]
            error = [None]

            def completion_handler(access_granted, err):
                granted[0] = access_granted
                error[0] = err

            self._store.requestFullAccessToRemindersWithCompletion_(completion_handler)

            if error[0]:
                logger.error(f"Reminders access error: {error[0]}")
                return False

            return granted[0]
        except AttributeError:
            # Fall back to older API
            try:
                granted = [False]
                error = [None]

                def completion_handler(access_granted, err):
                    granted[0] = access_granted
                    error[0] = err

                self._store.requestAccessToEntityType_completion_(
                    EventKit.EKEntityTypeReminder, completion_handler
                )

                if error[0]:
                    logger.error(f"Reminders access error: {error[0]}")
                    return False

                return granted[0]
            except Exception as e:
                logger.error(f"Failed to request reminders access: {e}")
                return False

    @property
    def name(self) -> str:
        return "get_reminders"

    @property
    def description(self) -> str:
        return (
            "Get reminders/tasks from the user's system Reminders app. "
            "Use this to check the user's to-do items, tasks, and reminders."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "list_name": {
                    "type": "string",
                    "description": (
                        "Name of the reminder list to fetch from. "
                        "If not specified, fetches from all lists."
                    ),
                },
                "include_completed": {
                    "type": "boolean",
                    "description": (
                        "Whether to include completed reminders. "
                        "Defaults to false (only incomplete reminders)."
                    ),
                },
            },
            "required": [],
        }

    def execute(self, list_name: str = None, include_completed: bool = False) -> str:
        """
        Get reminders from the system Reminders app.

        Args:
            list_name: Name of the list to fetch from (None for all lists)
            include_completed: Whether to include completed reminders

        Returns:
            Formatted string with reminders
        """
        if not EVENTKIT_AVAILABLE:
            return (
                "Reminders access is not available on this system. "
                "This feature requires macOS with pyobjc-framework-EventKit installed."
            )

        if not self._store:
            return "Reminders access has not been granted. Please allow reminders access in System Preferences."

        try:
            # Get calendars (reminder lists)
            calendars = self._store.calendarsForEntityType_(
                EventKit.EKEntityTypeReminder
            )

            if list_name:
                # Filter to specific list
                calendars = [c for c in calendars if c.title() == list_name]
                if not calendars:
                    available_lists = [
                        c.title()
                        for c in self._store.calendarsForEntityType_(
                            EventKit.EKEntityTypeReminder
                        )
                    ]
                    return (
                        f"Reminder list '{list_name}' not found. "
                        f"Available lists: {', '.join(available_lists)}"
                    )

            # Create predicate for reminders
            predicate = self._store.predicateForRemindersInCalendars_(calendars)

            # Fetch reminders (synchronous fetch)
            reminders = self._fetch_reminders_sync(predicate)

            if not reminders:
                if list_name:
                    return f"No reminders found in list '{list_name}'."
                return "No reminders found."

            # Filter by completion status
            if not include_completed:
                reminders = [r for r in reminders if not r.isCompleted()]

            if not reminders:
                return "No incomplete reminders found."

            # Sort by due date (items without due date last)
            def sort_key(r):
                due = r.dueDateComponents()
                if due:
                    # Create a date from components
                    year = due.year() if due.year() != 9223372036854775807 else 9999
                    month = due.month() if due.month() != 9223372036854775807 else 12
                    day = due.day() if due.day() != 9223372036854775807 else 31
                    return (0, year, month, day)
                return (1, 9999, 12, 31)

            reminders = sorted(reminders, key=sort_key)

            # Format reminders
            reminder_list = []
            for reminder in reminders:
                reminder_info = self._format_reminder(reminder)
                reminder_list.append(reminder_info)

            header = "Reminders"
            if list_name:
                header += f" from '{list_name}'"
            header += ":\n"

            return header + "\n".join(reminder_list)

        except Exception as e:
            logger.error(f"Error fetching reminders: {e}", exc_info=True)
            return f"Error fetching reminders: {e}"

    def _fetch_reminders_sync(self, predicate) -> list:
        """Fetch reminders synchronously."""
        import threading

        reminders = []
        done = threading.Event()

        def completion(result):
            nonlocal reminders
            if result:
                reminders = list(result)
            done.set()

        self._store.fetchRemindersMatchingPredicate_completion_(predicate, completion)

        # Wait for completion (with timeout)
        done.wait(timeout=10.0)
        return reminders

    def _format_reminder(self, reminder) -> str:
        """Format a single reminder for display."""
        title = reminder.title() or "Untitled"

        parts = [f"- {'[x]' if reminder.isCompleted() else '[ ]'} {title}"]

        # Add due date if present
        due_components = reminder.dueDateComponents()
        if due_components:
            year = due_components.year()
            month = due_components.month()
            day = due_components.day()

            # Check for valid components (large numbers indicate "not set")
            if year < 9000 and month < 13 and day < 32:
                due_str = f"{year:04d}-{month:02d}-{day:02d}"

                # Check for time
                hour = due_components.hour()
                minute = due_components.minute()
                if hour < 24 and minute < 60:
                    due_str += f" {hour:02d}:{minute:02d}"

                parts.append(f"  Due: {due_str}")

        # Add priority if set
        priority = reminder.priority()
        if priority > 0:
            priority_map = {1: "High", 5: "Medium", 9: "Low"}
            priority_str = priority_map.get(priority, f"Priority {priority}")
            parts.append(f"  Priority: {priority_str}")

        # Add notes if present (truncated)
        notes = reminder.notes()
        if notes:
            truncated = notes[:100] + "..." if len(notes) > 100 else notes
            parts.append(f"  Notes: {truncated}")

        # Add list name
        calendar = reminder.calendar()
        if calendar:
            parts.append(f"  List: {calendar.title()}")

        return "\n".join(parts)
