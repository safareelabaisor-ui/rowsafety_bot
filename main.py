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

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)
sheet = gc.open("ROW_SAFETY_LOG").sheet1

# ================= FASTAPI =================
app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

# ================= กันข้อความซ้ำ =================
LAST_UPDATE_ID = set()

def is_duplicate(update_id: int) -> bool:
    if update_id in LAST_UPDATE_ID:
        return True
    LAST_UPDATE_ID.add(update_id)
    if len(LAST_UPDATE_ID) > 1000:
        LAST_UPDATE_ID.clear()
    return False

# ================= LOG =================
def log_to_sheet(username, chat_id, message, location="-"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([now, username, chat_id, message, location])

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_duplicate(update.update_id):
        return

    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    log_to_sheet(user, chat_id, "/start")

    await update.message.reply_text(
        "⚡ ROW Safety AI Bot\n"
        "พิมพ์สถานการณ์หน้างาน\n"
        "หรือพิมพ์ EMERGENCY\n"
        "📍 สามารถส่ง Location ได้"
    )

async def emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_duplicate(update.update_id):
        return

    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    log_to_sheet(user, chat_id, "EMERGENCY")

    await update.message.reply_text(
        "🚨 EMERGENCY MODE\n"
        "1) หยุดงานทันที\n"
        "2) ถอยออกจากแนวสายไฟ\n"
        "3) ติดต่อผู้ควบคุมงาน"
    )

# ===== ข้อความธรรมดา =====
async def reply_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_duplicate(update.update_id):
        return

    text = update.message.text
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    log_to_sheet(user, chat_id, text)

    if "ฝน" in text:
        await update.message.reply_text(
            "⚠️ ฝนตก: ห้ามทำงานใกล้สายไฟแรงสูง"
        )
    else:
        await update.message.reply_text(
            "รับทราบ กำลังประเมินสถานการณ์หน้างาน"
        )

# ===== รับ Location =====
async def reply_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_duplicate(update.update_id):
        return

    loc = update.message.location
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    location_text = f"{loc.latitude},{loc.longitude}"

    log_to_sheet(
        user=user,
        chat_id=chat_id,
        message="ส่งพิกัดหน้างาน",
        location=location_text
    )

    await update.message.reply_text(
        f"📍 รับพิกัดแล้ว\nLat: {loc.latitude}\nLng: {loc.longitude}"
    )

# ================= REGISTER =================
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("emergency", emergency))
tg_app.add_handler(MessageHandler(filters.LOCATION, reply_location))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_text))

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
