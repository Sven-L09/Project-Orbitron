"""Shared date formatting utilities for Orbitron.

This module provides German and ISO date formatting functions that are
used across multiple agents (Executor, Tester, QuickResponder, Word system).

Previously, the `months_de` dictionary was duplicated in 4+ places.
Now it's centralized here.
"""

from datetime import datetime
from typing import Optional

# German month names — used by Executor, Tester, QuickResponder, and Word system
months_de: dict[int, str] = {
    1: "Januar",
    2: "Februar",
    3: "März",
    4: "April",
    5: "Mai",
    6: "Juni",
    7: "Juli",
    8: "August",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Dezember",
}


def format_date_de(dt: Optional[datetime] = None) -> str:
    """Format a datetime as a German date string.

    Args:
        dt: The datetime to format. Defaults to now.

    Returns:
        German date string like "24. Mai 2026"
    """
    if dt is None:
        dt = datetime.now()
    return f"{dt.day}. {months_de[dt.month]} {dt.year}"


def format_date_iso(dt: Optional[datetime] = None) -> str:
    """Format a datetime as an ISO date string.

    Args:
        dt: The datetime to format. Defaults to now.

    Returns:
        ISO date string like "2026-05-24"
    """
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%d")


def current_date_de() -> str:
    """Get the current date in German format.

    Returns:
        German date string like "24. Mai 2026"
    """
    return format_date_de(datetime.now())


def current_date_iso() -> str:
    """Get the current date in ISO format.

    Returns:
        ISO date string like "2026-05-24"
    """
    return format_date_iso(datetime.now())