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

def get_hadith(collection, number):
    # Try hadith-api (no key needed)
    try:
        url = f"https://hadith-api.vercel.app/api/hadith/{collection}/{number}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            arabic = data.get("arabic", "")
            english = data.get("english", {}).get("text", "")
            if arabic or english:
                return arabic, english, ""
    except:
        pass

    # Try cdn.jsdelivr.net hadith database
    try:
        url = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/eng-{collection}/{number}.json"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            hadith = data.get("hadith", {})
            arabic = hadith.get("arabic", "")
            english = hadith.get("text", "")
            return arabic, english, ""
    except:
        pass

    return "", "", ""

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

    await update.message.reply_text("⏳ Ищу хадис...")

    arabic, english, grade = get_hadith(collection, number)

    if not arabic and not english:
        await update.message.reply_text(
            f"❌ Хадис {NAMES.get(collection, collection)} №{number} не найден.\n"
            "Проверь номер и попробуй снова."
        )
        return

    msg = f"📖 *{NAMES.get(collection, collection)}, хадис №{number}*\n\n"

    if arabic:
        msg += f"🔤 *Арабский текст:*\n{arabic}\n\n"

    if english:
        msg += f"🌍 *Перевод (англ):*\n{english}\n"

    if grade:
        msg += f"\n✅ *Степень:* {grade}"

    msg += f"\n\n📚 *Источник:* {NAMES.get(collection, collection)}"

    await update.message.reply_text(msg, parse_mode="Markdown")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
app.run_polling()
