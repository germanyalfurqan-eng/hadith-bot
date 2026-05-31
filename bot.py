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
    try:
        url_en = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/eng-{collection}/{number}.min.json"
        url_ar = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/ara-{collection}/{number}.min.json"
        
        r_en = requests.get(url_en, timeout=15)
        r_ar = requests.get(url_ar, timeout=15)
        
        english = ""
        arabic = ""
        
        if r_en.status_code == 200:
            hadiths = r_en.json().get("hadiths", [])
            if hadiths:
                english = hadiths[0].get("text", "")
        
        if r_ar.status_code == 200:
            hadiths = r_ar.json().get("hadiths", [])
            if hadiths:
                arabic = hadiths[0].get("text", "")
        
        if arabic or english:
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
