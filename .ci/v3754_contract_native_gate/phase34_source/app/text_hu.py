from __future__ import annotations

from datetime import datetime, timezone


_HU_MONTHS = (
    "január",
    "február",
    "március",
    "április",
    "május",
    "június",
    "július",
    "augusztus",
    "szeptember",
    "október",
    "november",
    "december",
)


def format_hu_date(value: str | datetime | None) -> str:
    """Render a stable Hungarian player-facing calendar date."""
    if value is None:
        return "—"
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return "—"
    return f"{dt.year}. {_HU_MONTHS[dt.month - 1]} {dt.day}."


def lower_first(text: str) -> str:
    value = str(text).strip()
    if not value:
        return value
    return value[0].lower() + value[1:]


def format_hu_duration(seconds: float | int, *, future: bool = False) -> str:
    """Natural compact Hungarian duration for prose that is not a live deadline."""
    total = max(0, int(round(float(seconds))))
    if total < 45:
        base = "kevesebb mint egy perc"
    elif total < 90:
        base = "1 perc"
    elif total < 3600:
        base = f"{max(1, round(total / 60))} perc"
    elif total < 5400:
        base = "1 óra"
    elif total < 86400:
        hours = total // 3600
        minutes = (total % 3600) // 60
        base = f"{hours} óra" + (f" {minutes} perc" if minutes >= 5 else "")
    elif total < 172800:
        base = "1 nap"
    else:
        days = total // 86400
        hours = (total % 86400) // 3600
        base = f"{days} nap" + (f" {hours} óra" if hours else "")
    return f"{base} múlva" if future and total > 0 else base


def _coerce_datetime(value: str | int | float | datetime | None) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_discord_timestamp(value: str | int | float | datetime | None, *, style: str = "R") -> str:
    """Live Discord timestamp. ``R`` keeps counting as the message sits on screen."""
    dt = _coerce_datetime(value)
    if dt is None:
        return "—"
    safe_style = style if style in {"t", "T", "d", "D", "f", "F", "R"} else "R"
    return f"<t:{int(dt.timestamp())}:{safe_style}>"


def format_live_deadline(value: str | int | float | datetime | None) -> str:
    """Exact clock time plus a live relative countdown for important deadlines."""
    dt = _coerce_datetime(value)
    if dt is None:
        return "—"
    stamp = int(dt.timestamp())
    return f"<t:{stamp}:F> • <t:{stamp}:R>"


def format_hu_relative(value: str | int | float | datetime | None, *, now: datetime | None = None) -> str:
    """Backward-compatible name for Yoru's live relative timestamp.

    ``now`` is retained for API compatibility but Discord itself updates the relative
    countdown client-side, so rendered messages never freeze at the send time.
    """
    _ = now
    return format_discord_timestamp(value, style="R")
