import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
SOURCE_CHANNEL_ID = int(os.environ["SOURCE_CHANNEL_ID"])

CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/yourchannel")
CHANNEL_BUTTON_TEXT = os.environ.get("CHANNEL_BUTTON_TEXT", "Go to channel")

UK_TZ = "Europe/London"

# Telegram user IDs of the team — their messages never trigger the offline auto-reply.
# Set TEAM_USER_IDS="123,456" in Railway env.
TEAM_USER_IDS = {int(x) for x in os.environ.get("TEAM_USER_IDS", "").split(",") if x.strip()}

# Offline auto-reply templates — one is picked per chat, never the same one twice in a row.
# Placeholders: {when} = "today at 10:00 UK time" / "tomorrow (Saturday) at 10:00 UK time" / "on Monday at 10:00 UK time"
#               {note} = Saturday short-window / Sunday day-off notice (empty on weekdays)
OFFLINE_MESSAGES = [
    (
        "Hi! Our team is offline right now and will be back {when}.\n\n"
        "Your message has been marked as high priority — we'll reply to you first thing when we're back.\n\n"
        "{note}\n\n"
        "If it's urgent, please describe the issue in detail now so we can start on it right away."
    ),
    (
        "Thanks for your message! We're currently offline — the team returns {when}.\n\n"
        "Your request is already in the high-priority queue, so you'll hear from us first.\n\n"
        "{note}\n\n"
        "Feel free to send any details or screenshots in the meantime — it'll speed things up."
    ),
    (
        "Hey! You've reached us outside working hours (Mon–Fri 10:00–18:00 UK time). We'll be back {when}.\n\n"
        "Don't worry — your message is flagged as high priority and will be among the first we handle.\n\n"
        "{note}\n\n"
        "If something's blocked or stuck, drop the details here now and we'll jump on it as soon as we're online."
    ),
]

# Referral reminder — runs every 3 weeks at REFERRAL_HOUR UK time
REFERRAL_HOUR = 12  # noon
REFERRAL_INTERVAL_DAYS = 21

REFERRAL_MESSAGE = (
    "🚀 Referral Program — Updated\n\n"
    "We've upgraded our referral program: higher commissions and a lower entry "
    "— now every single referral counts from day one.\n\n"
    "💶 How it works:\n\n"
    "Your friend makes their first purchase using your referral code → you get €300 "
    "(paid 7 days after purchase)\n\n"
    "After that, you earn a commission on every future purchase they make:\n"
    "— 1–5 referrals: 4%\n"
    "— 6–15 referrals: 7%\n"
    "— 16–25 referrals: 10%\n"
    "— 25+ referrals: 12%\n\n"
    "Reward can be applied to your own setup costs or paid out directly.\n"
    "Your referral must provide your code before their first purchase.\n"
    "Want your referral code? Just message us 👇"
)

SOURCE_PATTERNS = [
    r"post taken from",
    r"source[:\s]",
    r"t\.me/",
    r"https?://t\.me",
]
