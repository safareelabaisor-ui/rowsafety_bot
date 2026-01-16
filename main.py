import os
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ======================
# Environment Variables
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL")  # https://rowsafety-bot.onrender.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = WEBHOOK_URL_BASE + WEBHOOK_PATH

# ======================
# FastAPI App
# ======================
app = FastAPI()

# ======================
# Telegram Application
# ======================
tg_app = Application.builder().token(BOT_TOKEN).build()

# ======================
# Telegram Handlers
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ ROW Safety AI Bot\n"
        "พิมพ์คำถามหน้างานได้เลย\n"
        "หรือพิมพ์ EMERGENCY"
    )

async def emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚨 EMERGENCY MODE\n"
        "1) หยุดงานทันที\n"
        "2) ถอยออกจากแนวสายไฟ\n"
        "3) ติดต่อผู้ควบคุมงาน"
    )

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()

    if "ฝน" in text:
        await update.message.reply_text(
            "⚠️ ฝนตก: ไม่ควรทำงานใกล้สายไฟแรงสูง"
        )
    elif "ลมแรง" in text:
        await update.message.reply_text(
            "⚠️ ลมแรง: เสี่ยงสายแกว่ง ควรหยุดงาน"
        )
    elif "ไฟดูด" in text:
        await update.message.reply_text(
            "🚨 ไฟดูด: ตัดแหล่งจ่ายไฟ และแจ้งหัวหน้างานทันที"
        )
    else:
        await update.message.reply_text(
            "รับทราบ กำลังประเมินสถานการณ์หน้างาน"
        )

# ======================
# Register Handlers
# ======================
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("emergency", emergency))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

# ======================
# Webhook Endpoint
# ======================
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

# ======================
# Health Check (optional)
# ======================
@app.get("/")
async def root():
    return {"status": "ROW Safety Bot is running"}

# ======================
# Startup Event
# ======================
@app.on_event("startup")
async def on_startup():
    await tg_app.initialize()
    await tg_app.bot.set_webhook(WEBHOOK_URL)
