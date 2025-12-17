"""Reminders tool using macOS EventKit."""

import logging
import sys
from datetime import datetime
from typing import Any, Optional

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


# Shared helper functions for reminder tools


def _get_event_store():
    """Get or create a shared EventKit event store."""
    if not EVENTKIT_AVAILABLE:
        return None
    try:
        store = EventKit.EKEventStore.alloc().init()
        # Request access
        try:
            store.requestFullAccessToRemindersWithCompletion_(lambda granted, err: None)
        except AttributeError:
            store.requestAccessToEntityType_completion_(
                EventKit.EKEntityTypeReminder, lambda granted, err: None
            )
        return store
    except Exception as e:
        logger.error(f"Failed to get event store: {e}")
        return None


def _get_calendar_by_name(store, list_name: Optional[str]):
    """Get a calendar/reminder list by name, or return the default."""
    calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)

    if list_name:
        for cal in calendars:
            if cal.title() == list_name:
                return cal
        return None

    # Return default calendar for reminders
    return store.defaultCalendarForNewReminders()


def _parse_due_date(date_str: str):
    """Parse a date string into NSDateComponents."""
    if not EVENTKIT_AVAILABLE:
        return None

    try:
        # Try parsing with time first
        if " " in date_str and ":" in date_str:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            components = Foundation.NSDateComponents.alloc().init()
            components.setYear_(dt.year)
            components.setMonth_(dt.month)
            components.setDay_(dt.day)
            components.setHour_(dt.hour)
            components.setMinute_(dt.minute)
            return components
        else:
            # Parse date only
            dt = datetime.strptime(date_str.split()[0], "%Y-%m-%d")
            components = Foundation.NSDateComponents.alloc().init()
            components.setYear_(dt.year)
            components.setMonth_(dt.month)
            components.setDay_(dt.day)
            return components
    except ValueError as e:
        logger.error(f"Failed to parse date '{date_str}': {e}")
        return None


def _find_reminder_by_title(store, title: str, list_name: Optional[str] = None):
    """Find a reminder by its title."""
    import threading

    calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)

    if list_name:
        calendars = [c for c in calendars if c.title() == list_name]
        if not calendars:
            return None, f"List '{list_name}' not found"

    predicate = store.predicateForRemindersInCalendars_(calendars)

    reminders = []
    done = threading.Event()

    def completion(result):
        nonlocal reminders
        if result:
            reminders = list(result)
        done.set()

    store.fetchRemindersMatchingPredicate_completion_(predicate, completion)
    done.wait(timeout=10.0)

    # Find reminder with matching title (case-insensitive)
    title_lower = title.lower()
    for reminder in reminders:
        if reminder.title() and reminder.title().lower() == title_lower:
            return reminder, None

    return None, f"Reminder '{title}' not found"


def _priority_str_to_int(priority: str) -> int:
    """Convert priority string to EventKit priority value."""
    priority_map = {"high": 1, "medium": 5, "low": 9, "none": 0}
    return priority_map.get(priority.lower(), 0)


class CreateReminderTool(Tool):
    """Tool for creating new reminders in the system Reminders app."""

    def __init__(self):
        self._store = None
        if EVENTKIT_AVAILABLE:
            self._store = _get_event_store()

    @property
    def name(self) -> str:
        return "create_reminder"

    @property
    def description(self) -> str:
        return (
            "Create a new reminder/task in the user's system Reminders app. "
            "Use this to add new to-do items, tasks, or reminders for the user."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The title/name of the reminder.",
                },
                "list_name": {
                    "type": "string",
                    "description": (
                        "Name of the reminder list to add to. "
                        "If not specified, adds to the default list."
                    ),
                },
                "due_date": {
                    "type": "string",
                    "description": (
                        "Due date in ISO format: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'. "
                        "Examples: '2024-12-25' or '2024-12-25 14:00'."
                    ),
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes or details for the reminder.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low", "none"],
                    "description": "Priority level of the reminder.",
                },
            },
            "required": ["title"],
        }

    def execute(
        self,
        title: str,
        list_name: str = None,
        due_date: str = None,
        notes: str = None,
        priority: str = None,
    ) -> str:
        """Create a new reminder."""
        if not EVENTKIT_AVAILABLE:
            return (
                "Reminders access is not available on this system. "
                "This feature requires macOS with pyobjc-framework-EventKit installed."
            )

        if not self._store:
            return "Reminders access has not been granted. Please allow reminders access in System Preferences."

        try:
            # Get the target calendar/list
            calendar = _get_calendar_by_name(self._store, list_name)
            if list_name and not calendar:
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

            if not calendar:
                return "No default reminder list found. Please create a list in the Reminders app first."

            # Create the reminder
            reminder = EventKit.EKReminder.reminderWithEventStore_(self._store)
            reminder.setTitle_(title)
            reminder.setCalendar_(calendar)

            # Set due date if provided
            if due_date:
                components = _parse_due_date(due_date)
                if components:
                    reminder.setDueDateComponents_(components)
                else:
                    return f"Invalid date format: '{due_date}'. Use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'."

            # Set notes if provided
            if notes:
                reminder.setNotes_(notes)

            # Set priority if provided
            if priority:
                reminder.setPriority_(_priority_str_to_int(priority))

            # Save the reminder
            success, error = self._store.saveReminder_commit_error_(
                reminder, True, None
            )

            if error:
                return f"Failed to save reminder: {error}"

            result = f"Created reminder '{title}'"
            if list_name:
                result += f" in list '{list_name}'"
            else:
                result += f" in list '{calendar.title()}'"
            if due_date:
                result += f" due {due_date}"
            if priority:
                result += f" with {priority} priority"

            return result

        except Exception as e:
            logger.error(f"Error creating reminder: {e}", exc_info=True)
            return f"Error creating reminder: {e}"


class EditReminderTool(Tool):
    """Tool for editing existing reminders in the system Reminders app."""

    def __init__(self):
        self._store = None
        if EVENTKIT_AVAILABLE:
            self._store = _get_event_store()

    @property
    def name(self) -> str:
        return "edit_reminder"

    @property
    def description(self) -> str:
        return (
            "Edit an existing reminder in the user's system Reminders app. "
            "Use this to update the title, due date, notes, or priority of a reminder."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The current title of the reminder to edit.",
                },
                "list_name": {
                    "type": "string",
                    "description": (
                        "Name of the reminder list to search in. "
                        "If not specified, searches all lists."
                    ),
                },
                "new_title": {
                    "type": "string",
                    "description": "New title for the reminder.",
                },
                "new_due_date": {
                    "type": "string",
                    "description": (
                        "New due date in ISO format: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'. "
                        "Use 'none' to clear the due date."
                    ),
                },
                "new_notes": {
                    "type": "string",
                    "description": (
                        "New notes for the reminder. Use 'none' to clear notes."
                    ),
                },
                "new_priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low", "none"],
                    "description": "New priority level for the reminder.",
                },
            },
            "required": ["title"],
        }

    def execute(
        self,
        title: str,
        list_name: str = None,
        new_title: str = None,
        new_due_date: str = None,
        new_notes: str = None,
        new_priority: str = None,
    ) -> str:
        """Edit an existing reminder."""
        if not EVENTKIT_AVAILABLE:
            return (
                "Reminders access is not available on this system. "
                "This feature requires macOS with pyobjc-framework-EventKit installed."
            )

        if not self._store:
            return "Reminders access has not been granted. Please allow reminders access in System Preferences."

        # Check if any changes were requested
        if not any([new_title, new_due_date, new_notes, new_priority]):
            return "No changes specified. Provide at least one of: new_title, new_due_date, new_notes, new_priority."

        try:
            # Find the reminder
            reminder, error = _find_reminder_by_title(self._store, title, list_name)
            if error:
                return error

            changes = []

            # Update title if provided
            if new_title:
                reminder.setTitle_(new_title)
                changes.append(f"title to '{new_title}'")

            # Update due date if provided
            if new_due_date:
                if new_due_date.lower() == "none":
                    reminder.setDueDateComponents_(None)
                    changes.append("cleared due date")
                else:
                    components = _parse_due_date(new_due_date)
                    if components:
                        reminder.setDueDateComponents_(components)
                        changes.append(f"due date to '{new_due_date}'")
                    else:
                        return f"Invalid date format: '{new_due_date}'. Use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'."

            # Update notes if provided
            if new_notes:
                if new_notes.lower() == "none":
                    reminder.setNotes_(None)
                    changes.append("cleared notes")
                else:
                    reminder.setNotes_(new_notes)
                    changes.append("updated notes")

            # Update priority if provided
            if new_priority:
                reminder.setPriority_(_priority_str_to_int(new_priority))
                if new_priority.lower() == "none":
                    changes.append("cleared priority")
                else:
                    changes.append(f"priority to '{new_priority}'")

            # Save the reminder
            success, error = self._store.saveReminder_commit_error_(
                reminder, True, None
            )

            if error:
                return f"Failed to save reminder: {error}"

            return f"Updated reminder '{title}': {', '.join(changes)}"

        except Exception as e:
            logger.error(f"Error editing reminder: {e}", exc_info=True)
            return f"Error editing reminder: {e}"


class CompleteReminderTool(Tool):
    """Tool for marking reminders as complete or incomplete."""

    def __init__(self):
        self._store = None
        if EVENTKIT_AVAILABLE:
            self._store = _get_event_store()

    @property
    def name(self) -> str:
        return "complete_reminder"

    @property
    def description(self) -> str:
        return (
            "Mark a reminder as complete (done) or incomplete (not done). "
            "Use this when the user has finished a task or wants to reopen a completed task."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The title of the reminder to mark as complete/incomplete.",
                },
                "list_name": {
                    "type": "string",
                    "description": (
                        "Name of the reminder list to search in. "
                        "If not specified, searches all lists."
                    ),
                },
                "completed": {
                    "type": "boolean",
                    "description": (
                        "Whether to mark as complete (true) or incomplete (false). "
                        "Defaults to true (mark as done)."
                    ),
                },
            },
            "required": ["title"],
        }

    def execute(
        self,
        title: str,
        list_name: str = None,
        completed: bool = True,
    ) -> str:
        """Mark a reminder as complete or incomplete."""
        if not EVENTKIT_AVAILABLE:
            return (
                "Reminders access is not available on this system. "
                "This feature requires macOS with pyobjc-framework-EventKit installed."
            )

        if not self._store:
            return "Reminders access has not been granted. Please allow reminders access in System Preferences."

        try:
            # Find the reminder
            reminder, error = _find_reminder_by_title(self._store, title, list_name)
            if error:
                return error

            # Check current status
            current_status = reminder.isCompleted()
            if current_status == completed:
                status_str = "complete" if completed else "incomplete"
                return f"Reminder '{title}' is already marked as {status_str}."

            # Update completion status
            reminder.setCompleted_(completed)

            # Set or clear completion date
            if completed:
                reminder.setCompletionDate_(Foundation.NSDate.date())
            else:
                reminder.setCompletionDate_(None)

            # Save the reminder
            success, error = self._store.saveReminder_commit_error_(
                reminder, True, None
            )

            if error:
                return f"Failed to save reminder: {error}"

            if completed:
                return f"Marked reminder '{title}' as complete."
            else:
                return f"Marked reminder '{title}' as incomplete (reopened)."

        except Exception as e:
            logger.error(f"Error completing reminder: {e}", exc_info=True)
            return f"Error completing reminder: {e}"
