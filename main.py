import os
import json
from datetime import datetime

import httpx
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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")          # https://xxxx.onrender.com
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

# ================= FASTAPI + TELEGRAM =================
app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

# ================= UTIL =================
async def reverse_geocode(lat: float, lon: float):
    """
    แปลง lat/lon → จังหวัด / อำเภอ (รองรับประเทศไทย)
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

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()

        addr = data.get("address", {})

        province = (
            addr.get("province")
            or addr.get("state")          # จังหวัด (TH)
            or addr.get("region")
            or "ไม่ทราบจังหวัด"
        )

        district = (
            addr.get("county")            # อำเภอ (TH)
            or addr.get("state_district")
            or addr.get("district")
            or addr.get("city")
            or "ไม่ทราบอำเภอ"
        )

        return province, district

    except Exception as e:
        print("Reverse geocode error:", e)
        return "ไม่ทราบจังหวัด", "ไม่ทราบอำเภอ"


def log_row(user, chat_id, text, location="", province="", district=""):
    """
    บันทึกข้อมูลลง Google Sheet
    """
    sheet.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user,
        chat_id,
        text,
        location,
        province,
        district,
    ])


# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    log_row(user, chat_id, "/start")

    await update.message.reply_text(
        "⚡ ROW Safety Bot\n"
        "พิมพ์สถานการณ์หน้างาน หรือส่ง Location 📍\n"
        "พิมพ์ EMERGENCY เมื่อเกิดเหตุฉุกเฉิน"
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
            "⚠️ ฝนตก: ห้ามทำงานใกล้สายไฟแรงสูง"
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
        f"พิกัด: {lat}, {lon}\n"
        f"จังหวัด: {province}\n"
        f"อำเภอ: {district}"
    )


# ================= REGISTER HANDLERS =================
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
