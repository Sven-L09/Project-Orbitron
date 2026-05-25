"""Google Calendar Service for Orbitron.

Provides CRUD operations for Google Calendar events using the Google Calendar API.
Supports:
- Listing upcoming events
- Creating new events
- Updating existing events
- Deleting events
- Finding events by text search
- Getting free/busy information
- Natural language date parsing (German)
- Conflict detection before creating events

Uses the Google Calendar API v3 with API key authentication for read operations
and OAuth2 service account for write operations.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Optional

import requests

from OrbitronUtils.dates import months_de as _months_de_int_to_str

logger = logging.getLogger("OrbitronCalendar")


# German month names for natural language date parsing (extended with abbreviations)
# Maps German month names (lowercase) to month numbers
MONTHS_DE = {
    "januar": 1, "jan": 1, "jänner": 1,
    "februar": 2, "feb": 2, "feber": 2,
    "märz": 3, "mar": 3, "maerz": 3,
    "april": 4, "apr": 4,
    "mai": 5, "may": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10, "oct": 10,
    "november": 11, "nov": 11,
    "dezember": 12, "dez": 12, "dec": 12,
}

WEEKDAYS_DE = {
    "montag": 0, "mo": 0, "mon": 0,
    "dienstag": 1, "di": 1, "die": 1, "tue": 1,
    "mittwoch": 2, "mi": 2, "mit": 2, "wed": 2,
    "donnerstag": 3, "do": 3, "don": 3, "thu": 3,
    "freitag": 4, "fr": 4, "fre": 4, "fri": 4,
    "samstag": 5, "sa": 5, "sam": 5, "sat": 5,
    "sonntag": 6, "so": 6, "son": 6, "sun": 6,
}


def parse_natural_date(text: str, reference_date: Optional[datetime] = None) -> Optional[datetime]:
    """Parse a natural language date string (German and English) into a datetime.

    Supports:
    - "morgen", "übermorgen", "heute"
    - "nächste Woche", "nächsten Montag"
    - "22. Mai 2026", "22.5.2026", "2026-05-22"
    - "morgen um 15 Uhr", "heute um 15:30"
    - "next Monday", "tomorrow", "today"
    - "in 3 Tagen", "in 2 Wochen"

    Args:
        text: Natural language date string
        reference_date: Reference date for relative calculations (defaults to now)

    Returns:
        Parsed datetime, or None if parsing fails
    """
    if not text:
        return None

    text = text.strip().lower()
    now = reference_date or datetime.now()

    # Try ISO format first: YYYY-MM-DD
    iso_match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if iso_match:
        try:
            return datetime(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            pass

    # Try German date format: DD.MM.YYYY or DD.MM.YY
    de_date_match = re.match(r"(\d{1,2})\.?\s*(\d{1,2})\.?\s*(\d{2,4})?", text)
    if de_date_match and not text.startswith(("20", "19")):
        try:
            day = int(de_date_match.group(1))
            month = int(de_date_match.group(2))
            year_str = de_date_match.group(3)
            year = int(year_str) if year_str else now.year
            if year < 100:
                year += 2000
            return datetime(year, month, day)
        except ValueError:
            pass

    # Try German date with month name: "22. Mai 2026", "22 Mai"
    de_month_match = re.match(r"(\d{1,2})\.?\s+(\w+)\s*(\d{4})?", text)
    if de_month_match:
        day = int(de_month_match.group(1))
        month_name = de_month_match.group(2).lower()
        year_str = de_month_match.group(3)
        if month_name in MONTHS_DE:
            month = MONTHS_DE[month_name]
            year = int(year_str) if year_str else now.year
            try:
                return datetime(year, month, day)
            except ValueError:
                pass

    # Relative dates
    if text in ("heute", "today"):
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    if text in ("morgen", "tomorrow"):
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)

    if text in ("übermorgen", "übermorgen", "day after tomorrow"):
        day_after = now + timedelta(days=2)
        return day_after.replace(hour=0, minute=0, second=0, microsecond=0)

    # "in X Tagen/Wochen"
    in_match = re.match(r"in\s+(\d+)\s+(tag|tagen|woche|wochen|day|days|week|weeks)", text)
    if in_match:
        amount = int(in_match.group(1))
        unit = in_match.group(2)
        if unit in ("tag", "tagen", "day", "days"):
            target = now + timedelta(days=amount)
        elif unit in ("woche", "wochen", "week", "weeks"):
            target = now + timedelta(weeks=amount)
        else:
            target = now + timedelta(days=amount)
        return target.replace(hour=0, minute=0, second=0, microsecond=0)

    # "nächsten Montag", "next Monday"
    next_day_match = re.match(r"(nächsten?|next)\s+(\w+)", text)
    if next_day_match:
        day_name = next_day_match.group(2).lower()
        target_weekday = WEEKDAYS_DE.get(day_name)
        if target_weekday is not None:
            days_ahead = (target_weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # Next week's same day
            target = now + timedelta(days=days_ahead)
            return target.replace(hour=0, minute=0, second=0, microsecond=0)

    # Time extraction: "um 15 Uhr", "um 15:30", "at 3pm"
    time_match = re.search(r"(?:um|at)\s+(\d{1,2})(?::(\d{2}))?\s*(?:uhr|pm|am|h)?", text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        # Handle PM
        if "pm" in text and hour < 12:
            hour += 12
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    return None


def parse_natural_datetime(text: str, reference_date: Optional[datetime] = None) -> tuple[Optional[datetime], Optional[datetime]]:
    """Parse a natural language date+time string and return (start, end) datetimes.

    If only a date is specified, returns (date 00:00, date 23:59).
    If a time is specified, returns (datetime, datetime + 1 hour).

    Args:
        text: Natural language date/time string
        reference_date: Reference date for relative calculations (defaults to now)

    Returns:
        Tuple of (start_datetime, end_datetime), or (None, None) if parsing fails
    """
    parsed = parse_natural_date(text, reference_date)
    if parsed is None:
        return None, None

    # Check if a specific time was mentioned
    time_match = re.search(r"(?:um|at)\s+(\d{1,2})(?::(\d{2}))?\s*(?:uhr|pm|am|h)?", text.lower())
    if time_match:
        # Specific time was given — default duration is 1 hour
        end = parsed + timedelta(hours=1)
        return parsed, end
    else:
        # Only date was given — full day event
        start = parsed
        end = parsed + timedelta(days=1) - timedelta(seconds=1)
        return start, end


class CalendarService:
    """Google Calendar API client for Orbitron.

    Uses the Google Calendar API v3 REST endpoints.
    IMPORTANT: Google Calendar API v3 requires OAuth2 (Service Account) for ALL operations.
    API keys alone are NOT supported by this API — they will return 401 errors.
    
    Setup:
    1. Create a Google Cloud project and enable the Calendar API
    2. Create a Service Account and download the JSON credentials
    3. Share your Google Calendar with the service account email
    4. Set GOOGLE_CALENDAR_CREDENTIALS in .env to the path of the JSON file
    """

    BASE_URL = "https://www.googleapis.com/calendar/v3"

    def __init__(
        self,
        api_key: Optional[str] = None,
        calendar_id: str = "primary",
        credentials_path: Optional[str] = None,
    ):
        """Initialize the Calendar Service.

        Args:
            api_key: Google Calendar API key (NOTE: API keys alone don't work with
                     Calendar API v3 — OAuth2 service account is required).
                     Falls back to GOOGLE_CALENDAR_API_KEY env var.
            calendar_id: Calendar ID to use (default: 'primary').
                         Use email address for specific calendars.
            credentials_path: Path to OAuth2 service account credentials JSON file.
                              Falls back to GOOGLE_CALENDAR_CREDENTIALS env var.
        """
        self.api_key = api_key or os.getenv("GOOGLE_CALENDAR_API_KEY", "")
        self.calendar_id = calendar_id
        self.credentials_path = credentials_path or os.getenv("GOOGLE_CALENDAR_CREDENTIALS")

        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

        # Try to load service account credentials
        self._service_account_info: Optional[dict[str, Any]] = None
        if self.credentials_path:
            self._load_service_account()

        # Determine authentication mode
        self._auth_mode = "none"
        if self._service_account_info:
            self._auth_mode = "oauth2"
        elif self.api_key:
            self._auth_mode = "api_key"
            logger.warning(
                "[CalendarService] API key mode detected. Note: Google Calendar API v3 "
                "does NOT support API keys — OAuth2 service account credentials are required. "
                "Set GOOGLE_CALENDAR_CREDENTIALS in .env to a service account JSON file."
            )

        logger.info(
            "[CalendarService] Initialized (calendar_id=%s, auth_mode=%s, api_key=%s, has_credentials=%s)",
            self.calendar_id,
            self._auth_mode,
            "set" if self.api_key else "not set",
            "yes" if self._service_account_info else "no",
        )

    def _load_service_account(self) -> None:
        """Load service account credentials from JSON file."""
        try:
            from pathlib import Path
            cred_path = Path(self.credentials_path)
            if cred_path.exists():
                with open(cred_path, "r", encoding="utf-8") as f:
                    self._service_account_info = json.load(f)
                logger.info("[CalendarService] Loaded service account credentials from %s", cred_path)
            else:
                logger.warning("[CalendarService] Credentials file not found: %s", cred_path)
        except Exception as e:
            logger.error("[CalendarService] Failed to load service account: %s", e)

    def _get_access_token(self) -> Optional[str]:
        """Get an OAuth2 access token using service account credentials.

        Uses JWT grant type for service account authentication.
        Falls back to API key for read-only operations.
        """
        if not self._service_account_info:
            return None

        # Check if we have a valid cached token
        if self._access_token and self._token_expiry:
            if datetime.now() < self._token_expiry - timedelta(minutes=5):
                return self._access_token

        try:
            import jwt
            import time

            now = int(time.time())
            payload = {
                "iss": self._service_account_info["client_email"],
                "scope": "https://www.googleapis.com/auth/calendar",
                "aud": "https://oauth2.googleapis.com/token",
                "iat": now,
                "exp": now + 3600,
            }

            signed_jwt = jwt.encode(
                payload,
                self._service_account_info["private_key"],
                algorithm="RS256",
            )

            response = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": signed_jwt,
                },
                timeout=30,
            )

            if response.status_code == 200:
                token_data = response.json()
                self._access_token = token_data["access_token"]
                self._token_expiry = datetime.now() + timedelta(seconds=token_data.get("expires_in", 3600))
                logger.info("[CalendarService] Obtained OAuth2 access token")
                return self._access_token
            else:
                logger.error("[CalendarService] Failed to get access token: %s", response.text)
                # Invalidate cached token on failure to prevent reuse of expired token
                self._access_token = None
                self._token_expiry = None
                return None

        except ImportError:
            logger.warning("[CalendarService] PyJWT not installed — write operations will use API key (may fail)")
            return None
        except Exception as e:
            logger.error("[CalendarService] Error getting access token: %s", e)
            # Invalidate cached token on any error to prevent reuse of stale credentials
            self._access_token = None
            self._token_expiry = None
            return None

    def _api_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        use_auth: bool = False,
    ) -> dict[str, Any]:
        """Make an authenticated request to the Google Calendar API.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            endpoint: API endpoint path (e.g., '/calendars/primary/events')
            params: Query parameters
            data: Request body (for POST/PUT/PATCH)
            use_auth: If True, use OAuth2 token; if False, use API key

        Returns:
            API response as dict
        """
        url = f"{self.BASE_URL}{endpoint}"

        params = dict(params or {})
        headers = {"Content-Type": "application/json"}

        # Pre-check: Ensure we have authentication before making the API call
        if use_auth:
            token = self._get_access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            elif self.api_key:
                # Fall back to API key (will fail for write operations)
                logger.warning("[CalendarService] No OAuth2 token available, falling back to API key")
                params["key"] = self.api_key
            else:
                # No authentication at all — return clear error instead of 403
                return {
                    "ok": False,
                    "error": (
                        "Google Calendar API nicht konfiguriert. "
                        "Die Google Calendar API v3 erfordert OAuth2 Service Account Credentials. "
                        "Bitte setze GOOGLE_CALENDAR_CREDENTIALS in der .env-Datei auf den Pfad zur Service Account JSON. "
                        "Anleitung: https://developers.google.com/calendar/api/quickstart/python"
                    ),
                    "status_code": 403,
                    "auth_mode": self._auth_mode,
                }
        else:
            if self._service_account_info:
                # Use OAuth2 token for all operations
                token = self._get_access_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                else:
                    return {
                        "ok": False,
                        "error": (
                            "Google Calendar API: OAuth2 Token konnte nicht abgerufen werden. "
                            "Prüfe die Service Account Credentials in GOOGLE_CALENDAR_CREDENTIALS."
                        ),
                        "status_code": 401,
                        "auth_mode": self._auth_mode,
                    }
            elif self.api_key:
                # API key mode — will likely fail with 401 for Calendar API v3
                # but try anyway in case the API changes
                logger.warning(
                    "[CalendarService] Using API key for read operation. "
                    "Note: Google Calendar API v3 typically requires OAuth2."
                )
                params["key"] = self.api_key
            else:
                # No authentication at all — return clear error instead of 403
                return {
                    "ok": False,
                    "error": (
                        "Google Calendar API nicht konfiguriert. "
                        "Die Google Calendar API v3 erfordert OAuth2 Service Account Credentials. "
                        "Bitte setze GOOGLE_CALENDAR_CREDENTIALS in der .env-Datei auf den Pfad zur Service Account JSON. "
                        "Anleitung: https://developers.google.com/calendar/api/quickstart/python"
                    ),
                    "status_code": 403,
                    "auth_mode": self._auth_mode,
                }

        try:
            response = requests.request(
                method=method,
                url=url,
                params=params,
                json=data,
                headers=headers,
                timeout=30,
            )

            if response.status_code in (200, 201, 204):
                if response.status_code == 204:
                    return {"ok": True, "status": "deleted"}
                return response.json()
            else:
                error_data = {}
                try:
                    error_data = response.json()
                except Exception:
                    error_data = {"message": response.text}

                error_msg = error_data.get("error", {}).get("message", response.text)
                status_code = response.status_code

                # Provide user-friendly error messages for common auth issues
                if status_code == 400:
                    error_detail = (
                        f"Bad request: {error_msg}. This usually means the request parameters are invalid "
                        "or the calendar ID is incorrect. For private calendars, OAuth2 credentials "
                        "are required — set GOOGLE_CALENDAR_CREDENTIALS in .env."
                    )
                elif status_code == 401:
                    error_detail = (
                        "Authentication required. The Google Calendar API needs OAuth2 credentials "
                        "for private calendars. Set GOOGLE_CALENDAR_CREDENTIALS in .env to a path "
                        "to a service account JSON file, or use a public calendar ID."
                    )
                elif status_code == 403:
                    error_detail = (
                        "Access denied. The service account does not have permission to access "
                        "this calendar. Share the calendar with the service account email address."
                    )
                elif status_code == 404:
                    error_detail = (
                        f"Calendar or event not found at endpoint '{endpoint}'. Make sure the calendar ID is correct "
                        "and the calendar is shared with the service account."
                    )
                else:
                    error_detail = error_msg

                logger.error(
                    "[CalendarService] API error %d: %s",
                    status_code,
                    error_msg[:200],
                )
                return {
                    "ok": False,
                    "error": error_detail,
                    "status_code": status_code,
                }

        except requests.exceptions.Timeout:
            return {"ok": False, "error": "Request timed out"}
        except requests.exceptions.ConnectionError:
            return {"ok": False, "error": "Connection error — check internet connection"}
        except Exception as e:
            logger.error("[CalendarService] Request failed: %s", e)
            return {"ok": False, "error": str(e)}

    # ========== Read Operations (API Key) ==========

    def list_calendars(self) -> dict[str, Any]:
        """List all calendars the user has access to.

        Returns:
            Dict with 'items' containing calendar list entries.
        """
        result = self._api_request("GET", "/users/me/calendarList")
        if "error" in result and "ok" in result and not result["ok"]:
            return result
        return {"ok": True, "calendars": result.get("items", [])}

    def get_upcoming_events(
        self,
        max_results: int = 10,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        calendar_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get upcoming events from the calendar.

        Args:
            max_results: Maximum number of events to return (1-2500)
            time_min: Start time in RFC3339 format (defaults to now)
            time_max: End time in RFC3339 format (optional)
            calendar_id: Calendar ID (defaults to self.calendar_id)

        Returns:
            Dict with 'events' containing event list.
        """
        cal_id = calendar_id or self.calendar_id

        params: dict[str, Any] = {
            "maxResults": min(max_results, 2500),
            "singleEvents": True,
            "orderBy": "startTime",
        }

        if time_min:
            params["timeMin"] = time_min
        else:
            # Default to now in RFC 3339 format with timezone
            # datetime.now() has no tz info, so %z produces empty string.
            # Use utcnow + Z suffix for reliable RFC 3339 compliance.
            params["timeMin"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        if time_max:
            params["timeMax"] = time_max

        result = self._api_request(
            "GET",
            f"/calendars/{cal_id}/events",
            params=params,
        )

        if isinstance(result, dict) and result.get("ok") is False:
            return result

        events = result.get("items", [])
        formatted_events = [self._format_event(e) for e in events]

        return {
            "ok": True,
            "events": formatted_events,
            "count": len(formatted_events),
        }

    def get_event(self, event_id: str, calendar_id: Optional[str] = None) -> dict[str, Any]:
        """Get a specific event by ID.

        Args:
            event_id: The event ID
            calendar_id: Calendar ID (defaults to self.calendar_id)

        Returns:
            Dict with event details.
        """
        cal_id = calendar_id or self.calendar_id
        result = self._api_request("GET", f"/calendars/{cal_id}/events/{event_id}")

        if isinstance(result, dict) and result.get("ok") is False:
            return result

        return {"ok": True, "event": self._format_event(result)}

    def search_events(
        self,
        query: str,
        max_results: int = 10,
        time_min: Optional[str] = None,
        calendar_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Search for events matching a text query.

        Args:
            query: Text to search for in event titles and descriptions
            max_results: Maximum number of results
            time_min: Start time in RFC3339 format (defaults to now)
            calendar_id: Calendar ID (defaults to self.calendar_id)

        Returns:
            Dict with matching events.
        """
        cal_id = calendar_id or self.calendar_id

        params: dict[str, Any] = {
            "q": query,
            "maxResults": min(max_results, 2500),
            "singleEvents": True,
            "orderBy": "startTime",
        }

        if time_min:
            params["timeMin"] = time_min
        else:
            params["timeMin"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        result = self._api_request(
            "GET",
            f"/calendars/{cal_id}/events",
            params=params,
        )

        if isinstance(result, dict) and result.get("ok") is False:
            return result

        events = result.get("items", [])
        formatted_events = [self._format_event(e) for e in events]

        return {
            "ok": True,
            "events": formatted_events,
            "count": len(formatted_events),
            "query": query,
        }

    def get_events_for_date(
        self,
        date: str,
        calendar_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get all events for a specific date.

        Args:
            date: Date in YYYY-MM-DD format
            calendar_id: Calendar ID (defaults to self.calendar_id)

        Returns:
            Dict with events for the specified date.
        """
        try:
            start = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return {"ok": False, "error": f"Invalid date format: {date}. Use YYYY-MM-DD."}

        end = start + timedelta(days=1)

        return self.get_upcoming_events(
            max_results=50,
            time_min=start.strftime("%Y-%m-%dT00:00:00+00:00"),
            time_max=end.strftime("%Y-%m-%dT00:00:00+00:00"),
            calendar_id=calendar_id,
        )

    def get_free_busy(
        self,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        calendar_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Check free/busy status for a time range.

        Args:
            time_min: Start time in RFC3339 format (defaults to now)
            time_max: End time in RFC3339 format (defaults to 24h from now)
            calendar_id: Calendar ID (defaults to self.calendar_id)

        Returns:
            Dict with busy periods.
        """
        cal_id = calendar_id or self.calendar_id

        if not time_min:
            time_min = datetime.utcnow().isoformat() + "Z"
        if not time_max:
            time_max = (datetime.utcnow() + timedelta(hours=24)).isoformat() + "Z"

        data = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": cal_id}],
        }

        result = self._api_request(
            "POST",
            "/freeBusy",
            data=data,
            use_auth=True,
        )

        if isinstance(result, dict) and result.get("ok") is False:
            return result

        calendars = result.get("calendars", {})
        busy_periods = calendars.get(cal_id, {}).get("busy", [])

        return {
            "ok": True,
            "calendar_id": cal_id,
            "busy_periods": busy_periods,
            "count": len(busy_periods),
        }

    # ========== Write Operations (OAuth2 Required) ==========

    def create_event(
        self,
        summary: str,
        start_time: str,
        end_time: str,
        description: str = "",
        location: str = "",
        timezone: str = "Europe/Berlin",
        reminders: Optional[dict[str, Any]] = None,
        attendees: Optional[list[str]] = None,
        calendar_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new calendar event.

        Args:
            summary: Event title/summary
            start_time: Start time in RFC3339 format (e.g., "2026-05-22T10:00:00+02:00")
            end_time: End time in RFC3339 format (e.g., "2026-05-22T11:00:00+02:00")
            description: Event description (optional)
            location: Event location (optional)
            timezone: Timezone (default: Europe/Berlin)
            reminders: Reminder settings, e.g., {"useDefault": True} or {"overrides": [{"method": "popup", "minutes": 30}]}
            attendees: List of attendee email addresses (optional)
            calendar_id: Calendar ID (defaults to self.calendar_id)

        Returns:
            Dict with created event details.
        """
        cal_id = calendar_id or self.calendar_id

        event_data: dict[str, Any] = {
            "summary": summary,
            "start": {
                "dateTime": start_time,
                "timeZone": timezone,
            },
            "end": {
                "dateTime": end_time,
                "timeZone": timezone,
            },
        }

        if description:
            event_data["description"] = description
        if location:
            event_data["location"] = location
        if reminders:
            event_data["reminders"] = reminders
        else:
            event_data["reminders"] = {"useDefault": True}
        if attendees:
            event_data["attendees"] = [{"email": email} for email in attendees]

        result = self._api_request(
            "POST",
            f"/calendars/{cal_id}/events",
            data=event_data,
            use_auth=True,
        )

        if isinstance(result, dict) and result.get("ok") is False:
            return result

        return {
            "ok": True,
            "event": self._format_event(result),
            "event_id": result.get("id"),
            "html_link": result.get("htmlLink"),
        }

    def update_event(
        self,
        event_id: str,
        summary: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        timezone: Optional[str] = None,
        calendar_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update an existing calendar event.

        Only the fields that are provided will be updated.

        Args:
            event_id: The event ID to update
            summary: New event title (optional)
            start_time: New start time in RFC3339 format (optional)
            end_time: New end time in RFC3339 format (optional)
            description: New description (optional)
            location: New location (optional)
            timezone: New timezone (optional, default: Europe/Berlin)
            calendar_id: Calendar ID (defaults to self.calendar_id)

        Returns:
            Dict with updated event details.
        """
        cal_id = calendar_id or self.calendar_id
        tz = timezone or "Europe/Berlin"

        # First, get the current event to preserve unchanged fields
        current = self._api_request("GET", f"/calendars/{cal_id}/events/{event_id}")
        if isinstance(current, dict) and current.get("ok") is False:
            return current

        # Build update payload — only include changed fields
        event_data: dict[str, Any] = {}

        if summary is not None:
            event_data["summary"] = summary
        else:
            event_data["summary"] = current.get("summary", "")

        if start_time is not None or end_time is not None:
            current_start = current.get("start", {})
            current_end = current.get("end", {})

            event_data["start"] = {
                "dateTime": start_time or current_start.get("dateTime", ""),
                "timeZone": tz,
            }
            event_data["end"] = {
                "dateTime": end_time or current_end.get("dateTime", ""),
                "timeZone": tz,
            }
        else:
            # Preserve existing times
            event_data["start"] = current.get("start", {})
            event_data["end"] = current.get("end", {})

        if description is not None:
            event_data["description"] = description
        else:
            event_data["description"] = current.get("description", "")

        if location is not None:
            event_data["location"] = location
        else:
            event_data["location"] = current.get("location", "")

        # Preserve other fields
        for key in ("attendees", "reminders", "recurrence", "visibility"):
            if key in current:
                event_data[key] = current[key]

        result = self._api_request(
            "PUT",
            f"/calendars/{cal_id}/events/{event_id}",
            data=event_data,
            use_auth=True,
        )

        if isinstance(result, dict) and result.get("ok") is False:
            return result

        return {
            "ok": True,
            "event": self._format_event(result),
            "event_id": result.get("id"),
        }

    def delete_event(
        self,
        event_id: str,
        calendar_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Delete a calendar event.

        Args:
            event_id: The event ID to delete
            calendar_id: Calendar ID (defaults to self.calendar_id)

        Returns:
            Dict with success status.
        """
        cal_id = calendar_id or self.calendar_id

        result = self._api_request(
            "DELETE",
            f"/calendars/{cal_id}/events/{event_id}",
            use_auth=True,
        )

        if isinstance(result, dict) and result.get("ok") is False:
            return result

        return {"ok": True, "deleted": event_id}

    def quick_create_event(
        self,
        text: str,
        calendar_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create an event from natural language text.

        Uses Google Calendar's quickAdd endpoint which parses text like
        "Meeting with John tomorrow at 3pm".

        Args:
            text: Natural language event description
            calendar_id: Calendar ID (defaults to self.calendar_id)

        Returns:
            Dict with created event details.
        """
        cal_id = calendar_id or self.calendar_id

        params = {"text": text}

        result = self._api_request(
            "POST",
            f"/calendars/{cal_id}/events/quickAdd",
            params=params,
            use_auth=True,
        )

        if isinstance(result, dict) and result.get("ok") is False:
            return result

        return {
            "ok": True,
            "event": self._format_event(result),
            "event_id": result.get("id"),
            "html_link": result.get("htmlLink"),
        }

    # ========== Helper Methods ==========

    def _format_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Format a Google Calendar event into a cleaner dict.

        Args:
            event: Raw Google Calendar API event

        Returns:
            Formatted event dict with key fields.
        """
        start = event.get("start", {})
        end = event.get("end", {})

        # Extract date or dateTime
        start_str = start.get("dateTime") or start.get("date", "Unknown")
        end_str = end.get("dateTime") or end.get("date", "Unknown")

        formatted = {
            "id": event.get("id", ""),
            "summary": event.get("summary", "(No title)"),
            "description": event.get("description", ""),
            "location": event.get("location", ""),
            "start": start_str,
            "end": end_str,
            "timezone": start.get("timeZone", ""),
            "status": event.get("status", ""),
            "html_link": event.get("htmlLink", ""),
            "creator": event.get("creator", {}).get("email", ""),
            "attendees": [
                att.get("email", "") for att in event.get("attendees", [])
            ],
        }

        # Add recurrence info if present
        if "recurrence" in event:
            formatted["recurrence"] = event["recurrence"]

        return formatted

    def get_status(self) -> dict[str, Any]:
        """Get the status of the calendar service.

        Returns:
            Dict with service status information.
        """
        return {
            "api_key_set": bool(self.api_key),
            "calendar_id": self.calendar_id,
            "has_credentials": self._service_account_info is not None,
            "has_access_token": self._access_token is not None,
            "auth_mode": self._auth_mode,
            "note": (
                "Full access (OAuth2)" if self._auth_mode == "oauth2"
                else "Read-only (API key, public calendars only)" if self._auth_mode == "api_key"
                else "No authentication configured — set GOOGLE_CALENDAR_API_KEY or GOOGLE_CALENDAR_CREDENTIALS"
            ),
        }

    def check_conflicts(
        self,
        start_time: str,
        end_time: str,
        calendar_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Check for conflicting events in a given time range.

        Args:
            start_time: Start time in RFC3339 format (e.g., "2026-05-22T10:00:00+02:00")
            end_time: End time in RFC3339 format (e.g., "2026-05-22T11:00:00+02:00")
            calendar_id: Calendar ID (defaults to self.calendar_id)

        Returns:
            Dict with 'has_conflicts' (bool) and 'conflicts' (list of events).
        """
        # Get events in the time range
        result = self.get_upcoming_events(
            max_results=50,
            time_min=start_time,
            time_max=end_time,
            calendar_id=calendar_id,
        )

        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error", "Failed to check conflicts"),
                "has_conflicts": False,
                "conflicts": [],
            }

        events = result.get("events", [])

        # Parse the requested time range for overlap detection
        try:
            req_start = self._parse_rfc3339(start_time)
            req_end = self._parse_rfc3339(end_time)
        except (ValueError, TypeError):
            # If we can't parse, just return all events as potential conflicts
            return {
                "ok": True,
                "has_conflicts": len(events) > 0,
                "conflicts": events,
                "total_events_in_range": len(events),
            }

        # Check each event for actual time overlap
        conflicts = []
        for event in events:
            evt_start_str = event.get("start", "")
            evt_end_str = event.get("end", "")

            try:
                evt_start = self._parse_rfc3339(evt_start_str)
                evt_end = self._parse_rfc3339(evt_end_str)

                # Check for overlap: two ranges overlap if start1 < end2 AND start2 < end1
                if req_start < evt_end and evt_start < req_end:
                    conflicts.append(event)
            except (ValueError, TypeError):
                # If we can't parse the event times, include it as a potential conflict
                conflicts.append(event)

        return {
            "ok": True,
            "has_conflicts": len(conflicts) > 0,
            "conflicts": conflicts,
            "total_events_in_range": len(events),
        }

    @staticmethod
    def _parse_rfc3339(time_str: str) -> datetime:
        """Parse an RFC3339 datetime string into a datetime object.

        Handles formats like:
        - "2026-05-22T10:00:00+02:00"
        - "2026-05-22T10:00:00Z"
        - "2026-05-22T10:00:00"
        - "2026-05-22" (date only)
        """
        if not time_str:
            raise ValueError("Empty time string")

        # Remove timezone offset for parsing
        # Handle +02:00, -05:00, Z suffixes
        time_str = time_str.strip()

        if time_str.endswith("Z"):
            time_str = time_str[:-1]

        # Remove timezone offset (+HH:MM or -HH:MM)
        tz_match = re.search(r"[+-]\d{2}:\d{2}$", time_str)
        if tz_match:
            time_str = time_str[:tz_match.start()]

        # Try different formats
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue

        raise ValueError(f"Cannot parse time string: {time_str}")