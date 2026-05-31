import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("TOKEN")

COLLECTIONS = {
    "бухари": "bukhari",
    "муслим": "muslim",
    "абу дауд": "abudawud",
    "тирмизи": "tirmidhi",
    "ибн маджа": "ibnmajah",
    "насаи": "nasai",
}

NAMES = {
    "bukhari": "Сахих аль-Бухари",
    "muslim": "Сахих Муслим",
    "abudawud": "Сунан Абу Дауда",
    "tirmidhi": "Сунан ат-Тирмизи",
    "ibnmajah": "Сунан Ибн Маджа",
    "nasai": "Сунан ан-Насаи",
}

def parse_query(text):
    text = text.lower().strip()
    for ru, en in COLLECTIONS.items():
        if text.startswith(ru):
            num = text.replace(ru, "").strip()
            if num.isdigit():
                return en, int(num)
    return None, None

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    collection, number = parse_query(text)

    if not collection or not number:
        await update.message.reply_text(
            "Напиши например:\n\n"
            "бухари 1\n"
            "муслим 2564\n"
            "абу дауд 4607\n"
            "тирмизи 2516\n"
            "ибн маджа 1\n"
            "насаи 1"
        )
        return

    url = f"https://api.sunnah.com/v1/hadiths/{collection}:{number}"
    headers = {"X-API-Key": os.environ.get("SUNNAH_API_KEY", "")}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()

        arabic = data.get("arabic", "")
        english = ""
        for lang in data.get("translations", []):
            if lang.get("lang") == "en":
                english = lang.get("body", "")
                break
        if not english:
            english = data.get("text", "нет перевода")

        grade = data.get("grades", [{}])
        grade_text = grade[0].get("grade", "") if grade else ""

        msg = (
            f"📖 *{NAMES.get(collection, collection)}, хадис №{number}*\n\n"
            f"🔤 *Арабский текст:*\n{arabic}\n\n"
            f"🌍 *Перевод (англ):*\n{english}\n"
        )
        if grade_text:
            msg += f"\n✅ *Степень:* {grade_text}"

        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text("Не удалось найти хадис. Проверь номер и попробуй снова.")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
app.run_polling()
