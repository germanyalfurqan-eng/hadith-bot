import os
import re
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

# ---------- ПАРСЕРЫ ЗАПРОСОВ ----------

def parse_hadith_query(text):
    text = text.lower().strip()
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
    """искать запрос"""
    text_lower = text.lower().strip()
    if text_lower.startswith("искать "):
        return text[7:].strip()
    if text_lower.startswith("поиск "):
        return text[6:].strip()
    return None

def parse_gemini_query(text):
    """гемини запрос"""
    text_lower = text.lower().strip()
    for prefix in ["гемини ", "гемини\n", "gemini ", "gemini\n"]:
        if text_lower.startswith(prefix):
            return text[len(prefix):].strip()
    if text_lower in ["гемини", "gemini"]:
        return ""
    return None

# ---------- ХАДИСЫ (локальная база) ----------

def get_hadith(collection, number):
    try:
        url_ar = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/ara-{collection}/{number}.min.json"
        url_ru = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/rus-{collection}/{number}.min.json"
        url_en = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/eng-{collection}/{number}.min.json"

        arabic, russian, english, grade = "", "", "", ""

        r_ar = requests.get(url_ar, timeout=10)
        if r_ar.status_code == 200:
            hadiths = r_ar.json().get("hadiths", [])
            if hadiths:
                arabic = hadiths[0].get("text", "")

        r_ru = requests.get(url_ru, timeout=10)
        if r_ru.status_code == 200:
            hadiths = r_ru.json().get("hadiths", [])
            if hadiths:
                h = hadiths[0]
                text = h.get("text", "")
                text = text.replace("\\n", "\n")
                text = re.sub(r"\[\d+\]", "", text)
                russian = text
                grades = h.get("grades", [])
                if grades:
                    g = grades[0].get("grade", "")
                    grade = GRADE_MAP.get(g, g)

        if not russian:
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

        translation = russian or english
        lang = "рус" if russian else "англ"

        if arabic or translation:
            return arabic, translation, lang, grade
    except Exception as e:
        print(f"Error: {e}")
    return "", "", "", ""

# ---------- КОРАН ----------

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

# ---------- ПОИСК ЧЕРЕЗ DORAR API ----------

def search_hadith(query):
    """Ищет хадисы через Dorar API"""
    try:
        url = f"https://dorar.net/dorar_api.json?skey={query}&page=1"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []

        data = r.json()
        html = data.get("ahadith", {}).get("result", "")
        if not html:
            return []

        results = []
        # Убираем HTML-теги кроме разделителей, затем разбиваем
        # Сначала заменим разделитель на уникальный маркер
        html = html.replace("--------------\n", "|||SPLIT|||")
        
        # Убираем все HTML-теги
        text_only = re.sub(r'<[^>]+>', ' ', html)
        text_only = unescape(text_only)
        
        # Разбиваем по маркеру
        blocks = text_only.split("|||SPLIT|||")
        
        for block in blocks[:5]:
            block = block.strip()
            if not block:
                continue
            
            # Убираем лишние пробелы
            block = re.sub(r'\s+', ' ', block).strip()
            
            # Извлекаем поля
            # Номер и текст
            match = re.match(r'^\d+\s*-\s*(.*)', block)
            text = match.group(1) if match else block
            
            # Ищем поля в оставшемся тексте
            rawi = ""
            muhaddith = ""
            source = ""
            page = ""
            grade = ""
            
            # الراوي
            m = re.search(r'الراوي:\s*([^\n]+?)(?:\s*المحدث:|$)', text_only)
            if m:
                rawi = m.group(1).strip()
                if rawi == "-":
                    rawi = ""
            
            # المحدث
            m = re.search(r'المحدث:\s*([^\n]+?)(?:\s*المصدر:|$)', text_only)
            if m:
                muhaddith = m.group(1).strip()
            
            # المصدر
            m = re.search(r'المصدر:\s*([^\n]+?)(?:\s*الصفحة|$)', text_only)
            if m:
                source = m.group(1).strip()
            
            # الصفحة أو الرقم
            m = re.search(r'الصفحة أو الرقم:\s*([^\n]+?)(?:\s*خلاصة|$)', text_only)
            if m:
                page = m.group(1).strip()
            
            # خلاصة حكم المحدث
            m = re.search(r'خلاصة حكم المحدث:\s*([^\n]+?)(?:\s*--------------|$)', text_only)
            if m:
                grade = m.group(1).strip()
            
            # Очищаем текст хадиса от метаданных
            # Берём только первую часть до الراوي
            if text:
                # Убираем всё после первой метки если она есть в тексте
                for marker in ["الراوي:", "المحدث:", "المصدر:"]:
                    if marker in text:
                        text = text.split(marker)[0].strip()
            
            if text and len(text) > 10:
                results.append({
                    "text": text,
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

# ---------- GEMINI ----------

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

# ---------- ОБРАБОТЧИК СООБЩЕНИЙ ----------

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

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
            msg += f"*{i}.* {r['text']}\n"
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
            msg += f"🔤 Арабский текст:\n{arabic}\n\n"
        if russian:
            msg += f"🌍 Перевод (рус):\n{russian}\n"
        msg += f"\n📚 Источник: Священный Коран, сура {surah}, аят {ayah}"
        await update.message.reply_text(msg)
        return

    # Хадисы (локальная база)
    collection, number = parse_hadith_query(text)
    if collection and number:
        await update.message.reply_text("⏳ Ищу хадис...")
        arabic, translation, lang, grade = get_hadith(collection, number)
        if not arabic and not translation:
            await update.message.reply_text(f"❌ Хадис {NAMES.get(collection, collection)} №{number} не найден.")
            return
        msg = f"📖 {NAMES.get(collection, collection)}, хадис №{number}\n\n"
        if arabic:
            msg += f"🔤 Арабский текст:\n{arabic}\n\n"
        if translation:
            msg += f"🌍 Перевод ({lang}):\n{translation}\n"
        if grade:
            msg += f"\n📊 Достоверность: {grade}"
        msg += f"\n\n📚 Источник: {NAMES.get(collection, collection)}, хадис №{number}"
        await update.message.reply_text(msg)
        return

    # Справка
    await update.message.reply_text(
        "📚 *Команды бота:*\n\n"
        "*Хадисы (6 сборников):*\n"
        "бухари 1 | муслим 1 | абу дауд 1\n"
        "тирмизи 1 | ибн маджа 1 | насаи 1\n\n"
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

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
app.run_polling()
