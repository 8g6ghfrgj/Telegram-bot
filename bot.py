import os
import re
import time
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
    CommandHandler
)

# ===============================
# قراءة التوكن من Render Environment
# ===============================
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

# ===============================
# أدوات
# ===============================
def clean_link(link: str) -> str:
    return (
        link.replace("*", "")
        .replace("(", "")
        .replace(")", "")
        .replace("[", "")
        .replace("]", "")
        .strip()
    )


def extract_links(line: str):
    return re.findall(r'https?://t\.me/[^\s]+', line)


# ===============================
# أوامر
# ===============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 بوت تصفية روابط تيليجرام\n\n"
        "📄 أرسل ملف TXT يحتوي على روابط\n\n"
        "الميزات:\n"
        "• تنظيف الروابط\n"
        "• حذف التكرار\n"
        "• تقسيم (قنوات / مجموعات / رسائل)\n"
        "• حساب وقت انتظار تقديري\n"
        "• إرسال الملفات تلقائيًا\n\n"
        "⚠️ لا يتم فحص الروابط الميتة (للسرعة)"
    )


# ===============================
# معالجة الملف
# ===============================
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document

    if not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ أرسل ملف TXT فقط")
        return

    # تحميل الملف
    file = await doc.get_file()
    content = await file.download_as_bytearray()
    lines = content.decode("utf-8", errors="ignore").splitlines()

    total_lines = len(lines)

    # حساب وقت تقديري
    speed = 10000  # سطر / دقيقة
    est_minutes = max(1, total_lines // speed)

    status_msg = await update.message.reply_text(
        f"📥 تم استلام الملف\n"
        f"📊 عدد الأسطر: {total_lines}\n"
        f"⏳ وقت الانتظار المتوقع: ~ {est_minutes} دقيقة\n\n"
        f"⚙️ جاري التصفية..."
    )

    channels_file = "channels.txt"
    groups_file = "groups.txt"
    messages_file = "messages.txt"

    channels = set()
    groups = set()
    message_groups_seen = set()

    start_time = time.time()

    with open(channels_file, "w", encoding="utf-8") as fc, \
         open(groups_file, "w", encoding="utf-8") as fg, \
         open(messages_file, "w", encoding="utf-8") as fm:

        for line in lines:
            line = clean_link(line)
            if "t.me/" not in line:
                continue

            for link in extract_links(line):

                # رسالة
                if "/c/" in link:
                    gid = re.search(r'/c/(\d+)', link)
                    if gid and gid.group(1) not in message_groups_seen:
                        fm.write(link + "\n")
                        message_groups_seen.add(gid.group(1))
                    continue

                # مجموعة
                if "joinchat" in link or "+" in link:
                    if link not in groups:
                        fg.write(link + "\n")
                        groups.add(link)
                    continue

                # قناة (افتراضي)
                if link not in channels:
                    fc.write(link + "\n")
                    channels.add(link)

    elapsed = int(time.time() - start_time)

    # إرسال الملفات
    await update.message.reply_document(
        open(channels_file, "rb"),
        caption=f"📢 روابط القنوات\n⏱️ الزمن: {elapsed} ثانية"
    )
    await update.message.reply_document(
        open(groups_file, "rb"),
        caption="👥 روابط المجموعات"
    )
    await update.message.reply_document(
        open(messages_file, "rb"),
        caption="📨 روابط الرسائل"
    )

    # تنظيف
    os.remove(channels_file)
    os.remove(groups_file)
    os.remove(messages_file)

    await status_msg.edit_text(
        f"✅ انتهت التصفية بنجاح\n"
        f"⏱️ الزمن الفعلي: {elapsed} ثانية"
    )


# ===============================
# تشغيل
# ===============================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("🤖 Bot is running on Render...")
    app.run_polling()


if __name__ == "__main__":
    main()
