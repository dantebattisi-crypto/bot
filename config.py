import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
SOURCE_CHANNEL_ID = int(os.environ["SOURCE_CHANNEL_ID"])

CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/yourchannel")
CHANNEL_BUTTON_TEXT = os.environ.get("CHANNEL_BUTTON_TEXT", "Go to channel")

UK_TZ = "Europe/London"
OFFLINE_MESSAGE = (
    "Hey! The whole team is most likely offline right now. "
    "Feel free to leave your question here and we'll get back to you as soon as possible!"
)

# Weekly referral reminder
# REFERRAL_DAY: 0=Monday, 1=Tuesday, ..., 6=Sunday
# REFERRAL_HOUR: hour in UK time (24h)
REFERRAL_DAY = 0   # Monday
REFERRAL_HOUR = 12  # noon

REFERRAL_MESSAGE = (
    "💰 Referral Program\n\n"
    "Every client gets a personal referral code. "
    "Share it — your referral must provide it before their first purchase.\n\n"
    "• €300 reward paid 7 days after their first purchase\n"
    "• Can be applied to your own setup costs or paid out directly\n"
    "• Ongoing commission on all future purchases:\n"
    "  — 3–14 referrals: 1.5%\n"
    "  — 15–19 referrals: 2.5%\n"
    "  — 20+ referrals: 4%\n\n"
    "Want your referral code? Just ask!"
)

SOURCE_PATTERNS = [
    r"post taken from",
    r"source[:\s]",
    r"t\.me/",
    r"https?://t\.me",
]
