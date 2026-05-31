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

GRADE_MAP = {
    "Sahih": "Сахих (достоверный) ✅",
    "Hasan": "Хасан (хороший) 🟡",
    "Daif": "Да'иф (слабый) ⚠️",
    "Mawdu": "Мавду' (выдуманный) ❌",
    "Hasan Sahih": "Хасан Сахих ✅",
    "Sahih Hasan": "Сахих Хасан ✅",
}

def parse_hadith_query(text):
    text = text.lower().strip()
    for ru, en in COLLECTIONS.items():
        if text.startswith(ru):
            num = text.replace(ru, "").strip()
            if num.isdigit():
                return en, int(num)
    return None, None

def parse_quran_query(text):
    # formats: "коран 2:255" or "коран 2 255"
    text = text.lower().strip()
    if text.startswith("коран"):
        ref = text.replace("коран", "").strip()
        if ":" in ref:
            parts = ref.split(":")
        elif " " in ref:
            parts = ref.split()
        else:
            return None, None
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]), int(parts[1])
    return None, None

def get_hadith(collection, number):
    try:
        url_ru = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/rus-{collection}/{number}.min.json"
        url_ar = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/ara-{collection}/{number}.min.json"
        url_en = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/eng-{collection}/{number}.min.json"

        arabic, russian, english, grade = "", "", "", ""

        r_ar = requests.get(url_ar, timeout=15)
        if r_ar.status_code == 200:
            hadiths = r_ar.json().get("hadiths", [])
            if hadiths:
                arabic = hadiths[0].get("text", "")

        r_ru = requests.get(url_ru, timeout=15)
        if r_ru.status_code == 200:
            hadiths = r_ru.json().get("hadiths", [])
            if hadiths:
                h = hadiths[0]
                russian = h.get("text", "").replace("\\n", "\n")
                grades = h.get("grades", [])
                if grades:
                    g = grades[0].get("grade", "")
                    grade = GRADE_MAP.get(g, g)

        if not russian:
            r_en = requests.get(url_en, timeout=15)
            if r_en.status_code == 200:
                hadiths = r_en.json().get("hadiths", [])
                if hadiths:
                    h = hadiths[0]
                    english = h.get("text", "")
                    if not grade:
                        grades = h.get("grades", [])
                        if grades:
                            g = grades[0].get("grade", "")
                            grade = GRADE_MAP.get(g, g)

        translation = russian or english
        lang = "рус" if russian else "англ"

        if arabic or translation:
            return arabic, translation, lang, grade
    except Exception as e:
        print(f"Error: {e}")
    return "", "", "", ""

def get_quran_ayah(surah, ayah):
    try:
        # Arabic
        url_ar = f"https://cdn.jsdelivr.net/gh/fawazahmed0/quran-api@1/editions/ara-quranindopak/{surah}/{ayah}.min.json"
        # Russian (Kuliev)
        url_ru = f"https://cdn.jsdelivr.net/gh/fawazahmed0/quran-api@1/editions/rus-kuliev/{surah}/{ayah}.min.json"

        arabic, russian = "", ""

        r_ar = requests.get(url_ar, timeout=15)
        if r_ar.status_code == 200:
            data = r_ar.json()
            arabic = data.get("text", "")

        r_ru = requests.get(url_ru, timeout=15)
        if r_ru.status_code == 200:
            data = r_ru.json()
            russian = data.get("text", "")

        return arabic, russian
    except Exception as e:
        print(f"Quran error: {e}")
    return "", ""

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Check if Quran query
    surah, ayah = parse_quran_query(text)
    if surah and ayah:
        await update.message.reply_text("⏳ Ищу аят...")
        arabic, russian = get_quran_ayah(surah, ayah)

        if not arabic and not russian:
            await update.message.reply_text(
                f"❌ Аят {surah}:{ayah} не найден.\nПроверь номер суры и аята."
            )
            return

        msg = f"📖 *Коран, {surah}:{ayah}*\n\n"
        if arabic:
            msg += f"🔤 *Арабский текст:*\n{arabic}\n\n"
        if russian:
            msg += f"🌍 *Перевод (Кулиев):*\n{russian}\n"
        msg += f"\n📚 *Источник:* Священный Коран, сура {surah}, аят {ayah}"

        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # Check if Hadith query
    collection, number = parse_hadith_query(text)
    if collection and number:
        await update.message.reply_text("⏳ Ищу хадис...")
        arabic, translation, lang, grade = get_hadith(collection, number)

        if not arabic and not translation:
            await update.message.reply_text(
                f"❌ Хадис {NAMES.get(collection, collection)} №{number} не найден.\n"
                "Проверь номер и попробуй снова."
            )
            return

        msg = f"📖 *{NAMES.get(collection, collection)}, хадис №{number}*\n\n"

        if arabic:
            msg += f"🔤 *Арабский текст:*\n{arabic}\n\n"
        if translation:
            msg += f"🌍 *Перевод ({lang}):*\n{translation}\n"
        if grade:
            msg += f"\n📊 *Достоверность:* {grade}"

        msg += f"\n\n📚 *Источник:* {NAMES.get(collection, collection)}, хадис №{number}"

        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # Help message
    await update.message.reply_text(
        "📚 *Команды бота:*\n\n"
        "*Хадисы:*\n"
        "бухари 1\n"
        "муслим 2564\n"
        "абу дауд 4607\n"
        "тирмизи 2516\n"
        "ибн маджа 1\n"
        "насаи 1\n\n"
        "*Коран:*\n"
        "коран 2:255\n"
        "коран 36:1\n\n"
        "Формат: название + номер",
        parse_mode="Markdown"
    )

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
app.run_polling()
