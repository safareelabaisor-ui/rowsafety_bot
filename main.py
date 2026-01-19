import os
import json
import asyncio
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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")   # เช่น https://rowsafety-bot.onrender.com
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

WEBHOOK_PATH = "/webhook"

# ================= GOOGLE SHEET =================
creds_dict = json.loads(GOOGLE_CREDS_JSON)

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)

sheet = gc.open("ROW_SAFETY_LOG").sheet1  # ต้องแชร์ Sheet ให้ service account

# ================= FASTAPI =================
app = FastAPI()

# ================= TELEGRAM =================
tg_app = Application.builder().token(BOT_TOKEN).build()

# ================= LOG FUNCTION =================
async def log_to_sheet(user, text):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        sheet.append_row,
        [now, user, text]
    )

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or "unknown"
    await log_to_sheet(user, "/start")
    await update.message.reply_text(
        "⚡ ROW Safety AI Bot\n"
        "พิมพ์สถานการณ์หน้างาน หรือพิมพ์ EMERGENCY"
    )

async def emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or "unknown"
    await log_to_sheet(user, "EMERGENCY")
    await update.message.reply_text(
        "🚨 EMERGENCY MODE\n"
        "1) หยุดงานทันที\n"
        "2) ถอยออกจากแนวสายไฟ\n"
        "3) ติดต่อผู้ควบคุมงาน"
    )

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user.username or "unknown"

    await log_to_sheet(user, text)

    if "ฝน" in text:
        await update.message.reply_text(
            "⚠️ ฝนตก: ห้ามทำงานใกล้สายไฟแรงสูง"
        )
    else:
        await update.message.reply_text(
            "รับทราบ กำลังประเมินสถานการณ์หน้างาน"
        )

# ================= REGISTER HANDLERS =================
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("emergency", emergency))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

# ================= WEBHOOK =================
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

# ================= STARTUP =================
@app.on_event("startup")
async def on_startup():
    await tg_app.initialize()
    await tg_app.bot.set_webhook(f"{WEBHOOK_URL}{WEBHOOK_PATH}")

# ================= HEALTH CHECK =================
@app.get("/")
async def root():
    return {"status": "ROW Safety Bot is running"}
