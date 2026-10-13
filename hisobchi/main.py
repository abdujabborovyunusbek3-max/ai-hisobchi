"""AI hisobchi — Telegram bot. Ishga tushirish: python -m hisobchi.main"""
import asyncio
import csv
import hashlib
import io
import logging
import os
from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
                          filters)

from . import db
from .ai import AIError, analyze, transcribe
from .report import build_report, period_range, tx_line

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("hisobchi")

TZ = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Tashkent"))
OWNER_IDS = {int(x) for x in os.environ.get("OWNER_IDS", "").replace(" ", "").split(",") if x}
SUPPORTED_IMAGES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024

HELP = """<b>AI hisobchi</b> 🧾

Menga shunchaki yozing, rasm yoki ovozli xabar yuboring — o'zim hisoblab boraman:
• <i>100 000 oylik berdim Aliga</i>
• <i>Validan 500 ming qarz oldim</i>
• <i>ijaraga 3 mln to'ladim</i>
• to'lov cheki yoki Click/Payme skrinshoti
• 🎤 ovozli xabar

Savol bering: <i>bu oy qancha oylik berdim?</i>, <i>Ali bilan hisob qanday?</i>

<b>Buyruqlar</b>
/hisobot — shu oy hisoboti (/hisobot bugun | hafta | oy | yil | hammasi)
/oxirgi — oxirgi 10 ta yozuv
/ochir — oxirgi yozuvni o'chirish (/ochir 15 — 15-raqamlisini)
/export — barcha yozuvlar CSV (Excel) faylda"""


def today() -> date:
    return datetime.now(TZ).date()


# ---------- ruxsat ----------

async def is_allowed(user_id: int) -> bool:
    if OWNER_IDS:
        return user_id in OWNER_IDS
    owner = await asyncio.to_thread(db.get_setting, "owner_id")
    return owner is not None and int(owner) == user_id


async def guard(update: Update) -> bool:
    user = update.effective_user
    if user and await is_allowed(user.id):
        return True
    if update.effective_message:
        await update.effective_message.reply_text("⛔ Bu shaxsiy bot. Sizga ruxsat yo'q.")
    return False


# ---------- buyruqlar ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not OWNER_IDS and await asyncio.to_thread(db.get_setting, "owner_id") is None:
        await asyncio.to_thread(db.set_setting, "owner_id", str(user.id))
        await update.message.reply_text(f"✅ Siz bot egasi sifatida ro'yxatdan o'tdingiz (ID: {user.id}).")
    if not await guard(update):
        return
    await update.message.reply_text(HELP, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await guard(update):
        await update.message.reply_text(HELP, parse_mode=ParseMode.HTML)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    start, end, title = period_range(context.args[0] if context.args else "oy", today())
    rows = await asyncio.to_thread(db.query_transactions, update.effective_user.id, date_from=start, date_to=end)
    await update.message.reply_text(build_report(rows, title), parse_mode=ParseMode.HTML)


async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    rows = await asyncio.to_thread(db.query_transactions, update.effective_user.id, limit=10, newest_first=True)
    if not rows:
        await update.message.reply_text("Hali yozuv yo'q.")
        return
    lines = [f"<code>#{r['id']}</code> {r['tx_date']:%d.%m} {tx_line(r)}" for r in rows]
    await update.message.reply_text("🕘 <b>Oxirgi yozuvlar</b>\n\n" + "\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    uid = update.effective_user.id
    if context.args:
        try:
            ids = [int(a.lstrip("#")) for a in context.args]
        except ValueError:
            await update.message.reply_text("Raqam yozing, masalan: /ochir 15")
            return
    else:
        last = await asyncio.to_thread(db.last_transaction_id, uid)
        ids = [last] if last else []
    n = await asyncio.to_thread(db.delete_transactions, uid, ids) if ids else 0
    await update.message.reply_text(f"🗑 {n} ta yozuv o'chirildi." if n else "O'chiradigan yozuv topilmadi.")


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    rows = await asyncio.to_thread(db.query_transactions, update.effective_user.id)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "sana", "turi", "summa", "valyuta", "kategoriya", "kim", "izoh", "manba"])
    for r in rows:
        w.writerow([r["id"], r["tx_date"].isoformat(), "kirim" if r["direction"] == "in" else "chiqim",
                    str(r["amount"]), r["currency"], r["category"], r["person"] or "", r["note"] or "", r["source"]])
    data = io.BytesIO(("﻿" + buf.getvalue()).encode("utf-8"))  # BOM: Excel o'zbekcha harflarni to'g'ri ochadi
    await update.message.reply_document(data, filename=f"hisob_{today().isoformat()}.csv",
                                        caption=f"{len(rows)} ta yozuv")


# ---------- asosiy ishlov ----------

def _to_amount(value) -> float | None:
    """Model ba'zan summani matn qilib qaytaradi ("100 000", "1,5"): songa aylantiramiz."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(" ", "").replace("\u00a0", "").replace(",", ".")
        cleaned = "".join(ch for ch in cleaned if ch.isdigit() or ch == ".")
        if cleaned.count(".") > 1:  # "100.000.000" kabi minglik ajratgich
            cleaned = cleaned.replace(".", "")
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None
    return None


def _parse_date(value: str | None) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


async def process(update: Update, *, text: str | None, image: bytes | None = None,
                  image_mime: str = "image/jpeg", source: str = "text") -> None:
    msg = update.effective_message
    uid = update.effective_user.id
    await msg.chat.send_action(ChatAction.TYPING)
    cats, people = await asyncio.to_thread(db.known_labels, uid)
    try:
        result = await analyze(today=today(), text=text, image=image, image_mime=image_mime,
                               categories=cats, people=people, owner_name=update.effective_user.full_name)
    except AIError as e:
        await msg.reply_text(f"⚠️ {e}")
        return

    intent = result.get("intent")
    if intent == "record":
        items = []
        for t in result.get("transactions") or []:
            t["amount"] = _to_amount(t.get("amount"))
            if t["amount"] is None or t["amount"] <= 0 or t.get("direction") not in ("in", "out"):
                continue
            t["tx_date"] = _parse_date(t.get("date")) or today()
            items.append(t)
        if not items:
            await msg.reply_text(result.get("reply") or "Summani topa olmadim. Aniqroq yozing.")
            return
        saved = await asyncio.to_thread(db.add_transactions, uid, items, source, text)
        lines = [tx_line(r) + ("" if r["tx_date"] == today() else f" · {r['tx_date']:%d.%m.%Y}") for r in saved]
        ids = ",".join(str(r["id"]) for r in saved)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data=f"del:{ids}")]])
        await msg.reply_text("✅ <b>Yozib qo'ydim</b>\n" + "\n".join(lines), parse_mode=ParseMode.HTML,
                             reply_markup=kb)
        return

    if intent == "query":
        q = result.get("query") or {}
        filters_ = dict(date_from=_parse_date(q.get("date_from")), date_to=_parse_date(q.get("date_to")),
                        person=q.get("person"), category=q.get("category"), direction=q.get("direction"))
        rows = await asyncio.to_thread(db.query_transactions, uid, **filters_)
        title_bits = []
        if filters_["person"]:
            title_bits.append(filters_["person"])
        if filters_["category"]:
            title_bits.append(filters_["category"])
        if filters_["date_from"] or filters_["date_to"]:
            f = filters_["date_from"].strftime("%d.%m.%Y") if filters_["date_from"] else "…"
            t = filters_["date_to"].strftime("%d.%m.%Y") if filters_["date_to"] else "…"
            title_bits.append(f"{f} – {t}")
        text_out = build_report(rows, " · ".join(title_bits) or "Barcha vaqt")
        if 0 < len(rows) <= 15:
            text_out += "\n\n<u>Yozuvlar:</u>\n" + "\n".join(f"{r['tx_date']:%d.%m} {tx_line(r)}" for r in rows)
        await msg.reply_text(text_out, parse_mode=ParseMode.HTML)
        return

    await msg.reply_text(result.get("reply") or "Tushunmadim. /yordam ni bosing.")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await guard(update):
        await process(update, text=update.message.text, source="text")


async def on_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    msg = update.message
    if msg.photo:
        tg_file, mime = await msg.photo[-1].get_file(), "image/jpeg"
    else:
        doc = msg.document
        if doc.mime_type not in SUPPORTED_IMAGES:
            await msg.reply_text("Faqat JPG, PNG yoki WEBP rasm yuboring.")
            return
        if doc.file_size and doc.file_size > MAX_IMAGE_BYTES:
            await msg.reply_text("Rasm juda katta (5 MB dan oshmasin). Oddiy rasm qilib yuboring.")
            return
        tg_file, mime = await doc.get_file(), doc.mime_type
    data = bytes(await tg_file.download_as_bytearray())
    await process(update, text=msg.caption, image=data, image_mime=mime, source="photo")


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    msg = update.message
    media = msg.voice or msg.audio
    await msg.chat.send_action(ChatAction.TYPING)
    data = bytes(await (await media.get_file()).download_as_bytearray())
    try:
        text = await transcribe(data, getattr(media, "file_name", None) or "voice.ogg")
    except AIError as e:
        await msg.reply_text(f"⚠️ {e}")
        return
    if not text:
        await msg.reply_text("Ovozda gap eshitilmadi. Qayta yuboring.")
        return
    await msg.reply_text(f"🎤 <i>{escape(text)}</i>", parse_mode=ParseMode.HTML)
    await process(update, text=text, source="voice")


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not await is_allowed(query.from_user.id):
        await query.answer("Ruxsat yo'q", show_alert=True)
        return
    if query.data.startswith("del:"):
        ids = [int(x) for x in query.data[4:].split(",") if x]
        n = await asyncio.to_thread(db.delete_transactions, query.from_user.id, ids)
        await query.answer("O'chirildi" if n else "Allaqachon o'chirilgan")
        await query.edit_message_text(f"🗑 Bekor qilindi ({n} ta yozuv o'chirildi).")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Xato", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            err = context.error
            await update.effective_message.reply_text(
                f"⚠️ Kutilmagan xato: {type(err).__name__}: {str(err)[:300]}")
        except Exception:
            pass


def build_app() -> Application:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler(["yordam", "help"], cmd_help))
    app.add_handler(CommandHandler("hisobot", cmd_report))
    app.add_handler(CommandHandler("oxirgi", cmd_last))
    app.add_handler(CommandHandler("ochir", cmd_delete))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_image))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    db.init_db()
    app = build_app()
    base_url = os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if base_url:
        # Render kabi hostinglarda: webhook rejimi (Telegram o'zi so'rov yuboradi, uxlab qolgan servis uyg'onadi)
        secret = os.environ.get("WEBHOOK_SECRET") or hashlib.sha256(
            os.environ["TELEGRAM_BOT_TOKEN"].encode()).hexdigest()[:32]
        log.info("Webhook rejimi: %s", base_url)
        app.run_webhook(listen="0.0.0.0", port=int(os.environ.get("PORT", "10000")), url_path="telegram",
                        webhook_url=base_url.rstrip("/") + "/telegram", secret_token=secret,
                        allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
    else:
        log.info("Polling rejimi (lokal)")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
