import asyncio
import logging
import os
import re
import sqlite3
import pandas as pd
from datetime import datetime, timedelta

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile)
from telegram.ext import (ApplicationBuilder, ContextTypes, CommandHandler,
                          CallbackQueryHandler, MessageHandler, filters,
                          Defaults)

# ---------------- CONFIG ----------------


def require_env(name):
    """Fails fast on startup if a required secret isn't set - nothing
    sensitive (token, admin IDs, PIN) ever gets a hardcoded fallback
    in the source code, so the bot simply won't run without them
    configured in Railway."""
    val = os.getenv(name)
    if not val:
        print(f"CRITICAL ERROR: {name} is missing")
        exit(1)
    return val


BOT_TOKEN = require_env("TOKEN_HEREDITAS_BOT")
ADMIN_IDS = [int(x.strip()) for x in require_env("HEREDITAS_ADMIN_IDS").split(",")]
ADMIN_PIN = require_env("HEREDITAS_ADMIN_PIN")

# Not sensitive - fine to have a default.
DB_NAME = os.getenv("HEREDITAS_DB_NAME", "hereditas_interviews.db")

# Recruitment schedule lives here - edit these for each new season.
SCHEDULE = {
    "10 Feb 2026": ("10:00", "13:00"),
    "11 Feb 2026": ("10:00", "13:00"),
}
SLOT_MINUTES = 10
INTERVIEWERS_PER_SLOT = 5

NAME_PATTERN = re.compile(r"^[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүІіҺһ]+_[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүІіҺһ]+$")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- TEXT (RU / KZ) ----------------
# Every user-facing phrase lives here, split by language key ("kk"/"ru").
# Edit the strings directly - the {placeholders} must stay as-is since
# the code fills them in with real values (name, date, time, etc).

TEXTS = {
    "kk": {
        "welcome": "👋 Сәлем, {name}!\n\n🤖 Hereditas ұйымының ботына қош келдіңіз.\n⬇️ Төмендегі мәзірді пайдаланыңыз:",
        "btn_book": "📅 Сұхбатқа жазылу",
        "btn_status": "ℹ️ Менің брониым",
        "btn_change": "🔄 Броньды өзгерту",
        "btn_cancel": "❌ Броньды бас тарту",
        "no_dates": "Қолжетімді күндер жоқ.",
        "step1_header": "📍 1/3 қадам — Күнді таңдаңыз:",
        "date_button": "{icon} {date} (бос орын: {free})",
        "no_times": "{date} үшін қолжетімді уақыт жоқ.",
        "step2_header": "📍 2/3 қадам — {date} үшін уақытты таңдаңыз:",
        "already_booking": "❌ Сізде брондау бар.",
        "step3_header": "📍 3/3 қадам — Уақытты растаңыз\n\n📅 {date}\n🕐 {time}",
        "btn_confirm": "✅ Растау",
        "btn_back": "⬅ Артқа",
        "ask_name": "📝 Аз ғана қалды! Тегі_Аты латын әрпімен жазыңыз (мысалы: Назарбаев_Нұрсұлтан):",
        "invalid_name": "Ой, дұрыс емес сияқты 🤔\nМынадай етіп жазыңыз: Назарбаев_Нұрсұлтан",
        "locking": "⏳ Уақытыңызды бекітудеміз...",
        "slot_taken": "❌ Уақыт жаңа ғана алынды. Басқасын таңдаңыз.",
        "success_book": "🎉 Дайын, {given_name}!\n\n📅 {date}\n🕐 {time}\n\nСұхбатта көріскенше!",
        "success_change": "🔄 Жаңартылды, {given_name}!\n\n📅 {date}\n🕐 {time}\n\nСұхбатта көріскенше!",
        "your_booking": "📅 Сіздің броньыңыз:\n{data}",
        "no_active_booking": "Белсенді брондау жоқ.",
        "confirm_cancel_prompt": "Осы броньды бас тартасыз ба?\n{data}",
        "btn_yes_cancel": "✅ Иә, бас тарту",
        "btn_no_keep": "⬅ Жоқ, қалдыру",
        "cancelled": "✅ Бронь бас тартылды.",
        "nothing_to_cancel": "Бас тартатын ештеңе жоқ.",
        "btn_back_menu": "⬅ Мәзірге оралу",
        "alert_already_booking": "Сізде брондау бар. \"Броньды өзгерту\" түймесін пайдаланыңыз.",
        "alert_nothing_to_change": "Өзгертетін белсенді брондау жоқ.",
        "generic_error": "⚠️ Бір қателік орын алды. /start арқылы қайта көріңіз.",
    },
    "ru": {
        "welcome": "👋 Привет, {name}!\n\n🤖 Добро пожаловать в бота организации Hereditas.\n⬇️ Используйте меню ниже:",
        "btn_book": "📅 Записаться на собеседование",
        "btn_status": "ℹ️ Мой статус",
        "btn_change": "🔄 Изменить бронь",
        "btn_cancel": "❌ Отменить бронь",
        "no_dates": "Нет доступных дат.",
        "step1_header": "📍 Шаг 1/3 — Выберите дату:",
        "date_button": "{icon} {date} (свободно мест: {free})",
        "no_times": "Нет доступного времени на {date}.",
        "step2_header": "📍 Шаг 2/3 — Выберите время на {date}:",
        "already_booking": "❌ У вас уже есть бронь.",
        "step3_header": "📍 Шаг 3/3 — Подтвердите слот\n\n📅 {date}\n🕐 {time}",
        "btn_confirm": "✅ Подтвердить",
        "btn_back": "⬅ Назад",
        "ask_name": "📝 Осталось немного! Введите Фамилия_Имя латиницей (например: Назарбаев_Нурсултан):",
        "invalid_name": "Хм, что-то не так 🤔\nПопробуйте так: Назарбаев_Нурсултан",
        "locking": "⏳ Закрепляем ваш слот...",
        "slot_taken": "❌ Слот только что заняли. Выберите другой.",
        "success_book": "🎉 Готово, {given_name}!\n\n📅 {date}\n🕐 {time}\n\nДо встречи на собеседовании!",
        "success_change": "🔄 Обновлено, {given_name}!\n\n📅 {date}\n🕐 {time}\n\nДо встречи на собеседовании!",
        "your_booking": "📅 Ваша бронь:\n{data}",
        "no_active_booking": "Активной брони нет.",
        "confirm_cancel_prompt": "Отменить эту бронь?\n{data}",
        "btn_yes_cancel": "✅ Да, отменить",
        "btn_no_keep": "⬅ Нет, оставить",
        "cancelled": "✅ Бронь отменена.",
        "nothing_to_cancel": "Нечего отменять.",
        "btn_back_menu": "⬅ Назад в меню",
        "alert_already_booking": "У вас уже есть бронь. Используйте «Изменить бронь».",
        "alert_nothing_to_change": "Активной брони для изменения нет.",
        "generic_error": "⚠️ Что-то пошло не так. Попробуйте /start снова.",
    },
}

DEFAULT_LANG = "kk"  # Kazakh shown first in the language picker


def t(lang):
    return TEXTS.get(lang, TEXTS[DEFAULT_LANG])


# ---------------- DATABASE ----------------


def db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_slot TEXT,
            time_slot TEXT,
            booked_by INTEGER,
            username TEXT,
            student_name TEXT
        )
    """)

    cur.execute("SELECT COUNT(*) FROM slots")
    if cur.fetchone()[0] == 0:
        for date, (start, end) in SCHEDULE.items():
            start_dt = datetime.strptime(f"{date} {start}", "%d %b %Y %H:%M")
            end_dt = datetime.strptime(f"{date} {end}", "%d %b %Y %H:%M")

            while start_dt < end_dt:
                label = f"{start_dt.strftime('%H:%M')} - {(start_dt + timedelta(minutes=SLOT_MINUTES)).strftime('%H:%M')}"
                for _ in range(INTERVIEWERS_PER_SLOT):
                    cur.execute(
                        "INSERT INTO slots (date_slot, time_slot) VALUES (?, ?)",
                        (date, label))
                start_dt += timedelta(minutes=SLOT_MINUTES)

    conn.commit()
    conn.close()


# ---------------- HELPERS ----------------


def is_admin(user_id):
    return user_id in ADMIN_IDS


def user_booking(user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT date_slot, time_slot FROM slots WHERE booked_by = ?",
                (user_id, ))
    r = cur.fetchone()
    conn.close()
    return f"{r['date_slot']} | {r['time_slot']}" if r else None


def available_dates_with_count():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT date_slot,
               SUM(CASE WHEN booked_by IS NULL THEN 1 ELSE 0 END) as free,
               COUNT(*) as total
        FROM slots
        GROUP BY date_slot
        HAVING free > 0
    """)
    res = [dict(r) for r in cur.fetchall()]
    conn.close()
    return res


def available_times(date):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT time_slot, COUNT(*) as free
        FROM slots
        WHERE date_slot = ? AND booked_by IS NULL
        GROUP BY time_slot
        HAVING free > 0
    """, (date, ))
    res = [dict(r) for r in cur.fetchall()]
    conn.close()
    return res


def book_slot(date, time, user_id, username, name):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE slots
        SET booked_by = ?, username = ?, student_name = ?
        WHERE id = (
            SELECT id FROM slots
            WHERE date_slot = ? AND time_slot = ?
            AND booked_by IS NULL
            LIMIT 1
        )
    """, (user_id, username, name, date, time))

    success = cur.rowcount == 1
    conn.commit()
    conn.close()
    return success


def change_slot(date, time, user_id, username, name):
    conn = db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE slots
            SET booked_by = NULL, username = NULL, student_name = NULL
            WHERE booked_by = ?
        """, (user_id, ))

        cur.execute(
            """
            UPDATE slots
            SET booked_by = ?, username = ?, student_name = ?
            WHERE id = (
                SELECT id FROM slots
                WHERE date_slot = ? AND time_slot = ?
                AND booked_by IS NULL
                LIMIT 1
            )
        """, (user_id, username, name, date, time))

        success = cur.rowcount == 1
        if success:
            conn.commit()
        else:
            conn.rollback()
        return success
    finally:
        conn.close()


def cancel_booking(user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE slots
        SET booked_by = NULL, username = NULL, student_name = NULL
        WHERE booked_by = ?
    """, (user_id, ))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def build_main_menu(uid, lang):
    tt = t(lang)
    if user_booking(uid):
        kb = [
            [InlineKeyboardButton(tt["btn_status"], callback_data="status")],
            [InlineKeyboardButton(tt["btn_change"], callback_data="change")],
            [InlineKeyboardButton(tt["btn_cancel"], callback_data="cancel")],
        ]
    else:
        kb = [[InlineKeyboardButton(tt["btn_book"], callback_data="book")]]
    return InlineKeyboardMarkup(kb)


def fullness_icon(free, total):
    if not total:
        return "🔴"
    pct = free / total
    if pct >= 0.5:
        return "🟢"
    if pct >= 0.2:
        return "🟡"
    return "🔴"


# ---------------- HANDLERS ----------------


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    # Language choice is the one thing worth keeping when we reset the
    # rest of the flow state on every trip back to the main menu.
    lang = context.user_data.get("lang")
    context.user_data.clear()
    if lang:
        context.user_data["lang"] = lang

    if not lang:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇰🇿 Қазақша", callback_data="lang_kk")],
            [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
        ])
        text = "🌐 Тілді таңдаңыз / Выберите язык"
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)
        return

    tt = t(lang)
    first_name = update.effective_user.first_name or ""
    text = tt["welcome"].format(name=first_name)
    kb = build_main_menu(uid, lang)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)


async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Every entry into the admin panel requires the PIN - not just the
    # database wipe. Booking List and Excel export can leak candidate
    # data, so they're gated too.
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    context.user_data["awaiting_admin_pin"] = True
    context.user_data.pop("admin_authed", None)
    text = "🔒 Enter admin PIN:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("📋 Booking List", callback_data="alist")],
          [InlineKeyboardButton("📊 Download Excel", callback_data="aexcel")],
          [
              InlineKeyboardButton("🧨 Clear the Database",
                                   callback_data="aclear")
          ], [InlineKeyboardButton("⬅ Back", callback_data="back")]]
    text = "Admin Panel"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))


def admin_authed(uid, context):
    return is_admin(uid) and context.user_data.get("admin_authed")


async def buttons_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    d = q.data
    uid = q.from_user.id
    lang = context.user_data.get("lang", DEFAULT_LANG)
    tt = t(lang)

    if d in ("lang_kk", "lang_ru"):
        context.user_data["lang"] = "kk" if d == "lang_kk" else "ru"
        await start_handler(update, context)
        return

    if d == "back":
        await start_handler(update, context)
        return

    if d == "aback":
        if not admin_authed(uid, context):
            return
        await show_admin_panel(update, context)
        return

    # Entry point for booking a new slot or changing an existing one.
    if d in ("book", "change"):
        if d == "change" and not user_booking(uid):
            await q.answer(tt["alert_nothing_to_change"], show_alert=True)
            return
        if d == "book" and user_booking(uid):
            await q.answer(tt["alert_already_booking"], show_alert=True)
            return

        context.user_data["mode"] = d
        dates = available_dates_with_count()
        if not dates:
            await q.edit_message_text(
                tt["no_dates"],
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(tt["btn_back"], callback_data="back")]]))
            return
        kb = []
        for x in dates:
            icon = fullness_icon(x["free"], x["total"])
            label = tt["date_button"].format(icon=icon, date=x["date_slot"], free=x["free"])
            kb.append([InlineKeyboardButton(label, callback_data=f"d_{x['date_slot']}")])
        kb.append([InlineKeyboardButton(tt["btn_back"], callback_data="back")])
        await q.edit_message_text(tt["step1_header"],
                                  reply_markup=InlineKeyboardMarkup(kb))
        return

    if d.startswith("d_"):
        date = d[2:]
        mode = context.user_data.get("mode", "book")
        times = available_times(date)
        if not times:
            await q.edit_message_text(
                tt["no_times"].format(date=date),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(tt["btn_back"], callback_data=mode)]]))
            return
        kb = [[
            InlineKeyboardButton(f"{tm['time_slot']} ({tm['free']}/{INTERVIEWERS_PER_SLOT})",
                                 callback_data=f"t_{date}|{tm['time_slot']}")
        ] for tm in times]
        kb.append([InlineKeyboardButton(tt["btn_back"], callback_data=mode)])
        await q.edit_message_text(tt["step2_header"].format(date=date),
                                  reply_markup=InlineKeyboardMarkup(kb))
        return

    if d.startswith("t_"):
        mode = context.user_data.get("mode", "book")
        if mode == "book" and user_booking(uid):
            await q.edit_message_text(
                tt["already_booking"],
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(tt["btn_back"], callback_data="back")]]))
            return

        context.user_data["pending"] = d[2:]
        date, time = context.user_data["pending"].split("|")
        kb = [
            [InlineKeyboardButton(tt["btn_confirm"], callback_data="confirm_slot")],
            [InlineKeyboardButton(tt["btn_back"], callback_data=f"d_{date}")]
        ]
        await q.edit_message_text(
            tt["step3_header"].format(date=date, time=time),
            reply_markup=InlineKeyboardMarkup(kb))
        return

    if d == "confirm_slot":
        if "pending" not in context.user_data:
            await start_handler(update, context)
            return
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text=tt["ask_name"])
        return

    if d == "status":
        s = user_booking(uid)
        text = tt["your_booking"].format(data=s) if s else tt["no_active_booking"]
        await q.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(tt["btn_back"], callback_data="back")]]))
        return

    if d == "cancel":
        booking = user_booking(uid)
        if not booking:
            await q.edit_message_text(
                tt["nothing_to_cancel"],
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(tt["btn_back"], callback_data="back")]]))
            return
        kb = [
            [InlineKeyboardButton(tt["btn_yes_cancel"], callback_data="confirm_cancel")],
            [InlineKeyboardButton(tt["btn_no_keep"], callback_data="back")]
        ]
        await q.edit_message_text(tt["confirm_cancel_prompt"].format(data=booking),
                                  reply_markup=InlineKeyboardMarkup(kb))
        return

    if d == "confirm_cancel":
        ok = cancel_booking(uid)
        msg = tt["cancelled"] if ok else tt["nothing_to_cancel"]
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(tt["btn_back_menu"], callback_data="back")]])
        await q.edit_message_text(msg, reply_markup=kb)
        return

    # ---------------- ADMIN (PIN-gated) ----------------

    if d == "alist":
        if not admin_authed(uid, context):
            return
        conn = db()
        cur = conn.cursor()
        cur.execute("""
            SELECT date_slot, time_slot, student_name, username
            FROM slots WHERE booked_by IS NOT NULL
            ORDER BY date_slot, time_slot
        """)
        rows = cur.fetchall()
        conn.close()

        text = "Bookings:\n\n"
        for r in rows:
            name = (r["student_name"] or "None")
            text += f"{r['date_slot']} | {r['time_slot']}\n{name} (@{r['username']})\n\n"

        if not rows:
            text = "Empty."

        await q.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅ Back", callback_data="aback")]]))
        return

    if d == "aexcel":
        if not admin_authed(uid, context):
            return
        conn = db()
        query = "SELECT date_slot, time_slot, student_name, username FROM slots WHERE booked_by IS NOT NULL ORDER BY date_slot, time_slot"
        df = pd.read_sql_query(query, conn)
        conn.close()

        if df.empty:
            await q.edit_message_text("No bookings to export.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="aback")]]))
            return

        filename = f"bookings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        df.columns = ["Date", "Time Slot", "Student Name", "Telegram Username"]
        df.to_excel(filename, index=False)

        with open(filename, 'rb') as f:
            await context.bot.send_document(chat_id=q.message.chat_id, document=InputFile(f, filename=filename), caption="Here is the current booking list.")

        os.remove(filename)
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text="Export complete. Return to Admin Panel?",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back to Admin", callback_data="aback")]])
        )
        return

    if d == "aclear":
        if not admin_authed(uid, context):
            return
        kb = [
            [InlineKeyboardButton("🧨 Yes, wipe everything", callback_data="confirm_wipe")],
            [InlineKeyboardButton("⬅ Cancel", callback_data="aback")]
        ]
        await q.edit_message_text(
            "⚠️ This will permanently delete ALL bookings. Are you sure?",
            reply_markup=InlineKeyboardMarkup(kb))
        return

    if d == "confirm_wipe":
        if not admin_authed(uid, context):
            return
        conn = db()
        conn.execute(
            "UPDATE slots SET booked_by=NULL, username=NULL, student_name=NULL")
        conn.commit()
        conn.close()
        await q.edit_message_text(
            "Database has been wiped.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅ Back to Admin", callback_data="aback")]]))
        return


async def text_input_handler(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    uid = update.effective_user.id
    lang = context.user_data.get("lang", DEFAULT_LANG)
    tt = t(lang)

    if context.user_data.get("awaiting_admin_pin"):
        context.user_data.pop("awaiting_admin_pin")
        if not is_admin(uid):
            return
        if txt == ADMIN_PIN:
            context.user_data["admin_authed"] = True
            await show_admin_panel(update, context)
        else:
            await update.message.reply_text("Wrong PIN.")
        return

    if "pending" in context.user_data:
        if not NAME_PATTERN.match(txt):
            await update.message.reply_text(tt["invalid_name"])
            return

        pending_data = context.user_data.pop("pending")
        mode = context.user_data.pop("mode", "book")
        date, time = pending_data.split("|")
        username = update.effective_user.username or "no_username"
        given_name = txt.split("_")[-1]

        temp_msg = await update.message.reply_text(tt["locking"])
        await asyncio.sleep(1)

        if mode == "change":
            ok = change_slot(date, time, uid, username, txt)
        else:
            ok = book_slot(date, time, uid, username, txt)

        if not ok:
            await temp_msg.edit_text(tt["slot_taken"])
        else:
            key = "success_change" if mode == "change" else "success_book"
            await temp_msg.edit_text(
                tt[key].format(given_name=given_name, date=date, time=time))

        return await start_handler(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        lang = context.user_data.get("lang", DEFAULT_LANG) if hasattr(context, "user_data") and context.user_data else DEFAULT_LANG
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=t(lang)["generic_error"])
        except Exception:
            pass


# ---------------- RUN ----------------

if __name__ == "__main__":
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("admins", admin_handler))
    app.add_handler(CallbackQueryHandler(buttons_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))
    app.add_error_handler(error_handler)

    print("Hereditas bot (beta1) running.")
    app.run_polling()
