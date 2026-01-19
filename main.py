import os
import json
from datetime import datetime

from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import gspread
from google.oauth2.service_account import Credentials

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

WEBHOOK_PATH = "/webhook"

# ================= GOOGLE SHEET =================
creds_dict = json.loads(GOOGLE_CREDS_JSON)
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)
sheet = gc.open("ROW_SAFETY_LOG").sheet1

# ================= TELEGRAM =================
app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

# ================= LOG =================
def log_to_sheet(time, username, chat_id, message, location="-"):
    sheet.append_row([time, username, chat_id, message, location])

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id
    log_to_sheet(now(), user, chat_id, "/start")
    await update.message.reply_text(
        "⚡ ROW Safety AI Bot\nพิมพ์สถานการณ์หน้างาน หรือกด 📎 ส่ง Location"
    )

async def emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id
    log_to_sheet(now(), user, chat_id, "EMERGENCY")
    await update.message.reply_text(
        "🚨 EMERGENCY MODE\n"
        "1) หยุดงานทันที\n"
        "2) ถอยออกจากแนวสายไฟ\n"
        "3) ติดต่อผู้ควบคุมงาน"
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    log_to_sheet(now(), user, chat_id, text)

    if "ฝน" in text:
        await update.message.reply_text("⚠️ ฝนตก: ห้ามทำงานใกล้สายไฟแรงสูง")
    elif "พิกัด" in text:
        await update.message.reply_text("📍 กด 📎 → Location → Send location")
    else:
        await update.message.reply_text("รับทราบ กำลังประเมินสถานการณ์หน้างาน")

async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id
    location = f"{loc.latitude},{loc.longitude}"

    log_to_sheet(
        now(),
        user,
        chat_id,
        "ส่งพิกัดหน้างาน",
        location
    )

    maps_link = f"https://maps.google.com/?q={loc.latitude},{loc.longitude}"
    await update.message.reply_text(
        f"📍 รับพิกัดเรียบร้อย\n{maps_link}"
    )

# ================= REGISTER =================
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("emergency", emergency))
tg_app.add_handler(MessageHandler(filters.LOCATION, location_handler))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

# ================= WEBHOOK =================
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.on_event("startup")
async def on_startup():
    await tg_app.initialize()
    await tg_app.bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)
