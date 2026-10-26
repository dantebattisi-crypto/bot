"""Redis connection and runtime settings (editable from the admin panel)."""
import html
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import redis

from config import REFERRAL_MESSAGE, REFERRAL_HOUR, REFERRAL_INTERVAL_DAYS, UK_TZ

r = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

CHATS_KEY = "bot:chats"
REFERRAL_LAST_SENT_KEY = "bot:referral:last_sent"

SETTINGS_KEY = "bot:settings"                      # hash
REFERRAL_TEXT_KEY = "bot:settings:referral_html"   # string (HTML)
OWN_POSTS_KEY = "bot:own_channel_posts"            # set of channel message_ids posted by the bot

DEFAULTS = {
    "relay_enabled": "1",       # пересылка постов из канала в чаты
    "referral_enabled": "1",    # реферальное напоминание
    "referral_interval_days": str(REFERRAL_INTERVAL_DAYS),
    "referral_hour": str(REFERRAL_HOUR),
}

INTERVAL_RANGE = (1, 90)
HOUR_RANGE = (0, 23)


def get_setting(name: str) -> str:
    val = r.hget(SETTINGS_KEY, name)
    return DEFAULTS[name] if val is None else val


def set_setting(name: str, value) -> None:
    if name not in DEFAULTS:
        raise KeyError(name)
    r.hset(SETTINGS_KEY, name, str(value))


def get_flag(name: str) -> bool:
    return get_setting(name) == "1"


def set_flag(name: str, on: bool) -> None:
    set_setting(name, "1" if on else "0")


def get_int(name: str) -> int:
    try:
        return int(get_setting(name))
    except ValueError:
        return int(DEFAULTS[name])


def relay_enabled() -> bool:
    return get_flag("relay_enabled")


def referral_enabled() -> bool:
    return get_flag("referral_enabled")


def referral_interval() -> int:
    return get_int("referral_interval_days")


def referral_hour() -> int:
    return get_int("referral_hour")


def referral_html() -> str:
    """Referral text as Telegram HTML. Falls back to the default from config."""
    return r.get(REFERRAL_TEXT_KEY) or html.escape(REFERRAL_MESSAGE, quote=False)


def set_referral_html(value: str | None) -> None:
    if value:
        r.set(REFERRAL_TEXT_KEY, value)
    else:
        r.delete(REFERRAL_TEXT_KEY)


def referral_is_custom() -> bool:
    return r.exists(REFERRAL_TEXT_KEY) == 1


def chats_count() -> int:
    return r.scard(CHATS_KEY)


def referral_last_sent() -> str | None:
    return r.get(REFERRAL_LAST_SENT_KEY)


def referral_next_send(now: datetime | None = None) -> datetime:
    """When the daily job will actually send next (ignores the on/off flag)."""
    tz = ZoneInfo(UK_TZ)
    now = now or datetime.now(tz)
    hour = referral_hour()
    first = datetime.combine(now.date(), time(hour), tzinfo=tz)
    if first <= now:
        first += timedelta(days=1)
    last = referral_last_sent()
    if not last:
        return first
    due = datetime.combine(
        datetime.fromisoformat(last).date() + timedelta(days=referral_interval()),
        time(hour), tzinfo=tz,
    )
    return max(due, first)


def mark_own_channel_post(message_id: int) -> None:
    r.sadd(OWN_POSTS_KEY, message_id)
    r.expire(OWN_POSTS_KEY, 60 * 60 * 24 * 7)


def is_own_channel_post(message_id: int) -> bool:
    return r.sismember(OWN_POSTS_KEY, str(message_id))
