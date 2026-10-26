import logging
import random
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

from config import (
    BOT_TOKEN, SOURCE_CHANNEL_ID, SOURCE_PATTERNS,
    CHANNEL_LINK, CHANNEL_BUTTON_TEXT, OFFLINE_MESSAGES, TEAM_USER_IDS,
)
from schedule import is_online, offline_period_key, render
import admin
import store

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
# httpx logs every request URL at INFO, and Telegram URLs contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)

_redis = store.r

CHATS_KEY = store.CHATS_KEY
AUTOREPLY_PREFIX = "bot:autoreply:"
AUTOREPLY_LAST_TPL_PREFIX = "bot:autoreply:last_tpl:"


# ---------- chats storage ----------

def load_chats() -> set:
    members = _redis.smembers(CHATS_KEY)
    return {int(m) for m in members}


def save_chats(chats: set):
    pipe = _redis.pipeline()
    pipe.delete(CHATS_KEY)
    if chats:
        pipe.sadd(CHATS_KEY, *chats)
    pipe.execute()


# ---------- auto-reply tracking ----------

def already_replied(chat_id: int) -> bool:
    key = AUTOREPLY_PREFIX + offline_period_key()
    return _redis.sismember(key, str(chat_id))


def mark_replied(chat_id: int):
    key = AUTOREPLY_PREFIX + offline_period_key()
    _redis.sadd(key, str(chat_id))
    _redis.expire(key, 60 * 60 * 24 * 4)  # longest offline period is Sat 11:00 → Mon 10:00


def pick_offline_message(chat_id: int) -> str:
    """Rotate templates per chat: never the same one twice in a row."""
    last = _redis.get(AUTOREPLY_LAST_TPL_PREFIX + str(chat_id))
    choices = list(range(len(OFFLINE_MESSAGES)))
    if last is not None and len(choices) > 1:
        choices = [i for i in choices if i != int(last)]
    idx = random.choice(choices)
    _redis.set(AUTOREPLY_LAST_TPL_PREFIX + str(chat_id), idx, ex=60 * 60 * 24 * 30)
    return render(OFFLINE_MESSAGES[idx])


# ---------- handlers ----------

def strip_source(text: str | None) -> str | None:
    if not text:
        return text
    lines = text.rstrip().split("\n")
    while lines:
        last = lines[-1].strip()
        if any(re.search(p, last, re.IGNORECASE) for p in SOURCE_PATTERNS):
            lines.pop()
        else:
            break
    return "\n".join(lines).rstrip() or None


async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post
    if not post or post.chat.id != SOURCE_CHANNEL_ID:
        return

    if store.is_own_channel_post(post.message_id):
        return  # posted by the bot itself via a custom broadcast — already sent to chats

    if not store.relay_enabled():
        logging.info("Channel relay is disabled — post not broadcast.")
        return

    chats = load_chats()
    if not chats:
        logging.info("No chats to broadcast to.")
        return

    text = strip_source(post.text or post.caption)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(CHANNEL_BUTTON_TEXT, url=CHANNEL_LINK)]])

    has_media = bool(post.photo or post.video or post.animation or post.document)
    long_caption = bool(text) and len(text) > 1024
    media_caption = None if long_caption else text
    media_keyboard = None if long_caption else keyboard

    for chat_id in chats:
        try:
            if post.photo:
                await context.bot.send_photo(chat_id, post.photo[-1].file_id, caption=media_caption, reply_markup=media_keyboard)
            elif post.video:
                await context.bot.send_video(chat_id, post.video.file_id, caption=media_caption, reply_markup=media_keyboard)
            elif post.animation:
                await context.bot.send_animation(chat_id, post.animation.file_id, caption=media_caption, reply_markup=media_keyboard)
            elif post.document:
                await context.bot.send_document(chat_id, post.document.file_id, caption=media_caption, reply_markup=media_keyboard)

            if text and (long_caption or not has_media):
                await context.bot.send_message(chat_id, text, reply_markup=keyboard)
        except Exception as e:
            logging.error(f"Failed to send to chat {chat_id}: {e}")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not update.effective_chat:
        return

    # Ignore messages from the bot itself and from the team
    user = update.effective_user
    if user and (user.id == context.bot.id or user.id in TEAM_USER_IDS):
        return

    if is_online():
        return

    chat_id = update.effective_chat.id
    if already_replied(chat_id):
        return

    await msg.reply_text(pick_offline_message(chat_id))
    mark_replied(chat_id)
    logging.info(f"Sent offline auto-reply to chat {chat_id}")


async def on_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            _redis.sadd(CHATS_KEY, update.message.chat.id)
            logging.info(f"Added to chat {update.message.chat.id} ({update.message.chat.title})")


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    _redis.sadd(CHATS_KEY, chat.id)
    logging.info(f"Bot activated in chat {chat.id} ({chat.title or chat.username or 'private'})")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel_post))
    # Catch all incoming messages for offline auto-reply
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_message))

    # Owner-only admin panel (runs before the handlers above) + referral reminder job
    admin.register(app)

    logging.info("Bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
