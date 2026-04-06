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

SOURCE_PATTERNS = [
    r"post taken from",
    r"source[:\s]",
    r"t\.me/",
    r"https?://t\.me",
]
