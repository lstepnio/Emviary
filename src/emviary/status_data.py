"""Defensive readers for optional status evidence, never for recovery authorization."""

import json
from datetime import UTC, datetime


def timestamp(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def json_object(value):
    if not isinstance(value, str) or len(value) > 65536:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}
