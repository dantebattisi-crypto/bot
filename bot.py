import logging
import re
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import redis

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

from config import (
    BOT_TOKEN, SOURCE_CHANNEL_ID, SOURCE_PATTERNS,
    CHANNEL_LINK, CHANNEL_BUTTON_TEXT, OFFLINE_MESSAGE, UK_TZ,
    REFERRAL_MESSAGE, REFERRAL_HOUR, REFERRAL_INTERVAL_DAYS,
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

_redis = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

CHATS_KEY = "bot:chats"
AUTOREPLY_PREFIX = "bot:autoreply:"
REFERRAL_LAST_SENT_KEY = "bot:referral:last_sent"


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

def night_period_key() -> str:
    now = datetime.now(ZoneInfo(UK_TZ))
    if now.hour < 10:
        return str((now - timedelta(days=1)).date())
    return str(now.date())


def already_replied(chat_id: int) -> bool:
    key = AUTOREPLY_PREFIX + night_period_key()
    return _redis.sismember(key, str(chat_id))


def mark_replied(chat_id: int):
    key = AUTOREPLY_PREFIX + night_period_key()
    _redis.sadd(key, str(chat_id))
    _redis.expire(key, 60 * 60 * 48)


def is_offline_hours() -> bool:
    hour = datetime.now(ZoneInfo(UK_TZ)).hour
    return hour >= 18 or hour < 10


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

    # Ignore messages from the bot itself
    if update.effective_user and update.effective_user.id == context.bot.id:
        return

    if not is_offline_hours():
        return

    chat_id = update.effective_chat.id
    if already_replied(chat_id):
        return

    await msg.reply_text(OFFLINE_MESSAGE)
    mark_replied(chat_id)
    logging.info(f"Sent offline auto-reply to chat {chat_id}")


async def on_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            _redis.sadd(CHATS_KEY, update.message.chat.id)
            logging.info(f"Added to chat {update.message.chat.id} ({update.message.chat.title})")


async def send_referral_reminder(context: ContextTypes.DEFAULT_TYPE):
    last_sent_str = _redis.get(REFERRAL_LAST_SENT_KEY)
    if last_sent_str:
        days_since = (datetime.now(ZoneInfo(UK_TZ)).date() - datetime.fromisoformat(last_sent_str).date()).days
        if days_since < REFERRAL_INTERVAL_DAYS:
            return

    chats = load_chats()
    for chat_id in chats:
        try:
            await context.bot.send_message(chat_id, REFERRAL_MESSAGE)
            logging.info(f"Sent referral reminder to chat {chat_id}")
        except Exception as e:
            logging.error(f"Failed to send referral reminder to {chat_id}: {e}")

    _redis.set(REFERRAL_LAST_SENT_KEY, str(datetime.now(ZoneInfo(UK_TZ)).date()))


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _redis.sadd(CHATS_KEY, update.effective_chat.id)
    await update.message.reply_text("Bot activated in this chat.")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel_post))
    # Catch all incoming messages for offline auto-reply
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_message))

    # Referral reminder — fires daily at noon UK time, but sends only every 21 days (tracked in Redis)
    app.job_queue.run_daily(
        send_referral_reminder,
        time=time(hour=REFERRAL_HOUR, minute=0, second=0, tzinfo=ZoneInfo(UK_TZ)),
    )

    logging.info("Bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
