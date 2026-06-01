import os
import re
import random
import requests
from html import unescape
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

COLLECTIONS = {
    "бухари": "bukhari",
    "муслим": "muslim",
    "абу дауд": "abudawud",
    "тирмизи": "tirmidhi",
    "ибн маджа": "ibnmajah",
    "насаи": "nasai",
    "муватта": "malik",
    "ахмад": "ahmad",
    "дарими": "darimi",
    "байхаки": "bayhaqi",
    "хаким": "hakim",
    "адаб": "adab",
}

NAMES = {
    "bukhari": "Сахих аль-Бухари",
    "muslim": "Сахих Муслим",
    "abudawud": "Сунан Абу Дауда",
    "tirmidhi": "Сунан ат-Тирмизи",
    "ibnmajah": "Сунан Ибн Маджа",
    "nasai": "Сунан ан-Насаи",
    "malik": "Муватта имама Малика",
    "ahmad": "Муснад имама Ахмада",
    "darimi": "Сунан ад-Дарими",
    "bayhaqi": "Сунан аль-Байхаки",
    "hakim": "Мустадрак аль-Хакима",
    "adab": "Аль-Адаб аль-Муфрад",
}

# Примерные максимальные номера хадисов для случайного выбора
MAX_HADITH = {
    "bukhari": 7563,
    "muslim": 3033,
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
    # Проверяем специальные команды
    if text == "случайный":
        return "random", None
    if text == "случайный бухари":
        return "random_bukhari", None
    if text == "случайный муслим":
        return "random_muslim", None
    if text == "случайный коран":
        return "random_quran", None
    for ru, en in COLLECTIONS.items():
        if text.startswith(ru):
            num = text.replace(ru, "").strip()
            if num.isdigit():
                return en, int(num)
    return None, None

def parse_quran_query(text):
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

def parse_search_query(text):
    text_lower = text.lower().strip()
    if text_lower.startswith("искать "):
        return text[7:].strip()
    if text_lower.startswith("поиск "):
        return text[6:].strip()
    return None

def parse_gemini_query(text):
    text_lower = text.lower().strip()
    for prefix in ["гемини ", "гемини\n", "gemini ", "gemini\n"]:
        if text_lower.startswith(prefix):
            return text[len(prefix):].strip()
    if text_lower in ["гемини", "gemini"]:
        return ""
    return None

def get_hadith(collection, number):
    try:
        url_ar = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/ara-{collection}/{number}.min.json"
        url_ru = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/rus-{collection}/{number}.min.json"
        url_en = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/eng-{collection}/{number}.min.json"

        arabic, russian, english, grade = "", "", "", ""

        # Арабский
        try:
            r_ar = requests.get(url_ar, timeout=10)
            if r_ar.status_code == 200:
                hadiths = r_ar.json().get("hadiths", [])
                if hadiths:
                    arabic = hadiths[0].get("text", "")
                    if arabic:
                        arabic = arabic.replace("\n", " ")
        except:
            pass

        # Русский
        try:
            r_ru = requests.get(url_ru, timeout=10)
            if r_ru.status_code == 200:
                hadiths = r_ru.json().get("hadiths", [])
                if hadiths:
                    h = hadiths[0]
                    text = h.get("text", "")
                    text = text.replace("\\n", " ")
                    text = re.sub(r"\[\d+\]", "", text)
                    russian = text
                    grades = h.get("grades", [])
                    if grades:
                        g = grades[0].get("grade", "")
                        grade = GRADE_MAP.get(g, g)
        except:
            pass

        # Английский (если нет русского)
        if not russian:
            try:
                r_en = requests.get(url_en, timeout=10)
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
            except:
                pass

        translation = russian or english
        lang = "рус" if russian else "англ"

        if arabic or translation:
            return arabic, translation, lang, grade
    except Exception as e:
        print(f"Error in get_hadith: {e}")
    return "", "", "", ""

def get_random_hadith(collection=None):
    """Получает случайный хадис из указанного сборника или случайного из bukhari/muslim"""
    if collection is None:
        collection = random.choice(["bukhari", "muslim"])
    
    max_num = MAX_HADITH.get(collection, 1000)
    
    # Пробуем до 10 раз найти существующий хадис
    for _ in range(10):
        num = random.randint(1, max_num)
        arabic, translation, lang, grade = get_hadith(collection, num)
        if arabic or translation:
            return collection, num, arabic, translation, lang, grade
    
    return None, None, "", "", "", ""

def get_quran_ayah(surah, ayah):
    try:
        url_ar = f"https://cdn.jsdelivr.net/gh/fawazahmed0/quran-api@1/editions/ara-quranindopak/{surah}/{ayah}.min.json"
        url_ru = f"https://cdn.jsdelivr.net/gh/fawazahmed0/quran-api@1/editions/rus-elmirkuliev/{surah}/{ayah}.min.json"

        arabic, russian = "", ""

        r_ar = requests.get(url_ar, timeout=10)
        if r_ar.status_code == 200:
            data = r_ar.json()
            arabic = data.get("text", "")

        r_ru = requests.get(url_ru, timeout=10)
        if r_ru.status_code == 200:
            data = r_ru.json()
            russian = data.get("text", "")

        return arabic, russian
    except Exception as e:
        print(f"Quran error: {e}")
    return "", ""

def get_random_quran():
    """Случайный аят из Корана"""
    surah = random.randint(1, 114)
    # Приблизительное количество аятов в сурах
    ayah_counts = {
        1:7, 2:286, 3:200, 4:176, 5:120, 6:165, 7:206, 8:75, 9:129, 10:109,
        11:123, 12:111, 13:43, 14:52, 15:99, 16:128, 17:111, 18:110, 19:98, 20:135,
        21:112, 22:78, 23:118, 24:64, 25:77, 26:227, 27:93, 28:88, 29:69, 30:60,
        31:34, 32:30, 33:73, 34:54, 35:45, 36:83, 37:182, 38:88, 39:75, 40:85,
        41:54, 42:53, 43:89, 44:59, 45:37, 46:35, 47:38, 48:29, 49:18, 50:45,
        51:60, 52:49, 53:62, 54:55, 55:78, 56:96, 57:29, 58:22, 59:24, 60:13,
        61:14, 62:11, 63:11, 64:18, 65:12, 66:12, 67:30, 68:52, 69:52, 70:44,
        71:28, 72:28, 73:20, 74:56, 75:40, 76:31, 77:50, 78:40, 79:46, 80:42,
        81:29, 82:19, 83:36, 84:25, 85:22, 86:17, 87:19, 88:26, 89:30, 90:20,
        91:15, 92:21, 93:11, 94:8, 95:8, 96:19, 97:5, 98:8, 99:8, 100:11,
        101:11, 102:8, 103:3, 104:9, 105:5, 106:4, 107:7, 108:3, 109:6, 110:3,
        111:5, 112:4, 113:5, 114:6
    }
    ayah = random.randint(1, ayah_counts.get(surah, 10))
    arabic, russian = get_quran_ayah(surah, ayah)
    return surah, ayah, arabic, russian

def search_hadith(query):
    try:
        url = f"https://dorar.net/dorar_api.json?skey={query}&page=1"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []

        data = r.json()
        html = data.get("ahadith", {}).get("result", "")
        if not html:
            return []

        text_only = re.sub(r'<[^>]+>', ' ', html)
        text_only = unescape(text_only)
        text_only = re.sub(r'\s+', ' ', text_only)

        blocks = text_only.split("--------------")

        results = []
        for block in blocks[:5]:
            block = block.strip()
            if not block:
                continue

            match = re.match(r'^\d+\s*-\s*(.*)', block)
            if not match:
                continue
            hadith_text = match.group(1).strip()

            rawi = ""
            muhaddith = ""
            source = ""
            page = ""
            grade = ""

            m = re.search(r'الراوي:\s*([^\n]+?)(?:\s*المحدث:|$)', block)
            if m:
                rawi = m.group(1).strip()
                if rawi == "-":
                    rawi = ""

            m = re.search(r'المحدث:\s*([^\n]+?)(?:\s*المصدر:|$)', block)
            if m:
                muhaddith = m.group(1).strip()

            m = re.search(r'المصدر:\s*([^\n]+?)(?:\s*الصفحة|$)', block)
            if m:
                source = m.group(1).strip()

            m = re.search(r'الصفحة أو الرقم:\s*([^\n]+?)(?:\s*خلاصة|$)', block)
            if m:
                page = m.group(1).strip()

            m = re.search(r'خلاصة حكم المحدث:\s*([^\n]+)', block)
            if m:
                grade = m.group(1).strip()

            for marker in ["الراوي:", "المحدث:", "المصدر:"]:
                if marker in hadith_text:
                    hadith_text = hadith_text.split(marker)[0].strip()

            if hadith_text and len(hadith_text) > 10:
                results.append({
                    "text": hadith_text,
                    "rawi": rawi,
                    "muhaddith": muhaddith,
                    "source": source,
                    "page": page,
                    "grade": grade,
                })

        return results
    except Exception as e:
        print(f"Search error: {e}")
        return []

def ask_gemini(question):
    if not GEMINI_API_KEY:
        return "❌ API-ключ Gemini не настроен."

    if not question:
        return "❌ Напиши вопрос после 'гемини'."

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        system_prompt = (
            "Ты — полезный ассистент в исламском Телеграм-боте. "
            "Отвечай на русском языке. "
            "Если вопрос религиозный — придерживайся суннитского ислама, Корана и Сунны. "
            "Будь уважителен, полезен и краток."
        )
        data = {
            "contents": [{"parts": [{"text": f"{system_prompt}\n\nВопрос: {question}"}]}]
        }
        r = requests.post(url, json=data, timeout=30)
        if r.status_code == 200:
            result = r.json()
            return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"❌ Ошибка Gemini: {r.status_code}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text:
        return

    # Поиск через Dorar
    search_query = parse_search_query(text)
    if search_query:
        await update.message.reply_text(f"🔍 Ищу: {search_query}...")
        results = search_hadith(search_query)

        if not results:
            await update.message.reply_text("❌ Ничего не найдено. Попробуй другое слово.")
            return

        msg = f"🔍 *Результаты поиска:* «{search_query}»\n\n"
        for i, r in enumerate(results, 1):
            msg += f"*{i}.* {r['text'][:300]}\n"
            if r['rawi']:
                msg += f"👤 *Передатчик:* {r['rawi']}\n"
            if r['muhaddith']:
                msg += f"🎓 *Учёный:* {r['muhaddith']}\n"
            if r['source']:
                msg += f"📚 *Источник:* {r['source']}"
                if r['page']:
                    msg += f" ({r['page']})"
                msg += "\n"
            if r['grade']:
                msg += f"📊 *Оценка:* {r['grade']}\n"
            msg += "\n"

        if len(msg) > 4000:
            await update.message.reply_text(msg[:4000], parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # Gemini
    gemini_question = parse_gemini_query(text)
    if gemini_question is not None:
        await update.message.reply_text("🤔 Думаю...")
        answer = ask_gemini(gemini_question)
        for i in range(0, len(answer), 4000):
            await update.message.reply_text(answer[i:i+4000])
        return

    # Коран
    surah, ayah = parse_quran_query(text)
    if surah and ayah:
        await update.message.reply_text("⏳ Ищу аят...")
        arabic, russian = get_quran_ayah(surah, ayah)
        if not arabic and not russian:
            await update.message.reply_text(f"❌ Аят {surah}:{ayah} не найден.")
            return
        msg = f"📖 Коран, {surah}:{ayah}\n\n"
        if arabic:
            msg += f"🔤 Арабский текст:\n{arabic[:500]}\n\n"
        if russian:
            msg += f"🌍 Перевод (рус):\n{russian[:1000]}\n"
        msg += f"\n📚 Источник: Священный Коран, сура {surah}, аят {ayah}"
        await update.message.reply_text(msg)
        return

    # Хадисы (включая случайные)
    collection, number = parse_hadith_query(text)
    if collection:
        # Случайный хадис
        if collection == "random":
            await update.message.reply_text("🎲 Ищу случайный хадис...")
            coll, num, arabic, translation, lang, grade = get_random_hadith()
            if coll:
                msg = f"🎲 *Случайный хадис*\n📖 {NAMES.get(coll, coll)}, хадис №{num}\n\n"
                if arabic:
                    msg += f"🔤 Арабский текст:\n{arabic[:500]}\n\n"
                if translation:
                    msg += f"🌍 Перевод ({lang}):\n{translation[:1500]}\n"
                if grade:
                    msg += f"\n📊 Достоверность: {grade}"
                msg += f"\n\n📚 Источник: {NAMES.get(coll, coll)}, хадис №{num}"
                await update.message.reply_text(msg, parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Не удалось найти хадис. Попробуй ещё раз.")
            return

        # Случайный бухари
        if collection == "random_bukhari":
            await update.message.reply_text("🎲 Ищу случайный хадис из Бухари...")
            coll, num, arabic, translation, lang, grade = get_random_hadith("bukhari")
            if coll:
                msg = f"🎲 *Случайный хадис*\n📖 {NAMES.get(coll, coll)}, хадис №{num}\n\n"
                if arabic:
                    msg += f"🔤 Арабский текст:\n{arabic[:500]}\n\n"
                if translation:
                    msg += f"🌍 Перевод ({lang}):\n{translation[:1500]}\n"
                if grade:
                    msg += f"\n📊 Достоверность: {grade}"
                msg += f"\n\n📚 Источник: {NAMES.get(coll, coll)}, хадис №{num}"
                await update.message.reply_text(msg, parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Не удалось найти хадис. Попробуй ещё раз.")
            return

        # Случайный муслим
        if collection == "random_muslim":
            await update.message.reply_text("🎲 Ищу случайный хадис из Муслима...")
            coll, num, arabic, translation, lang, grade = get_random_hadith("muslim")
            if coll:
                msg = f"🎲 *Случайный хадис*\n📖 {NAMES.get(coll, coll)}, хадис №{num}\n\n"
                if arabic:
                    msg += f"🔤 Арабский текст:\n{arabic[:500]}\n\n"
                if translation:
                    msg += f"🌍 Перевод ({lang}):\n{translation[:1500]}\n"
                if grade:
                    msg += f"\n📊 Достоверность: {grade}"
                msg += f"\n\n📚 Источник: {NAMES.get(coll, coll)}, хадис №{num}"
                await update.message.reply_text(msg, parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Не удалось найти хадис. Попробуй ещё раз.")
            return

        # Случайный аят
        if collection == "random_quran":
            await update.message.reply_text("🎲 Ищу случайный аят...")
            surah, ayah, arabic, russian = get_random_quran()
            if arabic or russian:
                msg = f"🎲 *Случайный аят*\n📖 Коран, {surah}:{ayah}\n\n"
                if arabic:
                    msg += f"🔤 Арабский текст:\n{arabic[:500]}\n\n"
                if russian:
                    msg += f"🌍 Перевод (рус):\n{russian[:1000]}\n"
                msg += f"\n📚 Источник: Священный Коран, сура {surah}, аят {ayah}"
                await update.message.reply_text(msg, parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Не удалось найти аят. Попробуй ещё раз.")
            return

        # Обычный хадис по номеру
        if number:
            await update.message.reply_text("⏳ Ищу хадис...")
            arabic, translation, lang, grade = get_hadith(collection, number)
            if not arabic and not translation:
                await update.message.reply_text(
                    f"❌ Хадис {NAMES.get(collection, collection)} №{number} не найден.\n"
                    "Проверь номер и попробуй снова."
                )
                return
            msg = f"📖 {NAMES.get(collection, collection)}, хадис №{number}\n\n"
            if arabic:
                msg += f"🔤 Арабский текст:\n{arabic[:500]}\n\n"
            if translation:
                msg += f"🌍 Перевод ({lang}):\n{translation[:1500]}\n"
            if grade:
                msg += f"\n📊 Достоверность: {grade}"
            msg += f"\n\n📚 Источник: {NAMES.get(collection, collection)}, хадис №{number}"
            await update.message.reply_text(msg)
            return

    # Справка
    if text.lower() in ["помощь", "справка", "команды", "хелп", "help", "/start"]:
        await update.message.reply_text(
            "📚 *Команды бота:*\n\n"
            "*Хадисы (12 сборников):*\n"
            "бухари 1 | муслим 1 | абу дауд 1\n"
            "тирмизи 1 | ибн маджа 1 | насаи 1\n"
            "муватта 1 | ахмад 1 | дарими 1\n"
            "байхаки 1 | хаким 1 | адаб 1\n\n"
            "*Случайный хадис/аят:*\n"
            "случайный — из Бухари или Муслима\n"
            "случайный бухари | случайный муслим\n"
            "случайный коран\n\n"
            "*Коран:*\n"
            "коран 2:255\n\n"
            "*Поиск по базе (340 000 хадисов):*\n"
            "искать بدعة\n"
            "искать намерения\n\n"
            "*ИИ (Gemini):*\n"
            "гемини твой вопрос\n\n"
            "*Справка:* помощь",
            parse_mode="Markdown"
        )
        return

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
app.run_polling()
