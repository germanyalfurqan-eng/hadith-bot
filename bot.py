import os
import re
import random
import requests
from html import unescape
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

COLLECTIONS = {
    "бухари": "bukhari",
    "муслим": "muslim",
    "абу дауд": "abudawud",
    "тирмизи": "tirmidhi",
    "ибн маджа": "ibnmajah",
    "насаи": "nasai",
    "муватта": "malik",
}

NAMES = {
    "bukhari": "Сахих аль-Бухари",
    "muslim": "Сахих Муслим",
    "abudawud": "Сунан Абу Дауда",
    "tirmidhi": "Сунан ат-Тирмизи",
    "ibnmajah": "Сунан Ибн Маджа",
    "nasai": "Сунан ан-Насаи",
    "malik": "Муватта имама Малика",
}

MAX_HADITH = {"bukhari": 7563, "muslim": 3033}

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
    if text == "случайный": return "random", None
    if text == "случайный бухари": return "random_bukhari", None
    if text == "случайный муслим": return "random_muslim", None
    if text == "случайный коран": return "random_quran", None
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
    t = text.lower().strip()
    if t.startswith("искать "): return t[7:].strip()
    if t.startswith("поиск "): return t[6:].strip()
    return None

def parse_translate(text):
    t = text.lower().strip()
    if t.startswith("переведи "): return t[9:].strip()
    if t == "переведи": return "REPLY"
    return None

def parse_deep_query(text):
    t = text.lower().strip()
    for p in ["deep ", "диип ", "дип ", "глубокий "]:
        if t.startswith(p):
            return t[len(p):].strip()
    if t in ["deep", "диип", "дип"]:
        return ""
    return None

def parse_tafsir_query(text):
    t = text.lower().strip()
    if t.startswith("тафсир "):
        ref = t[7:].strip()
        if ":" in ref:
            parts = ref.split(":")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return int(parts[0]), int(parts[1])
    return None, None

def get_hadith(collection, number):
    try:
        url_ar = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/ara-{collection}/{number}.min.json"
        url_ru = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/rus-{collection}/{number}.min.json"
        url_en = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/eng-{collection}/{number}.min.json"
        arabic, russian, english, grade = "", "", "", ""
        try:
            r = requests.get(url_ar, timeout=10)
            if r.status_code == 200:
                h = r.json().get("hadiths", [])
                if h:
                    arabic = h[0].get("text", "").replace("\n", " ")
        except: pass
        try:
            r = requests.get(url_ru, timeout=10)
            if r.status_code == 200:
                h = r.json().get("hadiths", [])
                if h:
                    t = h[0].get("text", "").replace("\\n", " ")
                    russian = re.sub(r"\[\d+\]", "", t)
                    g = h[0].get("grades", [])
                    if g: grade = GRADE_MAP.get(g[0].get("grade", ""), "")
        except: pass
        if not russian:
            try:
                r = requests.get(url_en, timeout=10)
                if r.status_code == 200:
                    h = r.json().get("hadiths", [])
                    if h:
                        english = h[0].get("text", "")
                        if not grade:
                            g = h[0].get("grades", [])
                            if g: grade = GRADE_MAP.get(g[0].get("grade", ""), "")
            except: pass
        translation = russian or english
        lang = "рус" if russian else "англ"
        if arabic or translation:
            return arabic, translation, lang, grade
    except Exception as e:
        print(f"Error: {e}")
    return "", "", "", ""

def get_random_hadith(collection=None):
    if collection is None: collection = random.choice(["bukhari", "muslim"])
    for _ in range(10):
        num = random.randint(1, MAX_HADITH.get(collection, 1000))
        a, t, l, g = get_hadith(collection, num)
        if a or t: return collection, num, a, t, l, g
    return None, None, "", "", "", ""

def get_quran_ayah(surah, ayah):
    try:
        ua = f"https://cdn.jsdelivr.net/gh/fawazahmed0/quran-api@1/editions/ara-quranindopak/{surah}/{ayah}.min.json"
        ur = f"https://cdn.jsdelivr.net/gh/fawazahmed0/quran-api@1/editions/rus-elmirkuliev/{surah}/{ayah}.min.json"
        a = requests.get(ua, timeout=10).json().get("text", "") if requests.get(ua, timeout=10).status_code == 200 else ""
        r = requests.get(ur, timeout=10).json().get("text", "") if requests.get(ur, timeout=10).status_code == 200 else ""
        return a, r
    except: return "", ""

def get_random_quran():
    surah = random.randint(1, 114)
    ayah_counts = {1:7,2:286,3:200,4:176,5:120,6:165,7:206,8:75,9:129,10:109,11:123,12:111,13:43,14:52,15:99,16:128,17:111,18:110,19:98,20:135,21:112,22:78,23:118,24:64,25:77,26:227,27:93,28:88,29:69,30:60,31:34,32:30,33:73,34:54,35:45,36:83,37:182,38:88,39:75,40:85,41:54,42:53,43:89,44:59,45:37,46:35,47:38,48:29,49:18,50:45,51:60,52:49,53:62,54:55,55:78,56:96,57:29,58:22,59:24,60:13,61:14,62:11,63:11,64:18,65:12,66:12,67:30,68:52,69:52,70:44,71:28,72:28,73:20,74:56,75:40,76:31,77:50,78:40,79:46,80:42,81:29,82:19,83:36,84:25,85:22,86:17,87:19,88:26,89:30,90:20,91:15,92:21,93:11,94:8,95:8,96:19,97:5,98:8,99:8,100:11,101:11,102:8,103:3,104:9,105:5,106:4,107:7,108:3,109:6,110:3,111:5,112:4,113:5,114:6}
    ayah = random.randint(1, ayah_counts.get(surah, 10))
    a, r = get_quran_ayah(surah, ayah)
    return surah, ayah, a, r

def search_hadith(query):
    try:
        r = requests.get(f"https://dorar.net/dorar_api.json?skey={query}&page=1", timeout=15)
        if r.status_code != 200: return []
        html = r.json().get("ahadith", {}).get("result", "")
        if not html: return []
        text_only = unescape(re.sub(r'<[^>]+>', ' ', html))
        text_only = re.sub(r'\s+', ' ', text_only)
        blocks = text_only.split("--------------")
        results = []
        for block in blocks[:5]:
            block = block.strip()
            if not block: continue
            m = re.match(r'^\d+\s*-\s*(.*)', block)
            if not m: continue
            hadith_text = m.group(1).strip()
            rawi = muhaddith = source = page = grade = ""
            for key, var in [("الراوي:", "rawi"), ("المحدث:", "muhaddith"), ("المصدر:", "source"), ("الصفحة أو الرقم:", "page"), ("خلاصة حكم المحدث:", "grade")]:
                m2 = re.search(rf'{key}\s*([^\n]+?)(?:\s*(?:المحدث|المصدر|الصفحة|خلاصة|$))', block)
                if m2:
                    val = m2.group(1).strip()
                    if val == "-": val = ""
                    if var == "rawi": rawi = val
                    elif var == "muhaddith": muhaddith = val
                    elif var == "source": source = val
                    elif var == "page": page = val
                    elif var == "grade": grade = val
            for marker in ["الراوي:", "المحدث:", "المصدر:"]:
                if marker in hadith_text:
                    hadith_text = hadith_text.split(marker)[0].strip()
            if hadith_text and len(hadith_text) > 10:
                results.append({"text": hadith_text, "rawi": rawi, "muhaddith": muhaddith, "source": source, "page": page, "grade": grade})
        return results
    except: return []

def search_similar_hadith(arabic_text):
    if not arabic_text or len(arabic_text) < 20: return []
    query = " ".join(arabic_text[:100].split()[-5:])
    try:
        r = requests.get(f"https://dorar.net/dorar_api.json?skey={query}&page=1", timeout=10)
        if r.status_code != 200: return []
        html = r.json().get("ahadith", {}).get("result", "")
        if not html: return []
        text_only = unescape(re.sub(r'<[^>]+>', ' ', html))
        blocks = re.sub(r'\s+', ' ', text_only).split("--------------")
        refs = []
        for block in blocks[:5]:
            block = block.strip()
            if not block: continue
            source = page = ""
            m = re.search(r'المصدر:\s*([^\n]+?)(?:\s*الصفحة|$)', block)
            if m: source = m.group(1).strip()
            m = re.search(r'الصفحة أو الرقم:\s*([^\n]+)', block)
            if m: page = m.group(1).strip()
            if source:
                ref = source + (f" №{page}" if page else "")
                if ref not in refs: refs.append(ref)
        return refs
    except: return []

def ask_deepseek(prompt, system=None):
    if not DEEPSEEK_API_KEY:
        return "❌ API-ключ DeepSeek не настроен."
    if system is None:
        system = "Ты — полезный ассистент в исламском Телеграм-боте. Отвечай на русском языке. Будь уважителен, полезен и краток."
    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 2000},
            timeout=30
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        else:
            return f"❌ Ошибка DeepSeek: {r.status_code}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text:
        return

    # Перевод
    tr = parse_translate(text)
    if tr == "REPLY":
        if update.message.reply_to_message and update.message.reply_to_message.text:
            await update.message.reply_text("🔄 Перевожу...")
            result = ask_deepseek(f"Переведи на русский:\n{update.message.reply_to_message.text}", "Ты — переводчик с арабского на русский. Переводи точно.")
            for i in range(0, len(result), 4000):
                await update.message.reply_text(result[i:i+4000])
            return
        else:
            await update.message.reply_text("❌ Ответь на сообщение с арабским текстом.")
            return
    if tr and tr != "REPLY":
        await update.message.reply_text("🔄 Перевожу...")
        result = ask_deepseek(f"Переведи на русский:\n{tr}", "Ты — переводчик с арабского на русский. Переводи точно.")
        for i in range(0, len(result), 4000):
            await update.message.reply_text(result[i:i+4000])
        return

    # Тафсир
    surah, ayah = parse_tafsir_query(text)
    if surah and ayah:
        await update.message.reply_text(f"📖 Ищу тафсир аята {surah}:{ayah}...")
        arabic_ayah, ru_ayah = get_quran_ayah(surah, ayah)
        prompt = f"Дай тафсир Ибн Касира на аят {surah}:{ayah} из Корана. Сначала приведи арабский текст тафсира, затем русский перевод."
        if arabic_ayah:
            prompt += f"\n\nАят: {arabic_ayah}"
        result = ask_deepseek(prompt, "Ты — знаток тафсира Ибн Касира. Даёшь оригинальный арабский текст тафсира и русский перевод.")
        for i in range(0, len(result), 4000):
            await update.message.reply_text(result[i:i+4000])
        return

    # DeepSeek вопрос
    deep_q = parse_deep_query(text)
    if deep_q is not None:
        await update.message.reply_text("🤔 Думаю...")
        if deep_q:
            result = ask_deepseek(deep_q)
        else:
            result = "❌ Напиши вопрос после 'deep'. Например: deep столица Саудовской Аравии?"
        for i in range(0, len(result), 4000):
            await update.message.reply_text(result[i:i+4000])
        return

    # Поиск
    sq = parse_search_query(text)
    if sq:
        await update.message.reply_text(f"🔍 Ищу: {sq}...")
        results = search_hadith(sq)
        if not results:
            await update.message.reply_text("❌ Ничего не найдено.")
            return
        msg = f"🔍 *Результаты поиска:* «{sq}»\n\n"
        for i, r in enumerate(results, 1):
            msg += f"*{i}.* {r['text'][:300]}\n"
            if r['rawi']: msg += f"👤 {r['rawi']}\n"
            if r['muhaddith']: msg += f"🎓 {r['muhaddith']}\n"
            if r['source']: msg += f"📚 {r['source']}" + (f" ({r['page']})" if r['page'] else "") + "\n"
            if r['grade']: msg += f"📊 {r['grade']}\n"
            msg += "\n"
        await update.message.reply_text(msg[:4000], parse_mode="Markdown")
        return

    # Коран
    surah, ayah = parse_quran_query(text)
    if surah and ayah:
        await update.message.reply_text("⏳ Ищу аят...")
        a, r = get_quran_ayah(surah, ayah)
        if not a and not r:
            await update.message.reply_text(f"❌ Аят {surah}:{ayah} не найден.")
            return
        msg = f"📖 Коран, {surah}:{ayah}\n\n"
        if a: msg += f"🔤 Арабский текст:\n{a[:500]}\n\n"
        if r: msg += f"🌍 Перевод (рус):\n{r[:1000]}\n"
        msg += f"\n📚 Священный Коран, сура {surah}, аят {ayah}"
        await update.message.reply_text(msg)
        return

    # Хадисы
    collection, number = parse_hadith_query(text)
    if collection:
        if collection in ["random", "random_bukhari", "random_muslim", "random_quran"]:
            await update.message.reply_text("🎲 Ищу...")
            if collection == "random_quran":
                s, a_num, ar, ru = get_random_quran()
                if ar or ru:
                    msg = f"🎲 *Случайный аят*\n📖 Коран, {s}:{a_num}\n\n"
                    if ar: msg += f"🔤 {ar[:500]}\n\n"
                    if ru: msg += f"🌍 {ru[:1000]}\n"
                    msg += f"\n📚 Коран, {s}:{a_num}"
                    await update.message.reply_text(msg, parse_mode="Markdown")
                else:
                    await update.message.reply_text("❌ Не удалось.")
                return
            else:
                coll_arg = None if collection == "random" else collection.replace("random_", "")
                coll, num, ar, tr, lang, grade = get_random_hadith(coll_arg)
                if coll:
                    similar = search_similar_hadith(ar)
                    msg = f"🎲 *Случайный хадис*\n📖 {NAMES.get(coll, coll)}, №{num}\n\n"
                    if ar: msg += f"🔤 {ar[:500]}\n\n"
                    if tr: msg += f"🌍 Перевод ({lang}):\n{tr[:1500]}\n"
                    if grade: msg += f"\n📊 {grade}"
                    msg += f"\n\n📚 {NAMES.get(coll, coll)}, №{num}"
                    if similar: msg += f"\n\n📖 Также передаётся:\n• " + "\n• ".join(similar[:5])
                    await update.message.reply_text(msg, parse_mode="Markdown")
                else:
                    await update.message.reply_text("❌ Не удалось.")
                return

        if number:
            await update.message.reply_text("⏳ Ищу хадис...")
            ar, tr, lang, grade = get_hadith(collection, number)
            if not ar and not tr:
                await update.message.reply_text(f"❌ Хадис {NAMES.get(collection, collection)} №{number} не найден.")
                return
            similar = search_similar_hadith(ar)
            msg = f"📖 {NAMES.get(collection, collection)}, №{number}\n\n"
            if ar: msg += f"🔤 {ar[:500]}\n\n"
            if tr: msg += f"🌍 Перевод ({lang}):\n{tr[:1500]}\n"
            if grade: msg += f"\n📊 {grade}"
            msg += f"\n\n📚 {NAMES.get(collection, collection)}, №{number}"
            if similar: msg += f"\n\n📖 Также передаётся:\n• " + "\n• ".join(similar[:5])
            await update.message.reply_text(msg)
            return

    # Справка
    if text.lower() in ["помощь", "справка", "команды", "хелп", "help", "/start"]:
        await update.message.reply_text(
            "📚 *Команды бота:*\n\n"
            "*Хадисы (7 сборников):*\nбухари 1 | муслим 1 | абу дауд 1\nтирмизи 1 | ибн маджа 1 | насаи 1 | муватта 1\n\n"
            "*Случайные:*\nслучайный | случайный бухари | случайный муслим | случайный коран\n\n"
            "*Коран:*\nкоран 2:255\n\n"
            "*Поиск:*\nискать بدعة\n\n"
            "*DeepSeek ИИ:*\ndeep вопрос\nтафсир 5:6\nпереведи текст\n(ответь на сообщение + переведи)\n\n"
            "*Справка:* помощь",
            parse_mode="Markdown"
        )
        return

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
app.run_polling()
