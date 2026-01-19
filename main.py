import os
import json
import datetime
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

import gspread
from google.oauth2.service_account import Credentials

# ================== ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("WEBHOOK_URL")  # https://rowsafety-bot.onrender.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = BASE_URL + WEBHOOK_PATH

SHEET_NAME = "ROW_SAFETY_LOG"

# ================== Google Sheet ==================
creds_dict = json.loads(os.getenv("GOOGLE_CREDS_JSON"))
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)
sheet = gc.open(SHEET_NAME).sheet1

# ================== FastAPI + Telegram ==================
app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

last_message = {}  # กันข้อความซ้ำ

def log_to_sheet(user, text):
    sheet.append_row([
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user,
        text
    ])

# ================== Handlers ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ ROW Safety AI Bot\nพิมพ์คำถามหน้างาน หรือ EMERGENCY"
    )

async def emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚨 EMERGENCY MODE\n"
        "1) หยุดงานทันที\n"
        "2) ถอยออกจากแนวสายไฟ\n"
        "3) ติดต่อผู้ควบคุมงาน"
    )

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    # กันข้อความซ้ำ
    if last_message.get(uid) == text:
        return
    last_message[uid] = text

    log_to_sheet(update.effective_user.username or uid, text)

    if "ฝน" in text:
        await update.message.reply_text(
            "⚠️ ฝนตก: ไม่ควรทำงานใกล้สายไฟแรงสูง"
        )
    else:
        await update.message.reply_text(
            "รับทราบ กำลังประเมินสถานการณ์หน้างาน"
        )

tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("emergency", emergency))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

# ================== Webhook ==================
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.on_event("startup")
async def on_startup():
    await tg_app.initialize()
    await tg_app.bot.set_webhook(WEBHOOK_URL)
