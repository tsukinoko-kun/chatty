"""Calendar tool using macOS EventKit."""

import logging
import sys
from datetime import datetime, timedelta
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
            "Calendar tool will be unavailable. "
            "Install with: pip install pyobjc-framework-EventKit"
        )
else:
    EVENTKIT_AVAILABLE = False


class CalendarTool(Tool):
    """Tool for reading calendar events from the system calendar."""

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
        """Request calendar access from the user."""
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

            self._store.requestFullAccessToEventsWithCompletion_(completion_handler)

            if error[0]:
                logger.error(f"Calendar access error: {error[0]}")
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
                    EventKit.EKEntityTypeEvent, completion_handler
                )

                if error[0]:
                    logger.error(f"Calendar access error: {error[0]}")
                    return False

                return granted[0]
            except Exception as e:
                logger.error(f"Failed to request calendar access: {e}")
                return False

    @property
    def name(self) -> str:
        return "get_calendar_events"

    @property
    def description(self) -> str:
        return (
            "Get calendar events from the user's system calendar. "
            "Use this to check the user's schedule, upcoming appointments, "
            "or events on specific dates."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": (
                        "Start date for the search range in YYYY-MM-DD format. "
                        "Defaults to today if not specified."
                    ),
                },
                "end_date": {
                    "type": "string",
                    "description": (
                        "End date for the search range in YYYY-MM-DD format. "
                        "Defaults to 7 days from start_date if not specified."
                    ),
                },
            },
            "required": [],
        }

    def execute(self, start_date: str = None, end_date: str = None) -> str:
        """
        Get calendar events within the specified date range.

        Args:
            start_date: Start date (YYYY-MM-DD format), defaults to today
            end_date: End date (YYYY-MM-DD format), defaults to 7 days from start

        Returns:
            Formatted string with calendar events
        """
        if not EVENTKIT_AVAILABLE:
            return (
                "Calendar access is not available on this system. "
                "This feature requires macOS with pyobjc-framework-EventKit installed."
            )

        if not self._store:
            return "Calendar access has not been granted. Please allow calendar access in System Preferences."

        try:
            # Parse dates
            if start_date:
                start = datetime.strptime(start_date, "%Y-%m-%d")
            else:
                start = datetime.now().replace(
                    hour=0, minute=0, second=0, microsecond=0
                )

            if end_date:
                end = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59
                )
            else:
                end = start + timedelta(days=7)

            # Convert to NSDate
            start_ns = Foundation.NSDate.dateWithTimeIntervalSince1970_(
                start.timestamp()
            )
            end_ns = Foundation.NSDate.dateWithTimeIntervalSince1970_(end.timestamp())

            # Get all calendars
            calendars = self._store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)

            # Create predicate for the date range
            predicate = self._store.predicateForEventsWithStartDate_endDate_calendars_(
                start_ns, end_ns, calendars
            )

            # Fetch events
            events = self._store.eventsMatchingPredicate_(predicate)

            if not events or len(events) == 0:
                return f"No calendar events found between {start.strftime('%Y-%m-%d')} and {end.strftime('%Y-%m-%d')}."

            # Format events
            event_list = []
            for event in sorted(
                events, key=lambda e: e.startDate().timeIntervalSince1970()
            ):
                event_info = self._format_event(event)
                event_list.append(event_info)

            header = f"Calendar events from {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}:\n"
            return header + "\n".join(event_list)

        except ValueError as e:
            return f"Invalid date format: {e}. Please use YYYY-MM-DD format."
        except Exception as e:
            logger.error(f"Error fetching calendar events: {e}", exc_info=True)
            return f"Error fetching calendar events: {e}"

    def _format_event(self, event) -> str:
        """Format a single event for display."""
        title = event.title() or "Untitled"

        # Format start/end times
        start_ts = event.startDate().timeIntervalSince1970()
        end_ts = event.endDate().timeIntervalSince1970()
        start_dt = datetime.fromtimestamp(start_ts)
        end_dt = datetime.fromtimestamp(end_ts)

        if event.isAllDay():
            time_str = f"{start_dt.strftime('%Y-%m-%d')} (all day)"
        else:
            if start_dt.date() == end_dt.date():
                time_str = f"{start_dt.strftime('%Y-%m-%d %H:%M')} - {end_dt.strftime('%H:%M')}"
            else:
                time_str = f"{start_dt.strftime('%Y-%m-%d %H:%M')} - {end_dt.strftime('%Y-%m-%d %H:%M')}"

        parts = [f"- {title}: {time_str}"]

        # Add location if present
        location = event.location()
        if location:
            parts.append(f"  Location: {location}")

        # Add notes if present (truncated)
        notes = event.notes()
        if notes:
            truncated = notes[:100] + "..." if len(notes) > 100 else notes
            parts.append(f"  Notes: {truncated}")

        return "\n".join(parts)
