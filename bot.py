import os
import re
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
# إعدادات
# ===============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 3
MAX_WORKERS = 20  # مناسب لـ Render

# ===============================
# أدوات ترتيب فقط (بدون شبكة)
# ===============================
def clean_link(text: str) -> str:
    return (
        text.replace("*", "")
        .replace("(", "")
        .replace(")", "")
        .replace("[", "")
        .replace("]", "")
        .strip()
    )


def extract_links(line: str):
    return re.findall(r'https?://t\.me/[^\s]+', line)


def is_bot(link: str) -> bool:
    return link.rstrip("/").split("/")[-1].lower().endswith("bot")


def is_group_join(link: str) -> bool:
    return "joinchat" in link or "+" in link


# ===============================
# فحص الروابط الميتة (يُستخدم فقط مع الزر)
# ===============================
def is_alive_fast(url: str) -> bool:
    try:
        r = requests.head(
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
        "🤖 بوت تصفية روابط تيليجرام\n\n"
        "📄 أرسل ملف TXT\n\n"
        "• سأعطيك الملفات فورًا\n"
        "• بدون فحص روابط\n"
        "• بعدها زر لتصفية الروابط الميتة لكل ملف"
    )


# ===============================
# التصفية السريعة (بدون شبكة)
# ===============================
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ أرسل ملف TXT فقط")
        return

    await update.message.reply_text("⚡ جاري ترتيب الروابط...")

    file = await doc.get_file()
    lines = (await file.download_as_bytearray()).decode("utf-8", errors="ignore").splitlines()

    channels, groups, bots, messages = set(), set(), set(), set()
    seen_msg_groups = set()

    for line in lines:
        line = clean_link(line)
        if "t.me/" not in line:
            continue

        for link in extract_links(line):

            # روابط رسائل
            if "/c/" in link:
                gid = re.search(r'/c/(\d+)', link)
                if gid and gid.group(1) not in seen_msg_groups:
                    messages.add(link)
                    seen_msg_groups.add(gid.group(1))
                continue

            # بوتات
            if is_bot(link):
                bots.add(link)
                continue

            # مجموعات انضمام
            if is_group_join(link):
                groups.add(link)
                continue

            # الباقي قنوات
            channels.add(link)

    files = {
        "channels.txt": ("📢 روابط القنوات", channels),
        "groups.txt": ("👥 روابط المجموعات", groups),
        "messages.txt": ("📨 روابط الرسائل", messages),
        "bots.txt": ("🤖 روابط البوتات", bots),
    }

    for fname, (title, data) in files.items():
        with open(fname, "w", encoding="utf-8") as f:
            for link in sorted(data):
                f.write(link + "\n")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧹 تصفية الروابط الميتة", callback_data=f"clean::{fname}")]
        ])

        await update.message.reply_document(
            open(fname, "rb"),
            caption=title,
            reply_markup=keyboard
        )

        # حفظ الملف للزر
        context.bot_data[fname] = fname

    await update.message.reply_text("✅ تم إرسال الملفات فورًا")


# ===============================
# زر تصفية الروابط الميتة (هنا فقط يوجد شبكة)
# ===============================
async def clean_dead_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    fname = query.data.split("::")[1]

    await query.edit_message_caption("🧹 جاري تصفية الروابط الميتة...")

    with open(fname, "r", encoding="utf-8") as f:
        links = [l.strip() for l in f if l.strip()]

    alive = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(is_alive_fast, url): url for url in links}
        for future in as_completed(futures):
            if future.result():
                alive.append(futures[future])

    alive_file = f"alive_{fname}"
    with open(alive_file, "w", encoding="utf-8") as f:
        for link in sorted(alive):
            f.write(link + "\n")

    await query.message.reply_document(
        open(alive_file, "rb"),
        caption="✅ الروابط النشطة فقط"
    )

    os.remove(alive_file)


# ===============================
# تشغيل
# ===============================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(clean_dead_links, pattern=r"^clean::"))
    print("🤖 Bot running (FAST correct flow)...")
    app.run_polling()


if __name__ == "__main__":
    main()
