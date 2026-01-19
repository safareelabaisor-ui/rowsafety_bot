import os
import json
from datetime import datetime

import httpx
import gspread
from fastapi import FastAPI, Request
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")          # https://xxx.onrender.com
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

if not BOT_TOKEN or not WEBHOOK_URL or not GOOGLE_CREDS_JSON:
    raise RuntimeError("❌ Missing ENV variables")

WEBHOOK_PATH = "/webhook"

# ================= GOOGLE SHEET =================
creds_dict = json.loads(GOOGLE_CREDS_JSON)

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)

# ต้อง share sheet ให้ service account ก่อน
sheet = gc.open("ROW_SAFETY_LOG").sheet1

# ================= FASTAPI + TELEGRAM =================
app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

# ================= UTIL =================
async def reverse_geocode(lat: float, lon: float):
    """
    แปลง lat/lng → จังหวัด / อำเภอ (ใช้ async ล้วน)
    """
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "zoom": 10,
        "addressdetails": 1,
    }
    headers = {"User-Agent": "rowsafety-bot"}

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params, headers=headers)
        data = r.json()

    addr = data.get("address", {})

    province = (
        addr.get("province")
        or addr.get("state")
        or addr.get("region")
        or "ไม่ทราบจังหวัด"
    )

    district = (
        addr.get("county")
        or addr.get("state_district")
        or addr.get("district")
        or "ไม่ทราบอำเภอ"
    )

    return province, district


def log_row(user, chat_id, text, location="", province="", district=""):
    """
    เขียน log ลง Google Sheet
    """
    sheet.append_row(
        [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user,
            chat_id,
            text,
            location,
            province,
            district,
        ],
        value_input_option="RAW",
    )

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    log_row(user, chat_id, "/start")

    await update.message.reply_text(
        "⚡ ROW Safety Bot\n\n"
        "• พิมพ์สถานการณ์หน้างาน\n"
        "• ส่ง Location 📍 เพื่อระบุจังหวัด/อำเภอ\n"
        "• พิมพ์ EMERGENCY เมื่อเกิดเหตุฉุกเฉิน"
    )


async def emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    log_row(user, chat_id, "EMERGENCY")

    await update.message.reply_text(
        "🚨 EMERGENCY MODE\n"
        "1) หยุดงานทันที\n"
        "2) ถอยออกจากแนวสายไฟ\n"
        "3) ติดต่อผู้ควบคุมงาน"
    )


async def text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    log_row(user, chat_id, text)

    if "ฝน" in text:
        await update.message.reply_text(
            "⚠️ ฝนตก: ไม่ควรทำงานใกล้สายไฟแรงสูง"
        )
    else:
        await update.message.reply_text(
            "รับทราบ กำลังประเมินสถานการณ์หน้างาน"
        )


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    lat = loc.latitude
    lon = loc.longitude

    province, district = await reverse_geocode(lat, lon)

    log_row(
        user=user,
        chat_id=chat_id,
        text="LOCATION",
        location=f"{lat},{lon}",
        province=province,
        district=district,
    )

    await update.message.reply_text(
        f"📍 รับตำแหน่งหน้างานแล้ว\n"
        f"จังหวัด: {province}\n"
        f"อำเภอ: {district}"
    )

# ================= REGISTER =================
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("emergency", emergency))
tg_app.add_handler(MessageHandler(filters.LOCATION, handle_location))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_reply))

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
    await tg_app.bot.set_webhook(f"{WEBHOOK_URL}{WEBHOOK_PATH}")
