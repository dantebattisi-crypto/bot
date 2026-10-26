"""Admin panel: channel relay on/off, custom broadcasts, referral reminder settings.

Access: only users in ADMIN_USER_IDS, only in a private chat with the bot. Every handler is
registered with a user filter AND re-checks the user inside (fail closed). If ADMIN_USER_IDS is
empty, nothing here is registered at all.
"""
import asyncio
import json
import logging
import secrets
from datetime import datetime, time
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.error import RetryAfter, BadRequest
from telegram.ext import (
    Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, filters,
)

import store
from config import ADMIN_USER_IDS, WEBAPP_URL, SOURCE_CHANNEL_ID, UK_TZ

log = logging.getLogger(__name__)

ADMIN_GROUP = -1          # runs before the regular handlers (group 0)
REFERRAL_JOB = "referral"
SEND_DELAY = 0.05         # ~20 msg/s, below Telegram's broadcast limit

AWAIT = "await"            # user_data: what the admin's next message is for
PENDING_BC = "pending_bc"  # user_data: message_id of the broadcast draft
SENDNOW_TOKEN = "sendnow"  # user_data: one-shot token for "send referral now"


def is_admin(update: Update) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    return (
        user is not None and user.id in ADMIN_USER_IDS
        and chat is not None and chat.type == chat.PRIVATE
    )


def run_in_background(context: ContextTypes.DEFAULT_TYPE, coro):
    """Long sends must not block update processing (PTB handles updates one by one),
    otherwise client auto-replies would stall during a broadcast."""
    return context.application.create_task(coro)


# ---------- sending ----------

async def _send_with_retry(coro_factory):
    try:
        return await coro_factory()
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        return await coro_factory()


async def send_to_chats(make_call) -> tuple[int, int]:
    """make_call(chat_id) -> coroutine. Returns (ok, total)."""
    chats = sorted(int(c) for c in store.r.smembers(store.CHATS_KEY))
    ok = 0
    for chat_id in chats:
        try:
            await _send_with_retry(lambda: make_call(chat_id))
            ok += 1
        except Exception as e:
            log.error(f"Send to {chat_id} failed: {e}")
        await asyncio.sleep(SEND_DELAY)
    return ok, len(chats)


async def send_referral_to_all(bot) -> tuple[int, int]:
    text = store.referral_html()
    res = await send_to_chats(lambda cid: bot.send_message(cid, text, parse_mode=ParseMode.HTML))
    store.r.set(store.REFERRAL_LAST_SENT_KEY, str(datetime.now(ZoneInfo(UK_TZ)).date()))
    log.info(f"Referral reminder sent to {res[0]}/{res[1]} chats")
    return res


async def referral_job(context: ContextTypes.DEFAULT_TYPE):
    """Daily job: sends only if enabled and the interval has passed."""
    if not store.referral_enabled():
        return
    last = store.referral_last_sent()
    if last:
        days = (datetime.now(ZoneInfo(UK_TZ)).date() - datetime.fromisoformat(last).date()).days
        if days < store.referral_interval():
            return
    await send_referral_to_all(context.bot)


def schedule_referral_job(app: Application):
    for job in app.job_queue.get_jobs_by_name(REFERRAL_JOB):
        job.schedule_removal()
    app.job_queue.run_daily(
        referral_job,
        time=time(hour=store.referral_hour(), minute=0, second=0, tzinfo=ZoneInfo(UK_TZ)),
        name=REFERRAL_JOB,
    )


# ---------- panel ----------

def _onoff(flag: bool, fem: bool = True) -> str:
    if fem:
        return "✅ включена" if flag else "⛔️ выключена"
    return "✅ включено" if flag else "⛔️ выключено"


def status_text() -> str:
    relay = store.relay_enabled()
    ref = store.referral_enabled()
    last = store.referral_last_sent() or "ещё не отправлялось"
    nxt = store.referral_next_send().strftime("%d.%m.%Y %H:00") if ref else "—"
    text_src = "свой" if store.referral_is_custom() else "по умолчанию"
    return (
        "<b>⚙️ Панель управления</b>\n\n"
        f"<b>Рассылка из канала:</b> {_onoff(relay)}\n\n"
        f"<b>Реф. напоминание:</b> {_onoff(ref, fem=False)}\n"
        f"• каждые {store.referral_interval()} дн. в {store.referral_hour():02d}:00 (UK)\n"
        f"• последнее: {last}\n"
        f"• следующее: {nxt}\n"
        f"• текст: {text_src}\n\n"
        f"Чатов в рассылке: {store.chats_count()}"
    )


def panel_keyboard() -> InlineKeyboardMarkup:
    relay = store.relay_enabled()
    ref = store.referral_enabled()
    rows = [
        [InlineKeyboardButton(
            ("⛔️ Выключить" if relay else "✅ Включить") + " рассылку из канала",
            callback_data="relay:toggle")],
        [InlineKeyboardButton(
            ("⛔️ Выключить" if ref else "✅ Включить") + " реф. напоминание",
            callback_data="ref:toggle")],
        [InlineKeyboardButton("📅 Интервал", callback_data="ref:interval"),
         InlineKeyboardButton("🕐 Время", callback_data="ref:hour")],
        [InlineKeyboardButton("✏️ Текст", callback_data="ref:text"),
         InlineKeyboardButton("👁 Превью", callback_data="ref:preview")],
    ]
    if store.referral_is_custom():
        rows.append([InlineKeyboardButton("↩️ Вернуть текст по умолчанию", callback_data="ref:reset")])
    rows += [
        [InlineKeyboardButton("🚀 Отправить напоминание сейчас", callback_data="ref:sendnow")],
        [InlineKeyboardButton("📣 Своя рассылка", callback_data="bc:start")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="panel:refresh")],
    ]
    return InlineKeyboardMarkup(rows)


def webapp_url() -> str | None:
    if not WEBAPP_URL:
        return None
    params = {
        "relay": int(store.relay_enabled()),
        "ref": int(store.referral_enabled()),
        "int": store.referral_interval(),
        "hour": store.referral_hour(),
        "last": store.referral_last_sent() or "",
        "next": store.referral_next_send().strftime("%Y-%m-%d %H:00"),
        "chats": store.chats_count(),
        "custom": int(store.referral_is_custom()),
        "v": int(datetime.now().timestamp()),  # cache-buster
    }
    sep = "&" if "?" in WEBAPP_URL else "?"
    return WEBAPP_URL + sep + urlencode(params)


def webapp_keyboard() -> ReplyKeyboardMarkup | None:
    url = webapp_url()
    if not url:
        return None
    return ReplyKeyboardMarkup(
        [[KeyboardButton("⚙️ Панель", web_app=WebAppInfo(url=url))]],
        resize_keyboard=True, is_persistent=True,
    )


async def send_panel(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id, status_text(), parse_mode=ParseMode.HTML,
                                   reply_markup=panel_keyboard())
    kb = webapp_keyboard()
    if kb:
        # The reply keyboard carries the current state in its URL, so refresh it every time.
        await context.bot.send_message(chat_id, "Мини-приложение — кнопка «⚙️ Панель» внизу.",
                                       reply_markup=kb)


async def refresh_panel_message(query):
    try:
        await query.edit_message_text(status_text(), parse_mode=ParseMode.HTML,
                                      reply_markup=panel_keyboard())
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


# ---------- flows shared by inline buttons and the mini app ----------

PROMPTS = {
    "broadcast": "📣 Пришли сообщение для рассылки — текст, фото, видео, файл, с форматированием.\n"
                 "Альбомы не поддерживаются (уйдёт только одно фото).\n/cancel — отмена.",
    "ref_text": "✏️ Пришли новый текст реф. напоминания одним сообщением. "
                "Жирный/курсив/ссылки сохранятся.\n/cancel — отмена.",
    "ref_interval": f"📅 Пришли интервал в днях ({store.INTERVAL_RANGE[0]}–{store.INTERVAL_RANGE[1]}).\n/cancel — отмена.",
    "ref_hour": f"🕐 Пришли час отправки по UK ({store.HOUR_RANGE[0]}–{store.HOUR_RANGE[1]}).\n/cancel — отмена.",
}


async def ask(chat_id: int, context: ContextTypes.DEFAULT_TYPE, what: str):
    context.user_data[AWAIT] = what
    context.user_data.pop(PENDING_BC, None)
    await context.bot.send_message(chat_id, PROMPTS[what])


async def ask_sendnow(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    token = secrets.token_hex(4)
    context.user_data[SENDNOW_TOKEN] = token
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"🚀 Да, отправить в {store.chats_count()} чатов",
                             callback_data=f"ref:sendnow:{token}"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel"),
    ]])
    await context.bot.send_message(
        chat_id,
        "Отправить реф. напоминание во все чаты прямо сейчас?\n"
        "Отсчёт интервала начнётся заново с сегодняшнего дня.",
        reply_markup=kb,
    )


async def preview_referral(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id, "👁 Так выглядит напоминание:")
    await context.bot.send_message(chat_id, store.referral_html(), parse_mode=ParseMode.HTML)


async def _run_referral_now(query, bot):
    ok, total = await send_referral_to_all(bot)
    await query.edit_message_text(f"✅ Напоминание отправлено: {ok}/{total} чатов.")


async def _run_broadcast(query, bot, from_chat: int, mid: int, with_channel: bool):
    lines = []
    if with_channel:
        try:
            sent = await bot.copy_message(SOURCE_CHANNEL_ID, from_chat, mid)
            store.mark_own_channel_post(sent.message_id)  # never relay our own post back
            lines.append("✅ Канал: опубликовано")
        except Exception as e:
            log.error(f"Broadcast to channel failed: {e}")
            lines.append(f"❌ Канал: ошибка ({e})")
    ok, total = await send_to_chats(lambda cid: bot.copy_message(cid, from_chat, mid))
    lines.append(f"✅ Чаты: {ok}/{total}")
    log.info(f"Custom broadcast {from_chat}/{mid}: " + "; ".join(lines))
    await query.edit_message_text("Рассылка готова.\n" + "\n".join(lines))


# ---------- handlers ----------

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    context.user_data.pop(AWAIT, None)
    await send_panel(update.effective_chat.id, context)
    raise ApplicationHandlerStop


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin's /start shows the panel; the regular /start handler (group 0) still runs after,
    exactly as before."""
    if not is_admin(update):
        return
    await send_panel(update.effective_chat.id, context)


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await ask(update.effective_chat.id, context, "broadcast")
    raise ApplicationHandlerStop


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    for key in (AWAIT, PENDING_BC, SENDNOW_TOKEN):
        context.user_data.pop(key, None)
    await update.effective_message.reply_text("Отменено.")
    raise ApplicationHandlerStop


async def on_admin_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edits of old messages in the admin DM are ignored (never become a draft or a setting)."""
    if is_admin(update):
        raise ApplicationHandlerStop


async def on_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Any new non-command admin message in DM. Never falls through to the offline auto-reply."""
    if not is_admin(update):
        return
    msg = update.effective_message
    chat_id = msg.chat_id
    waiting = context.user_data.get(AWAIT)

    if waiting == "broadcast":
        context.user_data.pop(AWAIT, None)
        context.user_data[PENDING_BC] = msg.message_id
        n = store.chats_count()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📤 Только в чаты ({n})", callback_data=f"bc:chats:{msg.message_id}")],
            [InlineKeyboardButton("📤 В чаты + в основной канал", callback_data=f"bc:both:{msg.message_id}")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
        ])
        note = "\n⚠️ Это часть альбома — уйдёт только это сообщение." if msg.media_group_id else ""
        await msg.reply_text("Вот это сообщение разослать?" + note, reply_markup=kb)

    elif waiting == "ref_text":
        if not msg.text:
            await msg.reply_text("Нужен именно текст (без фото). Пришли ещё раз или /cancel.")
        else:
            old = store.r.get(store.REFERRAL_TEXT_KEY)
            store.set_referral_html(msg.text_html)
            try:
                await preview_referral(chat_id, context)
            except BadRequest as e:
                store.set_referral_html(old)
                await msg.reply_text(f"Не получилось отправить такой текст ({e}). Оставил старый.")
            else:
                context.user_data.pop(AWAIT, None)
                await send_panel(chat_id, context)

    elif waiting in ("ref_interval", "ref_hour"):
        name, (lo, hi) = (
            ("referral_interval_days", store.INTERVAL_RANGE) if waiting == "ref_interval"
            else ("referral_hour", store.HOUR_RANGE)
        )
        try:
            value = int((msg.text or "").strip())
            if not lo <= value <= hi:
                raise ValueError
        except ValueError:
            await msg.reply_text(f"Нужно целое число от {lo} до {hi}. Ещё раз или /cancel.")
        else:
            context.user_data.pop(AWAIT, None)
            store.set_setting(name, value)
            if name == "referral_hour":
                schedule_referral_job(context.application)
            await send_panel(chat_id, context)

    else:
        await msg.reply_text("/admin — панель управления\n/broadcast — своя рассылка")

    raise ApplicationHandlerStop


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update):
        return  # silently ignored, exactly like before the panel existed
    data = query.data or ""
    chat_id = query.message.chat_id
    await query.answer()

    if data == "panel:refresh":
        await refresh_panel_message(query)
    elif data == "relay:toggle":
        store.set_flag("relay_enabled", not store.relay_enabled())
        log.info(f"Admin {query.from_user.id}: relay -> {store.relay_enabled()}")
        await refresh_panel_message(query)
    elif data == "ref:toggle":
        store.set_flag("referral_enabled", not store.referral_enabled())
        log.info(f"Admin {query.from_user.id}: referral -> {store.referral_enabled()}")
        await refresh_panel_message(query)
    elif data == "ref:reset":
        store.set_referral_html(None)
        await refresh_panel_message(query)
    elif data == "ref:preview":
        await preview_referral(chat_id, context)
    elif data == "ref:text":
        await ask(chat_id, context, "ref_text")
    elif data == "ref:interval":
        await ask(chat_id, context, "ref_interval")
    elif data == "ref:hour":
        await ask(chat_id, context, "ref_hour")
    elif data == "ref:sendnow":
        await ask_sendnow(chat_id, context)
    elif data.startswith("ref:sendnow:"):
        token = data.split(":", 2)[2]
        if context.user_data.get(SENDNOW_TOKEN) != token:
            await query.edit_message_text("Эта отправка уже выполнена или отменена.")
            return
        context.user_data.pop(SENDNOW_TOKEN, None)  # one-shot: protects from double taps
        await query.edit_message_text("⏳ Отправляю напоминание…")
        log.info(f"Admin {query.from_user.id}: referral send-now")
        run_in_background(context, _run_referral_now(query, context.bot))
    elif data == "bc:start":
        await ask(chat_id, context, "broadcast")
    elif data.startswith(("bc:chats:", "bc:both:")):
        _, mode, mid = data.split(":")
        if context.user_data.get(PENDING_BC) != int(mid):
            await query.edit_message_text("Эта рассылка уже отправлена или отменена.")
            return
        context.user_data.pop(PENDING_BC, None)  # one-shot: protects from double taps
        await query.edit_message_text("⏳ Отправляю…")
        log.info(f"Admin {query.from_user.id}: custom broadcast ({mode})")
        run_in_background(context, _run_broadcast(query, context.bot, chat_id, int(mid), mode == "both"))
    elif data == "cancel":
        for key in (AWAIT, PENDING_BC, SENDNOW_TOKEN):
            context.user_data.pop(key, None)
        await query.edit_message_text("Отменено.")


def _parse_webapp(raw: str) -> dict:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    action = data.get("action")
    if action == "save":
        out = {"action": "save"}
        for key in ("relay", "referral"):
            if not isinstance(data.get(key), bool):
                raise ValueError(f"bad {key}")
            out[key] = data[key]
        for key, (lo, hi) in (("interval", store.INTERVAL_RANGE), ("hour", store.HOUR_RANGE)):
            val = data.get(key)
            if not isinstance(val, int) or isinstance(val, bool) or not lo <= val <= hi:
                raise ValueError(f"bad {key}")
            out[key] = val
        return out
    if action in ("broadcast", "edit_text", "preview", "send_now", "reset_text"):
        return {"action": action}
    raise ValueError("unknown action")


async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    msg = update.effective_message
    chat_id = msg.chat_id
    try:
        data = _parse_webapp(msg.web_app_data.data)
    except (ValueError, TypeError) as e:
        log.warning(f"Bad web app data: {e}")
        await msg.reply_text("Не понял данные из панели, ничего не изменено.")
        raise ApplicationHandlerStop

    action = data["action"]
    if action == "save":
        hour_changed = data["hour"] != store.referral_hour()
        store.set_flag("relay_enabled", data["relay"])
        store.set_flag("referral_enabled", data["referral"])
        store.set_setting("referral_interval_days", data["interval"])
        store.set_setting("referral_hour", data["hour"])
        if hour_changed:
            schedule_referral_job(context.application)
        log.info(f"Admin {update.effective_user.id}: saved {data}")
        await msg.reply_text("💾 Сохранено.")
        await send_panel(chat_id, context)
    elif action == "broadcast":
        await ask(chat_id, context, "broadcast")
    elif action == "edit_text":
        await ask(chat_id, context, "ref_text")
    elif action == "preview":
        await preview_referral(chat_id, context)
    elif action == "reset_text":
        store.set_referral_html(None)
        await msg.reply_text("↩️ Текст сброшен на стандартный.")
        await send_panel(chat_id, context)
    elif action == "send_now":
        await ask_sendnow(chat_id, context)
    raise ApplicationHandlerStop


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=context.error)
    if isinstance(update, Update) and is_admin(update):
        try:
            await context.bot.send_message(update.effective_chat.id, f"⚠️ Ошибка: {context.error}")
        except Exception:
            pass


def register(app: Application):
    schedule_referral_job(app)
    app.add_error_handler(on_error)

    if not ADMIN_USER_IDS:
        log.warning("ADMIN_USER_IDS is empty — admin panel disabled.")
        return

    admin_dm = filters.ChatType.PRIVATE & filters.User(user_id=ADMIN_USER_IDS)
    new_msg = admin_dm & filters.UpdateType.MESSAGE
    g = ADMIN_GROUP
    app.add_handler(CommandHandler("admin", cmd_admin, filters=new_msg), group=g)
    app.add_handler(CommandHandler("broadcast", cmd_broadcast, filters=new_msg), group=g)
    app.add_handler(CommandHandler("cancel", cmd_cancel, filters=new_msg), group=g)
    app.add_handler(CommandHandler("start", cmd_start, filters=new_msg), group=g)
    app.add_handler(MessageHandler(new_msg & filters.StatusUpdate.WEB_APP_DATA, on_webapp_data), group=g)
    app.add_handler(MessageHandler(admin_dm & filters.UpdateType.EDITED_MESSAGE, on_admin_edit), group=g)
    app.add_handler(MessageHandler(new_msg & ~filters.COMMAND & ~filters.StatusUpdate.ALL, on_admin_message), group=g)
    app.add_handler(CallbackQueryHandler(on_callback), group=g)
    log.info(f"Admin panel enabled for users {sorted(ADMIN_USER_IDS)}.")
