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

def search_knowledge(text: str):
    text = text.lower()
    for item in load_knowledge():
        for kw in item.get("keywords", "").split(","):
            if kw.strip().lower() in text:
                return f"{item['answer']}\n📌 อ้างอิง: {item.get('ref','')}"
    return None

# ================= AREA RISK CONFIG =================
HIGH_RISK_DISTRICTS = [
    "อำเภอคลองหลวง",
]

HIGH_RISK_SUBDISTRICTS = [
    "คลองสาม",
    "คลองหนึ่ง",
]

# ================= RISK ASSESSMENT =================
def assess_risk(
    text: str = "",
    is_location: bool = False,
    subdistrict: str = "",
    district: str = "",
):
    text = text.lower()

    # 🔴 พื้นที่เสี่ยง
    if district in HIGH_RISK_DISTRICTS or subdistrict in HIGH_RISK_SUBDISTRICTS:
        return (
            "🔴 อันตรายสูง",
            "พื้นที่เสี่ยงเฉพาะ ต้องขออนุญาตและควบคุมงานเข้มงวด"
        )

    # 🔴 keyword เสี่ยงสูง
    high_keywords = [
        "สายไฟ", "ไฟแรงสูง", "พายุ", "ฝนตกหนัก",
        "เครน", "รถเครน", "ตัดต้นไม้ใกล้สายไฟ"
    ]

    for kw in high_keywords:
        if kw in text:
            return (
                "🔴 อันตรายสูง",
                "❌ หยุดงานทันที เสี่ยงไฟฟ้าดูด/ลัดวงจร"
            )

    # 🟡 หน้างานจริง
    if is_location:
        return (
            "🟡 เสี่ยงปานกลาง",
            "เป็นหน้างานจริง ควรตรวจสอบแนวสายไฟและใช้ PPE"
        )

    # 🟡 keyword กลาง
    medium_keywords = ["ฝน", "ลม", "เครื่องจักร", "รถบรรทุก"]
    for kw in medium_keywords:
        if kw in text:
            return (
                "🟡 เสี่ยงปานกลาง",
                "เพิ่มการควบคุมงานและเว้นระยะปลอดภัย"
            )

    # 🟢 ปกติ
    return (
        "🟢 ปกติ",
        "ยังไม่พบความเสี่ยงร้ายแรง ปฏิบัติตามมาตรฐานความปลอดภัย"
    )

# ================= GEO =================
async def reverse_geocode(lat: float, lon: float):
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "zoom": 18,
        "addressdetails": 1,
    }
    headers = {"User-Agent": "rowsafety-bot"}

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()

        addr = data.get("address", {})

        # 🇹🇭 Mapping สำหรับประเทศไทย (สำคัญ)
        village = addr.get("village") or "-"
        subdistrict = (
            addr.get("suburb")
            or addr.get("town")
            or addr.get("village")
            or "-"
        )
        district = (
            addr.get("county")
            or addr.get("city_district")
            or "-"
        )
        province = (
            addr.get("province")
            or addr.get("state")
            or "-"
        )

        return {
            "village": village,
            "subdistrict": subdistrict,
            "district": district.replace("อำเภอ", "").strip(),
            "province": province.replace("จังหวัด", "").strip(),
            "postcode": addr.get("postcode", "-"),
            "country": addr.get("country", "-"),
        }

    except Exception as e:
        print("Reverse geocode error:", e)
        return {
            "village": "-",
            "subdistrict": "-",
            "district": "-",
            "province": "-",
            "postcode": "-",
            "country": "-",
        }


    except Exception as e:
        print("Reverse geocode error:", e)
        return {
            "village": "-",
            "subdistrict": "-",
            "district": "-",
            "province": "-",
            "postcode": "-",
            "country": "-",
        }


# ================= LOG =================
def log_row(
    user,
    chat_id,
    text,
    location="",
    village="",
    subdistrict="",
    district="",
    province="",
    postcode="",
    country="",
    risk_level="",
):
    now_th = datetime.now(TH_TZ).strftime("%Y-%m-%d %H:%M:%S")
    log_sheet.append_row(
        [
            now_th,
            user,
            chat_id,
            text,
            location,
            village,
            subdistrict,
            district,
            province,
            postcode,
            country,
            risk_level,
        ],
        value_input_option="USER_ENTERED",
    )

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ ROW Safety Bot ⚡\n"
        "พิมพ์สถานการณ์หน้างาน หรือส่ง Location 📍\n"
        "พิมพ์ คู่มือ เพื่อเข้าดูข้อมูลเล่มแดง \n"
        "พิมพ์ /help เพื่อดูคำสั่ง\n"
        "พิมพ์ คู่มือ เพื่อหาข้อมูล\n"
        "พิมพ์ EMERGENCY เมื่อเกิดเหตุฉุกเฉิน"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 คำสั่งที่ใช้งานได้\n\n"
        "/start – เริ่มต้น\n"
        "/help – วิธีใช้งาน\n"
        "/emergency – เหตุฉุกเฉิน\n"
        "/danger – อันตราย\n"
        "/weather – ฝน/พายุ\n"
        "/machine – เครื่องจักร\n\n"
        "/safezone – ระยะปลอดภัย\n"
        "พิมพ์ข้อความเพื่อประเมินความเสี่ยง\n"
        "ส่ง Location เพื่อประเมินพื้นที่"
    )

async def emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_row(
        update.effective_user.username or "unknown",
        update.effective_chat.id,
        "EMERGENCY",
        risk_level="🔴 อันตรายสูง",
    )
    await update.message.reply_text(
        "🚨 EMERGENCY MODE\n"
        "1) หยุดงานทันที\n"
        "2) ถอยออกจากแนวสายไฟ\n"
        "3) ติดต่อผู้ควบคุมงาน\n"
        "🚨 EMERGENCY 🚨"
    )

async def text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    risk, advice = assess_risk(text)
    kb = search_knowledge(text)

    log_row(user, chat_id, text, risk_level=risk)

    msg = []
    if kb:
        msg.append(f"📘 จากคู่มือ:\n{kb}")
    msg.append(f"📊 ระดับความเสี่ยง: {risk}\n{advice}")

    await update.message.reply_text("\n\n".join(msg))

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    user = update.effective_user.username or "unknown"
    chat_id = update.effective_chat.id

    addr = await reverse_geocode(loc.latitude, loc.longitude)

    risk, advice = assess_risk(
        is_location=True,
        subdistrict=addr["subdistrict"],
        district=addr["district"],
    )

    log_row(
        user,
        chat_id,
        "LOCATION",
        f"{loc.latitude},{loc.longitude}",
        addr["village"],
        addr["subdistrict"],
        addr["district"],
        addr["province"],
        addr["postcode"],
        addr["country"],
        risk,
    )

    await update.message.reply_text(
        f"📍 พิกัดหน้างาน\n"
        f"ตำบล: {addr['subdistrict']}\n"
        f"อำเภอ: {addr['district']}\n"
        f"จังหวัด: {addr['province']}\n\n"
        f"📊 ความเสี่ยงพื้นที่: {risk}\n{advice}"
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
