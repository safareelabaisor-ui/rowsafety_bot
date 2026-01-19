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

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("WEBHOOK_URL")  # https://rowsafety-bot.onrender.com
WEBHOOK_PATH = f"/webhook"
WEBHOOK_URL = BASE_URL + WEBHOOK_PATH

LOG_DIR = "logs"
LOG_FILE = f"{LOG_DIR}/work_log.jsonl"

os.makedirs(LOG_DIR, exist_ok=True)

# ================= APP =================
app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

# ================= ANTI DUPLICATE =================
processed_updates = set()
MAX_CACHE = 1000

def is_duplicate(update_id: int) -> bool:
    if update_id in processed_updates:
        return True
    processed_updates.add(update_id)
    if len(processed_updates) > MAX_CACHE:
        processed_updates.pop()
    return False

# ================= LOGGER =================
def save_log(user_id: int, text: str, msg_type: str):
    log = {
        "time": datetime.utcnow().isoformat(),
        "user_id": user_id,
        "type": msg_type,
        "text": text,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_log(update.effective_user.id, "/start", "command")
    await update.message.reply_text(
        "⚡ ROW Safety AI Bot\n"
        "พิมพ์คำถามหน้างานได้เลย\n"
        "หรือพิมพ์ EMERGENCY"
    )

async def emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_log(update.effective_user.id, "EMERGENCY", "command")
    await update.message.reply_text(
        "🚨 EMERGENCY MODE\n"
        "1) หยุดงานทันที\n"
        "2) ถอยออกจากแนวสายไฟ\n"
        "3) ติดต่อผู้ควบคุมงาน"
    )

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    save_log(update.effective_user.id, text, "message")

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

# ================= WEBHOOK =================
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)

    if update and update.update_id:
        if is_duplicate(update.update_id):
            return {"ok": True}

        await tg_app.process_update(update)

    return {"ok": True}

# ================= STARTUP =================
@app.on_event("startup")
async def on_startup():
    await tg_app.initialize()
    await tg_app.bot.set_webhook(WEBHOOK_URL)

# ================= HEALTH CHECK =================
@app.get("/")
async def root():
    return {"status": "ROW Safety Bot running"}
