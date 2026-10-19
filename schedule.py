"""Working-hours schedule (UK time) and dynamic offline reply text.

Mon–Fri  10:00–18:00  — full support
Sat      10:00–11:00  — one short window (chat round + client requests)
Sun      day off
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

UK_TZ = "Europe/London"

# weekday (0=Mon) -> (open_hour, close_hour) or None for a day off
SCHEDULE = {
    0: (10, 18),
    1: (10, 18),
    2: (10, 18),
    3: (10, 18),
    4: (10, 18),
    5: (10, 11),
    6: None,
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def now_uk() -> datetime:
    return datetime.now(ZoneInfo(UK_TZ))


def is_online(now: datetime | None = None) -> bool:
    now = now or now_uk()
    window = SCHEDULE.get(now.weekday())
    if not window:
        return False
    start, end = window
    return start <= now.hour < end


def next_window(now: datetime | None = None) -> datetime:
    """Start of the next working window (today if it hasn't opened yet)."""
    now = now or now_uk()
    for offset in range(8):
        day = (now + timedelta(days=offset)).date()
        window = SCHEDULE.get(day.weekday())
        if not window:
            continue
        start = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo).replace(hour=window[0])
        if start > now:
            return start
    raise RuntimeError("schedule has no working days")


def offline_period_key(now: datetime | None = None) -> str:
    """One auto-reply per chat per offline period (= until the next window opens).
    Fri 18:00 → Sat 10:00 is one period; Sat 11:00 → Mon 10:00 is another."""
    return next_window(now).strftime("%Y-%m-%d-%H")


def _day_label(now: datetime, target: datetime) -> str:
    delta = (target.date() - now.date()).days
    if delta == 0:
        return "today"
    if delta == 1:
        return f"tomorrow ({DAY_NAMES[target.weekday()]})"
    return f"on {DAY_NAMES[target.weekday()]}"


def build_context(now: datetime | None = None) -> dict:
    """Placeholders for the offline templates."""
    now = now or now_uk()
    nxt = next_window(now)
    start, end = SCHEDULE[nxt.weekday()]
    when = f"{_day_label(now, nxt)} at {start}:00 UK time"

    if nxt.weekday() == 5:  # next window is the short Saturday one
        note = (
            f"Heads-up: on Saturdays we're online for a short window only, "
            f"{start}:00–{end}:00 UK time, for a quick round of client chats. "
            f"Full support resumes on Monday at 10:00 UK time."
        )
    elif now.weekday() in (5, 6):  # Saturday after the window, or Sunday
        note = "Sunday is our day off, so the next full working day is Monday."
    else:
        note = ""

    return {"when": when, "note": note}


def render(template: str, now: datetime | None = None) -> str:
    import re
    text = template.format(**build_context(now))
    # collapse the blank paragraph left behind when {note} is empty
    return re.sub(r"\n{3,}", "\n\n", text).strip()
