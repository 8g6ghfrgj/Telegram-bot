import os
import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
    CommandHandler,
    CallbackQueryHandler
)

# ===============================
# إعدادات أساسية
# ===============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 4
MAX_WORKERS = 20

# ===============================
# أدوات مساعدة
# ===============================
def clean_text(text: str) -> str:
    return (
        text.replace("*", "")
        .replace("(", "")
        .replace(")", "")
        .replace("[", "")
        .replace("]", "")
        .strip()
    )


def extract_links(text: str):
    return re.findall(r'https?://t\.me/[^\s]+', text)


def normalize(url: str) -> str:
    return url.strip().rstrip("/").lower()


def is_bot(url: str) -> bool:
    return url.split("/")[-1].endswith("bot")


def is_group_join(url: str) -> bool:
    return "joinchat" in url or "+" in url


def estimate_time(count: int) -> str:
    sec = max(1, int((count * TIMEOUT) / MAX_WORKERS))
    return f"⏳ تقريبًا {sec} ثانية"


def is_alive(url: str) -> bool:
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True
        )
        return r.status_code < 400
    except:
        return False


# ===============================
# /start
# ===============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 بوت تصفية وترتيب روابط تيليجرام\n\n"
        "📄 أرسل ملف TXT\n\n"
        "• تقسيم احترافي\n"
        "• بدون تكرار\n"
        "• بدون تداخل\n"
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
    lines = (await file.download_as_bytearray()).decode(
        "utf-8", errors="ignore"
    ).splitlines()

    channels, groups, bots, messages = set(), set(), set(), set()
    used_links = set()
    seen_msg_groups = set()

    for line in lines:
        line = clean_text(line)
        if "t.me/" not in line:
            continue

        for raw in extract_links(line):
            link = normalize(raw)

            if link in used_links:
                continue

            # روابط رسائل
            if "/c/" in link:
                gid = re.search(r'/c/(\d+)', link)
                if gid and gid.group(1) not in seen_msg_groups:
                    messages.add(link)
                    seen_msg_groups.add(gid.group(1))
                    used_links.add(link)
                continue

            # بوتات
            if is_bot(link):
                bots.add(link)
                used_links.add(link)
                continue

            # مجموعات
            if is_group_join(link):
                groups.add(link)
                used_links.add(link)
                continue

            # قنوات
            channels.add(link)
            used_links.add(link)

    files = {
        "channels.txt": ("📢 روابط القنوات", channels),
        "groups.txt": ("👥 روابط المجموعات", groups),
        "bots.txt": ("🤖 روابط البوتات", bots),
        "messages.txt": ("📨 روابط الرسائل", messages),
    }

    for fname, (title, data) in files.items():
        if not data:
            continue

        with open(fname, "w", encoding="utf-8") as f:
            for link in sorted(data):
                f.write(link + "\n")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🧹 تصفية الروابط الميتة",
                callback_data=f"clean::{fname}"
            )]
        ])

        await update.message.reply_document(
            open(fname, "rb"),
            caption=f"{title}\n📊 العدد: {len(data)}",
            reply_markup=keyboard
        )

    await update.message.reply_text("✅ تم التقسيم بنجاح")


# ===============================
# زر تنظيف الروابط الميتة
# ===============================
async def clean_dead_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    fname = query.data.split("::")[1]

    with open(fname, "r", encoding="utf-8") as f:
        links = list(set(normalize(l) for l in f if l.strip()))

    await query.edit_message_caption(
        f"🧹 جاري تصفية {len(links)} رابط\n{estimate_time(len(links))}"
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
# تشغيل البوت
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
