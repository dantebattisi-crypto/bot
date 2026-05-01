import logging
import json
import re
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

from config import (
    BOT_TOKEN, SOURCE_CHANNEL_ID, SOURCE_PATTERNS,
    CHANNEL_LINK, CHANNEL_BUTTON_TEXT, OFFLINE_MESSAGE, UK_TZ,
    REFERRAL_MESSAGE, REFERRAL_DAY, REFERRAL_HOUR,
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

CHATS_FILE = "chats.json"
AUTOREPLY_FILE = "autoreply.json"


# ---------- chats storage ----------

def load_chats() -> set:
    if os.path.exists(CHATS_FILE):
        with open(CHATS_FILE) as f:
            return set(json.load(f))
    return set()


def save_chats(chats: set):
    with open(CHATS_FILE, "w") as f:
        json.dump(list(chats), f)


# ---------- auto-reply tracking ----------

def night_period_key() -> str:
    """
    Returns a string key for the current night period (18:00 → 10:00 UK).
    Periods that started yesterday evening share yesterday's date as key.
    """
    now = datetime.now(ZoneInfo(UK_TZ))
    if now.hour < 10:
        return str((now - timedelta(days=1)).date())
    return str(now.date())


def load_autoreply() -> dict:
    if os.path.exists(AUTOREPLY_FILE):
        with open(AUTOREPLY_FILE) as f:
            return json.load(f)
    return {}


def save_autoreply(data: dict):
    with open(AUTOREPLY_FILE, "w") as f:
        json.dump(data, f)


def already_replied(chat_id: int) -> bool:
    key = night_period_key()
    data = load_autoreply()
    return str(chat_id) in data.get(key, [])


def mark_replied(chat_id: int):
    key = night_period_key()
    data = load_autoreply()
    # Keep only current period to avoid file growing forever
    data = {key: data.get(key, [])}
    if str(chat_id) not in data[key]:
        data[key].append(str(chat_id))
    save_autoreply(data)


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
            chats = load_chats()
            chats.add(update.message.chat.id)
            save_chats(chats)
            logging.info(f"Added to chat {update.message.chat.id} ({update.message.chat.title})")


async def send_referral_reminder(context: ContextTypes.DEFAULT_TYPE):
    chats = load_chats()
    for chat_id in chats:
        try:
            await context.bot.send_message(chat_id, REFERRAL_MESSAGE)
            logging.info(f"Sent referral reminder to chat {chat_id}")
        except Exception as e:
            logging.error(f"Failed to send referral reminder to {chat_id}: {e}")


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chats = load_chats()
    chats.add(update.effective_chat.id)
    save_chats(chats)
    await update.message.reply_text("Bot activated in this chat.")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel_post))
    # Catch all incoming messages for offline auto-reply
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_message))

    # Weekly referral reminder — runs every Monday (REFERRAL_DAY=0) at REFERRAL_HOUR:00 UK time
    app.job_queue.run_daily(
        send_referral_reminder,
        time=datetime.now(ZoneInfo(UK_TZ)).replace(hour=REFERRAL_HOUR, minute=0, second=0).timetz(),
        days=(REFERRAL_DAY,),
    )

    logging.info("Bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
