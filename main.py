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
    knowledge = load_knowledge()

    for item in knowledge:
        keywords = item.get("keywords", "")
        for kw in keywords.split(","):
            if kw.strip().lower() in user_text:
                return f"{item['answer']}\n📌 อ้างอิง: {item.get('ref','')}"
    return None


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
            or addr.get("city")
            or "ไม่ทราบอำเภอ"
        )

        return province, district

    except Exception as e:
        print("Reverse geocode error:", e)
        return "ไม่ทราบจังหวัด", "ไม่ทราบอำเภอ"

def log_row(user, chat_id, text, location="", province="", district=""):
    thai_time = datetime.now(timezone(timedelta(hours=7)))
    
    log_sheet.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user,
        chat_id,
        text,
        location,
        province,
        district,
    ],
    value_input_option="USER_ENTERED"
    )

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    log_row(user, chat_id, "/start")

    await update.message.reply_text(
        "⚡ ROW Safety Bot\n"
        "พิมพ์คำถามจากคู่มือ หรือส่ง Location 📍\n"
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
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 วิธีใช้งาน ROW Safety Bot\n\n"
        "/start – เริ่มต้นใช้งาน\n"
        "/emergency – เหตุฉุกเฉิน\n"
        "/danger – อันตรายใกล้สายไฟ\n"
        "/safezone – ระยะปลอดภัย\n"
        "/weather – ฝน/พายุ\n"
        "/machine – เครื่องจักร/เครน\n\n"
        "หรือพิมพ์คำถามเป็นข้อความได้เลย"
    )

async def cmd_from_kb(update: Update, context: ContextTypes.DEFAULT_TYPE, keyword: str):
    answer = search_knowledge(keyword)
    if answer:
        await update.message.reply_text(f"📘 จากคู่มือ:\n{answer}")
    else:
        await update.message.reply_text("❌ ไม่พบข้อมูลในคู่มือ")

async def danger_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_from_kb(update, context, "อันตราย")

async def safezone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_from_kb(update, context, "ระยะปลอดภัย")

async def weather_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_from_kb(update, context, "ฝน")

async def machine_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_from_kb(update, context, "เครื่องจักร")


async def text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    log_row(user, chat_id, text)

    answer = search_knowledge(text)
    if answer:
        await update.message.reply_text(f"📘 จากคู่มือหน่วย:\n{answer}")
        return

    if "ฝน" in text:
        await update.message.reply_text("⚠️ ฝนตก: ห้ามทำงานใกล้สายไฟแรงสูง")
    else:
        await update.message.reply_text("รับทราบ หากต้องการข้อมูลเฉพาะ โปรดระบุเพิ่ม")

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    lat = loc.latitude
    lon = loc.longitude

    province, district = await reverse_geocode(lat, lon)

    log_row(
        user,
        chat_id,
        "LOCATION",
        f"{lat},{lon}",
        province,
        district,
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
tg_app.add_handler(CommandHandler("help", help_cmd))
tg_app.add_handler(CommandHandler("danger", danger_cmd))
tg_app.add_handler(CommandHandler("safezone", safezone_cmd))
tg_app.add_handler(CommandHandler("weather", weather_cmd))
tg_app.add_handler(CommandHandler("machine", machine_cmd))

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
