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
