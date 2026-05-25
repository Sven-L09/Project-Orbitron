"""Calendar Skill for the Orbitron Orchestrator.

Provides calendar-related tools that the Orchestrator's decision agent can use
to manage Google Calendar events. These tools are registered with the
AutonomousAgent in the Orchestrator.
"""

import logging
from typing import Any, Optional

from OrbitronKernel.kernel import AgentSkill
from .calendar_service import CalendarService

logger = logging.getLogger("CalendarSkill")


class CalendarSkill(AgentSkill):
    """Skill providing Google Calendar tools for the Orchestrator.

    Tools provided:
    - calendar_list_upcoming: Get upcoming events
    - calendar_get_events_for_date: Get events for a specific date
    - calendar_search_events: Search events by text
    - calendar_create_event: Create a new event
    - calendar_update_event: Update an existing event
    - calendar_delete_event: Delete an event
    - calendar_quick_create: Create event from natural language
    - calendar_get_free_busy: Check free/busy times
    - calendar_check_conflicts: Check for scheduling conflicts before creating events
    """

    def __init__(self, calendar_service: Optional[CalendarService] = None):
        """Initialize the Calendar Skill.

        Args:
            calendar_service: Optional CalendarService instance.
                              If not provided, one will be created from env vars.
        """
        super().__init__(
            name="calendar",
            description="Google Calendar integration — manage events, check schedules, create appointments",
        )

        self.calendar_service = calendar_service or CalendarService()

        # Register all calendar tools
        self._register_tools()

        logger.info("[CalendarSkill] Initialized with %d tools", len(self._tools))

    def _register_tools(self) -> None:
        """Register all calendar tools with their schemas and handlers."""

        # --- calendar_list_upcoming ---
        self.register_tool(
            name="calendar_list_upcoming",
            schema={
                "description": "List upcoming calendar events. Returns the next N events from the user's calendar.",
                "parameters": {
                    "type": "object",
                    "required": [],
                    "properties": {
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of events to return (default: 10, max: 2500)",
                        },
                        "time_min": {
                            "type": "string",
                            "description": "Start time in ISO 8601/RFC 3339 format (e.g., '2026-05-21T00:00:00+02:00'). Defaults to now.",
                        },
                        "time_max": {
                            "type": "string",
                            "description": "End time in ISO 8601/RFC 3339 format. Optional upper bound.",
                        },
                    },
                },
            },
            handler=self._handle_list_upcoming,
        )

        # --- calendar_get_events_for_date ---
        self.register_tool(
            name="calendar_get_events_for_date",
            schema={
                "description": "Get all calendar events for a specific date. Provide the date in YYYY-MM-DD format.",
                "parameters": {
                    "type": "object",
                    "required": ["date"],
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "The date to get events for, in YYYY-MM-DD format (e.g., '2026-05-22')",
                        },
                    },
                },
            },
            handler=self._handle_get_events_for_date,
        )

        # --- calendar_search_events ---
        self.register_tool(
            name="calendar_search_events",
            schema={
                "description": "Search calendar events by text. Searches event titles and descriptions for matching text.",
                "parameters": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Text to search for in event titles and descriptions",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results (default: 10)",
                        },
                    },
                },
            },
            handler=self._handle_search_events,
        )

        # --- calendar_create_event ---
        self.register_tool(
            name="calendar_create_event",
            schema={
                "description": "Create a new calendar event. You must provide a title, start time, and end time.",
                "parameters": {
                    "type": "object",
                    "required": ["summary", "start_time", "end_time"],
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Event title/summary",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Start time in ISO 8601 format (e.g., '2026-05-22T10:00:00+02:00')",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "End time in ISO 8601 format (e.g., '2026-05-22T11:00:00+02:00')",
                        },
                        "description": {
                            "type": "string",
                            "description": "Event description (optional)",
                        },
                        "location": {
                            "type": "string",
                            "description": "Event location (optional)",
                        },
                        "timezone": {
                            "type": "string",
                            "description": "Timezone (default: Europe/Berlin)",
                        },
                        "attendees": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of attendee email addresses (optional)",
                        },
                    },
                },
            },
            handler=self._handle_create_event,
        )

        # --- calendar_update_event ---
        self.register_tool(
            name="calendar_update_event",
            schema={
                "description": "Update an existing calendar event. Provide the event ID and the fields you want to change.",
                "parameters": {
                    "type": "object",
                    "required": ["event_id"],
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "The ID of the event to update",
                        },
                        "summary": {
                            "type": "string",
                            "description": "New event title (optional)",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "New start time in ISO 8601 format (optional)",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "New end time in ISO 8601 format (optional)",
                        },
                        "description": {
                            "type": "string",
                            "description": "New description (optional)",
                        },
                        "location": {
                            "type": "string",
                            "description": "New location (optional)",
                        },
                    },
                },
            },
            handler=self._handle_update_event,
        )

        # --- calendar_delete_event ---
        self.register_tool(
            name="calendar_delete_event",
            schema={
                "description": "Delete a calendar event by its ID.",
                "parameters": {
                    "type": "object",
                    "required": ["event_id"],
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "The ID of the event to delete",
                        },
                    },
                },
            },
            handler=self._handle_delete_event,
        )

        # --- calendar_quick_create ---
        self.register_tool(
            name="calendar_quick_create",
            schema={
                "description": "Create a calendar event from natural language text. Example: 'Meeting with John tomorrow at 3pm'. Google Calendar parses the text automatically.",
                "parameters": {
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Natural language event description (e.g., 'Team meeting tomorrow at 2pm')",
                        },
                    },
                },
            },
            handler=self._handle_quick_create,
        )

        # --- calendar_get_free_busy ---
        self.register_tool(
            name="calendar_get_free_busy",
            schema={
                "description": "Check free/busy times in the calendar. Returns busy periods for a given time range.",
                "parameters": {
                    "type": "object",
                    "required": [],
                    "properties": {
                        "time_min": {
                            "type": "string",
                            "description": "Start time in ISO 8601 format (defaults to now)",
                        },
                        "time_max": {
                            "type": "string",
                            "description": "End time in ISO 8601 format (defaults to 24h from now)",
                        },
                    },
                },
            },
            handler=self._handle_get_free_busy,
        )

        # --- calendar_check_conflicts ---
        self.register_tool(
            name="calendar_check_conflicts",
            schema={
                "description": "Check if a proposed time range conflicts with existing calendar events. Use this BEFORE creating a new event to avoid double-booking.",
                "parameters": {
                    "type": "object",
                    "required": ["start_time", "end_time"],
                    "properties": {
                        "start_time": {
                            "type": "string",
                            "description": "Proposed start time in ISO 8601 format (e.g., '2026-05-22T10:00:00+02:00')",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Proposed end time in ISO 8601 format (e.g., '2026-05-22T11:00:00+02:00')",
                        },
                    },
                },
            },
            handler=self._handle_check_conflicts,
        )

    # ========== Tool Handlers ==========

    def _handle_list_upcoming(self, args: dict[str, Any]) -> str:
        """Handle calendar_list_upcoming tool call."""
        try:
            result = self.calendar_service.get_upcoming_events(
                max_results=args.get("max_results", 10),
                time_min=args.get("time_min"),
                time_max=args.get("time_max"),
            )
            return self._format_result(result)
        except Exception as e:
            logger.error("[CalendarSkill] Error listing upcoming events: %s", e)
            return self._format_result({"ok": False, "error": str(e)})

    def _handle_get_events_for_date(self, args: dict[str, Any]) -> str:
        """Handle calendar_get_events_for_date tool call."""
        try:
            result = self.calendar_service.get_events_for_date(
                date=args.get("date", ""),
            )
            return self._format_result(result)
        except Exception as e:
            logger.error("[CalendarSkill] Error getting events for date: %s", e)
            return self._format_result({"ok": False, "error": str(e)})

    def _handle_search_events(self, args: dict[str, Any]) -> str:
        """Handle calendar_search_events tool call."""
        try:
            result = self.calendar_service.search_events(
                query=args.get("query", ""),
                max_results=args.get("max_results", 10),
            )
            return self._format_result(result)
        except Exception as e:
            logger.error("[CalendarSkill] Error searching events: %s", e)
            return self._format_result({"ok": False, "error": str(e)})

    def _handle_create_event(self, args: dict[str, Any]) -> str:
        """Handle calendar_create_event tool call."""
        try:
            result = self.calendar_service.create_event(
                summary=args.get("summary", ""),
                start_time=args.get("start_time", ""),
                end_time=args.get("end_time", ""),
                description=args.get("description", ""),
                location=args.get("location", ""),
                timezone=args.get("timezone", "Europe/Berlin"),
                attendees=args.get("attendees"),
            )
            return self._format_result(result)
        except Exception as e:
            logger.error("[CalendarSkill] Error creating event: %s", e)
            return self._format_result({"ok": False, "error": str(e)})

    def _handle_update_event(self, args: dict[str, Any]) -> str:
        """Handle calendar_update_event tool call."""
        try:
            result = self.calendar_service.update_event(
                event_id=args.get("event_id", ""),
                summary=args.get("summary"),
                start_time=args.get("start_time"),
                end_time=args.get("end_time"),
                description=args.get("description"),
                location=args.get("location"),
                timezone=args.get("timezone"),
            )
            return self._format_result(result)
        except Exception as e:
            logger.error("[CalendarSkill] Error updating event: %s", e)
            return self._format_result({"ok": False, "error": str(e)})

    def _handle_delete_event(self, args: dict[str, Any]) -> str:
        """Handle calendar_delete_event tool call."""
        try:
            result = self.calendar_service.delete_event(
                event_id=args.get("event_id", ""),
            )
            return self._format_result(result)
        except Exception as e:
            logger.error("[CalendarSkill] Error deleting event: %s", e)
            return self._format_result({"ok": False, "error": str(e)})

    def _handle_quick_create(self, args: dict[str, Any]) -> str:
        """Handle calendar_quick_create tool call."""
        try:
            result = self.calendar_service.quick_create_event(
                text=args.get("text", ""),
            )
            return self._format_result(result)
        except Exception as e:
            logger.error("[CalendarSkill] Error quick creating event: %s", e)
            return self._format_result({"ok": False, "error": str(e)})

    def _handle_get_free_busy(self, args: dict[str, Any]) -> str:
        """Handle calendar_get_free_busy tool call."""
        try:
            result = self.calendar_service.get_free_busy(
                time_min=args.get("time_min"),
                time_max=args.get("time_max"),
            )
            return self._format_result(result)
        except Exception as e:
            logger.error("[CalendarSkill] Error getting free/busy: %s", e)
            return self._format_result({"ok": False, "error": str(e)})

    def _handle_check_conflicts(self, args: dict[str, Any]) -> str:
        """Handle calendar_check_conflicts tool call."""
        try:
            result = self.calendar_service.check_conflicts(
                start_time=args.get("start_time", ""),
                end_time=args.get("end_time", ""),
            )
            return self._format_result(result)
        except Exception as e:
            logger.error("[CalendarSkill] Error checking conflicts: %s", e)
            return self._format_result({"ok": False, "error": str(e)})

    def _format_result(self, result: dict[str, Any]) -> str:
        """Format a result dict as a JSON string for the LLM."""
        import json
        return json.dumps(result, ensure_ascii=False, default=str)