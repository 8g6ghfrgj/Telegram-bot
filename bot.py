import os
import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
    CommandHandler,
    CallbackQueryHandler
)

# ===============================
# إعدادات
# ===============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 4
MAX_WORKERS = 20

# ===============================
# أدوات عامة
# ===============================
def extract_links(text: str):
    return re.findall(r'https?://[^\s]+', text)


def normalize(url: str) -> str:
    url = url.strip()
    url = re.split(r'[^\w:/?=&.+-]', url)[0]
    return url.lower().rstrip("/")


def strip_query(url: str) -> str:
    return url.split("?")[0]


def estimate_time(count: int) -> str:
    sec = max(1, int((count * TIMEOUT) / MAX_WORKERS))
    return f"⏳ تقريبًا {sec} ثانية"


def is_alive(url: str) -> bool:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        return r.status_code < 400
    except:
        return False


# ===============================
# Telegram rules
# ===============================
def is_telegram(url: str) -> bool:
    return "t.me/" in url or "telegram.me/" in url


def tg_is_bot(url: str) -> bool:
    name = url.split("/")[-1].split("?")[0]
    return name.endswith("bot")


def tg_is_message(url: str) -> bool:
    return bool(re.search(r'/\d+$', url) or "/c/" in url)


def tg_is_group(url: str) -> bool:
    return "joinchat" in url or "+" in url


# ===============================
# WhatsApp rules
# ===============================
def is_whatsapp(url: str) -> bool:
    return "chat.whatsapp.com" in url or "wa.me/" in url


# ===============================
# /start
# ===============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 بوت ترتيب وتصفية جميع الروابط\n\n"
        "📄 أرسل ملف TXT\n\n"
        "• Telegram / WhatsApp / Other\n"
        "• تصنيف احترافي\n"
        "• بدون تكرار\n"
        "• زر لتنظيف الروابط الميتة"
    )


# ===============================
# معالجة الملف
# ===============================
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ أرسل ملف TXT فقط")
        return

    await update.message.reply_text("⚡ جاري تحليل وترتيب الروابط...")

    file = await doc.get_file()
    lines = (await file.download_as_bytearray()).decode("utf-8", errors="ignore").splitlines()

    tg_channels, tg_groups, tg_bots, tg_messages = set(), set(), set(), set()
    wa_groups, wa_numbers = set(), set()
    other_links = set()
    seen = set()

    for line in lines:
        for raw in extract_links(line):
            link = normalize(raw)
            if not link.startswith("http"):
                continue

            base = strip_query(link)
            if base in seen:
                continue

            # ===== Telegram =====
            if is_telegram(link):

                if tg_is_message(link):
                    tg_messages.add(link)
                    seen.add(base)
                    continue

                if tg_is_bot(link):
                    tg_bots.add(base)
                    seen.add(base)
                    continue

                if tg_is_group(link):
                    tg_groups.add(link)
                    seen.add(base)
                    continue

                tg_channels.add(link)
                seen.add(base)
                continue

            # ===== WhatsApp =====
            if is_whatsapp(link):
                if "chat.whatsapp.com" in link:
                    wa_groups.add(link)
                else:
                    wa_numbers.add(link)

                seen.add(base)
                continue

            # ===== Other =====
            other_links.add(link)
            seen.add(base)

    files = {
        "tg_channels.txt": ("📢 Telegram Channels", tg_channels),
        "tg_groups.txt": ("👥 Telegram Groups", tg_groups),
        "tg_bots.txt": ("🤖 Telegram Bots", tg_bots),
        "tg_messages.txt": ("📨 Telegram Messages", tg_messages),
        "wa_groups.txt": ("👥 WhatsApp Groups", wa_groups),
        "wa_numbers.txt": ("📱 WhatsApp Numbers", wa_numbers),
        "other_links.txt": ("🌐 Other Links", other_links),
    }

    for fname, (title, data) in files.items():
        if not data:
            continue

        with open(fname, "w", encoding="utf-8") as f:
            for link in sorted(data):
                f.write(link + "\n")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧹 تصفية الروابط الميتة", callback_data=f"clean::{fname}")]
        ])

        await update.message.reply_document(
            open(fname, "rb"),
            caption=f"{title}\n📊 العدد: {len(data)}",
            reply_markup=keyboard
        )

    await update.message.reply_text("✅ تم التقسيم والتنظيف بالكامل")


# ===============================
# تصفية الروابط الميتة
# ===============================
async def clean_dead_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    fname = query.data.split("::")[1]

    with open(fname, "r", encoding="utf-8") as f:
        links = list(set(l.strip() for l in f if l.strip()))

    await query.edit_message_caption(
        f"🧹 تصفية {len(links)} رابط\n{estimate_time(len(links))}"
    )

    start_time = time.time()
    alive = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(is_alive, url): url for url in links}
        for future in as_completed(futures):
            if future.result():
                alive.append(futures[future])

    with open(fname, "w", encoding="utf-8") as f:
        for link in sorted(alive):
            f.write(link + "\n")

    duration = int(time.time() - start_time)

    await query.message.reply_document(
        open(fname, "rb"),
        caption=(
            "✅ تم تنظيف الملف\n"
            f"📊 المتبقي: {len(alive)} رابط نشط\n"
            f"⏱ الوقت: {duration} ثانية"
        )
    )


# ===============================
# تشغيل
# ===============================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(clean_dead_links, pattern=r"^clean::"))

    print("🤖 Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
