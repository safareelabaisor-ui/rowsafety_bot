import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

WEBHOOK_PATH = "/webhook"
TH_TZ = ZoneInfo("Asia/Bangkok")

# ================= RISK KEYWORDS =================
DANGER_KEYWORDS = [
    "ฝน", "พายุ", "ฟ้าผ่า",
    "เครน", "รถเครน",
    "ตัดต้นไม้", "โค่นต้นไม้",
]

WARNING_KEYWORDS = [
    "ใกล้สาย", "เครื่องจักร",
    "รถ", "ยก", "ขุด", "เจาะ",
]

# ================= GOOGLE SHEET =================
creds_dict = json.loads(GOOGLE_CREDS_JSON)

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)

log_sheet = gc.open("ROW_SAFETY_LOG").sheet1
kb_sheet = gc.open("ROW_SAFETY_KNOWLEDGE").sheet1

# ================= FASTAPI + TELEGRAM =================
app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

# ================= KNOWLEDGE BASE =================
knowledge_cache = []

def load_knowledge():
    global knowledge_cache
    if not knowledge_cache:
        knowledge_cache = kb_sheet.get_all_records()
    return knowledge_cache

def search_knowledge(user_text: str):
    user_text = user_text.lower()
    for item in load_knowledge():
        for kw in item.get("keywords", "").split(","):
            if kw.strip().lower() in user_text:
                return f"{item['answer']}\n📌 อ้างอิง: {item.get('ref','')}"
    return None

# ================= RISK ASSESS =================
def assess_risk(text: str):
    text = text.lower()

    danger = any(k in text for k in DANGER_KEYWORDS)
    warning = any(k in text for k in WARNING_KEYWORDS)

    if danger:
        return (
            "🔴 อันตรายสูง",
            "❌ หยุดงานทันที\n"
            "⚡ เสี่ยงต่อสายไฟแรงสูง\n"
            "📞 แจ้งหัวหน้างาน"
        )

    if warning:
        return (
            "🟡 เฝ้าระวัง",
            "⚠️ ตรวจสอบระยะปลอดภัย\n"
            "👷‍♂️ สวมอุปกรณ์ป้องกัน\n"
            "👀 ควบคุมงานใกล้ชิด"
        )

    return "🟢 ปกติ", "✅ ยังไม่พบความเสี่ยงร้ายแรง"

# ================= UTIL =================
async def reverse_geocode(lat: float, lon: float):
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
        province = addr.get("province") or addr.get("state") or "ไม่ทราบจังหวัด"
        district = (
            addr.get("county")
            or addr.get("state_district")
            or addr.get("district")
            or "ไม่ทราบอำเภอ"
        )
        return province, district

    except Exception:
        return "ไม่ทราบจังหวัด", "ไม่ทราบอำเภอ"

def log_row(user, chat_id, text, location="", province="", district=""):
    now_th = datetime.now(TH_TZ).strftime("%Y-%m-%d %H:%M:%S")
    log_sheet.append_row(
        [now_th, user, chat_id, text, location, province, district],
        value_input_option="USER_ENTERED",
    )

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id
    log_row(user, chat_id, "/start")

    await update.message.reply_text(
        "⚡ ROW Safety Bot\n"
        "พิมพ์สถานการณ์หน้างาน หรือส่ง Location 📍\n"
        "พิมพ์ /help เพื่อดูคำสั่ง\n"
        "พิมพ์ คู่มือ เพื่อหาข้อมูล\n"
        "พิมพ์คำถามจากคู่มือ\n"
        "พิมพ์ EMERGENCY เมื่อเกิดเหตุฉุกเฉิน"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 คำสั่งที่ใช้ได้\n\n"
        "/start\n/help\n/emergency\n"
        "/danger /safezone /weather /machine\n\n"
        "หรือพิมพ์สถานการณ์หน้างานได้เลย"
    )

async def emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_row(update.effective_user.username, update.effective_chat.id, "EMERGENCY")
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

    kb = search_knowledge(text)
    if kb:
        await update.message.reply_text(f"📘 จากคู่มือ:\n{kb}")
        return

    level, msg = assess_risk(text)
    await update.message.reply_text(
        f"📊 ประเมินความเสี่ยง: {level}\n\n{msg}"
    )

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    province, district = await reverse_geocode(loc.latitude, loc.longitude)

    log_row(
        update.effective_user.username,
        update.effective_chat.id,
        "LOCATION",
        f"{loc.latitude},{loc.longitude}",
        province,
        district,
    )

    await update.message.reply_text(
        f"📍 ตำแหน่งหน้างาน\n"
        f"จังหวัด: {province}\n"
        f"อำเภอ: {district}"
    )

# ================= REGISTER =================
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("help", help_cmd))
tg_app.add_handler(CommandHandler("emergency", emergency))
tg_app.add_handler(MessageHandler(filters.LOCATION, handle_location))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_reply))

# ================= WEBHOOK =================
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    update = Update.de_json(await request.json(), tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.on_event("startup")
async def on_startup():
    await tg_app.initialize()
    await tg_app.bot.set_webhook(f"{WEBHOOK_URL}{WEBHOOK_PATH}")
