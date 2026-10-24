"""Shared immutable day-feed Blob key contract for reader and writer."""
from datetime import date


def day_blob_key(day: date) -> str:
    if not isinstance(day,date):
        raise ValueError("valid JST date required")
    return f"race-ai/day/{day.isoformat()}.json"
