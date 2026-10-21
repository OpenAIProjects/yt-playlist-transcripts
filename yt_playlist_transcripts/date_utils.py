"""Date parsing helpers for inclusive upload-date filtering."""

import re
from datetime import date, datetime, timedelta, timezone


_RELATIVE_DAYS_RE = re.compile(r"^[+-]?\d+$")


def parse_since(value: str, today: date | None = None) -> date:
    """Parse ISO dates or day offsets from today (for example, -1 is yesterday)."""
    value = value.strip()
    today = today or date.today()
    if _RELATIVE_DAYS_RE.fullmatch(value):
        return today + timedelta(days=int(value))
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("expected YYYY-MM-DD or an integer day offset such as -1 or 0") from exc


def parse_upload_date(info: dict) -> date | None:
    """Read a yt-dlp upload/release date from flat or fully resolved metadata."""
    for key in ("upload_date", "release_date"):
        value = info.get(key)
        if not value:
            continue
        value = str(value).strip()
        try:
            if re.fullmatch(r"\d{8}", value):
                return datetime.strptime(value, "%Y%m%d").date()
            return date.fromisoformat(value[:10])
        except ValueError:
            pass

    for key in ("release_timestamp", "timestamp"):
        value = info.get(key)
        if value is not None:
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
            except (TypeError, ValueError, OverflowError, OSError):
                pass
    return None
