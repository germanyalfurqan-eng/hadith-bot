import os
import asyncio
import re
import random
import json
import base64
import hmac
import hashlib
import time
import collections
import subprocess
import shutil
import requests
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import parse_qsl
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, ChatMemberHandler, CommandHandler

# ============ АЛЬ-МУХАЙМИН (الموحد المهيمن) — наша выверенная база ============
# Плоский индекс: { "907": {book, chapter, riwayat:[{text, short_ref, sources}], verified}, ... }
MUHAYMIN_INDEX_URL = "https://raw.githubusercontent.com/germanyalfurqan-eng/hadith-bot/main/muhaymin_index.json"
_muhaymin_cache = None

def get_muhaymin(number):
    """Вернуть хадис аль-Мухаймина по глобальному номеру (int/str) или None."""
    global _muhaymin_cache
    try:
        if _muhaymin_cache is None:
            r = requests.get(MUHAYMIN_INDEX_URL, timeout=15)
            if r.status_code == 200:
                _muhaymin_cache = r.json()
            else:
                return None
        return _muhaymin_cache.get(str(int(number)))
    except:
        pass
    return None

# ---- Просмотр базы по книгам/главам (для удобного обзора) ----
_book_struct_cache = None
def build_book_structure():
    """Из кэша индекса собрать [{title, start, end, chapters:[{title,start,count}]}]."""
    global _book_struct_cache
    if _book_struct_cache is not None:
        return _book_struct_cache
    get_muhaymin(1)  # подгрузить кэш
    if not _muhaymin_cache:
        return []
    items = sorted(((int(k), e) for k, e in _muhaymin_cache.items()), key=lambda x: x[0])
    books = []
    for n, e in items:
        bt = e.get("book", "") or "—"; ct = e.get("chapter", "") or "—"
        if not books or books[-1]["title"] != bt:
            books.append({"title": bt, "start": n, "end": n, "chapters": []})
        bk = books[-1]; bk["end"] = n
        if not bk["chapters"] or bk["chapters"][-1]["title"] != ct:
            bk["chapters"].append({"title": ct, "start": n, "count": 0})
        bk["chapters"][-1]["count"] += 1
    _book_struct_cache = books
    return books

def parse_browse(text):
    t = text.lower().strip()
    if t in ("книги", "оглавление", "فهرس", "содержание"):
        return ("books", None)
    if t.startswith("книга "):
        return ("book", text.strip()[6:].strip())
    return (None, None)

def fmt_books():
    bs = build_book_structure()
    if not bs:
        return "❌ База недоступна."
    msg = "📚 الموحد المهيمن — 44 книги:\n\n"
    for i, b in enumerate(bs, 1):
        nh = sum(c["count"] for c in b["chapters"])
        msg += f"{i}. {b['title']}  (№{b['start']}–{b['end']}, {nh} хад.)\n"
    msg += "\n👉 «книга <номер или название>» — главы; «мухэймин <номер>» — хадис."
    return msg

def fmt_book_chapters(arg):
    bs = build_book_structure()
    b = None
    if arg.isdigit() and 1 <= int(arg) <= len(bs):
        b = bs[int(arg) - 1]
    else:
        for x in bs:
            if arg and arg in x["title"]:
                b = x; break
    if not b:
        return "❌ Книга не найдена. Напиши «книги» — список."
    msg = f"📕 {b['title']}  (№{b['start']}–{b['end']}, {len(b['chapters'])} глав)\n\n"
    for c in b["chapters"]:
        msg += f"  [{c['start']}] {c['title']}  ({c['count']})\n"
    msg += "\n👉 «мухэймин <номер>» — открыть хадис."
    return msg

# ---- Поиск по sunnah.one (хадис + хукм достоверности + тахридж + شرح) ----
def search_sunnah_one(query, limit=4):
    """Вернуть (count, [{marked, text, hukm, takhreej, sharh_id}]) — с дедупом одинаковых матнов."""
    try:
        url = "https://search.sunnah.one/?action=search&ver=2&q=" + requests.utils.quote(query)
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if r.status_code != 200:
            return 0, []
        d = r.json()
        out = []; seen = set()
        for it in d.get("data", []):
            raw = it.get("text") or ""
            plain = re.sub(r"</?mark>", "", raw).strip()
            key = re.sub(r"[^ء-ي]", "", plain)[:45]
            if not key or key in seen:
                continue
            seen.add(key)
            out.append({
                "marked": raw, "text": plain,
                "hukm": re.sub(r"[\[\]]", "", str(it.get("hukm") or "")).strip(),
                "takhreej": (it.get("takhreej") or "").strip(),
                "sharh_id": it.get("sharh_id"),
            })
            if len(out) >= limit:
                break
        return d.get("count", 0), out
    except Exception:
        return 0, []

def hukm_emoji(h):
    if any(w in h for w in ("صحيح", "حسن", "جيد", "ثابت", "قوي")):
        return "✅"
    if any(w in h for w in ("ضعيف", "منكر", "موضوع", "باطل", "لا يصح", "واه", "متروك", "كذب", "شاذ")):
        return "⚠️"
    return "ℹ️"

def _esc_mark(t):
    """Экранировать HTML и превратить <mark>искомое</mark> в <u>подчёркнутое</u>."""
    t = (t or "").replace("<mark>", "\x00").replace("</mark>", "\x01")
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return t.replace("\x00", "<u>").replace("\x01", "</u>")

def takhreej_html(tk):
    """Экранировать тахридж и сделать ссылки на sunnah.com для известных сборников."""
    out = _esc_mark(tk)
    for ar, slug in {"البخاري": "bukhari", "مسلم": "muslim", "أبو داود": "abudawud",
                     "الترمذي": "tirmidhi", "النسائي": "nasai", "ابن ماجه": "ibnmajah",
                     "ابن ماجة": "ibnmajah", "مالك": "malik", "أحمد": "ahmad", "الدارمي": "darimi"}.items():
        out = re.sub(ar + r"\s*\(\s*(\d+)\s*\)",
                     lambda m, s=slug, a=ar: f'<a href="https://sunnah.com/{s}:{m.group(1)}">{a} ({m.group(1)})</a>',
                     out)
    return out

def parse_sunnah(text):
    t = text.lower().strip()
    for trig in ("сунна ", "достоверность ", "хукм "):
        if t.startswith(trig):
            return text.strip()[len(trig):].strip()
    return None

def parse_smart_sunnah(text):
    """«хадис о ...» / «хадис про ...» — поиск по СМЫСЛУ (через DeepSeek -> ключевые слова)."""
    t = text.lower().strip()
    for trig in ("хадис о ", "хадис про ", "достоверность хадиса о ", "достоверность хадиса про ", "найди хадис "):
        if t.startswith(trig):
            return text.strip()[len(trig):].strip()
    return None

# Код первоисточника (verified_from) -> арабское имя; цифры лат->араб
SRC_AR = {"ahmad": "أحمد", "bukhari": "البخاري", "muslim": "مسلم", "abudawud": "أبو داود",
          "tirmidhi": "الترمذي", "nasai": "النسائي", "ibnmajah": "ابن ماجه", "malik": "مالك",
          "humaydi": "الحميدي", "tayalisi": "الطيالسي", "ibnabishayba": "ابن أبي شيبة",
          "darimi": "الدارمي", "abuyala": "أبو يعلى", "ishaq": "إسحاق بن راهويه",
          "nasaikubra": "النسائي الكبرى", "ibnhibban": "ابن حبان", "ibnkhuzayma": "ابن خزيمة",
          "abuawana": "أبو عوانة", "adabmufrad": "الأدب المفرد", "abdbinhumayd": "عبد بن حميد",
          "ismail": "إسماعيل بن جعفر", "ibnaljad": "ابن الجعد", "ibnmubarak": "ابن المبارك"}
_LAT2AR = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
def fmt_src_ref(short_ref, verified_from):
    """Чистая метка первоисточника: из verified_from (надёжный номер) -> «أحمد ٩٦٠»."""
    if verified_from:
        p = verified_from.split()
        name = SRC_AR.get(p[0], p[0])
        num = (p[1] if len(p) > 1 else "").translate(_LAT2AR)
        return f"{name} {num}".strip()
    return (short_ref or "—").strip()

# ---- Поиск передатчиков (موسوعة رواة الحديث — hawramani) ----
def search_transmitters(name, limit=8):
    """Вернуть [{title, url}] из موسوعة رواة الحديث (WP REST API)."""
    try:
        url = ("https://hadithtransmitters.hawramani.com/wp-json/wp/v2/search?per_page="
               + str(limit) + "&search=" + requests.utils.quote(name))
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if r.status_code != 200:
            return []
        return [{"title": (it.get("title") or "").strip(), "url": it.get("url") or ""}
                for it in r.json() if it.get("title")]
    except Exception:
        return []

def parse_transmitter(text):
    t = text.lower().strip()
    for trig in ("передатчик ", "равий ", "راوي ", "рави "):
        if t.startswith(trig):
            return text.strip()[len(trig):].strip()
    return None

REVERSE_INDEX_URL = "https://raw.githubusercontent.com/germanyalfurqan-eng/hadith-bot/main/reverse_index.json"
_reverse_cache = None

def get_reverse_index():
    global _reverse_cache
    if _reverse_cache is None:
        r = requests.get(REVERSE_INDEX_URL, timeout=10)
        if r.status_code == 200:
            _reverse_cache = r.json()
    return _reverse_cache

def find_in_murhid(source_code, number):
    """source_code — код первоисточника (bukhari/tayalisi/...), number — int.
    Возвращает список мест в аль-Мухаймине: [{m, v, chapter}, ...]."""
    idx = get_reverse_index()
    if not idx:
        return []
    return idx.get(f"{source_code} {int(number)}", [])

# Транслитерация названий первоисточников (рус.) -> код в обратном индексе.
# Триггеры проверяются по startswith, сначала длинные.
SOURCE_TRIGGERS = [
    ("ибн аби шейба", "ibnabishayba"), ("ибн абу шейба", "ibnabishayba"),
    ("ибн аби шайба", "ibnabishayba"), ("ибн абу шайба", "ibnabishayba"),
    ("исхак бин рахавайх", "ishaq"), ("исхак ибн рахавайх", "ishaq"),
    ("исмаил бин джафар", "ismail_jafar"), ("исмаил ибн джафар", "ismail_jafar"),
    ("абд бин хумайд", "abdbinhumayd"), ("абд ибн хумайд", "abdbinhumayd"),
    ("ибн аль-джад", "ibnaljad"), ("ибн хузайма", "ibnkhuzayma"),
    ("ибн хиббан", "ibnhibban"),
    ("ат-таялиси", "tayalisi"), ("ат-тиялиси", "tayalisi"),
    ("таялиси", "tayalisi"), ("тиялиси", "tayalisi"), ("тайалиси", "tayalisi"),
    ("аль-хумайди", "humaydi"), ("хумайди", "humaydi"),
    ("ад-дарими", "darimi"), ("дарими", "darimi"),
    ("абу йала", "abuyala"), ("абу яла", "abuyala"), ("абу йа'ла", "abuyala"),
    ("исхак", "ishaq"),
    # источники, у которых есть и свой сборник в боте (для кросс-ссылки):
    ("аль-бухари", "bukhari"), ("бухари", "bukhari"),
    ("муслим", "muslim"), ("абу дауд", "abudawud"),
    ("ат-тирмизи", "tirmidhi"), ("тирмизи", "tirmidhi"),
    ("ибн маджа", "ibnmajah"), ("ан-насаи", "nasai"), ("насаи", "nasai"),
    ("малик", "malik"), ("муватта", "malik"),
    ("ахмад", "ahmad"),
]
SOURCE_NAMES_RU = {
    "bukhari": "аль-Бухари", "muslim": "Муслим", "abudawud": "Абу Дауд",
    "tirmidhi": "ат-Тирмизи", "ibnmajah": "Ибн Маджа", "nasai": "ан-Насаи",
    "malik": "Малик", "ahmad": "Ахмад", "tayalisi": "ат-Таялиси",
    "humaydi": "аль-Хумайди", "ibnabishayba": "Ибн Аби Шейба",
    "darimi": "ад-Дарими", "abuyala": "Абу Я'ла", "ishaq": "Исхак ибн Рахавайх",
    "ibnkhuzayma": "Ибн Хузайма", "ibnhibban": "Ибн Хиббан",
    "abdbinhumayd": "Абд ибн Хумайд", "ismail_jafar": "Исмаил ибн Джафар",
    "ibnaljad": "Ибн аль-Джа'д",
}
# коды первоисточников, у которых НЕТ своего сборника в боте — для них
# показываем сам текст риваята из аль-Мухаймина.
SOURCE_ONLY_CODES = {"tayalisi", "humaydi", "ibnabishayba", "darimi", "abuyala",
                     "ishaq", "ibnkhuzayma", "ibnhibban", "abdbinhumayd",
                     "ismail_jafar", "ibnaljad"}

def parse_source_query(text):
    """'тиялиси 323' -> ('tayalisi', 323). Иначе (None, None)."""
    t = text.lower().strip()
    for trig, code in SOURCE_TRIGGERS:
        if t.startswith(trig):
            num = t[len(trig):].strip()
            if num.isdigit():
                return code, int(num)
    return None, None

def _clean_chapter(t):
    """Привести арабский заголовок главы к читаемому виду."""
    t = (t or "").replace("للاا", "الله")
    t = re.sub(r"\s+([ً-ٟ])", r"\1", t)   # убрать пробелы перед огласовками
    t = re.sub(r"\s+", " ", t).strip().rstrip(".").strip()
    if t.startswith("باب "):
        t = t[4:].strip()
    return t

def muhaymin_crossref_note(code, number):
    """Готовая строка-отметка: где этот первоисточник встречается в Мухаймине.
    Один и тот же хадис автор может приводить в нескольких главах — показываем
    номер + главу для каждого вхождения."""
    places = find_in_murhid(code, number)
    if not places:
        return ""
    nm = SOURCE_NAMES_RU.get(code, code)
    n = len(places)
    if n == 1:
        p = places[0]
        ch = _clean_chapter(p.get("chapter", ""))
        line = f"№{p['m']} (риваят {p['v']})"
        if ch:
            line += f" — {ch}"
        return f"\n📌 *Этот хадис есть в аль-Мухаймине* ({nm} {number}):\n{line}"
    head = (f"\n📌 *Этот хадис в аль-Мухаймине приводится {n} раз* "
            f"(один и тот же хадис в разных главах, {nm} {number}):")
    lines = []
    for p in places[:10]:
        ch = _clean_chapter(p.get("chapter", ""))
        line = f"• №{p['m']} (риваят {p['v']})"
        if ch:
            line += f" — {ch}"
        lines.append(line)
    if n > 10:
        lines.append(f"…и ещё {n - 10}")
    return head + "\n" + "\n".join(lines)

# ============ КОНЕЦ ВСТАВКИ ============

TOKEN = os.environ.get("TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
# GPT (OpenAI) для особых задач. Читаем под несколькими именами — чтобы сработало как ни назвал переменную на Railway.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("GPT_API_KEY") or os.environ.get("OPENAI_KEY") or os.environ.get("CHATGPT_API_KEY") or ""
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
# Google Gemini (бесплатный лимит) — запасной/основной мотор для особых задач, если у OpenAI нет денег
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")   # актуальная бесплатная модель (1.5-flash устаревает)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER_ID = 131827895
OWNER_CHANNEL_ID = -1001660979432
LOG_CHAT_ID = -1003480426073
GITHUB_REPO = "germanyalfurqan-eng/hadith-bot"
ANNOUNCE_CHAT_ID = -1003982210885
APP_CHANNEL_ID = -1003989206932   # @muslimoonapp — публичный канал приложения (обновления для подписчиков)

GUIDE_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/bot_guide_tg.txt"
MAIN_KB = ReplyKeyboardMarkup([["📖 Инструкция"]], resize_keyboard=True)
def get_guide():
    try:
        r = requests.get(GUIDE_URL, timeout=6)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return "📖 Инструкция временно недоступна, попробуй позже."
MEMORY_FILE = "memory.json"
REGISTRY_FILE = "registry.json"

COLLECTIONS = {
    "бухари": "bukhari", "муслим": "muslim", "абу дауд": "abudawud",
    "тирмизи": "tirmidhi", "ибн маджа": "ibnmajah", "насаи": "nasai", "муватта": "malik",
    "ахмад": "ahmad_local",
}
NAMES = {
    "bukhari": "Сахих аль-Бухари", "muslim": "Сахих Муслим", "abudawud": "Сунан Абу Дауда",
    "tirmidhi": "Сунан ат-Тирмизи", "ibnmajah": "Сунан Ибн Маджа", "nasai": "Сунан ан-Насаи",
    "malik": "Муватта имама Малика", "ahmad_local": "Муснад имама Ахмада",
}
MAX_HADITH = {"bukhari": 7563, "muslim": 3033}
GRADE_MAP = {
    "Sahih": "Сахих ✅", "Hasan": "Хасан 🟡", "Daif": "Да'иф ⚠️",
    "Mawdu": "Мавду' ❌", "Hasan Sahih": "Хасан Сахих ✅", "Sahih Hasan": "Сахих Хасан ✅",
}
AI_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

pending_edits = {}

def today():
    return datetime.now().strftime("%d.%m.%Y")

# ============ ПАМЯТЬ ============
def load_memory():
    try:
        r = requests.get(f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{MEMORY_FILE}", timeout=5)
        if r.status_code == 200:
            data = r.json()
            result = []
            for item in data:
                if isinstance(item, str):
                    result.append({"date": "—", "text": item})
                else:
                    result.append(item)
            return result
    except:
        pass
    return []

def save_memory(data):
    try:
        content = json.dumps(data, ensure_ascii=False, indent=2)
        b64 = base64.b64encode(content.encode()).decode()
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{MEMORY_FILE}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        r = requests.get(api_url, headers=headers, timeout=5)
        sha = r.json().get("sha", "") if r.status_code == 200 else ""
        payload = {"message": "update memory", "content": b64}
        if sha:
            payload["sha"] = sha
        requests.put(api_url, headers=headers, json=payload, timeout=10)
    except:
        pass

def format_memory_item(text):
    if not OPENROUTER_API_KEY:
        return text
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": AI_MODEL, "messages": [{"role": "user", "content": f"Перефразируй кратко и структурированно: {text}"}]},
            timeout=10
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
    except:
        pass
    return text

# ============ РЕЕСТР ============
def load_registry():
    try:
        r = requests.get(f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{REGISTRY_FILE}", timeout=5)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return []

def save_registry(data):
    try:
        content = json.dumps(data, ensure_ascii=False, indent=2)
        b64 = base64.b64encode(content.encode()).decode()
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{REGISTRY_FILE}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        r = requests.get(api_url, headers=headers, timeout=5)
        sha = r.json().get("sha", "") if r.status_code == 200 else ""
        payload = {"message": "update registry", "content": b64}
        if sha:
            payload["sha"] = sha
        requests.put(api_url, headers=headers, json=payload, timeout=10)
    except:
        pass

def add_to_registry(entry):
    data = load_registry()
    entry["id"] = len(data) + 1
    entry["status"] = "ожидает"
    entry["date"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    data.append(entry)
    save_registry(data)
    return entry["id"]

def mark_done(eid):
    data = load_registry()
    for e in data:
        if e["id"] == eid:
            e["status"] = "готово"
            save_registry(data)
            return True
    return False

def delete_entry(eid):
    data = [e for e in load_registry() if e["id"] != eid]
    save_registry(data)
    return True

def search_registry(query):
    return [e for e in load_registry() if query.lower() in e.get("description", "").lower()]

def ai_describe_media(text_hint=""):
    if not OPENROUTER_API_KEY:
        return text_hint or "без описания"
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": AI_MODEL, "messages": [{"role": "user", "content": f"Опиши кратко этот файл (5-10 слов): {text_hint}"}]},
            timeout=10
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
    except:
        pass
    return text_hint or "без описания"

def _ffmpeg_bin():
    return shutil.which("ffmpeg") or "ffmpeg"

def parse_audio_meta(text):
    """Достаём метаданные из команды: имя "X" исполнитель "Y" описание "Z".
    Кавычки любые (" « » “ ” ' ), опечатки терпим (исполнительнь, описани...)."""
    Q = r'["«»“”‘’«»\']'
    NQ = r'["«»“”‘’«»\'\n]'
    def grab(keys):
        m = re.search(r'(?:' + '|'.join(keys) + r')\s*[:=]?\s*' + Q + r'([^' + NQ[1:-1] + r']{1,150})', text, re.IGNORECASE)
        return m.group(1).strip() if m else ""
    title   = grab(['имя', 'назван\\w*', 'тайтл', 'title'])
    artist  = grab(['исполнител\\w*', 'артист', 'автор', 'performer', 'artist'])
    comment = grab(['описани\\w*', 'коммент\\w*', 'desc\\w*', 'comment'])
    return title, artist, comment

# ⚙️ Формула ВЫВЕРЕНА ffmpeg-замерами против эталона «нейро/Auphonic» (10.06.2026, черновик↔нейро):
#   Цель эталона: I≈-16 LUFS, TP≈-1.5, LRA≈3 (выровненная громкость для долгого прослушивания).
#   highpass(гул) → afftdn(мягкий шумодав) → acompressor r2.5 (МЯГКИЙ выравниватель: LRA→~3, НЕ давит в кашу
#   как прежний r4=LRA 0.9) → loudnorm dynamic I=-16:LRA=4 (адаптивно выравнивает) → alimiter.
#   Итог на лекции: I=-15.8, TP=-1.6, LRA=3.2 (= нейро). На коротком войсе не крушит (LRA 4.1). 192k/44.1k.
_ENH_PRE = ("highpass=f=70,"
            "afftdn=nf=-25:nr=10,"
            "acompressor=threshold=-18dB:ratio=2.5:attack=20:release=250")

def enhance_audio(input_path, output_path, artist="", title="", comment="", enhance=True):
    """Конвертация (+опц. студийное улучшение «как нейро/Auphonic») в mp3 через ffmpeg.
    Цепочка выверена замерами (см. _ENH_PRE): шумодав + мягкое выравнивание громкости (LRA≈3) +
    нормализация к -16 LUFS, пик -1.5. Теги пишем метаданными."""
    try:
        cmd = [_ffmpeg_bin(), "-y", "-i", input_path]
        if enhance:
            af = _ENH_PRE + ",loudnorm=I=-16:TP=-1.5:LRA=4,alimiter=level_in=1:level_out=1:limit=0.98"
            cmd += ["-af", af, "-ar", "44100", "-ac", "2", "-b:a", "192k"]
        else:
            cmd += ["-ar", "44100", "-ac", "2", "-b:a", "160k"]
        if title:   cmd += ["-metadata", "title=" + title]
        if artist:  cmd += ["-metadata", "artist=" + artist]
        if comment: cmd += ["-metadata", "comment=" + comment]
        cmd += [output_path]
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        if r.returncode != 0:
            print("ffmpeg error:", (r.stderr or b"").decode("utf-8", "ignore")[-600:])
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 100
    except Exception as e:
        print(f"enhance_audio error: {e}")
        return False

def convert_to_mp3(input_path, output_path, artist="", title="", comment=""):
    """Простая конвертация в mp3 (без улучшения). Сначала ffmpeg, при сбое — pydub."""
    if enhance_audio(input_path, output_path, artist=artist, title=title, comment=comment, enhance=False):
        return True
    try:
        from pydub import AudioSegment
        sound = AudioSegment.from_file(input_path)
        sound.export(output_path, format="mp3", bitrate="160k", tags={
            "artist": artist or "Unknown",
            "title": title or "Без названия",
            "comment": comment or ""
        })
        return True
    except Exception as e:
        print(f"Convert error: {e}")
        return False

def is_owner(update: Update) -> bool:
    user_id = update.effective_user.id if update.effective_user else 0
    sender_chat_id = 0
    if update.message and update.message.sender_chat:
        sender_chat_id = update.message.sender_chat.id

    if user_id == OWNER_ID:
        return True

    if sender_chat_id == OWNER_CHANNEL_ID:
        return True

    return False

# ============ ПАРСЕРЫ ============
def parse_hadith_query(text):
    text = text.lower().strip()
    # аль-Мухаймин: "мухэймин 145" / "мухаймин 145" / "муршид 145"
    for trigger in ("мухэймин ", "мухаймин ", "муршид "):
        if text.startswith(trigger):
            num = text[len(trigger):].strip()
            if num.isdigit():
                return "riwayat", int(num)

    if text == "случайный": return "random", None
    if text == "случайный бухари": return "random_bukhari", None
    if text == "случайный муслим": return "random_muslim", None
    if text == "случайный коран": return "random_quran", None
    for ru, en in COLLECTIONS.items():
        if text.startswith(ru):
            num = text.replace(ru, "").strip()
            if num.isdigit(): return en, int(num)
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

def parse_botyara(text):
    t = text.lower().strip()
    for p in ["ботяра ", "botyara "]:
        if t.startswith(p): return t[len(p):].strip()
    if t in ["ботяра", "botyara"]: return ""
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

# Словарь: русское значение → арабский корень
RU_TO_ROOT = {
    "аман": "أمن", "амана": "أمن", "вера": "أمن", "безопасность": "أمن",
    "барака": "برك", "баракат": "برك", "благословение": "برك",
    "батин": "بطن", "скрытый": "بطن", "внутренний": "بطن",
    "вахй": "وحي", "откровение": "وحي",
    "ваджд": "وجد", "нахождение": "وجد", "экстаз": "وجد",
    "гъайб": "غيب", "сокрытое": "غيب", "гайб": "غيب",
    "гъафара": "غفر", "прощение": "غفر", "гафара": "غفر",
    "дин": "دين", "религия": "دين",
    "дуа": "دعو", "мольба": "دعو", "молитва": "دعو",
    "дунья": "دني", "мир": "دني", "ближний": "دني",
    "дараба": "ضرب", "бить": "ضرب", "удар": "ضرب", "пример": "ضرب",
    "зикр": "ذكر", "поминание": "ذكر", "помнить": "ذكر",
    "закят": "زكو", "милостыня": "زكو", "очищение": "زكو",
    "ильм": "علم", "знание": "علم", "наука": "علم",
    "иман": "أمن",
    "ислам": "سلم", "покорность": "سلم",
    "ихлас": "خلص", "искренность": "خلص",
    "ихсан": "حسن", "совершенство": "حسن", "добро": "حسن",
    "кутуб": "كتب", "писание": "كتب", "писать": "كتب", "китаб": "كتب",
    "кафир": "كفر", "неверный": "كفر", "неверие": "كفر",
    "калима": "كلم", "слово": "كلم", "речь": "كلم",
    "кадар": "قدر", "предопределение": "قدر", "судьба": "قدر",
    "курбан": "قرب", "близость": "قرب", "жертва": "قرب",
    "кибла": "قبل", "направление": "قبل",
    "киям": "قوم", "стояние": "قوم", "восстание": "قوم",
    "нур": "نور", "свет": "نور",
    "нафс": "نفس", "душа": "نفس", "эго": "نفس",
    "наби": "نبأ", "пророк": "نبأ",
    "ни'ма": "نعم", "благо": "نعم", "милость": "نعم",
    "рабб": "ربب", "господь": "ربب", "господин": "ربب",
    "рахман": "رحم", "милостивый": "رحم", "милосердие": "رحم",
    "рахим": "رحم", "милосердный": "رحم",
    "рух": "روح", "дух": "روح",
    "ризк": "رزق", "удел": "رزق", "пропитание": "رزق",
    "сабр": "صبر", "терпение": "صبر", "терпеть": "صبر",
    "салят": "صلو", "намаз": "صلو",
    "саум": "صوم", "пост": "صوم", "поститься": "صوم",
    "салам": "سلم", "приветствие": "سلم",
    "саджда": "سجد", "поклон": "سجد", "земной": "سجد",
    "тавба": "توب", "покаяние": "توب", "раскаяние": "توب",
    "таква": "وقي", "богобоязненность": "وقي", "набожность": "وقي",
    "тафсир": "فسر", "толкование": "فسر", "разъяснение": "فسر",
    "таухид": "وحد", "единобожие": "وحد", "единство": "وحد",
    "хадис": "حدث", "рассказ": "حدث", "предание": "حدث",
    "халяль": "حلل", "дозволенное": "حلل",
    "харам": "حرم", "запретное": "حرم", "запрет": "حرم",
    "хамд": "حمد", "хвала": "حمد", "восхваление": "حمد",
    "хакк": "حقق", "истина": "حقق", "право": "حقق",
    "хукм": "حكم", "мудрость": "حكم", "суд": "حكم", "правило": "حكم", "закон": "حكم",
    "хаят": "حيي", "жизнь": "حيي",
    "хиджра": "هجر", "переселение": "هجر",
    "шариат": "شرع", "путь": "شرع",
    "шайтан": "شطن", "сатана": "شطن", "дьявол": "شطن",
    "шахада": "شهد", "свидетельство": "شهد", "свидетель": "شهد",
    "шукр": "شكر", "благодарность": "شكر", "благодарить": "شكر",
    "фикх": "فقه", "понимание": "فقه",
    "фаджр": "فجر", "рассвет": "فجر",
    "фатиха": "فتح", "открывающая": "فتح", "открытие": "فتح",
    "джахиль": "جهل", "невежество": "جهل", "незнание": "جهل",
    "джанна": "جنن", "рай": "جنن", "сад": "جنن",
    "джихад": "جهد", "усердие": "جهد", "борьба": "جهد",
    "тагут": "طغي", "тиран": "طغي", "преступление": "طغي",
    "тахара": "طهر", "чистота": "طهر",
    "талак": "طلق", "развод": "طلق",
    "тарика": "طرق", "метод": "طرق",
    "ахль": "أهل", "семья": "أهل", "люди": "أهل",
    "ахира": "أخر", "последняя": "أخر", "загробный": "أخر",
    "адаб": "أدب", "воспитание": "أدب", "этика": "أدب",
    "азан": "أذن", "призыв": "أذن", "разрешение": "أذن",
    "залим": "ظلم", "несправедливый": "ظلم", "зульм": "ظلم", "несправедливость": "ظلم",
    "захир": "ظهر", "явный": "ظهر", "внешний": "ظهر",
    "фасад": "فسد", "нечестие": "فسد", "порча": "فسد",
    "фитра": "فطر", "естество": "فطر", "природа": "فطر",
    "фуркан": "فرق", "различение": "فرق", "критерий": "فرق",
    "кысас": "قصص", "возмездие": "قصص", "рассказ": "قصص",
    "сира": "سير", "жизнеописание": "سير",
    "сунна": "سنن", "обычай": "سنن",
    "хикма": "حكم", "хидая": "هدي", "наставление": "هدي", "худа": "هدي", "руководство": "هدي",
    "ваджиб": "وجب", "обязательное": "وجب", "долг": "وجب",
    "вали": "ولي", "покровитель": "ولي", "друг": "ولي", "святой": "ولي",
    "му'мин": "أمن", "верующий": "أمن",
    "муслим": "سلم", "мусульманин": "سلم",
    "мушрик": "شرك", "многобожник": "شرك", "язычник": "شرك",
    "мунафик": "نفق", "лицемер": "نفق",
    "муттаки": "وقي", "богобоязненный": "وقي",
    "баракят": "برك", "благодать": "برك",
    "басир": "بصر", "видящий": "بصر", "зрение": "بصر",
    "далиль": "دلل", "доказательство": "دلل", "указание": "دلل",
    "да'ва": "دعو", "проповедь": "دعو",
}


def find_root_transliteration(arabic_root):
    """Ищет транслитерацию корня через corpus.quran.com"""
    try:
        url = f"https://corpus.quran.com/search.jsp?q={arabic_root}"
        r = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en"
        })
        match = re.search(r'qurandictionary\.jsp\?q=(\w+)', r.text)
        if match:
            return match.group(1)

        r2 = requests.get(
            f"https://corpus.quran.com/qurandictionary.jsp?q={arabic_root}",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}
        )
        if "No results found" not in r2.text and len(r2.text) > 500:
            return arabic_root
    except:
        pass
    return None

def parse_registry_command(text):
    t = text.lower().strip()
    if t in ["в реестр", "реестр добавить", "ботяра сохрани"]: return "add_media"
    if t == "реестр": return "all"
    if t.startswith("реестр "): return t[8:].strip()
    if t == "ожидает": return "pending"
    for cmd in ["сделано ", "готово "]:
        if t.startswith(cmd):
            n = t[len(cmd):].strip()
            if n.isdigit(): return f"done_{n}"
    if t.startswith("удали "):
        n = t[6:].strip()
        if n.isdigit(): return f"delete_{n}"
    if t.startswith("результат "):
        parts = t[10:].strip().split(" ", 1)
        if parts[0].isdigit():
            return f"result_{parts[0]}_{parts[1] if len(parts) > 1 else ''}"
    return None

# ============ ХАДИСЫ ============
# ---- Муслим: нумерация Абд аль-Баки (как в приложении и у учёных), а НЕ fawazahmed0 (M197) ----
_MUSLIM_BAQI = None
def _load_muslim_baqi():
    """Карта Муслима Абд аль-Баки {num: {ar, fw}} (docs/muslim_baqi.json), грузим один раз."""
    global _MUSLIM_BAQI
    if _MUSLIM_BAQI is not None:
        return _MUSLIM_BAQI
    _MUSLIM_BAQI = {}
    for u in (f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/docs/muslim_baqi.json",
              f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/docs/muslim_baqi.json"):
        try:
            r = requests.get(u, timeout=20)
            if r.status_code == 200:
                _MUSLIM_BAQI = {int(x["num"]): x for x in r.json() if "num" in x}
                break
        except: pass
    return _MUSLIM_BAQI

def _norm_ar(s):
    return re.sub(r"[^ء-ي]", "", s or "")

def get_muslim_baqi_hadith(number):
    """Муслим по Абд аль-Баки: арабский — из нашей карты (верный текст+номер); готовый русский —
    из fawazahmed0 rus-muslim/{fw}, НО только если арабский fawaz[fw] СОВПАЛ с нашим (поле fw местами
    битое — без сверки вернули бы чужой перевод = баг M197). None → номера нет в Абд аль-Баки (общий путь)."""
    try:
        e = _load_muslim_baqi().get(int(number))
        if not e:
            return None
        arabic = (e.get("ar") or "").replace("\n", " ").strip()
        russian = grade = ""
        fw = e.get("fw")
        if fw and arabic:
            try:
                ra = requests.get(f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/ara-muslim/{fw}.min.json", timeout=10)
                ok = False
                if ra.status_code == 200:
                    ha = ra.json().get("hadiths", [])
                    if ha:
                        ok = _norm_ar(ha[0].get("text", ""))[:40] == _norm_ar(arabic)[:40]
                if ok:
                    rr = requests.get(f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/rus-muslim/{fw}.min.json", timeout=10)
                    if rr.status_code == 200:
                        hr = rr.json().get("hadiths", [])
                        if hr:
                            russian = re.sub(r"\[\d+\]", "", hr[0].get("text", "").replace("\\n", " "))
            except: pass
        return arabic, russian, ("рус" if russian else "араб"), grade
    except:
        return None

def get_hadith(collection, number):
    if collection == "muslim":
        res = get_muslim_baqi_hadith(number)
        if res is not None:
            return res
    try:
        ua = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/ara-{collection}/{number}.min.json"
        ur = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/rus-{collection}/{number}.min.json"
        ue = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/eng-{collection}/{number}.min.json"
        arabic = russian = english = grade = ""
        # арабский — главное; берём с повтором и фолбэк-CDN (бывают таймауты)
        ua_fallback = f"https://raw.githubusercontent.com/fawazahmed0/hadith-api/1/editions/ara-{collection}/{number}.min.json"
        for u in (ua, ua, ua_fallback):
            try:
                r = requests.get(u, timeout=15)
                if r.status_code == 200:
                    h = r.json().get("hadiths", [])
                    if h and h[0].get("text", "").strip():
                        arabic = h[0].get("text", "").replace("\n", " ")
                        break
            except: pass
        try:
            r = requests.get(ur, timeout=10)
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
                r = requests.get(ue, timeout=10)
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
        if arabic or translation: return arabic, translation, lang, grade
    except: pass
    return "", "", "", ""

def get_ahmad_hadith(number):
    try:
        if number <= 561:
            url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/ahmad_1.json"
        elif number <= 1380:
            url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/ahmad_2.json"
        elif number <= 14600:
            url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/ahmad_3a.json"
        else:
            url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/ahmad_3b.json"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for h in data:
                if h["number"] == number:
                    grade_map = {"صحيح": "Сахих ✅", "حسن": "Хасан 🟡", "ضعيف": "Да'иф ⚠️"}
                    grade = grade_map.get(h.get("grade", ""), h.get("grade", ""))
                    return h["arabic"], "", "араб", grade
    except: pass
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
        a = r = ""
        ra = requests.get(ua, timeout=10)
        if ra.status_code == 200: a = ra.json().get("text", "")
        rr = requests.get(ur, timeout=10)
        if rr.status_code == 200: r = rr.json().get("text", "")
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
        t = re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ', html)))
        blocks = t.split("--------------")
        results = []
        for b in blocks[:5]:
            b = b.strip()
            if not b: continue
            m = re.match(r'^\d+\s*-\s*(.*)', b)
            if not m: continue
            text = m.group(1).strip()
            rawi = muhaddith = source = page = grade = ""
            for k, v in [("الراوي:", "rawi"), ("المحدث:", "muhaddith"), ("المصدر:", "source"), ("الصفحة أو الرقم:", "page"), ("خلاصة حكم المحدث:", "grade")]:
                m2 = re.search(rf'{k}\s*([^\n]+)', b)
                if m2:
                    val = m2.group(1).strip()
                    if val == "-": val = ""
                    if v == "rawi": rawi = val
                    elif v == "muhaddith": muhaddith = val
                    elif v == "source": source = val
                    elif v == "page": page = val
                    elif v == "grade": grade = val
            for mk in ["الراوي:", "المحدث:", "المصدر:"]:
                if mk in text: text = text.split(mk)[0].strip()
            if text and len(text) > 10:
                results.append({"text": text, "rawi": rawi, "muhaddith": muhaddith, "source": source, "page": page, "grade": grade})
        return results
    except: return []

def search_similar_hadith(arabic_text):
    if not arabic_text or len(arabic_text) < 20: return []
    q = " ".join(arabic_text[:100].split()[-5:])
    try:
        r = requests.get(f"https://dorar.net/dorar_api.json?skey={q}&page=1", timeout=10)
        if r.status_code != 200: return []
        html = r.json().get("ahadith", {}).get("result", "")
        if not html: return []
        t = re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ', html)))
        blocks = t.split("--------------")
        refs = []
        for b in blocks[:5]:
            if not b.strip(): continue
            source = page = ""
            m = re.search(r'المصدر:\s*([^\n]+)', b)
            if m: source = m.group(1).strip()
            m = re.search(r'الصفحة أو الرقم:\s*([^\n]+)', b)
            if m: page = m.group(1).strip()
            if source:
                ref = source + (f" №{page}" if page else "")
                if ref not in refs: refs.append(ref)
        return refs
    except: return []

# ===== 🚨 АВТО-РУБИЛЬНИК ЗАЩИТЫ КЛЮЧА (анти-спам ИИ) =====
# Если за окно слишком много вызовов ИИ — АВТО-выключаем ИИ и ждём владельца (защита баланса DeepSeek).
_AI_CALLS = []
_AI_KILL = False           # авто-выключение (спам)
_AI_KILL_MANUAL = False    # ручное выключение владельцем
_AI_KILL_PENDING = None    # текст уведомления владельцу (отправится при следующем апдейте)
_MAINTENANCE = False       # B4: режим обслуживания (бот стоп/старт) — для остальных бот молчит-заглушка, владелец работает
AI_RATE_LIMIT = 35         # >35 вызовов ИИ за окно → авария
AI_RATE_WINDOW = 120       # секунд
def ai_kill_active():
    return _AI_KILL or _AI_KILL_MANUAL
def ai_note_call():
    """Учесть вызов ИИ; вернуть False, если ИИ выключен или сработал авто-рубильник (спам)."""
    global _AI_KILL, _AI_KILL_PENDING
    if _AI_KILL or _AI_KILL_MANUAL:
        return False
    now = time.time(); _AI_CALLS.append(now)
    while _AI_CALLS and now - _AI_CALLS[0] > AI_RATE_WINDOW:
        _AI_CALLS.pop(0)
    if len(_AI_CALLS) > AI_RATE_LIMIT:
        _AI_KILL = True
        _AI_KILL_PENDING = (f"🚨 АВТО-РУБИЛЬНИК: {len(_AI_CALLS)} запросов к ИИ за {AI_RATE_WINDOW}с — похоже на спам. "
                            f"ИИ ВЫКЛЮЧЕН автоматически (защита баланса DeepSeek). Включить: «ии вкл».")
        return False
    return True

def ask_deepseek(prompt, system, max_tokens=2000):
    """Личный ответ владельцу через DeepSeek API. max_tokens — потолок длины ответа
    (для перевода длинных хадисов поднимаем, иначе текст обрывается на полуслове)."""
    if not ai_note_call():   # 🚨 защита: ИИ выключен/спам → не тратим ключ
        return None
    try:
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={"model": DEEPSEEK_MODEL,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": prompt}],
                  "max_tokens": max_tokens},
            timeout=90)
        if r.status_code == 200:
            ответ = r.json()["choices"][0]["message"]["content"]
            ответ = ответ.replace("\n\n\n", "\n\n")
            return f"{ответ}\n\n⚡ *Модель:* 🐬 DeepSeek"
    except Exception:
        pass
    return None

def deepseek_balance():
    """Остаток баланса DeepSeek API (чтобы следить, не кончается ли)."""
    try:
        r = requests.get("https://api.deepseek.com/user/balance",
                         headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

# === Строгий учёт расхода GPT (внутренняя кухня R30): токены+стоимость → data/gpt_spend.json + уведомление в LOG ===
OPENAI_PRICES = {  # USD за 1M токенов (вход, выход) — приблизительно
    "gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.0),
    "gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.0, 8.0), "gpt-5": (1.25, 10.0),
}
GPT_SPEND_FILE = "data/gpt_spend.json"
_LAST_GPT_SPEND = {}
def _gpt_price(model):
    for k, v in OPENAI_PRICES.items():
        if model and k in str(model):
            return v
    return OPENAI_PRICES["gpt-4o-mini"]   # дефолт-оценка
def _record_gpt_spend(model, pin, pout):
    """Записать расход одного GPT-вызова: стоимость + накопительный итог. _now_msk определён ниже (вызов в рантайме — ок)."""
    global _LAST_GPT_SPEND
    pi, po = _gpt_price(model)
    cost = (int(pin or 0) / 1e6) * pi + (int(pout or 0) / 1e6) * po
    rec = {"t": _now_msk(), "model": model, "in": int(pin or 0), "out": int(pout or 0), "cost": round(cost, 6)}
    try:
        os.makedirs("data", exist_ok=True)
        hist = json.load(open(GPT_SPEND_FILE, encoding="utf-8")) if os.path.exists(GPT_SPEND_FILE) else {"total": 0.0, "calls": 0, "log": []}
        hist["total"] = round(float(hist.get("total", 0.0)) + cost, 6)
        hist["calls"] = int(hist.get("calls", 0)) + 1
        hist["log"] = (hist.get("log", []) + [rec])[-500:]
        json.dump(hist, open(GPT_SPEND_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        rec["total"], rec["calls"] = hist["total"], hist["calls"]
    except Exception:
        pass
    _LAST_GPT_SPEND = rec
    return rec

def ask_gpt(prompt, system=None, max_tokens=900):
    """GPT (OpenAI) для особых задач. Ключ — переменная OPENAI_API_KEY на Railway. Возвращает текст или None/ошибку."""
    if not OPENAI_API_KEY:
        return None
    try:
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": OPENAI_MODEL, "messages": msgs, "max_tokens": max_tokens},
            timeout=90)
        if r.status_code == 200:
            j = r.json()
            try:
                u = j.get("usage") or {}
                _record_gpt_spend(j.get("model", OPENAI_MODEL), u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
            except Exception:
                pass
            return j["choices"][0]["message"]["content"].strip()
        return f"⚠️ GPT вернул код {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return f"⚠️ GPT недоступен: {e}"

def ask_gemini(prompt, system=None):
    """Google Gemini (бесплатный лимит). Ключ — GEMINI_API_KEY на Railway."""
    if not GEMINI_API_KEY:
        return None
    try:
        parts = []
        if system:
            parts.append({"text": system + "\n\n"})
        parts.append({"text": prompt})
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": parts}]},
            timeout=90)
        if r.status_code == 200:
            j = r.json()
            return j["candidates"][0]["content"]["parts"][0]["text"].strip()
        return f"⚠️ Gemini код {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return f"⚠️ Gemini недоступен: {e}"

def ask_special(prompt, system=None):
    """Особые задачи: пробуем OpenAI (если есть ключ+деньги), иначе Gemini (бесплатный лимит). Возвращает (ответ, имя_модели)."""
    if OPENAI_API_KEY:
        a = ask_gpt(prompt, system)
        if a and not str(a).startswith("⚠️"):
            return a, f"GPT · {OPENAI_MODEL}"
    if GEMINI_API_KEY:
        a = ask_gemini(prompt, system)
        if a and not str(a).startswith("⚠️"):
            return a, f"Gemini · {GEMINI_MODEL}"
    # вернём хоть какую-то диагностику
    if OPENAI_API_KEY:
        return ask_gpt(prompt, system), "GPT"
    if GEMINI_API_KEY:
        return ask_gemini(prompt, system), "Gemini"
    return None, None

def ask_ai(prompt, system=None, owner=False, max_tokens=None):
    if ai_kill_active():   # 🚨 авто-рубильник: ИИ выключен (спам/вручную) — не дёргаем ни DeepSeek, ни бесплатные
        return "⏸ ИИ временно на паузе (защита от спама). Включит владелец."
    if system is None:
        system = f"Ты — полезный ассистент в исламском Телеграм-боте. Отвечай на русском. Сегодняшняя дата: {datetime.now().strftime('%d.%m.%Y')}."
    # для владельца — сначала его DeepSeek
    if owner and DEEPSEEK_API_KEY:
        d = ask_deepseek(prompt, system, max_tokens or 2000)
        if d is not None:
            return d
    модели = [
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-r1:free",
        "qwen/qwen3-235b-a22b:free",
        "microsoft/phi-4-reasoning-plus:free",
        "openrouter/auto",
    ]

    имена = {
        "meta-llama/llama-3.3-70b-instruct:free": "🦙 Llama 3.3 70B (Meta)",
        "deepseek/deepseek-r1:free": "🧠 DeepSeek R1",
        "qwen/qwen3-235b-a22b:free": "⚡ Qwen3 235B (Alibaba)",
        "microsoft/phi-4-reasoning-plus:free": "🔬 Phi-4 Reasoning (Microsoft)",
        "openrouter/auto": "🔄 Auto (OpenRouter)",
    }

    if not OPENROUTER_API_KEY:
        return "❌ API-ключ не настроен."

    if system is None:
        system = f"Ты — полезный ассистент в исламском Телеграм-боте. Отвечай на русском. Сегодняшняя дата: {datetime.now().strftime('%d.%m.%Y')}."

    for модель in модели:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": модель,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": max_tokens or 1500
                },
                timeout=60
            )

            if r.status_code == 200:
                ответ = r.json()["choices"][0]["message"]["content"]
                имя_модели = имена.get(модель, модель)
                if max_tokens is None and len(ответ) > 2500:   # обрез только для обычного чата; перевод (max_tokens задан) — целиком
                    ответ = ответ[:2500] + "\n\n...(ответ сокращён)"
                ответ = ответ.replace("\n\n\n", "\n\n")
                return f"{ответ}\n\n⚡ *Модель:* {имя_модели}"
            elif r.status_code == 429:
                continue
            else:
                continue
        except:
            continue
    return "❌ Все AI-модели временно недоступны. Попробуйте позже."

def ask_ai_with_memory(prompt, owner=True):
    memory = load_memory()
    system = (f"Ты — исламский ассистент в Телеграм-боте Muslimoon. Отвечай по-русски. Сегодня {datetime.now().strftime('%d.%m.%Y')}.\n"
              "Отвечай ЛАКОНИЧНО и ПО СУЩЕСТВУ: обычно 2–6 предложений, без воды, без длинных вступлений и "
              "заключений, без повторов вопроса. Где уместно — короткий довод (аят/хадис/правило). "
              "Списком — только если он реально нужен. НЕ выдумывай хадисы и факты; если не уверен — честно скажи.")
    if memory:
        memory_text = "\n".join([f"- [{m.get('date','—')}] {m.get('text','')}" for m in memory])
        system += f"\n\nЧто ты знаешь о владельце и контексте:\n{memory_text}"
    return ask_ai(prompt, system, owner=owner)

# ---- Накопительный кэш переводов матнов (хранится в репо на GitHub) ----
TRANS_FILE = "translations.json"
_trans_cache = None
_trans_dirty = 0
def _load_trans():
    # G9: кэш переводов теперь в ветке data (запись в main = редеплой Railway = Conflict).
    global _trans_cache
    if _trans_cache is None:
        _trans_cache = {}
        try:
            d = _data_get(TRANS_FILE, None)          # сначала ветка data
            if isinstance(d, dict):
                _trans_cache = d
            else:                                    # миграция: разовый перенос накопленного из main
                r = requests.get(f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{TRANS_FILE}", timeout=8)
                if r.status_code == 200:
                    _trans_cache = r.json()
        except Exception:
            pass
    return _trans_cache
def _save_trans():
    """Записать кэш переводов в ветку data (не трогаем main → нет редеплоя/Conflict)."""
    if not GITHUB_TOKEN:
        return
    _data_put(TRANS_FILE, _trans_cache, f"translations ({len(_trans_cache)})")
def flush_trans():
    global _trans_dirty
    if _trans_dirty:
        _save_trans(); _trans_dirty = 0
def _trans_key(arabic):
    t = re.sub(r"[ً-ٰٟـ]", "", arabic or "")
    return "".join(c for c in t if "ء" <= c <= "ي")[:300]
def _is_mostly_arabic(s):
    """True, если арабского в строке не меньше, чем русского → перевод НЕ сделан (модель вернула оригинал)."""
    if not s:
        return False
    ar = len(re.findall(r'[؀-ۿ]', s)); ru = len(re.findall(r'[А-Яа-яЁё]', s))
    return ar >= 8 and ar >= ru

def _chunk_by_paras(text, maxlen=1200):
    """Режем длинный текст на куски по абзацам (≤maxlen): free-модели переводят короткое надёжнее длинного."""
    chunks = []; cur = ''
    for p in re.split(r'\n+', text):
        p = p.strip()
        if not p:
            continue
        if cur and len(cur) + len(p) + 1 > maxlen:
            chunks.append(cur); cur = ''
        cur = (cur + '\n' + p) if cur else p
        while len(cur) > maxlen:
            cut = cur.rfind(' ', 0, maxlen)
            if cut < maxlen // 2:
                cut = maxlen
            chunks.append(cur[:cut].strip()); cur = cur[cut:].strip()
    if cur:
        chunks.append(cur)
    return chunks

def translate_matn(arabic, src="", owner=False, force=False):
    """Перевод матна на русский с накопительным кэшем (оригинал+перевод+источник).
    force=True — переперевести заново (минуя кэш). Длинные тексты переводим ПО АБЗАЦАМ, иначе free-модель
    часто возвращает арабский оригинал вместо перевода. Битый арабский кэш игнорируем и переводим заново."""
    global _trans_dirty
    if not arabic or len(arabic) < 5:
        return ""
    cache = _load_trans()
    key = _trans_key(arabic)
    if key in cache and not force:
        v = cache[key]
        cru = v.get("ru", "") if isinstance(v, dict) else v
        if cru and not _is_mostly_arabic(cru):
            return cru                 # нормальный русский кэш
        # иначе — старый битый (арабский) кэш: игнорируем и переводим заново ниже
    sysmsg = ("Ты профессиональный переводчик с арабского на русский. "
              "Переведи текст на русский язык ПОЛНОСТЬЮ, до конца (не обрывай). "
              "Ответ ДОЛЖЕН быть на РУССКОМ — НЕ копируй арабский, НЕ оставляй арабские предложения. "
              "Имена и термины передавай по-русски. "
              "Без вступлений, без пояснений, без кавычек, без указания модели — только перевод.")
    def _one(t):
        r = ask_ai("Переведи на русский:\n" + t, sysmsg, owner=owner, max_tokens=4000)
        if not r or r.startswith("❌") or r.startswith("⏸"):
            return None
        return re.sub(r"\n*⚡ \*Модель:.*$", "", r, flags=re.S).strip()
    if len(arabic) > 1400:
        parts = []
        for ch in _chunk_by_paras(arabic, 1200):
            tr = _one(ch)
            if tr and not _is_mostly_arabic(tr):   # арабский-эхо отбрасываем
                parts.append(tr)
        ru = "\n".join(parts).strip()
    else:
        ru = (_one(arabic) or "").strip()
    if ru and not _is_mostly_arabic(ru):
        cache[key] = {"ar": arabic[:600], "ru": ru, "src": (src or "")[:120]}
        _trans_dirty += 1
        if _trans_dirty >= 3:          # батч: коммитим в репо каждые 3 новых
            _save_trans(); _trans_dirty = 0
        return ru
    return ""                          # перевод не удался (арабский/пусто) — мусор не кэшируем

async def send_long(update, text, parse_mode=None):
    limit = 3900
    while text:
        if len(text) <= limit:
            chunk, text = text, ""
        else:
            cut = text.rfind("\n", 0, limit)        # резать по строке
            if cut < limit // 2:
                cut = text.rfind(" ", 0, limit)      # иначе по пробелу
            if cut <= 0:
                cut = limit
            chunk, text = text[:cut], text[cut:].lstrip("\n ")
        try:
            if parse_mode:
                await update.message.reply_text(chunk, parse_mode=parse_mode)
            else:
                await update.message.reply_text(chunk)
        except Exception:
            await update.message.reply_text(chunk)   # фолбэк без разметки

async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        member = update.chat_member
        user = member.new_chat_member.user
        now = datetime.now().strftime("%d.%m.%Y, %H:%M")
        name = user.full_name
        username = f"@{user.username}" if user.username else "нет"
        uid = user.id
        if member.new_chat_member.status == "member":
            msg = f"➕ {name}\n🔗 {username}\n🆔 {uid}\n📁 {chat.title}\n🕐 {now}"
        elif member.new_chat_member.status in ["left", "kicked"]:
            a = "🚫 Удалён" if member.new_chat_member.status == "kicked" else "➖ Вышел"
            msg = f"{a} {name}\n🔗 {username}\n🆔 {uid}\n📁 {chat.title}\n🕐 {now}"
        else: return
        await context.bot.send_message(chat_id=LOG_CHAT_ID, text=msg)
    except: pass

_AI_BAN = set()   # чёрный список (chat_id/user_id) — кого НЕ обслуживать ИИ; владелец правит командами «бан/разбан»

def _ai_loop_guard(update, text):
    """Анти-цикл и анти-спам для ИИ: не реагировать на ПЕРЕСЛАННЫЕ сообщения и на НАШИ ЖЕ лог-сообщения
    (их пересылали в группу → бот отвечал сам себе и жёг ключ)."""
    try:
        if update.message and update.message.forward_origin is not None:
            return True
    except Exception:
        pass
    t = text or ""
    if ("ключ потрачен" in t) or ("#ии" in t) or ("#ботяра" in t) or ("⚡ *Модель:*" in t) or ("Модель:* 🐬" in t):
        return True
    return False

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = update.message.text or ""
    text = text.strip()

    # 📥 СКРИН-ЗАЯВКА владельца: фото с подписью «заявка ...»/«замечание ...» → запись с номером + архив в рабочий журнал (LOG)
    try:
        if is_owner(update) and update.message.photo and (update.message.caption or "").strip().lower().startswith(("заявка", "замечание")):
            cap = (update.message.caption or "").strip()
            body = cap[6:].strip() if cap.lower().startswith("заявка") else cap[9:].strip()
            dup = req_dup(body) if len(body) >= 6 else None
            if dup:
                await update.message.reply_text(f"⚠️ Похоже, ты это уже присылал — заявка №{dup}. Не дублирую.")
                return
            rid = req_add(body or "(скрин)", img_flag=True, imgkey=str(update.message.photo[-1].file_id))
            try:
                await context.bot.copy_message(LOG_CHAT_ID, update.effective_chat.id, update.message.message_id)
                await context.bot.send_message(LOG_CHAT_ID, f"📥 Заявка владельца №{rid} ({_now_msk()}): {(body or '(скрин)')[:300]}")
            except Exception:
                pass
            await update.message.reply_text(f"📥 Заявка №{rid} со скрином записана ✅. Список — «заявки».")
            return
    except Exception:
        pass

    # 🚨 авто-рубильник ИИ (защита баланса DeepSeek): уведомить владельца о срабатывании + команды управления
    global _AI_KILL, _AI_KILL_MANUAL, _AI_KILL_PENDING
    if _AI_KILL_PENDING:
        _m = _AI_KILL_PENDING; _AI_KILL_PENDING = None
        try: await context.bot.send_message(OWNER_ID, _m)
        except Exception: pass
        try: await context.bot.send_message(LOG_CHAT_ID, _m)
        except Exception: pass
    if is_owner(update) and text.lower() in ("ии вкл", "ии включи", "включи ии", "ai on"):
        _AI_KILL = False; _AI_KILL_MANUAL = False; _AI_CALLS.clear()
        await update.message.reply_text("✅ ИИ снова включён."); return
    if is_owner(update) and text.lower() in ("ии выкл", "выключи ии", "ai off", "ии стоп"):
        _AI_KILL_MANUAL = True
        await update.message.reply_text("⏸ ИИ выключен вручную. Включить: «ии вкл»."); return
    if is_owner(update) and text.lower() in ("ии статус", "статус ии", "ai status"):
        await update.message.reply_text(f"ИИ: {'⏸ ВЫКЛ' if ai_kill_active() else '✅ вкл'}\nВызовов за {AI_RATE_WINDOW}с: {len(_AI_CALLS)}/{AI_RATE_LIMIT}\nавто-выкл={_AI_KILL} · ручной={_AI_KILL_MANUAL}"); return

    # B4: режим обслуживания — «бот стоп» / «бот старт» (только владелец); для остальных бот отвечает заглушкой
    global _MAINTENANCE
    if is_owner(update) and text.lower() in ("бот стоп", "бот выкл", "стоп бот", "обслуживание", "обслуживание вкл"):
        _MAINTENANCE = True
        await update.message.reply_text("🔧 Режим обслуживания ВКЛ. Для остальных бот отвечает заглушкой (поиск/ИИ не работают). Вернуть в эфир: «бот старт»."); return
    if is_owner(update) and text.lower() in ("бот старт", "бот вкл", "старт бот", "обслуживание выкл"):
        _MAINTENANCE = False
        await update.message.reply_text("✅ Бот снова в эфире (обслуживание выключено)."); return
    if _MAINTENANCE and not is_owner(update):
        try: await update.message.reply_text("🔧 Бот на техническом обслуживании — скоро вернёмся, ин ша Аллах.")
        except Exception: pass
        return

    if text in ("📖 Инструкция", "инструкция", "путеводитель", "гайд", "/guide"):
        await send_long(update, get_guide())
        return
    if is_owner(update) and text.strip().lower() in ("анонс", "обновление", "релиз"):
        try:
            r = requests.get(f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/release_notes.txt", timeout=8)
            note = r.text if r.status_code == 200 else "Нет release_notes.txt"
            await context.bot.send_message(ANNOUNCE_CHAT_ID, note)
            await update.message.reply_text("✅ Опубликовано в канале обновлений.")
        except Exception as e:
            await update.message.reply_text("Ошибка анонса: " + str(e))
        return
    # ===== Владельцу: баланс DeepSeek + ресурсы =====
    if is_owner(update) and text.strip().lower() in ("баланс", "баланс дипсик", "дипсик баланс", "deepseek баланс", "баланс ии"):
        b = deepseek_balance()
        if not b:
            await update.message.reply_text("⚠️ Не удалось получить баланс DeepSeek (проверь ключ/сеть).\nСтраница: platform.deepseek.com/usage")
            return
        lines = ["💳 *Баланс DeepSeek*", f"Доступен: {'✅ да' if b.get('is_available') else '❌ НЕТ'}"]
        for i in b.get("balance_infos", []):
            lines.append(f"• {i.get('currency','')}: осталось *{i.get('total_balance','?')}* (пополнено {i.get('topped_up_balance','?')}, бонус {i.get('granted_balance','?')})")
        lines.append("\n📈 Подробно: platform.deepseek.com/usage")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)
        return
    if is_owner(update) and text.strip().lower() in ("ресурсы", "рабочий стол", "ссылки", "инструменты"):
        await update.message.reply_text(
            "🧰 *Рабочие ресурсы*\n"
            "• 💳 DeepSeek расход/баланс: platform.deepseek.com/usage  (команда: баланс)\n"
            f"• 🔤 Переводы по сборникам: github.com/{GITHUB_REPO}/tree/data/translations\n"
            f"• 📊 Журналы (расход+накопление): github.com/{GITHUB_REPO}/blob/data/journal.json\n"
            f"• 🔐 Доступы: github.com/{GITHUB_REPO}/blob/data/access.json\n"
            "• 📱 Мини-апп: germanyalfurqan-eng.github.io/hadith-bot/\n\n"
            "Команды: баланс · журнал ии · накопление · ресурсы · анонс",
            parse_mode="Markdown", disable_web_page_preview=True)
        return

    if is_owner(update) and text.strip().lower() in ("запросы", "что ищут", "аналитика", "статистика поиска"):
        j = _journal_load(); s = j.get("searches", {})
        top = sorted(s.get("top", {}).items(), key=lambda x: -x[1].get("n", 0))[:20]
        lines = [f"🔎 *Что ищут* (всего поисков: {s.get('total', 0)})"]
        if top:
            for q, e in top:
                lines.append(f"• {q} — {e.get('n', 0)}× ({e.get('tab', '')}, нашли {e.get('cnt', 0)})")
        else:
            lines.append("пока пусто")
        await update.message.reply_text("\n".join(lines)[:3900], parse_mode="Markdown")
        return

    if is_owner(update) and text.strip().lower() in ("отзывы", "обратная связь", "комментарии", "ошибки людей"):
        j = _journal_load(); fb = j.get("feedback", [])
        if not fb:
            await update.message.reply_text("Отзывов пока нет.")
            return
        lines = ["💬 *Отзывы / ошибки (последние)*"]
        for x in fb[:15]:
            c = f" · {x['ctx']}" if x.get("ctx") else ""
            lines.append(f"\n*№{x.get('id','?')}* · {x['d']} · {x['u']}{c}\n  «{x['t']}»")
        await update.message.reply_text("\n".join(lines)[:3900], parse_mode="Markdown")
        return

    # ===== Владельцу: журналы (расход ИИ и накопление) =====
    if is_owner(update) and text.strip().lower() in ("журнал ии", "расход", "статистика ии", "ии журнал", "журнал"):
        j = _journal_load(); u = j["usage"]; t = u["totals"]
        lines = ["🧠 *Журнал ИИ (расход твоего ключа)*",
                 f"Всего вызовов: {t.get('calls',0)} · 🆕 свежих(потрачено): {t.get('fresh',0)} · ♻️ из базы(бесплатно): {t.get('cached',0)}"]
        bu = t.get("by_user", {})
        if bu:
            lines.append("\n👤 По людям:")
            for uid, info in sorted(bu.items(), key=lambda x: -x[1].get("calls", 0))[:10]:
                lines.append(f"• {info.get('name', uid)}: {info.get('calls',0)} (свежих {info.get('fresh',0)})")
        rec = u.get("recent", [])[:10]
        if rec:
            lines.append("\n🕘 Последние (кто · когда · что):")
            for x in rec:
                loc = f" {x.get('src','')} №{x.get('num','')}" if x.get("src") else ""
                who = x.get('u', '?'); uid_ = x.get('id', '')
                who_full = who if (str(uid_) in ('', who)) else f"{who} [id {uid_}]"
                lines.append(f"  {'🆕' if x.get('fresh') else '♻️'} {x['d']} · {who_full} · {x.get('f','')}{loc}")
        lines.append("\n📄 Файл: github.com/" + GITHUB_REPO + "/blob/data/journal.json")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return
    if is_owner(update) and text.strip().lower() in ("накопление", "журнал накопления", "накопления", "переводы накоплено"):
        j = _journal_load(); tr = j["translations"]; tot = tr.get("totals", {})
        lines = ["📚 *Накопление переводов* (растут файлы по сборникам)"]
        if tot:
            lines.append("Всего по сборникам:")
            for s, c in sorted(tot.items(), key=lambda x: -x[1]):
                lines.append(f"• {s}: {c}")
        else:
            lines.append("пока пусто")
        rec = tr.get("recent", [])[:10]
        if rec:
            lines.append("\n➕ Последние добавленные:")
            for x in rec:
                lines.append(f"  {x['d']} {x['s']} №{x['n']}")
        lines.append("\n📁 Папка: github.com/" + GITHUB_REPO + "/tree/data/translations")
        lines.append("ℹ️ Удаляется ТОЛЬКО тобой. Копится только полезное (мусор/ошибки не пишем).")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # ===== Владельцу: ЧЁРНЫЙ СПИСОК (бан чата/пользователя по id) =====
    if is_owner(update):
        _tl = text.strip().lower()
        # ===== ПОЛНАЯ ИНСТРУКЦИЯ команд владельца (чтобы не запоминать): «команды» / «помощь» =====
        if _tl in ("команды", "помощь", "хелп", "/команды", "инструкция", "что умеешь"):
            await update.message.reply_text(
                "🛠 *Команды владельца* (пиши боту в личку):\n\n"
                "📥 *Заявки/замечания мне (Claude):*\n"
                "• `заявка <текст>` — записать заявку с номером (предупрежу, если точный дубль)\n"
                "• *фото с подписью* `заявка <текст>` — скрин-заявка (скрин уходит в рабочий журнал, с МСК-временем)\n"
                "• `заявки` — список (невыполненные первыми + от пользователей)\n"
                "• `заявка done <№>` — пометить выполненной\n\n"
                "🤖 *ИИ (внутренняя кухня, только тебе):*\n"
                "• `гпт <вопрос>` — спросить GPT/Gemini\n\n"
                "💬 *Связь с пользователем:*\n"
                "• `написать <ID> <текст>` — отправить юзеру сообщение от твоего имени (ID берёшь из журнала #ии)\n\n"
                "📣 *Канал и закреп:*\n"
                "• `анонс` — запостить текущее обновление в @muslimoonapp\n"
                "• `анонс <текст>` — свой текст в канал\n"
                "• `закреп` — сообщение с кнопкой приложения (закрепляется автоматически)\n"
                "• `закреп <текст>` — свой текст под кнопкой\n\n"
                "⚙️ *Управление:*\n"
                "• `ии вкл` / `ии выкл` — ИИ для пользователей вкл/выкл\n"
                "• `бот стоп` / `бот старт` — режим обслуживания\n\n"
                "ℹ️ Эту шпаргалку всегда можно открыть командой *команды*.",
                parse_mode="Markdown")
            return
        # ===== GPT (OpenAI) для особых задач: «гпт <вопрос>» / «gpt <вопрос>» =====
        if _tl == "гпт" or _tl == "gpt" or _tl.startswith("гпт ") or _tl.startswith("gpt ") or _tl.startswith("гпт\n") or _tl.startswith("gpt\n"):
            q = text.strip()[3:].strip()
            if not q:
                await update.message.reply_text("Напиши: гпт <вопрос>")
                return
            if not OPENAI_API_KEY and not GEMINI_API_KEY:
                await update.message.reply_text("⚠️ Нет ни OPENAI_API_KEY, ни GEMINI_API_KEY (валидного). Railway → Variables: имя без пробелов, и Redeploy.")
                return
            try: await update.message.reply_text("🤖 Думаю…")
            except Exception: pass
            ans, model = ask_special(q)
            await update.message.reply_text(((ans or "Не удалось получить ответ.") + (f"\n\n— {model}" if model else ""))[:4000])
            # СТРОГИЙ лог расхода GPT в внутренний журнал (Gemini бесплатный — не логируем как расход)
            if model and str(model).startswith("GPT") and _LAST_GPT_SPEND:
                s = _LAST_GPT_SPEND
                try:
                    await context.bot.send_message(LOG_CHAT_ID, f"💸 GPT-расход ({s.get('t')}): {s.get('model')} · in {s.get('in')}/out {s.get('out')} ток. ≈ ${s.get('cost', 0):.4f} · всего GPT ≈ ${s.get('total', 0):.4f} ({s.get('calls', '?')} вызовов). Баланс — platform.openai.com/usage")
                except Exception:
                    pass
            return
        # === НАПИСАТЬ ПОЛЬЗОВАТЕЛЮ по ID (релей через бота — для юзеров без @username, по их ID из журнала): «написать <ID> <текст>» ===
        if _tl.startswith("написать ") or _tl.startswith("ответить ") or _tl.startswith("напиши "):
            parts = text.strip().split(None, 2)   # [команда, ID, текст]
            if len(parts) >= 3 and parts[1].lstrip('-').isdigit():
                target_uid = int(parts[1]); body = parts[2]
                try:
                    await context.bot.send_message(target_uid, f"💬 Сообщение от разработчика Muslimoon:\n\n{body}")
                    await update.message.reply_text(f"✅ Отправлено пользователю {target_uid}.")
                except Exception as e:
                    await update.message.reply_text(f"⚠️ Не смог отправить {target_uid}: {e}\n(Юзер мог не запускать бота или заблокировал.)")
            else:
                await update.message.reply_text("Формат: написать <ID> <текст>\nНапр.: написать 6692711031 Ассаламу алейкум!\n(ID берётся из журнала #ии; бот отправит юзеру от твоего имени.)")
            return
        # ===== ЗАКРЕП: сообщение с кнопкой открытия приложения + автозакреп. «закреп <свой текст>» = свой текст =====
        if _tl == "закреп" or _tl == "закрепить" or _tl.startswith("закреп "):
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
            custom = text.strip()[7:].strip() if _tl.startswith("закреп ") else ""
            body = custom or ("📗 *Muslimoon* — Коран и хадисы 🌙\n🔎 Поиск по хадисам и аятам · 📚 чтение Мактабы (8589 книг) · 👤 передатчики · 📖 тафсир.\n\nЖми кнопку ниже 👇")
            is_private = update.effective_chat and update.effective_chat.type == "private"
            if is_private:
                kb = InlineKeyboardButton("📗 𝗠𝗨𝗦𝗟𝗜𝗠𝗢𝗢𝗡-𝗔𝗣𝗣", web_app=WebAppInfo(url=WEBAPP_URL))
            else:
                kb = InlineKeyboardButton("📗 𝗠𝗨𝗦𝗟𝗜𝗠𝗢𝗢𝗡-𝗔𝗣𝗣", url="https://t.me/muslimoontt_bot?startapp")
            msg = await update.message.reply_text(body, reply_markup=InlineKeyboardMarkup([[kb]]), parse_mode="Markdown")
            try:
                await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=msg.message_id, disable_notification=True)
                await update.message.reply_text("📌 Закреплено. Перешли это сообщение в свой канал/группу и закрепи там. ✍️ Свой текст: «закреп <твой текст>».")
            except Exception:
                await update.message.reply_text("Сообщение с кнопкой отправлено ✅. Авто-закрепить не вышло — закрепи вручную (зажми сообщение → «Закрепить»). ✍️ Свой текст: «закреп <твой текст>».")
            return
        # ===== ЗАЯВКИ владельца: список (невыполненные первыми + от пользователей) =====
        if _tl == "заявки" or _tl == "список заявок" or _tl == "мои заявки":
            j = _journal_load(); reqs = j.get("requests", []); fb = j.get("feedback", [])
            open_r = [r for r in reqs if not r.get("done")]; done_r = [r for r in reqs if r.get("done")]
            lines = [f"📋 *Заявки владельца* — открытых {len(open_r)} · выполнено {len(done_r)}\n"]
            if open_r:
                lines.append("🔴 *Не сделано:*")
                for r in open_r[:30]:
                    lines.append(f"№{r['id']} ({r['d']}){' 📷' if r.get('img') else ''}: {(r.get('t') or '')[:200]}")
            else:
                lines.append("✅ Открытых заявок нет.")
            if fb:
                lines.append(f"\n📨 *От пользователей* (последние, всего {len(fb)}):")
                for x in fb[:8]:
                    lines.append(f"№{x.get('id','?')} {x.get('u','')}: {(x.get('t') or '')[:140]}")
            lines.append("\nℹ️ Добавить: «заявка <текст>». Закрыть: «заявка done <№>».")
            await update.message.reply_text("\n".join(lines)[:4000], parse_mode="Markdown")
            return
        # ===== Закрыть заявку: «заявка done <№>» / «заявка готово <№>» =====
        if _tl.startswith("заявка done ") or _tl.startswith("заявка готово "):
            try:
                rid = int("".join(ch for ch in _tl if ch.isdigit()))
            except Exception:
                rid = 0
            j = _journal_load(); hit = False
            for r in j.get("requests", []):
                if r.get("id") == rid:
                    r["done"] = True; hit = True; break
            if hit:
                _journal_save(f"заявка #{rid} done")
                await update.message.reply_text(f"✅ Заявка №{rid} помечена выполненной.")
            else:
                await update.message.reply_text(f"Не нашёл заявку №{rid}.")
            return
        # ===== Добавить заявку: «заявка <текст>» / «замечание <текст>» (+ подсказка о дубле) =====
        if _tl.startswith("заявка ") or _tl.startswith("замечание ") or _tl == "заявка" or _tl == "замечание":
            body = text.strip()[6:].strip() if _tl.startswith("заявк") or _tl == "заявка" else text.strip()[9:].strip()
            if not body:
                await update.message.reply_text("✍️ Напиши: *заявка <текст>* — запишу с номером. Скрин: пришли фото с подписью «заявка ...».", parse_mode="Markdown")
                return
            dup = req_dup(body)
            if dup:
                await update.message.reply_text(f"⚠️ Похоже, ты это уже присылал — *заявка №{dup}*. Не дублирую.\n(Если всё же другое — допиши подробнее и пришли ещё раз.)", parse_mode="Markdown")
                return
            rid = req_add(body)
            try: await context.bot.send_message(LOG_CHAT_ID, f"📥 Заявка владельца №{rid} ({_now_msk()}):\n{body[:1500]}")
            except Exception: pass
            await update.message.reply_text(f"📥 *Заявка №{rid}* записана ✅ ({_now_msk()})\nСписок — команда «заявки».", parse_mode="Markdown")
            return
        # ===== АНОНС в канал приложения вручную ===== «анонс» = текущий update_note.txt; «анонс <текст>» = свой
        if _tl == "анонс" or _tl.startswith("анонс ") or _tl.startswith("анонс\n"):
            custom = text.strip()[5:].strip()
            note = custom
            if not note:
                try:
                    rr = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/update_note.txt",
                                      headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}, timeout=8)
                    if rr.status_code == 200:
                        note = base64.b64decode(rr.json().get("content", "")).decode("utf-8").strip()
                except Exception:
                    note = ""
            if not note:
                await update.message.reply_text("Пусто. Напиши: анонс <текст обновления>")
                return
            body = note + "\n\n———\n📲 Приложение: https://t.me/muslimoontt_bot/app\n🤖 Бот: https://t.me/muslimoontt_bot"
            try:
                await context.bot.send_message(APP_CHANNEL_ID, body, disable_web_page_preview=True)
                j = _journal_load(); j["app_post"] = {"note": note, "d": datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
                _journal_save("анонс → канал приложения (вручную)")
                await update.message.reply_text("✅ Опубликовал в канал @muslimoonapp.")
            except Exception as e:
                await update.message.reply_text("❌ Не вышло: " + str(e)[:200])
            return
        if _tl in ("ошибки", "журнал ошибок", "errors"):
            errs = _data_get("errors.json", []) or []
            open_errs = [e for e in errs if not e.get('fixed')]
            if not errs:
                await update.message.reply_text("✅ Журнал ошибок пуст.")
            else:
                lines = ["🐞 Журнал ошибок — открытых: " + str(len(open_errs)) + " / всего: " + str(len(errs))]
                for e in sorted(errs, key=lambda x: (x.get('fixed', False), -x.get('seq', x.get('count', 1))))[:25]:
                    mark = "✅" if e.get('fixed') else "🔴"
                    lines.append(f"{mark} {e.get('eid','A-?')} [{e.get('ver','')}] {e.get('where','')}: {e.get('msg','')[:110]} (×{e.get('count',1)})")
                lines.append("\nРешить: «ошибка решена A-001» (по номеру) или «ошибка решена <часть текста>».")
                await update.message.reply_text("\n".join(lines)[:3900])
            return
        _mfix = re.match(r"^ошибка\s+(решена|исправлена)\s+(.+)$", _tl)
        if _mfix:
            frag = _mfix.group(2).strip()
            errs = _data_get("errors.json", []) or []; n = 0
            _fl = frag.lower()
            for e in errs:
                if _fl == str(e.get('eid', '')).lower() or frag in (e.get('msg', '') + ' ' + e.get('where', '')).lower():
                    e['fixed'] = True; n += 1
            _data_put("errors.json", errs, "errlog: помечено решённым")
            await update.message.reply_text(f"✅ Помечено решёнными: {n}.")
            return
        if _tl in ("баны", "чёрный список", "черный список", "бан список", "блок список"):
            cfg0 = load_access(); cur = [str(x) for x in cfg0.get("blacklist", [])]; notes0 = cfg0.get("ban_notes", {}) or {}
            lines = []
            for x in cur:
                nt = notes0.get(str(x), "")
                lines.append("• "+str(x)+(" — "+nt if nt else ""))
            await update.message.reply_text("⛔ Чёрный список ("+str(len(cur))+"):\n" + ("\n".join(lines) if lines else "пусто") + "\n\nКоманды: «бан <id> [причина]» (можно несколько id, или ОТВЕТЬ «бан» на уведомление) / «разбан <id>».")
            return
        # БАН/РАЗБАН: несколько id, бан по ответу на уведомление (id берём из него), причина-комментарий
        if re.match(r"^(бан|разбан)\b", _tl):
            act = "разбан" if _tl.startswith("разбан") else "бан"
            ids = re.findall(r"-?\d{3,}", text)
            reason = ""
            rep = update.message.reply_to_message
            if not ids and rep and (rep.text or rep.caption):
                rtxt = rep.text or rep.caption or ""
                ids = re.findall(r"-?\d{3,}", rtxt)
                reason = re.sub(r"\s+", " ", rtxt).strip()[:200]
            if not reason:
                rest = re.sub(r"^(бан|разбан)", "", text, flags=re.I)
                rest = re.sub(r"-?\d{3,}", "", rest).strip(" :—-,.\n\t")
                reason = rest[:200]
            ids = list(dict.fromkeys(ids))
            if not ids:
                await update.message.reply_text("Укажи id: «бан 123456» (можно несколько: «бан 111 222»), либо ОТВЕТЬ «бан» на уведомление с id.")
                return
            cfg = load_access(); bl = [str(x) for x in cfg.get("blacklist", [])]; notes = dict(cfg.get("ban_notes", {}) or {})
            done = []
            for tid in ids:
                tid = str(tid)
                if act == "бан":
                    if tid not in bl: bl.append(tid)
                    notes[tid] = reason or notes.get(tid, "") or "вручную"
                    done.append(tid)
                else:
                    bl = [x for x in bl if x != tid]; notes.pop(tid, None); done.append(tid)
            save_access({"blacklist": bl, "ban_notes": notes})
            if act == "бан":
                await update.message.reply_text("⛔ Забанено: " + ", ".join(done) + (("\n📝 " + reason) if reason else "") + "\nВсего в ЧС: " + str(len(bl)))
                try:
                    jrn = "⛔ ЧЁРНЫЙ СПИСОК +" + ", ".join(done) + (("\n📝 причина: " + reason) if reason else "") + "\nВсего в бане: " + str(len(bl))
                    if update.effective_chat and update.effective_chat.id != LOG_CHAT_ID:
                        await context.bot.send_message(LOG_CHAT_ID, jrn)
                except Exception: pass
            else:
                await update.message.reply_text("✅ Разбанено: " + ", ".join(done) + "\nВ ЧС осталось: " + str(len(bl)))
            return
        # ===== Режим групп =====
        if _tl in ("группы", "группа список", "список групп"):
            a = load_access(); mode = "ВСЕМ (любые группы)" if a.get("group_open", True) else "ТОЛЬКО разрешённые"
            wl = a.get("group_wl", [])
            await update.message.reply_text(
                "👥 Режим групп: *" + mode + "*\nРазрешённые ("+str(len(wl))+"): " + (", ".join(wl) if wl else "—") +
                "\n\nКоманды:\n• «группы только свои» — бот работает лишь в разрешённых\n• «группы всем» — в любых\n"
                "• «группа разреши <id>» / «группа запрети <id>»\n• «покинь <id>» — выйти из группы\n• «бан <id>» — полностью игнорировать",
                parse_mode="Markdown")
            return
        if _tl in ("группы только свои", "группы свои", "группы только разрешенные", "группы только разрешённые"):
            save_access({"group_open": False}); await update.message.reply_text("👥 Готово: бот работает ТОЛЬКО в разрешённых группах. Разреши нужные: «группа разреши <id>»."); return
        if _tl in ("группы всем", "группы все", "группы открыть"):
            save_access({"group_open": True}); await update.message.reply_text("👥 Готово: бот работает в ЛЮБЫХ группах (по доступу)."); return
        mg = re.match(r"^группа\s+(разреши|запрети)\s+(-?\d{3,})$", _tl)
        if mg:
            act, gid = mg.group(1), mg.group(2); a = load_access(); wl = [str(x) for x in a.get("group_wl", [])]
            if act == "разреши":
                if gid not in wl: wl.append(gid)
                save_access({"group_wl": wl}); await update.message.reply_text(f"✅ Группа {gid} разрешена.")
            else:
                wl = [x for x in wl if x != gid]; save_access({"group_wl": wl}); await update.message.reply_text(f"🚫 Группа {gid} убрана из разрешённых.")
            return
        ml = re.match(r"^покинь\s+(-?\d{3,})$", _tl)
        if ml:
            gid = int(ml.group(1))
            try:
                await context.bot.leave_chat(gid); await update.message.reply_text(f"➖ Вышел из чата {gid}.")
            except Exception as e:
                await update.message.reply_text(f"Не удалось выйти из {gid}: {e}")
            return

    user_id = update.effective_user.id if update.effective_user else 0
    chat_type = update.effective_chat.type
    chat_id = update.effective_chat.id

    # ЧЁРНЫЙ СПИСОК: забаненный чат/пользователь — полностью игнорируем (кроме владельца). Команды «бан/разбан».
    if user_id != OWNER_ID:
        try: load_access()   # подтянуть _AI_BAN (кэшируется)
        except Exception: pass
        if chat_id in _AI_BAN or user_id in _AI_BAN:
            return
        # Режим «только свои группы»: в неразрешённой группе бот полностью молчит
        if chat_type in ("group", "supergroup"):
            acc = _access_cache or {}
            if not acc.get("group_open", True) and str(chat_id) not in (acc.get("group_wl") or []):
                return

    # Проверка: ответ на сообщение бота
    is_reply_to_bot = False
    is_reply_to_channel = False
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        # ВАЖНО: «ответ боту» = ответ ТОЛЬКО на сообщение НАШЕГО бота (по id),
        # а не любого другого бота/канала в чате. Иначе бот влезал в чужие диалоги
        # (кто-то ответил другому боту/каналу «🙂» — наш бот считал это обращением и тратил ключ).
        try:
            if replied.from_user and context.bot and replied.from_user.id == context.bot.id:
                is_reply_to_bot = True
        except Exception:
            pass
        if replied.sender_chat:
            is_reply_to_channel = True

    # ============ G9: «ботяра» для белого списка (не владелец) ============
    if user_id != OWNER_ID and text and not _ai_loop_guard(update, text):
        _bq = parse_botyara(text)
        _triggered = (_bq is not None) or (is_reply_to_bot and not is_reply_to_channel)
        if _triggered and feature_allowed('bot', tg_user_dict(update)):
            clean = _bq if _bq else text.replace("ботяра", "").strip()
            if (not clean) and update.message.reply_to_message and update.message.reply_to_message.text:
                clean = update.message.reply_to_message.text
            if not clean:
                clean = "продолжи"
            # жёсткие лимиты: на пользователя И на чат (анти-спам/анти-burn ключа)
            if (not rate_ok('bot:' + str(user_id), limit=4, window=120)) or (not rate_ok('botchat:' + str(chat_id), limit=6, window=120)):
                return
            await update.message.reply_text("🤔 Думаю...")
            result = ask_ai_with_memory(clean)
            await send_long(update, result)
            await log_bot_ai(update, context)
            return

    # ============ G9: доступ к боту (Бухари 333, мухэймин, искать…) — по умолчанию ВСЕМ ============
    if user_id != OWNER_ID and not feature_allowed('botsearch', tg_user_dict(update)):
        if chat_type == "private":
            try:
                await update.message.reply_text("🔒 Бот пока доступен не всем. Обратись к владельцу за доступом.")
            except Exception:
                pass
        return  # в группах — тихо, чтобы не спамить

    # ============ ВЛАДЕЛЕЦ: РЕЕСТР ============
    if is_owner(update):
        has_media = update.message.audio or update.message.voice or update.message.video or update.message.photo or update.message.document
        is_forward = update.message.forward_origin is not None

        if text and parse_registry_command(text) == "add_media":
            if update.message.reply_to_message:
                replied = update.message.reply_to_message
                if replied.audio or replied.voice or replied.video or replied.photo or replied.document:
                    hint = replied.caption or ""
                    await update.message.reply_text("🔍 Анализирую...")
                    desc = ai_describe_media(hint)
                    pending_edits[chat_id] = {"action": "add_registry", "description": desc}
                    await update.message.reply_text(f"📝 {desc}\n\nСохранить в реестр? (да/нет)")
                    return
                else:
                    await update.message.reply_text("❌ Ответь на медиа.")
            else:
                await update.message.reply_text("❌ Ответь на медиа командой 'в реестр'.")
            return

        if chat_id in pending_edits and pending_edits[chat_id].get("action") == "add_registry":
            pending = pending_edits.pop(chat_id)
            if text.lower() in ["да", "ок", "ok", "yes", "сохранить"]:
                eid = add_to_registry({"type": "медиа", "description": pending["description"]})
                await update.message.reply_text(f"✅ #{eid}\n📝 {pending['description']}\n📌 ожидает")
            else:
                await update.message.reply_text("❌ Отмена.")
            return

        if chat_type == "private" and (is_forward or has_media):
            hint = text or ""
            await update.message.reply_text("🔍 Анализирую...")
            desc = ai_describe_media(hint)
            pending_edits[chat_id] = {"action": "add_registry", "description": desc}
            await update.message.reply_text(f"📝 {desc}\n\nСохранить в реестр? (да/нет)")
            return

        if text:
            reg_cmd = parse_registry_command(text)
            if reg_cmd and reg_cmd != "add_media":
                if reg_cmd == "all":
                    data = load_registry()
                    if not data: await update.message.reply_text("📋 Пусто."); return
                    msg = "📋 *Реестр:*\n\n"
                    for e in data[-20:]:
                        icon = "🟢" if e["status"] == "готово" else "🔴"
                        msg += f"#{e['id']} {icon} {e.get('description','')[:100]}\n"
                    await send_long(update, msg, "Markdown"); return
                if reg_cmd == "pending":
                    data = [e for e in load_registry() if e["status"] == "ожидает"]
                    if not data: await update.message.reply_text("📋 Нет ожидающих."); return
                    msg = "📋 *Ожидает:*\n\n" + "\n".join([f"#{e['id']} 🔴 {e.get('description','')[:100]}" for e in data])
                    await send_long(update, msg, "Markdown"); return
                if reg_cmd.startswith("done_"):
                    eid = int(reg_cmd.split("_")[1])
                    data = load_registry()
                    for e in data:
                        if e["id"] == eid:
                            pending_edits[chat_id] = {"action": "done_registry", "id": eid, "desc": e.get("description","")[:100]}
                            await update.message.reply_text(f"✅ Отметить #{eid} как готовое?\n\n{e.get('description','')[:100]}\n\nНапиши «да» или «нет».")
                            return
                    await update.message.reply_text("❌ Не найдено."); return
                if reg_cmd.startswith("delete_"):
                    eid = int(reg_cmd.split("_")[1])
                    data = load_registry()
                    for e in data:
                        if e["id"] == eid:
                            pending_edits[chat_id] = {"action": "delete_registry", "id": eid, "desc": e.get("description","")[:100]}
                            await update.message.reply_text(f"⚠️ Удалить #{eid}?\n\n{e.get('description','')[:100]}\n\nНапиши «да» или «нет».")
                            return
                    await update.message.reply_text("❌ Не найдено."); return
                if reg_cmd.startswith("result_"):
                    parts = reg_cmd.split("_", 2)
                    eid = int(parts[1])
                    link = parts[2] if len(parts) > 2 else ""
                    data = load_registry()
                    for e in data:
                        if e["id"] == eid:
                            e["result"] = link; e["status"] = "готово"
                            save_registry(data)
                            await update.message.reply_text(f"✅ #{eid} результат сохранён."); return
                    await update.message.reply_text("❌ Не найдено."); return
                results = search_registry(reg_cmd)
                if results:
                    msg = f"🔍 *«{reg_cmd}»:*\n\n" + "\n".join([f"#{e['id']} {'🟢' if e['status']=='готово' else '🔴'} {e['description'][:100]}" for e in results])
                    await send_long(update, msg, "Markdown")
                else:
                    await update.message.reply_text("❌ Не найдено в реестре.")
                return

    # ============ ВЛАДЕЛЕЦ: АУДИО → MP3 (конвертация / студийное улучшение / метаданные) ============
    # Ответь на аудио/войс в чате и напиши:
    #   «mp3»                         → пришлю mp3
    #   «mp3 имя "X" исполнитель "Y" описание "Z"» → mp3 с тегами
    #   «улучшить»                    → шумодав + выравнивание громкости (как Auphonic) → чистый mp3
    #   «улучшить имя "X" ...»         → улучшенный mp3 + теги
    if is_owner(update) and text and update.message.reply_to_message:
        _tl = text.lower().strip()
        _rep = update.message.reply_to_message
        _has_audio = bool(_rep.audio or _rep.voice or _rep.video or
                          (_rep.document and (_rep.document.mime_type or '').startswith('audio')))
        _want_mp3     = bool(re.match(r'^(бахни\s*)?(mp3|мп3|конверт\w*)\b', _tl))
        _want_enhance = bool(re.match(r'^(улучши\w*|почисти\w*|студий\w*|auphonic)\b', _tl))
        _has_meta     = bool(re.search(r'(имя|исполнител\w*|назван\w*|описани\w*|title|artist|performer)\s*[:=]?\s*["«»“‘\']', _tl))
        if _has_audio and (_want_mp3 or _want_enhance or _has_meta):
            await update.message.reply_text("✨ Улучшаю звук (шумодав + громкость)…" if _want_enhance else "🎧 Делаю mp3…")
            _fobj = _rep.audio or _rep.voice or _rep.video or _rep.document
            _t_meta, _a_meta, _c_meta = parse_audio_meta(text)
            # свободный заголовок после команды без кавычек: «mp3 Лекция о посте»
            if not _t_meta:
                _rest = re.sub(r'^\s*(бахни\s*)?(mp3|мп3|улучши\w*|почисти\w*|конверт\w*|студий\w*|auphonic)\b[\s:.\-—]*', '', text, flags=re.IGNORECASE).strip()
                if _rest and not re.search(r'["«»“‘\']|исполнител|описани|artist|performer|comment', _rest, re.IGNORECASE):
                    _t_meta = _rest[:150]
            _title  = _t_meta or (getattr(_rep.audio, 'title', None) if _rep.audio else None) or (datetime.utcnow()+timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
            _artist = _a_meta or (getattr(_rep.audio, 'performer', None) if _rep.audio else None) \
                      or (_rep.sender_chat.title if _rep.sender_chat else (_rep.from_user.full_name if _rep.from_user else "Muslimoon"))
            _comment = _c_meta or ""
            try:
                _f = await _fobj.get_file()
                _src = f"/tmp/{_f.file_id}.src"
                _out = f"/tmp/{_f.file_id}.mp3"
                await _f.download_to_drive(_src)
                _ok = enhance_audio(_src, _out, artist=_artist, title=_title, comment=_comment, enhance=_want_enhance)
                if _ok:
                    _cap = "✨ Звук улучшен (шумоподавление + громкость −16 LUFS)" if _want_enhance else "🎵 MP3"
                    if _t_meta or _a_meta or _c_meta:
                        _cap += f"\n🏷 {_title} — {_artist}" + (f"\n📝 {_comment}" if _comment else "")
                    await update.message.reply_audio(audio=open(_out, "rb"), title=_title, performer=_artist, caption=_cap)
                else:
                    await update.message.reply_text("❌ Не удалось обработать аудио. Нужен ffmpeg в деплое — после Redeploy (nixpacks.toml) заработает.")
                for _p in (_src, _out):
                    try: os.remove(_p)
                    except Exception: pass
            except Exception as e:
                await update.message.reply_text("❌ Ошибка обработки аудио: " + str(e)[:200])
            return

    # ============ ВЛАДЕЛЕЦ: ПАМЯТЬ ============
    if is_owner(update) and text:
        t_lower = text.lower().strip()

        # Обработка подтверждений
        if chat_id in pending_edits:
            pending = pending_edits.get(chat_id)
            if pending.get("action") == "clear_memory":
                if t_lower == "точно ботяра":
                    pending_edits.pop(chat_id); save_memory([])
                    await update.message.reply_text("🧠 Память полностью очищена.")
                else:
                    pending_edits.pop(chat_id)
                    await update.message.reply_text("❌ Удаление отменено.")
                return
            if pending.get("action") == "delete_memory":
                if t_lower in ["да", "ок", "ok", "yes", "удалить"]:
                    pending_edits.pop(chat_id)
                    memory = load_memory()
                    idx = pending["index"]
                    if 0 <= idx < len(memory):
                        removed = memory.pop(idx); save_memory(memory)
                        await update.message.reply_text(f"🗑 Удалено:\n{removed.get('text','')}")
                else:
                    pending_edits.pop(chat_id)
                    await update.message.reply_text("❌ Удаление отменено.")
                return
            if pending.get("action") == "delete_memory_word":
                if t_lower in ["да", "ок", "ok", "yes", "удалить"]:
                    word = pending["word"]; pending_edits.pop(chat_id)
                    memory = load_memory()
                    before = len(memory)
                    memory = [m for m in memory if word.lower() not in m.get("text", "").lower()]
                    save_memory(memory)
                    await update.message.reply_text(f"🗑 Удалено {before - len(memory)} записей с «{word}».")
                else:
                    pending_edits.pop(chat_id)
                    await update.message.reply_text("❌ Удаление отменено.")
                return
            if pending.get("action") == "done_registry":
                if t_lower in ["да", "ок", "ok", "yes"]:
                    pending_edits.pop(chat_id); mark_done(pending["id"])
                    await update.message.reply_text(f"✅ #{pending['id']} готово.")
                else:
                    pending_edits.pop(chat_id)
                    await update.message.reply_text("❌ Отмена.")
                return
            if pending.get("action") == "delete_registry":
                if t_lower in ["да", "ок", "ok", "yes", "удалить"]:
                    pending_edits.pop(chat_id); delete_entry(pending["id"])
                    await update.message.reply_text(f"🗑 #{pending['id']} удалено.")
                else:
                    pending_edits.pop(chat_id)
                    await update.message.reply_text("❌ Отмена.")
                return
            if "new_text" in pending:
                if t_lower in ["да", "сохранить", "ок", "ok", "yes"]:
                    pending_edits.pop(chat_id)
                    memory = load_memory()
                    idx = pending["index"]
                    if 0 <= idx < len(memory):
                        memory[idx]["text"] = pending["new_text"]; memory[idx]["date"] = today()
                        save_memory(memory)
                        await update.message.reply_text(f"✅ Запись #{idx+1} обновлена.")
                elif t_lower in ["нет", "не надо", "отмена", "no"]:
                    pending_edits.pop(chat_id)
                    await update.message.reply_text("❌ Правка отменена.")
                else:
                    await update.message.reply_text("🔄 Переделываю...")
                    new_text = format_memory_item(f"{pending['original']} — {text}")
                    pending_edits[chat_id]["new_text"] = new_text
                    await update.message.reply_text(f"📝 Новый вариант:\n\n{new_text}\n\nСохранить? (да/нет)")
                return

        # Запомнить
        if t_lower.startswith("запомни:") or t_lower.startswith("запомни "):
            fact = text.split(" ", 1)[1].strip() if " " in text else ""
            if fact:
                await update.message.reply_text("🧠 Структурирую...")
                formatted = format_memory_item(fact)
                memory = load_memory()
                memory.append({"date": today(), "text": formatted})
                save_memory(memory)
                new_id = len(memory)
                await update.message.reply_text(f"✅ Запись #{new_id} [{today()}]\n📝 {formatted}\n\n✏️ Исправить: исправь память {new_id}: текст")
            return

        # Очистить память (с подтверждением)
        botyara_q = parse_botyara(text)
        if botyara_q is not None:
            if botyara_q in ["очисти свою память", "очисти память", "забудь всё", "сотри память", "стереть память"]:
                pending_edits[chat_id] = {"action": "clear_memory"}
                await update.message.reply_text("⚠️ Ты хочешь удалить ВСЮ память!\nЭто нельзя отменить.\n\nЕсли уверен — напиши: **точно ботяра**")
                return

        # Просмотр памяти
        if t_lower == "память":
            memory = load_memory()
            if not memory:
                await update.message.reply_text("🧠 Память пуста.")
            else:
                msg = "🧠 *Что я знаю:*\n\n"
                for i, m in enumerate(memory):
                    msg += f"*{i+1}.* [{m.get('date','—')}] {m.get('text','')}\n\n"
                await send_long(update, msg, "Markdown")
            return

        # Удалить запись памяти
        if t_lower.startswith("удали память "):
            val = text[13:].strip()
            memory = load_memory()
            if val.isdigit():
                idx = int(val) - 1
                if 0 <= idx < len(memory):
                    pending_edits[chat_id] = {"action": "delete_memory", "index": idx, "text": memory[idx].get("text", "")}
                    await update.message.reply_text(f"⚠️ Удалить запись #{idx+1}?\n\n{memory[idx].get('text','')}\n\nНапиши «да» или «нет».")
                else:
                    await update.message.reply_text("❌ Такого номера нет.")
            else:
                found = [m for m in memory if val.lower() in m.get("text", "").lower()]
                if found:
                    pending_edits[chat_id] = {"action": "delete_memory_word", "word": val, "count": len(found)}
                    msg = f"⚠️ Удалить {len(found)} записей с «{val}»?\n\n"
                    for f in found[:5]: msg += f"• {f.get('text','')[:100]}\n"
                    if len(found) > 5: msg += f"...и ещё {len(found)-5}\n"
                    msg += "\nНапиши «да» или «нет»."
                    await update.message.reply_text(msg)
                else:
                    await update.message.reply_text(f"❌ Не найдено записей с «{val}».")
            return

        # Исправить память
        if t_lower.startswith("исправь память "):
            rest = text[15:].strip()
            parts = rest.split(":", 1)
            if len(parts) == 2 and parts[0].strip().isdigit():
                idx = int(parts[0].strip()) - 1
                instruction = parts[1].strip()
                memory = load_memory()
                if 0 <= idx < len(memory):
                    original = memory[idx].get("text", "")
                    await update.message.reply_text("🔄 Переделываю...")
                    new_text = format_memory_item(f"{original} — {instruction}")
                    pending_edits[chat_id] = {"index": idx, "original": original, "new_text": new_text}
                    await update.message.reply_text(f"📝 Было:\n{original}\n\n✏️ Стало:\n{new_text}\n\nСохранить? (да/нет)")
                else:
                    await update.message.reply_text("❌ Такого номера нет.")
            else:
                await update.message.reply_text("❌ Формат: исправь память 2: сделай короче")
            return

        # Быстрая очистка памяти
        if t_lower == "очистить память":
            save_memory([])
            await update.message.reply_text("🧠 Память очищена.")
            return

    # ============ AI ДЛЯ ВЛАДЕЛЬЦА И ЕГО КАНАЛА ============
    if user_id == OWNER_ID or (update.message.sender_chat and update.message.sender_chat.id == OWNER_CHANNEL_ID):
        # AI в личке на любое сообщение
        if chat_type == "private":
            # Проверяем не команда ли это
            is_command = False
            if parse_hadith_query(text)[0]: is_command = True
            if parse_browse(text)[0]: is_command = True
            if parse_source_query(text)[0] in SOURCE_ONLY_CODES: is_command = True
            if parse_quran_query(text)[0]: is_command = True
            if parse_search_query(text): is_command = True
            if parse_sunnah(text): is_command = True
            if parse_smart_sunnah(text): is_command = True
            if parse_transmitter(text): is_command = True
            if parse_translate(text): is_command = True
            if parse_tafsir_query(text)[0]: is_command = True
            if parse_registry_command(text): is_command = True
            if text.lower() in ["память", "помощь", "справка", "команды"]: is_command = True
            if text.lower().startswith(("запомни", "удали память", "исправь память", "очистить память", "бахни mp3")): is_command = True
            if text.lower().startswith("корень "): is_command = True
            if parse_botyara(text) is not None: is_command = True

            if not is_command:
                await update.message.reply_text("🤔 Думаю...")
                result = ask_ai_with_memory(text)
                await send_long(update, result)
                await log_bot_ai(update, context)
                return

        # В чате/канале: отвечаем ТОЛЬКО если есть "ботяра" или ответ боту
        elif chat_type != "private" and not _ai_loop_guard(update, text):
            if "ботяра" in text.lower() or (is_reply_to_bot and not is_reply_to_channel):
                if not rate_ok('botchat:' + str(chat_id), limit=6, window=120):
                    return
                clean = text.replace("ботяра", "").strip()
                if update.message.reply_to_message and update.message.reply_to_message.text:
                    quoted = update.message.reply_to_message.text
                    clean = f"{clean}\n\nСообщение на которое я отвечаю:\n{quoted}" if clean else f"Прокомментируй это сообщение:\n{quoted}"
                if not clean:
                    clean = "продолжи"
                await update.message.reply_text("🤔 Думаю...")
                result = ask_ai_with_memory(clean)
                await send_long(update, result)
                await log_bot_ai(update, context)
                return

        # AI на "ботяра" в группах
        if (parse_botyara(text) is not None or is_reply_to_bot) and not _ai_loop_guard(update, text):
            if not rate_ok('botchat:' + str(chat_id), limit=6, window=120):
                return
            clean = text
            botyara_q = parse_botyara(text)
            if botyara_q is not None:
                clean = botyara_q if botyara_q else ""
            if not clean:
                clean = "продолжи"
            await update.message.reply_text("🤔 Думаю...")
            result = ask_ai_with_memory(clean)
            await send_long(update, result)
            await log_bot_ai(update, context)
            return

        # Перевод
        tr = parse_translate(text)
        if tr == "REPLY":
            if update.message.reply_to_message and update.message.reply_to_message.text:
                await update.message.reply_text("🔄 Перевожу...")
                result = ask_ai(f"Переведи на русский:\n{update.message.reply_to_message.text}", "Ты — переводчик.")
                await send_long(update, result)
            return
        if tr and tr != "REPLY":
            await update.message.reply_text("🔄 Перевожу...")
            result = ask_ai(f"Переведи на русский:\n{tr}", "Ты — переводчик.")
            await send_long(update, result)
            return

        # Тафсир
        surah, ayah = parse_tafsir_query(text)
        if surah and ayah:
            await update.message.reply_text(f"📖 Ищу тафсир {surah}:{ayah}...")
            arabic_ayah, _ = get_quran_ayah(surah, ayah)
            prompt = f"Дай тафсир Ибн Касира на аят {surah}:{ayah}."
            if arabic_ayah: prompt += f"\n\nАят: {arabic_ayah}"
            result = ask_ai(prompt, "Ты — знаток тафсира Ибн Касира.", owner=is_owner(update))
            await send_long(update, result)
            return

    # ============ КОМАНДА: КОРЕНЬ СЛОВА ИЗ КОРАНА ============
    if text.lower().startswith("корень "):
        query = text[7:].strip()

        if not query:
            await update.message.reply_text(
                "❌ Напишите корень после команды.\n"
                "Пример: `корень علم` или `корень хукм`",
                parse_mode="Markdown"
            )
            return

        await update.message.reply_text(f"🔍 Ищу корень «{query}»...")

        # Определяем, что ввёл пользователь — арабский или русский
        is_arabic = bool(re.search(r'[؀-ۿ]', query))

        if is_arabic:
            arabic_root = query
        else:
            arabic_root = RU_TO_ROOT.get(query.lower().strip())
            if not arabic_root:
                await update.message.reply_text(
                    f"❌ Слово «{query}» не найдено в словаре.\n\n"
                    f"📖 *Примеры:* хукм, ильм, сабр, китаб, таухид, ризк, джихад\n"
                    f"🔤 Или напишите арабский корень: `корень حكم`",
                    parse_mode="Markdown"
                )
                return

        latin_key = find_root_transliteration(arabic_root)

        if latin_key:
            url = f"https://corpus.quran.com/qurandictionary.jsp?q={latin_key}"
            await update.message.reply_text(
                f"📖 Корень: {query} → {arabic_root} → {latin_key}\n\n"
                f"🔗 {url}",
                disable_web_page_preview=False
            )
        else:
            direct_url = f"https://corpus.quran.com/qurandictionary.jsp?q={arabic_root}"
            await update.message.reply_text(
                f"📖 *Корень:* {query} → {arabic_root}\n\n"
                f"🔗 [Попробовать открыть в Corpus Quran]({direct_url})\n\n"
                f"💡 Если страница не открылась — корень не найден в базе.",
                parse_mode="Markdown",
                disable_web_page_preview=False
            )
        return

    # ============ ПЕРЕДАТЧИК (راوي) — موسوعة رواة الحديث ============
    tr_name = parse_transmitter(text)
    if tr_name:
        query = tr_name
        if re.search(r"[а-яА-ЯёЁ]", tr_name):   # русское имя -> арабское
            await update.message.reply_text("🔤 Перевожу имя на арабский...")
            ar = ask_ai("Дай арабское написание имени этого передатчика хадисов. "
                        "Только арабское имя, без пояснений:\n" + tr_name,
                        "Ты знаток рижаль (передатчиков хадисов). Отвечай ТОЛЬКО арабским именем.",
                        owner=is_owner(update))
            ar = re.sub(r"\n*⚡ \*Модель:.*$", "", ar or "", flags=re.S)
            ar = re.sub(r"[^؀-ۿ\s]", " ", ar).strip()
            query = ar or tr_name
        await update.message.reply_text(f"🧑‍🏫 Ищу передатчиков «{query}»...")
        res = search_transmitters(query, 8)
        if not res:
            await update.message.reply_text("❌ Не найдено в موسوعة رواة الحديث. Попробуй другое написание.")
            return
        msg = f"🧑‍🏫 <b>Передатчики «{query}»</b> (موسوعة رواة الحديث):\n\n"
        for i, t in enumerate(res, 1):
            title = t["title"].replace("<", "").replace(">", "")
            msg += f'{i}. <a href="{t["url"]}">{title}</a>\n'
        msg += "\n👉 Нажми имя — откроется полная ترجمة: جرح وتعديل, что сказали учёные, источники."
        await send_long(update, msg, "HTML")
        return

    # ============ ПОИСК ПО SUNNAH.ONE (الدرر السنية): хукм + перевод + تخريج ============
    sun = parse_sunnah(text)
    smart = parse_smart_sunnah(text)
    if sun or smart:
        if smart:
            await update.message.reply_text(f"🧠 Подбираю ключевые слова для «{smart}»...")
            kw = ask_ai(
                "Из описания хадиса по смыслу выдай 4-7 КЛЮЧЕВЫХ АРАБСКИХ СЛОВ из его матна. "
                "Только слова через пробел, без огласовок, без перевода и пояснений.\nОписание: " + smart,
                "Ты знаток хадисов. Отвечай ТОЛЬКО арабскими словами через пробел.",
                owner=is_owner(update))
            kw = re.sub(r"\n*⚡ \*Модель:.*$", "", kw or "", flags=re.S)
            kw = re.sub(r"[^؀-ۿ\s]", " ", kw).strip()
            if not kw:
                await update.message.reply_text("❌ Не удалось подобрать ключевые слова.")
                return
            await update.message.reply_text(f"🔎 Ищу по словам: {kw}")
            query = kw
        else:
            await update.message.reply_text(f"🔎 Ищу: {sun}...")
            query = sun
        cnt, res = search_sunnah_one(query, limit=4)
        if not res:
            await update.message.reply_text("❌ Ничего не найдено (или источник недоступен).")
            return
        await update.message.reply_text(f"🔎 الدرر السنية — найдено: {cnt}, версий: {len(res)}")
        # ── ГЛАВНАЯ версия: полно, с переводом ──
        r0 = res[0]
        main = f"{hukm_emoji(r0['hukm'])} <b>الحكم:</b> {_esc_mark(r0['hukm'] or '—')}\n"
        main += f"📜 <b>{_esc_mark(r0['marked'])}</b>\n"
        if is_owner(update):
            ru = translate_matn(r0["text"], src=r0.get("takhreej", ""), owner=True)
            if ru:
                main += f"🌍 {_esc_mark(ru)}\n"
        if r0["takhreej"]:
            main += f"📋 {takhreej_html(r0['takhreej'])}\n"
        await send_long(update, main, "HTML")
        # ── ОСТАЛЬНЫЕ версии: компактно, в одном посте, без перевода ──
        if len(res) > 1:
            others = "📚 <b>Другие варианты (тот же смысл):</b>\n\n"
            for r in res[1:]:
                others += f"{hukm_emoji(r['hukm'])} <b>{_esc_mark(r['hukm'] or '—')}</b>\n"
                others += f"{_esc_mark(r['marked'])}\n"
                if r["takhreej"]:
                    others += f"📋 {takhreej_html(r['takhreej'])}\n"
                others += "\n"
            await send_long(update, others, "HTML")
        flush_trans()   # сохранить новые переводы в репо
        return

    # ============ ДЛЯ ВСЕХ: ПОИСК ХАДИСОВ ============
    sq = parse_search_query(text)
    if sq:
        await update.message.reply_text(f"🔍 Ищу: {sq}...")
        results = search_hadith(sq)
        if not results:
            await update.message.reply_text("❌ Ничего не найдено.")
            return
        msg = f"🔍 *«{sq}»*\n\n"
        for i, r in enumerate(results, 1):
            msg += f"*{i}.* {r['text'][:300]}\n"
            if r.get('rawi'): msg += f"👤 {r['rawi']}\n"
            if r.get('source'): msg += f"📚 {r['source']}\n"
            if r.get('grade'): msg += f"📊 {r['grade']}\n"
            msg += "\n"
        await send_long(update, msg, "Markdown")
        return

    # ============ ДЛЯ ВСЕХ: КОРАН ============
    surah, ayah = parse_quran_query(text)
    if surah and ayah:
        await update.message.reply_text("⏳ Ищу аят...")
        a, r = get_quran_ayah(surah, ayah)
        if not a and not r:
            await update.message.reply_text(f"❌ Аят {surah}:{ayah} не найден.")
            return
        msg = f"📖 Коран, {surah}:{ayah}\n\n"
        if a:
            msg += f"🔤 {a}\n\n"
        if r:
            msg += f"🌍 {r}\n"
        msg += f"\n📚 Коран, {surah}:{ayah}"
        await send_long(update, msg)
        return

    # ============ ПРОСМОТР БАЗЫ ПО КНИГАМ/ГЛАВАМ ============
    bmode, barg = parse_browse(text)
    if bmode == "books":
        await send_long(update, fmt_books())
        return
    if bmode == "book":
        await send_long(update, fmt_book_chapters(barg))
        return

    # ============ ДЛЯ ВСЕХ: ХАДИСЫ ============
    collection, number = parse_hadith_query(text)

    # ПЕРВОИСТОЧНИКИ без своего сборника (Таялиси, Хумайди, Ибн Аби Шейба, ...)
    # -> показываем сам текст риваята из аль-Мухаймина + где ещё встречается.
    if not collection:
        scode, snum = parse_source_query(text)
        if scode and scode in SOURCE_ONLY_CODES:
            places = find_in_murhid(scode, snum)
            nm = SOURCE_NAMES_RU.get(scode, scode)
            if not places:
                await update.message.reply_text(
                    f"❌ {nm} {snum} в аль-Мухаймине не найден.")
                return
            data = get_muhaymin(places[0]["m"])
            riw = data.get("riwayat", []) if data else []
            v = places[0]["v"] - 1
            msg = f"📖 *{nm} {snum}*\n"
            if 0 <= v < len(riw):
                r = riw[v]
                msg += f"📂 {places[0].get('chapter','')}\n\n"
                msg += f"{r.get('text','')}\n"
                if r.get("sources"):
                    msg += f"📎 {r['sources']}\n"
            msg += muhaymin_crossref_note(scode, snum)
            await send_long(update, msg)
            return

    # АЛЬ-МУХАЙМИН — поиск по нашему выверенному индексу
    if collection == "riwayat":
        await update.message.reply_text("🔍 Ищу хадис в аль-Мухаймине...")
        data = get_muhaymin(number)
        if data:
            riw = data.get("riwayat", [])
            # ── шапка хадиса (отдельным сообщением) ──
            head = f"📖 الموحد المهيمن — хадис №{number}\n"
            if data.get("book"):
                head += f"📕 {data['book']}\n"
            if data.get("chapter"):
                head += f"📂 {data['chapter']}\n"
            if data.get("note"):
                head += f"{data['note']}\n"
            head += f"📚 Риваятов (версий): {len(riw)}"
            await update.message.reply_text(head)
            # ── каждая версия — своим сообщением ──
            SEP = "━━━━━━━━━━━━━━"
            for i, r in enumerate(riw, 1):
                vmark = "✅" if r.get("verified") else "⏳"
                vf = (r.get("verified_from") or r.get("restored_from") or "").strip()
                ref = fmt_src_ref(r.get("short_ref", ""), vf)
                body = f"▫️ Риваят {i}/{len(riw)} {vmark}  📖 {ref}\n{SEP}\n{r.get('text','')}\n"
                ru = r.get("text_ru_ready")
                if not ru and is_owner(update):
                    ru = translate_matn(r.get("text", ""), src=vf, owner=True)
                if ru:
                    body += f"\n🌍 {ru}\n"
                await send_long(update, body)
            flush_trans()
        else:
            await update.message.reply_text(f"❌ Хадис №{number} в аль-Мухаймине не найден.")
        return

    if collection:
        if collection in ["random", "random_bukhari", "random_muslim", "random_quran"]:
            await update.message.reply_text("🎲 Ищу...")
            if collection == "random_quran":
                s, n, ar, ru = get_random_quran()
                if ar or ru:
                    msg = f"🎲 Коран, {s}:{n}\n\n"
                    if ar: msg += f"🔤 {ar}\n\n"
                    if ru: msg += f"🌍 {ru}\n"
                    await send_long(update, msg)
                else:
                    await update.message.reply_text("❌ Не удалось.")
                return
            else:
                c = None if collection == "random" else collection.replace("random_", "")
                c, n, ar, tr, lang, gr = get_random_hadith(c)
                if c:
                    similar = search_similar_hadith(ar)
                    msg = f"🎲 {NAMES.get(c, c)}, №{n}\n\n"
                    if ar: msg += f"🔤 {ar}\n\n"
                    if tr: msg += f"🌍 ({lang}): {tr}\n"
                    if gr: msg += f"\n📊 {gr}"
                    msg += f"\n\n📚 {NAMES.get(c, c)}, №{n}"
                    if similar: msg += f"\n\n📖 Также:\n• " + "\n• ".join(similar[:5])
                    await send_long(update, msg)
                else:
                    await update.message.reply_text("❌ Не удалось.")
                return

        if number:
            await update.message.reply_text("⏳ Ищу хадис...")
            if collection == "ahmad_local":
                ar, tr, lang, gr = get_ahmad_hadith(number)
            else:
                ar, tr, lang, gr = get_hadith(collection, number)
            if not ar and not tr:
                hint = ""
                if collection == "muslim":
                    hint = ("\nℹ️ У Муслима нумерация источника местами пустая/нестандартная "
                            "(مقدمة и т.п.). Надёжнее искать по тексту: «сунна <часть хадиса>».")
                await update.message.reply_text(
                    f"❌ {NAMES.get(collection, collection)} №{number} не найден (пусто в источнике).{hint}")
                return
            similar = search_similar_hadith(ar) if collection != "ahmad_local" else []
            msg = f"📖 {NAMES.get(collection, collection)}, №{number}\n\n"
            if ar:
                msg += f"🔤 {ar}\n\n"
            if tr:
                msg += f"🌍 ({lang}): {tr}\n"
            elif collection == "muslim" and ar:
                msg += "ℹ️ Арабский — по нумерации Абд аль-Баки (как в приложении и у учёных). Готовый русский перевод для этого номера ещё сверяется.\n"
            if gr:
                msg += f"\n📊 {gr}"
            msg += f"\n\n📚 {NAMES.get(collection, collection)}, №{number}"
            if similar:
                msg += f"\n\n📖 Также:\n• " + "\n• ".join(similar[:5])
            _src_code = {"ahmad_local": "ahmad"}.get(collection, collection)
            msg += muhaymin_crossref_note(_src_code, number)

            await send_long(update, msg)
            return

    # ============ ПОМОЩЬ ============
    if text.lower() in ["помощь", "справка", "команды", "хелп", "help", "/start"]:
        await update.message.reply_text(
            "📚 *Команды бота:*\n\n"
            "*Хадисы (8 сборников):*\nбухари 1 | муслим 1 | абу дауд 1\nтирмизи 1 | ибн маджа 1 | насаи 1 | муватта 1\nахмад 1\n\n"
            "*Аль-Мухаймин (الموحد المهيمن):*\nмухаймин 907 | муршид 907\n"
            "📚 книги — список 44 книг\n📕 книга 5 | книга الصيام — главы книги\n\n"
            "*Первоисточники → где в Мухаймине:*\nтиялиси 323 | хумайди 28 | ибн аби шейба 100\n(а для бухари/муслим/ахмад отметка добавляется к самому хадису)\n\n"
            "*Передатчик (راوي):*\nпередатчик الزهري | передатчик Абу Хурайра\n(список рави → جرح وتعديل на موسوعة رواة الحديث)\n\n"
            "*Случайные:*\nслучайный | случайный бухари | случайный муслим | случайный коран\n\n"
            "*Коран:*\nкоран 2:255\n\n"
            "*Поиск:*\nискать بدعة\n\n"
            "*Достоверность (الدرر السنية):*\nсунна من غشنا (по тексту)\nхадис о терпении (по смыслу, через ИИ)\n(матн + хукм صحيح/ضعيف + перевод + تخريج со ссылками)\n\n"
            "*Корень слова:*\nкорень علм | корень хукм\n\n"
            "*Для владельца:*\n"
            "⚙️ бот стоп / бот старт (обслуживание) · ии вкл / ии выкл / ии статус\n"
            "🤖 ботяра вопрос | ботяра очисти свою память\n"
            "🔄 переведи текст\n"
            "📖 тафсир 2:255\n"
            "🎧 Аудио (reply на аудио/войс): mp3 · улучшить\n"
            "   теги: mp3 имя \"X\" исполнитель \"Y\" описание \"Z\"\n\n"
            "*Память (владелец):*\nзапомни: факт | память | удали память 2\nисправь память 2: текст | очистить память\n\n"
            "*Реестр (владелец):*\nв реестр (reply) | реестр | ожидает\nсделано 1 | удали 1 | результат 1 ссылка",
            parse_mode="Markdown",
            reply_markup=MAIN_KB
        )

WEBAPP_URL = "https://germanyalfurqan-eng.github.io/hadith-bot/"

# ============ G9: БЕЗОПАСНОСТЬ + ГРАНУЛЯРНЫЙ ДОСТУП ============
# Хранилище правил доступа и кэшей — в ОТДЕЛЬНОЙ ветке `data`, чтобы запись
# не меняла `main` и Railway не передеплоивался (это и убирает ошибку Conflict).

_data_branch_ready = False
def _ensure_data_branch():
    """Гарантировать существование ветки data (создаём из main при первой записи)."""
    global _data_branch_ready
    if _data_branch_ready or not GITHUB_TOKEN:
        return _data_branch_ready
    h = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/git/ref/heads/data", headers=h, timeout=10)
        if r.status_code == 200:
            _data_branch_ready = True
            return True
        rm = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/git/ref/heads/main", headers=h, timeout=10)
        sha = rm.json().get("object", {}).get("sha", "") if rm.status_code == 200 else ""
        if not sha:
            return False
        rc = requests.post(f"https://api.github.com/repos/{GITHUB_REPO}/git/refs", headers=h,
                           json={"ref": "refs/heads/data", "sha": sha}, timeout=10)
        _data_branch_ready = rc.status_code in (200, 201) or "already exists" in (rc.text or "")
    except Exception:
        pass
    return _data_branch_ready

def _data_get(path, default=None):
    """Прочитать JSON из ветки data через contents API (без CDN-кэша)."""
    try:
        if GITHUB_TOKEN:
            api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}?ref=data"
            r = requests.get(api, headers={"Authorization": f"token {GITHUB_TOKEN}"}, timeout=8)
            if r.status_code == 200:
                return json.loads(base64.b64decode(r.json().get("content", "")).decode("utf-8"))
            return default
        r = requests.get(f"https://raw.githubusercontent.com/{GITHUB_REPO}/data/{path}", timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return default

def _data_put(path, obj, message):
    """Записать JSON в ветку data."""
    if not GITHUB_TOKEN or not _ensure_data_branch():
        return False
    try:
        content = json.dumps(obj, ensure_ascii=False, indent=1)
        b64 = base64.b64encode(content.encode("utf-8")).decode()
        api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
        h = {"Authorization": f"token {GITHUB_TOKEN}"}
        r = requests.get(api + "?ref=data", headers=h, timeout=8)
        sha = r.json().get("sha", "") if r.status_code == 200 else ""
        payload = {"message": message, "content": b64, "branch": "data"}
        if sha:
            payload["sha"] = sha
        rp = requests.put(api, headers=h, json=payload, timeout=12)
        return rp.status_code in (200, 201)
    except Exception:
        return False

def verify_init_data(init_data, max_age=86400):
    """Проверить Telegram WebApp initData (HMAC по TOKEN). Вернуть dict user или None."""
    if not init_data or not TOKEN:
        return None
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
        recv_hash = data.pop("hash", None)
        if not recv_hash:
            return None
        check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv_hash):
            return None
        if max_age:
            try:
                if time.time() - int(data.get("auth_date", "0")) > max_age:
                    return None
            except Exception:
                pass
        u = data.get("user")
        return json.loads(u) if u else None
    except Exception:
        return None

# ---- Правила доступа (хранятся в data/access.json) ----
ACCESS_FILE = "access.json"
ACCESS_FEATURES = ["app", "translate", "neuro", "bot", "botsearch"]   # app = первый рубильник (вход)
DEFAULT_ACCESS = {
    "all": {"public": False, "whitelist": []},             # public=главный рубильник «всё всем»; whitelist=полный доступ конкретным
    "app": {"public": False, "whitelist": []},             # 📱 вход в мини-апп
    "translate": {"public": False, "whitelist": []},       # 📱 перевод (DeepSeek)
    "neuro": {"public": False, "whitelist": []},           # 📱 нейро-подбор (DeepSeek)
    "bot": {"public": False, "whitelist": []},             # 🤖 ботяра (ИИ в боте)
    "botsearch": {"public": True, "whitelist": []},        # 🤖 поиск в боте (Бухари 333, мухэймин, искать…) — по умолчанию ВСЕМ
    "blacklist": [],                                        # ⛔ чёрный список chat_id/user_id — полностью игнорируем
    "ban_notes": {},                                        # ⛔ комментарии к банам {id: "причина"} — журнал ЧС
    "group_open": True,                                      # 👥 True=бот работает в любых группах; False=только в group_wl
    "group_wl": [],                                          # 👥 разрешённые группы (id) при group_open=False
}
_access_cache = None

def _merge_access(cfg, base=None):
    """Наложить cfg поверх base (по умолчанию — дефолт). Частичный cfg НЕ затирает
    отсутствующие секции; неизвестные ключи и мусор в whitelist отбрасываются."""
    out = json.loads(json.dumps(base if base is not None else DEFAULT_ACCESS))
    for k, dv in DEFAULT_ACCESS.items():
        if k not in out:
            out[k] = json.loads(json.dumps(dv))
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            if k in DEFAULT_ACCESS and isinstance(v, dict):
                if "public" in v and "public" in DEFAULT_ACCESS[k]:
                    out[k]["public"] = bool(v["public"])
                if isinstance(v.get("whitelist"), list):
                    out[k]["whitelist"] = [str(x).strip() for x in v["whitelist"] if str(x).strip()][:500]
    # чёрный список (плоский список id) — отдельной обработкой (не {public,whitelist})
    bl = cfg.get("blacklist") if (isinstance(cfg, dict) and isinstance(cfg.get("blacklist"), list)) else out.get("blacklist")
    out["blacklist"] = [str(x).strip() for x in (bl or []) if str(x).strip()][:2000]
    # комментарии к банам {id: причина}
    bn = cfg.get("ban_notes") if (isinstance(cfg, dict) and isinstance(cfg.get("ban_notes"), dict)) else out.get("ban_notes")
    out["ban_notes"] = {str(k).strip(): str(v)[:300] for k, v in (bn or {}).items() if str(k).strip()}
    # режим групп
    if isinstance(cfg, dict) and "group_open" in cfg:
        out["group_open"] = bool(cfg["group_open"])
    elif "group_open" not in out:
        out["group_open"] = True
    gw = cfg.get("group_wl") if (isinstance(cfg, dict) and isinstance(cfg.get("group_wl"), list)) else out.get("group_wl")
    out["group_wl"] = [str(x).strip() for x in (gw or []) if str(x).strip()][:2000]
    return out

def _sync_ban():
    """Обновить in-memory _AI_BAN из access-конфига (id чатов/юзеров)."""
    try:
        _AI_BAN.clear()
        for x in (_access_cache or {}).get("blacklist", []):
            s = str(x).strip()
            if s.lstrip("-").isdigit():
                _AI_BAN.add(int(s))
    except Exception:
        pass

def load_access():
    global _access_cache
    if _access_cache is None:
        _access_cache = _merge_access(_data_get(ACCESS_FILE, None))
        _sync_ban()
    return _access_cache

def save_access(cfg):
    global _access_cache
    _access_cache = _merge_access(cfg, base=load_access())   # мержим поверх текущего
    _sync_ban()
    _data_put(ACCESS_FILE, _access_cache, "G9 access update")
    return _access_cache

def _norm(x):
    s = str(x).strip().lower()
    m = re.match(r'^(?:id|ид|айди)[\s:\-]+(.+)$', s)   # «Id: 12345» / «ид - 12345» → 12345
    if m:
        s = m.group(1).strip()
    return s.lstrip("@").strip()

def _in_list(user, lst):
    if not user or not lst:
        return False
    uid = _norm(user.get("id"))
    un = _norm(user.get("username")) if user.get("username") else None
    for w in lst:
        w = _norm(w)
        if w and (w == uid or (un and w == un)):
            return True
    return False

def feature_allowed(feature, user):
    """owner | 🌐 all.public (всё всем) | полный белый список | feature.public | feature.whitelist."""
    if user and str(user.get("id")) == str(OWNER_ID):
        return True
    acc = load_access()
    if acc.get("all", {}).get("public"):              # главный рубильник: всё открыто каждому
        return True
    if _in_list(user, acc.get("all", {}).get("whitelist")):
        return True
    f = acc.get(feature, {})
    if f.get("public"):
        return True
    return _in_list(user, f.get("whitelist"))

def tg_user_dict(update):
    u = update.effective_user
    if not u:
        return None
    return {"id": u.id, "username": u.username or ""}

# ---- Rate-limit (в памяти, на пользователя+функцию) ----
_rl = collections.defaultdict(list)
# ---- ЧАСОВОЙ лимит ИИ (контроль расхода ключа): аноним << app-юзер < whitelist < владелец(∞) ----
AI_HOUR_ANON = 12      # анонимный (без Telegram-апп / ip) — намного меньше
AI_HOUR_USER = 40      # обычный пользователь Telegram-приложения
AI_HOUR_WL   = 100     # в белом списке (персональный лимит от разработчиков)
HELP_CHAT_LINK = "https://t.me/jamaat_ru"
_ai_limit_notif = {}   # uid -> время последнего уведомления владельцу (не спамить)
def rate_ok(bucket, limit=20, window=60):
    now = time.time()
    q = _rl[bucket]
    while q and now - q[0] > window:
        q.pop(0)
    if len(q) >= limit:
        return False
    q.append(now)
    return True
# ---- НАКОПЛЕНИЕ ПО СБОРНИКАМ + ЖУРНАЛЫ (накопление, расход ИИ) + КОНТРОЛЬ КАЧЕСТВА ----
# Файлы (ветка data): translations/<source>.json = {"<num>":{ar,ru}}; journal.json = {translations, usage}.
# Принципы: только ДОБАВЛЯЕМ (ничего не удаляем без владельца); копим только ПОЛЕЗНОЕ (не мусор).
_coll_cache = {}
_journal_cache = None
def _coll_path(source):
    return f"translations/{source}.json"
def _coll_load(source):
    if source not in _coll_cache:
        _coll_cache[source] = _data_get(_coll_path(source), {}) or {}
    return _coll_cache[source]
def _journal_load():
    global _journal_cache
    if _journal_cache is None:
        j = _data_get("journal.json", None) or {}
        j.setdefault("translations", {"totals": {}, "recent": []})
        j.setdefault("usage", {"totals": {"calls": 0, "fresh": 0, "cached": 0, "by_user": {}}, "recent": []})
        j.setdefault("feedback", [])
        j.setdefault("fb_seq", 0)
        j.setdefault("searches", {"total": 0, "top": {}})
        j.setdefault("app", {"opens": 0, "by_user": {}, "by_day": {}})
        _journal_cache = j
    return _journal_cache
_app_dirty = 0
def app_hit(user):
    """Статистика приложения: запуски, уникальные пользователи, по дням."""
    global _app_dirty
    j = _journal_load(); a = j["app"]
    a["opens"] = a.get("opens", 0) + 1
    uid = str((user or {}).get("id") or "")
    if uid:
        bu = a["by_user"]; bu[uid] = bu.get(uid, 0) + 1
    day = datetime.now().strftime("%d.%m.%Y")
    a["by_day"][day] = a["by_day"].get(day, 0) + 1
    if len(a["by_day"]) > 120:
        a["by_day"] = dict(sorted(a["by_day"].items())[-90:])
    _app_dirty += 1
    if _app_dirty >= 5:
        _journal_save("app stats"); _app_dirty = 0
    return a
_search_dirty = 0
def searchlog_add(q, tab, cnt):
    """Аналитика: что ищут чаще всего (агрегируем, пишем батчами)."""
    global _search_dirty
    key = (q or "").strip().lower()[:60]
    if not key:
        return
    j = _journal_load(); s = j["searches"]
    s["total"] = s.get("total", 0) + 1
    e = s["top"].setdefault(key, {"n": 0, "tab": tab, "cnt": 0})
    e["n"] += 1; e["tab"] = tab; e["cnt"] = cnt
    if len(s["top"]) > 800:
        s["top"] = dict(sorted(s["top"].items(), key=lambda x: -x[1]["n"])[:500])
    _search_dirty += 1
    if _search_dirty >= 8:
        _journal_save("searches"); _search_dirty = 0
def feedback_add(user, ctx, txt, has_img=False):
    """Отзыв/ошибка → нумерованный журнал (каждому свой № для поиска в журналах/Telegram)."""
    j = _journal_load()
    j["fb_seq"] = j.get("fb_seq", 0) + 1
    fid = j["fb_seq"]
    name = ("@" + user["username"]) if (user and user.get("username")) else str((user or {}).get("id") or "аноним")
    j["feedback"].insert(0, {"id": fid, "d": datetime.now().strftime("%d.%m.%Y %H:%M"), "u": name,
                             "uid": str((user or {}).get("id") or ""), "ctx": (ctx or "")[:200], "t": (txt or "")[:1000],
                             "img": bool(has_img), "done": False})
    j["feedback"] = j["feedback"][:500]
    _journal_save(f"отзыв #{fid} от {name}")
    return fid
def _now_msk():
    """Точное московское время (сервер Railway в UTC; МСК = UTC+3). Для всех заявок — по требованию владельца."""
    return (datetime.utcnow() + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M МСК")
def req_add(txt, img_flag=False, imgkey=""):
    """Заявка/замечание ВЛАДЕЛЬЦА → нумерованный журнал requests[] (отдельно от пользовательских feedback[])."""
    j = _journal_load()
    j["req_seq"] = j.get("req_seq", 0) + 1
    rid = j["req_seq"]
    j.setdefault("requests", []).insert(0, {"id": rid, "d": _now_msk(),
                                            "t": (txt or "")[:1500], "img": bool(img_flag), "imgkey": imgkey, "done": False})
    j["requests"] = j["requests"][:1000]
    _journal_save(f"заявка #{rid}")
    return rid
def req_dup(txt):
    """Если заявка ТОЧНО дублирует уже записанную — вернуть её номер (иначе None). Только при высокой схожести."""
    import difflib
    n = (txt or "").strip().lower()
    if len(n) < 6:
        return None
    j = _journal_load()
    for r in j.get("requests", []):
        o = (r.get("t") or "").strip().lower()
        if o and (o == n or difflib.SequenceMatcher(None, o, n).ratio() > 0.9):
            return r.get("id")
    return None
def _journal_save(msg):
    if _journal_cache is not None:
        _data_put("journal.json", _journal_cache, msg)
def _good_ru(ru):
    """Контроль качества: копим только осмысленный русский перевод, не ошибки/мусор."""
    if not ru or len(ru.strip()) < 5:
        return False
    low = ru.strip().lower()
    if low.startswith("❌") or "недоступ" in low or "api-ключ" in low or "не настроен" in low:
        return False
    return bool(re.search(r'[а-яё]', low))
def coll_add_translation(source, num, ar, ru):
    """Накопить ПОЛЕЗНЫЙ перевод в сборник + журнал. Вернуть {source,num,total,new} или None."""
    source = re.sub(r'[^a-z0-9_]+', '', (source or '').lower())
    if not source or num in (None, '') or not _good_ru(ru):
        return None
    d = _coll_load(source); key = str(num)
    if key in d and d[key].get("ru") == ru:
        return {"source": source, "num": key, "total": len(d), "new": False}
    new = key not in d
    prev_d = (d.get(key) or {}).get("d")   # сохраняем ДАТУ ПЕРВОГО перевода, не перетираем
    d[key] = {"ar": (ar or '')[:1500], "ru": ru, "d": prev_d or datetime.now().strftime("%d.%m.%Y")}
    if not _data_put(_coll_path(source), d, f"translations/{source}: +№{key} (всего {len(d)})"):
        return None
    if new:
        j = _journal_load()
        j["translations"]["totals"][source] = len(d)
        j["translations"]["recent"].insert(0, {"d": datetime.now().strftime("%d.%m.%Y %H:%M:%S"), "s": source, "n": key})
        j["translations"]["recent"] = j["translations"]["recent"][:200]
        _journal_save(f"журнал: +перевод {source} №{key}")
    return {"source": source, "num": key, "total": len(d), "new": new}
# ---- Накопление нейро-подбора: data/neuro.json = {"<kind>|<запрос>": [фразы]} (повтор НЕ тратит ключ) ----
_neuro_cache = None
def _neuro_load():
    global _neuro_cache
    if _neuro_cache is None:
        _neuro_cache = _data_get("neuro.json", {}) or {}
    return _neuro_cache
def neuro_get(key):
    return _neuro_load().get(key)
def neuro_put(key, phrases):
    c = _neuro_load(); c[key] = phrases
    _data_put("neuro.json", c, f"neuro: +{key[:40]} (всего {len(c)})")
    return len(c)
# ---- Накопление умного ИИ-поиска КНИГ Мактабы: data/booksearch.json = {"<рус.запрос>": {ar,author,note}} ----
_bsearch_cache = None
def _bsearch_load():
    global _bsearch_cache
    if _bsearch_cache is None:
        _bsearch_cache = _data_get("booksearch.json", {}) or {}
    return _bsearch_cache
def bsearch_get(key):
    return _bsearch_load().get(key)
def bsearch_put(key, val):
    c = _bsearch_load(); c[key] = val
    _data_put("booksearch.json", c, f"booksearch: +{key[:40]} (всего {len(c)})")
    return len(c)
# ---- Перевод названий книг (накопление): data/booknames.json = {"<ар.название>": {"ru":..,"voc":..}} ----
_bnames_cache = None
def _bnames_load():
    global _bnames_cache
    if _bnames_cache is None:
        _bnames_cache = _data_get("booknames.json", {}) or {}
    return _bnames_cache
def bnames_put(newmap):
    c = _bnames_load(); c.update(newmap)
    _data_put("booknames.json", c, f"booknames: +{len(newmap)} (всего {len(c)})")
    return len(c)
# ---- Описание книги + Википедия (накопление): data/bookinfo.json = {"<ар.назв>|<автор>": {...}} ----
_binfo_cache = None
def _binfo_load():
    global _binfo_cache
    if _binfo_cache is None:
        _binfo_cache = _data_get("bookinfo.json", {}) or {}
    return _binfo_cache
def binfo_get(key):
    return _binfo_load().get(key)
def binfo_put(key, val):
    c = _binfo_load(); c[key] = val
    _data_put("bookinfo.json", c, f"bookinfo: +{key[:40]} (всего {len(c)})")
    return len(c)
# ---- Накопление ИИ-справок о равиях: data/rijal_ai.json = {имя: текст} (повтор НЕ тратит ключ) ----
_rijal_cache = None
def _rijal_load():
    global _rijal_cache
    if _rijal_cache is None:
        _rijal_cache = _data_get("rijal_ai.json", {}) or {}
    return _rijal_cache
def rijal_ai_get(name):
    return _rijal_load().get((name or '').strip())
def rijal_ai_put(name, bio):
    name = (name or '').strip()
    if not name or not bio:
        return
    c = _rijal_load(); c[name] = bio
    _data_put("rijal_ai.json", c, f"rijal_ai: +{name[:30]} (всего {len(c)})")
# ---- Кэш огласовок (تشكيل) по сборникам: data/tashkeel/<source>.json = {num: огласованный текст} ----
_tk_cache = {}
def _tk_path(source):
    return f"tashkeel/{source}.json"
def _tk_load(source):
    if source not in _tk_cache:
        _tk_cache[source] = _data_get(_tk_path(source), {}) or {}
    return _tk_cache[source]
def tashkeel_add(source, num, vocalized):
    source = re.sub(r'[^a-z0-9_]+', '', (source or '').lower())
    if not source or num in (None, '') or not vocalized:
        return
    d = _tk_load(source); d[str(num)] = vocalized
    _data_put(_tk_path(source), d, f"tashkeel/{source}: +№{num} (всего {len(d)})")
# ---- Накопление تخريج (ВЗАИМОСВЯЗЬ хадисов): data/takhrij/<source>.json = {num:{sci,local,muh,d}} ----
# sci = {takhreej,hukm} (sunnah.one), local = {code:[№...]} (наши сборники), muh = [№... в аль-Мухаймин].
# Нашли раз → дальше отдаём мгновенно/бесплатно. Только ДОБАВЛЯЕМ (не удаляем).
_takh_cache = {}
def _takh_path(source):
    return f"takhrij/{source}.json"
def _takh_load(source):
    if source not in _takh_cache:
        _takh_cache[source] = _data_get(_takh_path(source), {}) or {}
    return _takh_cache[source]
def takhrij_get(source, num):
    source = re.sub(r'[^a-z0-9_]+', '', (source or '').lower())
    if not source or num in (None, ''):
        return None
    return (_takh_load(source) or {}).get(str(num))
def _clean_local(loc):
    out = {}
    if isinstance(loc, dict):
        for k, v in list(loc.items())[:40]:
            kk = re.sub(r'[^a-z0-9_]+', '', str(k).lower())[:40]
            if kk and isinstance(v, list):
                out[kk] = [str(x)[:12] for x in v[:12]]
    return out
def takhrij_put(source, num, sci, local, muh):
    source = re.sub(r'[^a-z0-9_]+', '', (source or '').lower())
    if not source or num in (None, ''):
        return None
    d = _takh_load(source); key = str(num); prev = d.get(key) or {}
    sci_c = {}
    if isinstance(sci, dict) and (sci.get("takhreej") or sci.get("hukm")):
        sci_c = {"takhreej": str(sci.get("takhreej") or "")[:800], "hukm": str(sci.get("hukm") or "")[:60]}
    local_c = _clean_local(local) or (prev.get("local") or {})
    muh_c = [str(x)[:12] for x in (muh or [])[:120] if x] or (prev.get("muh") or [])
    sci_c = sci_c or (prev.get("sci") or {})
    if not sci_c and not local_c and not muh_c:
        return None
    d[key] = {"sci": sci_c, "local": local_c, "muh": muh_c, "d": prev.get("d") or datetime.now().strftime("%d.%m.%Y")}
    if not _data_put(_takh_path(source), d, f"takhrij/{source}: +№{key} (всего {len(d)})"):
        return None
    return {"source": source, "num": key, "total": len(d)}

# ---- Arabus (арабско-русский словарь Баранова): прокси+кэш arabus.ru/search/<слово> → корень/значения ----
# Накопление в data/arabus.json = {слово:{count,entries:[{ar,gram,ru}],d}}. CORS у arabus закрыт → тянем сервером.
_arabus_cache = None
def _arabus_key(w):
    return re.sub(r'[ً-ْٰـ]', '', (w or '')).strip()[:60]   # без огласовок/تطويل
def _arabus_clean(x):
    x = re.sub(r'<[^>]+>', '', x or '')
    for a, b in (('&quot;', '"'), ('&amp;', '&'), ('&gt;', '>'), ('&lt;', '<'), ('&#39;', "'"), ('&nbsp;', ' ')):
        x = x.replace(a, b)
    return re.sub(r'\s+', ' ', x).strip()
def _arabus_variants(w):
    # словарь Баранова ищет по корню/основе → не нашли точное слово, пробуем убрать приставки/окончания/корень
    w = re.sub(r'[ً-ْٰـ]', '', (w or '')).strip()
    out = []; seen = set()
    def add(x):
        x = (x or '').strip()
        if 2 <= len(x) <= 24 and x not in seen:
            seen.add(x); out.append(x)
    if w:
        add(w)
    pres = ['وال', 'فال', 'بال', 'كال', 'لل', 'ال', 'و', 'ف', 'ب', 'ك', 'ل', 'أ', 'است', 'سي', 'ست', 'ي', 'ت', 'ن']
    bases = [w] + [w[len(p):] for p in pres if w.startswith(p) and len(w) - len(p) >= 2]
    sufs = ['تموها', 'نا', 'وا', 'تم', 'تن', 'هما', 'كما', 'تما', 'هم', 'هن', 'كم', 'كن', 'ها', 'تها', 'ته', 'ون', 'ين', 'ان', 'ات', 'ة', 'ه', 'ك', 'ت', 'ي']
    for b in bases:
        add(b)
        for s in sufs:
            if b.endswith(s) and len(b) - len(s) >= 2:
                add(b[:-len(s)])
    for b in list(seen):
        sk = re.sub(r'[اويىءآإأ]', '', b)
        if len(sk) >= 3:
            add(sk)
        if b[:1] in 'أإا' and len(b) >= 4:
            add(b[1:])
    # слабые глаголы (корень с و/ي в середине): из 3-буквенной основы подставить و/ا/ي
    for c in list(out):
        if len(c) == 3:
            for mid in ('و', 'ا', 'ي'):
                add(c[0] + mid + c[2])
        elif len(c) == 2:
            for mid in ('و', 'ا', 'ي'):
                add(c[0] + mid + c[1])
    return out[:16]

def _arabus_scrape(word):
    # вернуть (ok, entries): ok=True если ответ 200 (даже если статей 0); ошибка сети → ok=False
    try:
        rr = requests.get("https://arabus.ru/search/" + requests.utils.quote(word),
                          headers={"User-Agent": "Mozilla/5.0", "Referer": "https://arabus.ru/"}, timeout=18)
        if rr.status_code != 200:
            return False, []
        html = rr.text
    except Exception:
        return False, []
    entries = []
    for ch in html.split('class="word_in_list"')[1:]:
        ar = re.search(r'word_db">(.*?)</div>', ch, re.S)
        gram = re.search(r'other_db">(.*?)</div>', ch, re.S)
        mean = re.search(r'meaning_db">(.*?)</p>', ch, re.S)
        e = {"ar": _arabus_clean(ar.group(1)) if ar else "",
             "gram": _arabus_clean(gram.group(1)) if gram else "",
             "ru": _arabus_clean(mean.group(1)) if mean else ""}
        if e["ar"] or e["ru"]:
            entries.append(e)
        if len(entries) >= 30:
            break
    return True, entries

_ARABUS_FV = 3   # версия фолбэка: при росте — перепроверяем старые ПУСТЫЕ кэши
def arabus_fetch(word, root=""):
    global _arabus_cache
    key = _arabus_key(word)
    if not key:
        return {"word": "", "count": 0, "entries": []}
    if _arabus_cache is None:
        _arabus_cache = _data_get("arabus.json", {}) or {}
    # 1) есть подсказка-корень → отдаём ВСЮ СЕМЬЮ КОРНЯ (как в Arabus), кэш по корню
    rk = _arabus_key(root)
    if rk and 2 <= len(rk) <= 6:
        ckey = "r:" + rk
        c = _arabus_cache.get(ckey)
        if c and c.get("count"):
            return {**c, "word": key}
        for cand in [rk] + ([rk[0] + m + rk[2] for m in ('و', 'ا', 'ي')] if len(rk) == 3 else []):
            ok, ents = _arabus_scrape(cand)
            if ents:
                res = {"word": key, "matched": cand, "count": len(ents), "entries": ents,
                       "fv": _ARABUS_FV, "d": datetime.now().strftime("%d.%m.%Y")}
                _arabus_cache[ckey] = res
                _data_put("arabus.json", _arabus_cache, f"arabus: +r:{rk} ({len(ents)})")
                return {**res, "word": key}
    # 2) по самому слову (кэш по слову)
    cached = _arabus_cache.get(key)
    if cached and (cached.get("count") or cached.get("fv") == _ARABUS_FV):
        return cached            # есть статьи ИЛИ пусто, но проверено текущим фолбэком
    cands = []
    for c in _arabus_variants(key):
        if c not in cands:
            cands.append(c)
    matched = None; entries = []; any_ok = False
    for cand in cands[:18]:
        ok, ents = _arabus_scrape(cand)
        any_ok = any_ok or ok
        if ents:
            matched = cand; entries = ents; break
    if not any_ok:                       # сеть недоступна — не кэшируем (перепроверим позже)
        return {"word": key, "count": 0, "entries": []}
    res = {"word": key, "matched": matched or key, "count": len(entries), "entries": entries,
           "fv": _ARABUS_FV, "d": datetime.now().strftime("%d.%m.%Y")}
    _arabus_cache[key] = res
    _data_put("arabus.json", _arabus_cache, f"arabus: +{key}→{matched or '∅'} ({len(entries)})")
    return res
# ---- ИИ-перевод/проверка ОДНОГО арабского слова: точный перевод+корень; ИИ имеет приоритет над Arabus;
#      накопление в data/wordai.json = {ключ:{ru,root,gram,d,w}} + уведомление владельцу (проверь ИИ vs Arabus) ----
_wordai_cache = None
def _wordai_key(w):
    return re.sub(r'[ً-ْٰـ]', '', (w or '')).strip()[:60]
def wordai_get(key):
    global _wordai_cache
    if _wordai_cache is None:
        _wordai_cache = _data_get("wordai.json", {}) or {}
    return _wordai_cache.get(key)
def wordai_put(key, val):
    global _wordai_cache
    if _wordai_cache is None:
        _wordai_cache = _data_get("wordai.json", {}) or {}
    _wordai_cache[key] = val
    _data_put("wordai.json", _wordai_cache, f"wordai: +{key}")
    return len(_wordai_cache)

def was_translated(text):
    """Уже есть перевод этого текста в памяти? (свежий vs из базы — для журнала расхода)."""
    try:
        return _trans_key(text) in _load_trans()
    except Exception:
        return False
def usage_log(user, feat, fresh, length=0, src="", num=""):
    """Журнал расхода ИИ: кто/когда/функция/свежий(потрачен ключ) или из базы (бесплатно)."""
    j = _journal_load(); u = j["usage"]; t = u["totals"]
    t["calls"] = t.get("calls", 0) + 1
    t["fresh"] = t.get("fresh", 0) + (1 if fresh else 0)
    t["cached"] = t.get("cached", 0) + (0 if fresh else 1)
    uid = str((user or {}).get("id") or "аноним")
    name = ("@" + user["username"]) if (user and user.get("username")) else uid
    bu = t["by_user"].setdefault(uid, {"name": name, "calls": 0, "fresh": 0})
    bu["calls"] += 1; bu["fresh"] += (1 if fresh else 0); bu["name"] = name
    u["recent"].insert(0, {"d": datetime.now().strftime("%d.%m.%Y %H:%M:%S"), "u": name, "id": uid, "f": feat,
                           "fresh": bool(fresh), "len": length, "src": src, "num": str(num)})
    u["recent"] = u["recent"][:300]
    _journal_save(f"журнал: {feat} {name} ({'свежий' if fresh else 'из базы'})")

async def log_bot_ai(update, context, feat="ботяра"):
    """Расход ИИ из самого бота (ботяра/группы) → в journal.json + зеркало в LOG-канал.
    Раньше это НЕ логировалось → трата в группах была не видна (ЗАМЕЧАНИЯ #13)."""
    try:
        user = tg_user_dict(update)
        try:
            await asyncio.get_event_loop().run_in_executor(None, usage_log, user, feat, True)
        except Exception:
            pass
        uid = (user or {}).get("id")
        if user and user.get("username"):
            who = "@" + user["username"]
        elif uid:
            who = f"[{uid}](tg://user?id={uid})"
        else:
            who = "аноним"
        ch = update.effective_chat
        where = ""
        if ch and getattr(ch, "type", "") != "private":
            title = (getattr(ch, "title", "") or "чат").replace("[", "(").replace("]", ")")
            mid = getattr(update.message, "message_id", None)
            link = ""
            try:
                # для супергрупп (-100) канонический /c/<short>/<mid> всегда рабочий для участника;
                # ch.username часто = username привязанного КАНАЛА (ссылка била, как "jamaatru")
                if str(ch.id).startswith("-100"):
                    link = f"https://t.me/c/{str(ch.id)[4:]}/{mid}" if mid else (f"https://t.me/{ch.username}" if getattr(ch, "username", None) else "")
                elif getattr(ch, "username", None):
                    link = f"https://t.me/{ch.username}/{mid}" if mid else f"https://t.me/{ch.username}"
            except Exception:
                link = ""
            where = (f" · в [{title}]({link})" if link else f" · в «{title}»") + f" ({ch.type}, id={ch.id})"
        await context.bot.send_message(LOG_CHAT_ID,
            f"#ии #ботяра 🤖 {feat}: 👤 {who}{where} — 🆕 свежий (DeepSeek, ключ потрачен)\n⛔ забанить: `бан {(update.effective_user.id if update.effective_user else '')}`" + (f" · `бан {ch.id}`" if (ch and getattr(ch,'type','')!='private') else ""),
            parse_mode="Markdown", disable_web_page_preview=True)
    except Exception:
        pass
# ============ КОНЕЦ G9-БЛОКА ============

def wide_search(q, page=1):
    """M127 Шаг 1: широкий поиск по большому корпусу через sunnah.one (turath-движок).
    Возвращает text + hukm (достоверность) + takhreej (где передаётся, словами) + source/loc.
    Постранично: sunnah.one отдаёт 20 результатов на страницу, параметр page=N (M189-пагинация)."""
    try:
        page = max(1, int(page))
    except Exception:
        page = 1
    try:
        r = requests.get("https://search.sunnah.one/",
                         params={"action": "search", "ver": "2", "q": q, "page": str(page)},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 200:
            j = r.json()
            out = []
            for x in (j.get("data") or [])[:40]:
                out.append({
                    "text": x.get("text", ""),
                    "hukm": x.get("hukm", ""),
                    "takhreej": x.get("takhreej", ""),
                    "source": str(x.get("source", "")),
                    "loc": str(x.get("source_location", "")),
                })
            return {"count": j.get("count", 0), "data": out, "page": page}
    except Exception as e:
        return {"count": 0, "data": [], "error": str(e), "page": page}
    return {"count": 0, "data": [], "page": page}


# ===== ОБЩИЙ ПОИСК ПО ВСЕЙ МАКТАБЕ (turath) — основной поиск =====
# Движок: api.turath.io/search (по всем ~8589 книгам Шамили). book_id = id нашего каталога.
# Порядок по умолчанию: ① 40 первоисточников → ② избранное → ③ كتب السنة → ④ тафсир → ⑤ остальное.
MAKTABA_FIRST_RANK = {  # канонические издания первоисточников (по авторитетности)
    1681: 1,   # صحيح البخاري - ط السلطانية
    1727: 2,   # صحيح مسلم - ت عبد الباقي
    1726: 3,   # سنن أبي داود
    7895: 4,   # سنن الترمذي - ت بشار
    829:  5,   # سنن النسائي - ط المصرية
    1198: 6,   # سنن ابن ماجه - ت عبد الباقي
    1699: 7,   # موطأ مالك - ت عبد الباقي
    25794: 8,  # مسند أحمد - ط الرسالة
    1446: 9,   # صحيح ابن خزيمة
    1729: 10,  # صحيح ابن حبان (الإحسان)
    1424: 11,  # المستدرك للحاكم - ط الرسالة
}
MAKTABA_FAV_IDS = {148097, 47}  # Мукбиль «الجامع الصحيح مما ليس في الصحيحين», Аʿзами «الجامع الكامل» (Мухэймин — наш, не turath)
MAKTABA_TAFSIR_CATS = {"التفسير", "علوم القرآن وأصول التفسير"}
_maktaba_catmap = None
def _maktaba_catmap_load():
    """{book_id: категория} из живого каталога (GitHub Pages). Кэш в памяти."""
    global _maktaba_catmap
    if _maktaba_catmap is not None:
        return _maktaba_catmap
    m = {}
    for u in ("https://germanyalfurqan-eng.github.io/hadith-bot/catalog.json",
              "https://raw.githubusercontent.com/germanyalfurqan-eng/hadith-bot/main/docs/catalog.json"):
        try:
            r = requests.get(u, timeout=20)
            if r.status_code == 200:
                for it in r.json():
                    m[it.get("i")] = it.get("c", "")
                if m:
                    break
        except Exception:
            continue
    _maktaba_catmap = m
    return m

MAKTABA_FIRST_CSV = ",".join(str(b) for b in list(MAKTABA_FIRST_RANK.keys()) + list(MAKTABA_FAV_IDS))

def _turath_search(q, page=1, book_id=None):
    params = {"q": q, "page": str(page)}
    if book_id:
        params["book_id"] = book_id   # turath поддерживает список id через запятую → фильтр по конкретным книгам
    try:
        r = requests.get("https://api.turath.io/search", params=params,
                         headers={"User-Agent": "Mozilla/5.0", "Referer": "https://app.turath.io/"}, timeout=20)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"count": 0, "data": []}

def _maktaba_item(x, cm):
    bid = x.get("book_id"); meta = x.get("meta")
    if isinstance(meta, str):
        try: meta = json.loads(meta)
        except Exception: meta = {}
    meta = meta or {}
    return {
        "book_id": bid, "cat_id": x.get("cat_id"), "cat": cm.get(bid, ""),
        "book_name": meta.get("book_name", ""), "author": meta.get("author_name", ""),
        "page": meta.get("page"), "vol": meta.get("vol"), "page_id": meta.get("page_id"),
        "headings": meta.get("headings") or [],
        "snip": (x.get("snip") or x.get("text") or "")[:600],
    }

def maktaba_search(q, page=1):
    """ОСНОВНОЙ поиск. Стр.1: сначала адресный запрос по 40 первоисточникам+избранному (наверх),
    затем общий по всей Мактабе. Стр.>1: только общий (первоисточники уже показаны)."""
    try:
        page = max(1, int(page))
    except Exception:
        page = 1
    try:
        cm = _maktaba_catmap_load()
        general = _turath_search(q, page)
        items = [_maktaba_item(x, cm) for x in (general.get("data") or [])]
        def gtier(it):
            if it["cat"] == "كتب السنة": return (2, 0)
            if it["cat"] in MAKTABA_TAFSIR_CATS: return (3, 0)
            return (4, 0)
        items = [z[2] for z in sorted([(gtier(it), i, it) for i, it in enumerate(items)],
                                      key=lambda z: (z[0][0], z[0][1], z[1]))]
        first_n = 0
        if page == 1:
            fs = _turath_search(q, 1, MAKTABA_FIRST_CSV)
            fitems = [_maktaba_item(x, cm) for x in (fs.get("data") or [])]
            def frank(it):
                b = it["book_id"]
                if b in MAKTABA_FIRST_RANK: return (0, MAKTABA_FIRST_RANK[b])
                if b in MAKTABA_FAV_IDS: return (1, 0)
                return (2, 0)
            fitems.sort(key=frank)
            seen = set((it["book_id"], it.get("page_id")) for it in fitems)
            items = [it for it in items if (it["book_id"], it.get("page_id")) not in seen]
            items = fitems + items
            first_n = len(fitems)
        return {"count": general.get("count", 0), "data": items, "page": page, "first_n": first_n}
    except Exception as e:
        return {"count": 0, "data": [], "error": str(e), "page": page}


# ===== НЕЙРОМУХАДДИС: поиск передатчика по 150 трудам ильм-риджаля (джарх-ва-тадиль) =====
_rijal_ids = None
_rijal_critic = None
def _rijal_load():
    """Список book_id корпуса риджаля + {book_id: критик} из живого rijal_corpus.json. Кэш."""
    global _rijal_ids, _rijal_critic
    if _rijal_ids is not None:
        return _rijal_ids, _rijal_critic
    ids = []; crit = {}
    for u in ("https://germanyalfurqan-eng.github.io/hadith-bot/hadith/rijal_corpus.json",
              "https://raw.githubusercontent.com/germanyalfurqan-eng/hadith-bot/main/docs/hadith/rijal_corpus.json"):
        try:
            r = requests.get(u, timeout=20)
            if r.status_code == 200:
                j = r.json()
                for c in (j.get("critics") or []):
                    for b in (c.get("books") or []):
                        bid = b.get("id")
                        if bid:
                            ids.append(bid); crit[bid] = c.get("critic", "")
                if ids:
                    break
        except Exception:
            continue
    _rijal_ids = ids; _rijal_critic = crit
    return ids, crit

def rijal_search(name, page=1):
    """Ищет имя передатчика по всем трудам риджаля (turath &book_id=csv) → места джарх/тадиль."""
    try:
        page = max(1, int(page))
    except Exception:
        page = 1
    ids, crit = _rijal_load()
    if not ids:
        return {"count": 0, "data": [], "page": page, "books": 0}
    csv = ",".join(str(i) for i in ids)
    try:
        r = requests.get("https://api.turath.io/search", params={"q": name, "book_id": csv, "page": str(page)},
                         headers={"User-Agent": "Mozilla/5.0", "Referer": "https://app.turath.io/"}, timeout=30)
        if r.status_code != 200:
            return {"count": 0, "data": [], "page": page, "books": len(ids)}
        j = r.json(); out = []
        for x in (j.get("data") or []):
            bid = x.get("book_id"); meta = x.get("meta")
            if isinstance(meta, str):
                try: meta = json.loads(meta)
                except Exception: meta = {}
            meta = meta or {}
            out.append({
                "book_id": bid, "critic": crit.get(bid, ""),
                "book_name": meta.get("book_name", ""), "author": meta.get("author_name", ""),
                "page": meta.get("page"), "vol": meta.get("vol"), "page_id": meta.get("page_id"),
                "snip": (x.get("snip") or x.get("text") or "")[:700],
            })
        return {"count": j.get("count", 0), "data": out, "page": page, "books": len(ids)}
    except Exception as e:
        return {"count": 0, "data": [], "error": str(e), "page": page, "books": len(ids)}

def turath_page(book_id, pg):
    """M216: страница книги Мактабы/turath по book_id+pg → {text, meta, pg}. Прокси (CORS у turath закрыт)."""
    try:
        bid = re.sub(r'[^0-9]', '', str(book_id or ''))[:8]
        p = re.sub(r'[^0-9]', '', str(pg or '1'))[:6] or '1'
        if not bid:
            return {}
        r = requests.get('https://api.turath.io/page', params={'book_id': bid, 'pg': p},
                         headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://app.turath.io/'}, timeout=15)
        if r.status_code == 200:
            j = r.json(); meta = j.get('meta')
            if isinstance(meta, str):
                try: meta = json.loads(meta)
                except Exception: meta = {}
            return {'text': j.get('text', ''), 'meta': meta or {}, 'pg': int(p)}
    except Exception as e:
        return {'err': str(e)}
    return {}

# M201: ИИ-проверка цепочки передатчиков (иснада) — извлечь полный список имён. Кэш data/isnad_ai.json.
_isnadai_cache = None
def isnad_ai(text):
    global _isnadai_cache
    if _isnadai_cache is None:
        _isnadai_cache = _data_get("isnad_ai.json", {}) or {}
    key = _trans_key(text)
    if key in _isnadai_cache:
        return {"names": _isnadai_cache[key], "cached": True}
    sysm = ("Извлеки из арабского хадиса ТОЛЬКО цепочку передатчиков (иснад) — имена передатчиков по порядку, "
            "как в тексте, до начала матна. По ОДНОМУ имени на строку, арабскими буквами. "
            "НЕ включай слова حدثنا/أخبرنا/أنبأنا/نا/ثنا/عن/قال/سمعت. Только имена людей. Если иснада нет — ничего.")
    out = ask_deepseek((text or "")[:2000], sysm) or ""
    names = []
    for ln in out.splitlines():
        ln = re.sub(r'^[\d\.\-\)\s•]+', '', ln).strip()
        if re.search(r'[؀-ۿ]', ln) and 2 <= len(ln) <= 40:
            names.append(ln)
    names = names[:25]
    if names:
        _isnadai_cache[key] = names
        _data_put("isnad_ai.json", _isnadai_cache, f"isnad_ai: +{key} ({len(names)})")
    return {"names": names, "cached": False}

async def _api_serve(application=None):
    from aiohttp import web
    loop = asyncio.get_event_loop()
    async def _notify_usage(user, feat, fresh, src, num, saved, q=""):
        # зеркалим ВСЮ активность ИИ в рабочий канал-журнал (LOG_CHAT_ID) — и траты, и из базы.
        # M301 (по требованию владельца): кэш-вызовы НЕ глушим — показываем с тем же ПОДРОБНЫМ описанием
        # (что/где/запрос), чтобы видеть активность функции; разница только в метке 🆕 потрачено / ♻️ из базы.
        if not application:
            return
        uid = (user or {}).get("id")
        if user and user.get("username"):
            who = "@" + user["username"]
        elif uid:
            who = f"[{uid}](tg://user?id={uid})"   # кликабельно: перейти к человеку по ID
        else:
            who = "аноним"
        tag = "🆕 свежий (DeepSeek, ключ потрачен)" if fresh else "♻️ из базы (ключ НЕ потрачен)"
        loc = f" {src} №{num}" if (src and num not in (None, '')) else ""
        if saved and saved.get("new"):
            _what = (": " + saved["what"]) if saved.get("what") else ""
            extra = f" · 📦 накоплено{_what} (в базе всего {saved.get('total', '?')})"
        else:
            extra = ""
        ftag = {"перевод": "#перевод", "нейро": "#нейро", "огласовки": "#огласовки"}.get(feat, "#" + re.sub(r"\s+", "", feat))
        _qs = (" · 🔎 «" + str(q)[:70] + "»") if q else ""   # M301: ЗА ЧТО потрачено (текст запроса)
        try:
            await application.bot.send_message(LOG_CHAT_ID, f"#ии {ftag} 🤖 {feat}: {who}{loc} — {tag}{extra}{_qs}", parse_mode="Markdown")
        except Exception:
            pass
    async def _notify(text):
        if application:
            try:
                await application.bot.send_message(LOG_CHAT_ID, text)
            except Exception:
                pass
    def _cors(resp):
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        resp.headers['Access-Control-Allow-Methods'] = 'POST,GET,OPTIONS'
        return resp
    def _deny(feature):
        return _cors(web.json_response(
            {'error': 'forbidden', 'feature': feature,
             'message': 'Эта функция тебе пока не открыта. Попроси доступ у владельца.'}, status=403))
    def _ratelimited():
        return _cors(web.json_response({'error': 'rate', 'message': 'Слишком часто, подожди немного.'}, status=429))
    async def _ai_quota(user, r):
        # часовой лимит ИИ; None=можно, иначе вернуть 429 с сообщением. Владелец — без лимита.
        if user and str(user.get('id')) == str(OWNER_ID):
            return None
        acc = load_access()
        wl = _in_list(user, acc.get('all', {}).get('whitelist')) or _in_list(user, acc.get('neuro', {}).get('whitelist'))
        known = bool(user and user.get('id'))
        lim = AI_HOUR_WL if wl else (AI_HOUR_USER if known else AI_HOUR_ANON)
        uid = _uid(user, r)
        if rate_ok('aihour:' + uid, lim, 3600):
            return None
        now = time.time()
        if now - _ai_limit_notif.get(uid, 0) > 1800:
            _ai_limit_notif[uid] = now
            who = ('@' + user['username']) if (user and user.get('username')) else uid
            tier = 'whitelist' if wl else ('app-юзер' if known else 'аноним')
            try: await _notify(f"⏰ #лимитии ЛИМИТ ИИ исчерпан: {who} ({tier} · {lim}/час). Для статистики/решения о персональном лимите. Разбан/лимит: правь whitelist «neuro».")
            except Exception: pass
        msg = ('⏳ Лимит ИИ-запросов на этот час исчерпан'
               + ((' — у анонимных запросов лимит НАМНОГО меньше, чем через Telegram-приложение. Откройте приложение для большего лимита.') if not known else '.')
               + '\nРазработчики могут выдать вам ПЕРСОНАЛЬНЫЙ лимит — напишите в чат: ' + HELP_CHAT_LINK)
        return _cors(web.json_response({'error': 'ai_quota', 'message': msg}, status=429))
    async def _body(r):
        try:
            raw = await r.read()
            return json.loads(raw.decode('utf-8'))   # форсируем UTF-8 (иначе aiohttp может decode как cp1251 → мохибейк кириллицы)
        except Exception:
            try:
                return await r.json()
            except Exception:
                return {}
    def _uid(user, r):
        return str(user.get('id')) if user else ('ip:' + (r.remote or '?'))

    async def health(r): return _cors(web.json_response({'ok': True}))
    async def opt(r): return _cors(web.Response(text=''))

    async def access(r):
        # POST {initData, action:'get'|'set', config?}
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        is_owner_u = bool(user and str(user.get('id')) == str(OWNER_ID))
        if d.get('action') == 'set':
            if not is_owner_u:
                return _deny('app')
            acc = await loop.run_in_executor(None, save_access, d.get('config') or {})
            return _cors(web.json_response({'ok': True, 'config': acc}))
        await loop.run_in_executor(None, load_access)   # прогреть кэш (1-й раз — сеть)
        allow = {f: feature_allowed(f, user) for f in ACCESS_FEATURES}
        resp = {'ok': True,
                'me': {'id': (user or {}).get('id'), 'username': (user or {}).get('username'),
                       'owner': is_owner_u, 'verified': bool(user)},
                'allow': allow}
        if is_owner_u:
            resp['config'] = load_access()
        return _cors(web.json_response(resp))

    async def neuro(r):
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('neuro:' + _uid(user, r), 10, 60):   # защита нейронки: жёстче (10/60), чтобы не жечь ключ
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        try:
            meaning = (d.get('meaning') or '').strip()[:500]
            if len(meaning) < 2:   # пустой/слишком короткий запрос — не зовём ИИ и НЕ кэшируем (фикс мусора «hadith|»)
                return _cors(web.json_response({'phrases': [], 'cached': False}))
            force = bool(d.get('force'))   # переподобрать заново (минуя кэш) — для исправления плохого подбора
            nkey = (d.get('kind') or 'hadith') + '|' + meaning.lower()
            kind = (d.get('kind') or 'hadith')
            # 1) ПАМЯТЬ: уже искали этот смысл? → отдаём готовое, БЕЗ траты ключа (самообучение)
            cached = None if force else await loop.run_in_executor(None, neuro_get, nkey)
            if cached:
                if isinstance(cached, list):   # старый формат (только фразы)
                    cached = {'phrases': cached, 'quran': [], 'note': '', 'fixed': ''}
                await loop.run_in_executor(None, usage_log, user, "нейро", False, len(meaning), "", "")
                await _notify_usage(user, "нейро", False, "", "", None, q=meaning)
                out = dict(cached); out['cached'] = True
                return _cors(web.json_response(out))
            # 2) УМНЫЙ ИИ-поиск: понять смысл (исправить опечатки), дать НОМЕР аята и/или характерную арабскую фразу
            sysm = ("Ты — умный поиск по Корану и хадисам. Запрос на русском (ВОЗМОЖНЫ ОПЕЧАТКИ) описывает аят/хадис "
                    "ПО СМЫСЛУ, либо это транскрипция арабского слова. Пойми, ЧТО хочет человек (мысленно исправь "
                    "опечатки), и ответь СТРОГО 5 строками (метки именно так):\n"
                    "АЯТЫ: <номера сура:аят через запятую, если запрос про конкретный аят/историю Корана; иначе ->\n"
                    "ХАДИСЫ: <если ЗНАЕШЬ конкретный хадис — источник и номер, напр. «Бухари 3437 ; Муслим 162»; иначе ->\n"
                    "ФРАЗЫ: <2-6 УНИКАЛЬНЫХ арабских фраз из самого текста (НЕ общие слова النبي/رسول الله!) — обязательно дай САМУЮ ЯРКУЮ/иконичную фразу-«изюминку» этого хадиса И фразы из РАЗНЫХ его версий; через ;>\n"
                    "ИСПРАВЛЕНО: <исправленный запрос, если были опечатки; иначе ->\n"
                    "ЗАМЕТКА: <очень кратко по-русски, что это>\n"
                    "Примеры:\n"
                    "«аят про зарезать корову» → АЯТЫ: 2:67,2:68,2:69,2:70,2:71 / ФРАЗЫ: اذبحوا بقرة / ИСПРАВЛЕНО: - / ЗАМЕТКА: сура Бакара, заклание коровы\n"
                    "«дела по намрениям» → АЯТЫ: - / ФРАЗЫ: إنما الأعمال بالنيات ; الأعمال بالنيات / ИСПРАВЛЕНО: дела по намерениям / ЗАМЕТКА: хадис о намерениях\n"
                    "«присяга абу бакру» → АЯТЫ: - / ФРАЗЫ: بايعت أبا بكر ; استخلف أبو بكر / ИСПРАВЛЕНО: - / ЗАМЕТКА: присяга Абу Бакру\n"
                    "«аятуль курси» → АЯТЫ: 2:255 / ФРАЗЫ: الله لا اله الا هو الحي القيوم / ИСПРАВЛЕНО: аят аль-Курси / ЗАМЕТКА: Аят аль-Курси\n"
                    "«али отказался стереть расулюллах» → АЯТЫ: - / ХАДИСЫ: Бухари 2698 ; Муслим 1783 / ФРАЗЫ: امح رسول الله ; لا أمحوك / ИСПРАВЛЕНО: - / ЗАМЕТКА: Худайбия, Али отказался стереть «Расулюллах»\n"
                    "«бидаа нововведение» → АЯТЫ: 5:3 ; 42:21 ; 57:27 ; 3:85 / ФРАЗЫ: محدثات الأمور ; شرعوا لهم من الدين / ИСПРАВЛЕНО: бид'а (нововведение) / ЗАМЕТКА: тема нововведений в религии\n"
                    "«аллах милостивее к рабам чем мать к ребёнку» → АЯТЫ: - / ХАДИСЫ: Бухари 5999 ; Муслим 2754 / ФРАЗЫ: لله أرحم بعباده من هذه بولدها ; أترون هذه طارحة ولدها في النار / ИСПРАВЛЕНО: - / ЗАМЕТКА: милость Аллаха (история с пленницей)\n"
                    "«хадис про изображения/статуи/التماثيل в доме» → АЯТЫ: - / ХАДИСЫ: Бухари 2105 ; Муслим 2107 / ФРАЗЫ: إن أصحاب هذه الصور يعذبون يوم القيامة ; نمرقة فيها تصاوير ; أحيوا ما خلقتم ; لا تدخل الملائكة بيتا فيه صورة / ИСПРАВЛЕНО: - / ЗАМЕТКА: запрет изображений/статуй\n"
                    "КРИТИЧНО: номер хадиса давай ТОЛЬКО при 100% уверенности — НЕВЕРНЫЙ номер ХУЖЕ, чем его отсутствие (не угадывай близкий!). ГЛАВНОЕ и САМОЕ НАДЁЖНОЕ — дай ТОЧНУЮ уникальную арабскую ФРАЗУ из самого текста хадиса (4-9 слов ПОДРЯД, дословно как в сборнике): приложение найдёт ИМЕННО этот хадис по фразе в своей базе. Лучше точная фраза без номера, чем выдуманный номер. "
                    "ВАЖНО: если запрос — ТЕМА/ПОНЯТИЕ (напр. «нововведение/бид'а», «терпение», «довольство родителей», «лицемерие»), "
                    "в АЯТЫ дай 3-8 номеров аятов, СВЯЗАННЫХ С ТЕМОЙ ПО СМЫСЛУ — даже если само слово в них не встречается дословно (НЕ пиши «нет аятов по теме»). "
                    "Бери РЕАЛЬНЫЕ слова текста ДОСЛОВНО как в сборнике (не пересказ, не выдумывай фразу). Если это просто тема одним словом — дай также 3-5 арабских "
                    "ключевых слов в ФРАЗЫ. Выведи ТОЛЬКО эти 5 строк.")
            txt = await loop.run_in_executor(None, ask_deepseek, "Запрос: " + meaning, sysm) or ""
            def _grab(lbl):
                m = re.search(lbl + r'\s*[:：]\s*(.+)', txt); return m.group(1).strip() if m else ''
            ayl, hadl, phl, fixl, notel = _grab('АЯТЫ'), _grab('ХАДИСЫ'), _grab('ФРАЗЫ'), _grab('ИСПРАВЛЕНО'), _grab('ЗАМЕТКА')
            quran = re.findall(r'\d{1,3}:\d{1,3}', ayl)[:12]
            # ХАДИСЫ: «Бухари 3437 ; Муслим 162» → [{src,num}]
            hadiths = []
            for part in re.split(r'[;,\n]', hadl or ''):
                mm = re.search(r'([А-Яа-яЁё \-]+?)\s*№?\s*(\d{1,5})', part)
                if mm: hadiths.append({'src': mm.group(1).strip(), 'num': mm.group(2)})
            hadiths = hadiths[:8]
            ph = [re.sub(r'^[\d\.\-\)\s]+', '', p).strip() for p in re.split(r'[;\n،]', phl) if re.search(r'[؀-ۿ]', p)][:6]
            if not ph and not quran and not hadiths:   # фолбэк: метки не распознались — берём любые арабские строки
                ph = [re.sub(r'^[\d\.\-\)\s]+', '', x).strip() for x in (txt or '').splitlines() if re.search(r'[؀-ۿ]', x)][:6]
            fixed = '' if fixl in ('', '-', '—', '–') else fixl[:120]
            note = '' if notel in ('', '-', '—', '–') else notel[:200]
            result = {'phrases': ph, 'quran': quran, 'hadiths': hadiths, 'note': note, 'fixed': fixed}
            saved = None
            if ph or quran or hadiths:
                try: saved = {"new": True, "total": await loop.run_in_executor(None, neuro_put, nkey, result)}
                except Exception: saved = None
            await loop.run_in_executor(None, usage_log, user, "нейро", True, len(meaning), "", "")
            await _notify_usage(user, "нейро", True, "", "", saved, q=meaning)
            out = dict(result); out['cached'] = False
            return _cors(web.json_response(out))
        except Exception as e:
            return _cors(web.json_response({'phrases': [], 'error': str(e)}))

    async def booksearch(r):
        # Умный ИИ-поиск КНИГИ Мактабы своими словами на русском → арабское название + автор + ключевые слова.
        # Накопление в data/booksearch.json (повтор не тратит ключ). Гейт = нейро.
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('booksearch:' + _uid(user, r), 12, 60):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        try:
            q = (d.get('q') or '').strip()[:300]
            if len(q) < 2:
                return _cors(web.json_response({'ar': [], 'author': [], 'cached': False}))
            force = bool(d.get('force'))
            key = q.lower()
            cached = None if force else await loop.run_in_executor(None, bsearch_get, key)
            if cached:
                await loop.run_in_executor(None, usage_log, user, "поиск книги", False, len(q), "", "")
                out = dict(cached); out['cached'] = True
                return _cors(web.json_response(out))
            sysm = ("Ты — каталог исламской библиотеки «المكتبة الشاملة» (тысячи книг). Запрос на русском "
                    "(своими словами, ВОЗМОЖНЫ ОПЕЧАТКИ) описывает КНИГУ и/или АВТОРА (часто транскрипция арабских имён). "
                    "Определи, что хотят, и ответь СТРОГО 5 строками (метки именно так):\n"
                    "АВТОР: <арабское имя автора как в каталоге, если запрос про автора/учёного; иначе ->\n"
                    "НАЗВАНИЕ: <точные арабские названия книг, до 4 вариантов через ; как пишутся в библиотеке; если назван только автор — перечисли его САМЫЕ ИЗВЕСТНЫЕ книги>\n"
                    "КЛЮЧИ: <2-6 арабских ключевых слов из названий/имени для поиска; через ;>\n"
                    "РЕЖИМ: <author — если ищут все книги автора; book — если конкретную книгу>\n"
                    "ЗАМЕТКА: <очень кратко по-русски, что это>\n"
                    "Примеры:\n"
                    "«ибн каим» → АВТОР: ابن قيم الجوزية / НАЗВАНИЕ: زاد المعاد ; مدارج السالكين ; إعلام الموقعين / КЛЮЧИ: ابن القيم ; ابن قيم الجوزية / РЕЖИМ: author / ЗАМЕТКА: имам Ибн аль-Каййим — показать все его книги\n"
                    "«недуги сердца ибн каим» → АВТОР: ابن قيم الجوزية / НАЗВАНИЕ: أمراض القلوب وشفاؤها / КЛЮЧИ: أمراض القلوب ; شفاؤها / РЕЖИМ: book / ЗАМЕТКА: трактат о болезнях сердца\n"
                    "«альбани сильсиля» → АВТОР: الألباني / НАЗВАНИЕ: السلسلة الصحيحة ; السلسلة الضعيفة / КЛЮЧИ: السلسلة ; الصحيحة ; الضعيفة ; الألباني / РЕЖИМ: book / ЗАМЕТКА: шейх аль-Альбани — Сильсиля ас-Сахиха и ад-Даифа\n"
                    "«сахих бухари» → АВТОР: البخاري / НАЗВАНИЕ: صحيح البخاري ; الجامع الصحيح / КЛЮЧИ: صحيح البخاري ; الجامع الصحيح / РЕЖИМ: book / ЗАМЕТКА: сборник достоверных хадисов\n"
                    "Бери РЕАЛЬНЫЕ арабские названия/имена как в каталоге. Выведи ТОЛЬКО эти 5 строк.")
            txt = await loop.run_in_executor(None, ask_deepseek, "Запрос: " + q, sysm) or ""
            def _grab(lbl):
                m = re.search(lbl + r'\s*[:：]\s*(.+)', txt); return m.group(1).strip() if m else ''
            naml, autl, keyl, model, notel = _grab('НАЗВАНИЕ'), _grab('АВТОР'), _grab('КЛЮЧИ'), _grab('РЕЖИМ'), _grab('ЗАМЕТКА')
            def _arlist(s):
                return [re.sub(r'^[\d\.\-\)\s]+', '', x).strip() for x in re.split(r'[;\n،]', s or '') if re.search(r'[؀-ۿ]', x)][:6]
            ar = _arlist(naml) + _arlist(keyl)
            seen = set(); ar = [x for x in ar if not (x in seen or seen.add(x))][:8]
            author = _arlist(autl)
            mode = 'author' if 'author' in (model or '').lower() else 'book'
            note = '' if notel in ('', '-', '—', '–') else notel[:200]
            result = {'ar': ar, 'author': author, 'mode': mode, 'note': note}
            saved = None
            if ar or author:
                try:
                    _tot = await loop.run_in_executor(None, bsearch_put, key, result)
                    _ttl = (ar[0] if ar else (author[0] if author else ''))
                    saved = {"new": True, "total": _tot, "what": f"книга «{q[:30]}» → {_ttl}"}
                except Exception: saved = None
            await loop.run_in_executor(None, usage_log, user, "поиск книги", True, len(q), "", "")
            await _notify_usage(user, "поиск книги", True, "", "", saved)
            out = dict(result); out['cached'] = False
            return _cors(web.json_response(out))
        except Exception as e:
            return _cors(web.json_response({'ar': [], 'author': [], 'error': str(e)}))

    async def booktrans(r):
        # Перевод названий книг (пачкой) на русский + огласованный арабский. Накопление data/booknames.json.
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('booktrans:' + _uid(user, r), 20, 60):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        try:
            titles = d.get('titles') or []
            titles = [str(t).strip()[:200] for t in titles if str(t).strip()][:40]
            if not titles:
                return _cors(web.json_response({'map': {}}))
            cache = _bnames_load()
            out_map = {}; need = []
            for t in titles:
                if t in cache: out_map[t] = cache[t]
                else: need.append(t)
            new_map = {}
            if need:
                numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(need))
                sysm = ("Переведи названия исламских книг с арабского на русский. Для КАЖДОГО номера выведи ОДНУ строку строго в формате:\n"
                        "<номер>| <русский перевод> || <тот же арабский, но С ОГЛАСОВКАМИ (تشكيل)>\n"
                        "Русский — кратко и понятно (можно транслитерацию известных названий: «Сахих аль-Бухари»). "
                        "Огласуй арабский правильно. Ничего лишнего, только строки по числу названий.")
                txt = await loop.run_in_executor(None, ask_deepseek, numbered, sysm) or ""
                for line in txt.splitlines():
                    mm = re.match(r'\s*(\d{1,3})\s*[\|\.\)]\s*(.+)', line)
                    if not mm: continue
                    idx = int(mm.group(1)) - 1; rest = mm.group(2).strip()
                    if idx < 0 or idx >= len(need): continue
                    if '||' in rest:
                        ru, voc = rest.split('||', 1); ru = ru.strip(); voc = voc.strip()
                    else:
                        ru = rest.strip(); voc = ''
                    if ru:
                        new_map[need[idx]] = {'ru': ru[:200], 'voc': voc[:200]}
                if new_map:
                    try: await loop.run_in_executor(None, bnames_put, new_map)
                    except Exception: pass
                out_map.update(new_map)
            await loop.run_in_executor(None, usage_log, user, "перевод названий", bool(need), len(titles), "", "")
            return _cors(web.json_response({'map': out_map, 'translated': len(new_map)}))
        except Exception as e:
            return _cors(web.json_response({'map': {}, 'error': str(e)}))

    async def bookinfo(r):
        # Описание книги (ИИ) + ссылки на Википедию автора/книги. Накопление data/bookinfo.json.
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('bookinfo:' + _uid(user, r), 15, 60):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        try:
            title = (d.get('title') or '').strip()[:200]
            author = (d.get('author') or '').strip()[:120]
            if not title:
                return _cors(web.json_response({}))
            key = title + '|' + author
            force = bool(d.get('force'))
            cached = None if force else await loop.run_in_executor(None, binfo_get, key)
            if cached:
                out = dict(cached); out['cached'] = True
                return _cors(web.json_response(out))
            sysm = ("Дай КРАТКУЮ структурированную справку об исламской книге. Ответь СТРОГО этими строками (метки точно так, без лишнего):\n"
                    "НАЗВАНИЕ_РУ: <русский перевод названия>\n"
                    "АВТОР: <имя автора (рус.) + годы жизни по хиджре/григ., если знаешь>\n"
                    "СОСТАВЛЕНА: <примерная дата/век написания и место (город/страна), если известно; иначе ->\n"
                    "ОПИСАНИЕ: <2-3 предложения: о чём книга, тематика, значение>\n"
                    "СРЕДА: <в какой среде/течении используется и ценится: суннизм (и какой мазхаб/манхадж), суфизм, шиизм, и т.п.; кратко>\n"
                    "ОЦЕНКА: <как оценивают учёные: похвала и/или критика, кратко и по делу>\n"
                    "ВИКИ_АВТОР: <URL Википедии об авторе (ru.wikipedia.org или ar.wikipedia.org), если уверен; иначе ->\n"
                    "ВИКИ_КНИГА: <URL Википедии о книге, если уверен; иначе ->\n"
                    "Не выдумывай ссылки и факты — если не уверен, ставь -. Будь точен и лаконичен. Выведи ТОЛЬКО эти строки.")
            txt = await loop.run_in_executor(None, ask_deepseek, f"Книга: {title}\nАвтор: {author}", sysm) or ""
            def _grab(lbl):
                m = re.search(lbl + r'\s*[:：]\s*(.+)', txt); return m.group(1).strip() if m else ''
            ru = _grab('НАЗВАНИЕ_РУ'); desc = _grab('ОПИСАНИЕ')
            author = _grab('АВТОР'); composed = _grab('СОСТАВЛЕНА'); env = _grab('СРЕДА'); evl = _grab('ОЦЕНКА')
            wa = _grab('ВИКИ_АВТОР'); wb = _grab('ВИКИ_КНИГА')
            def _url(s):
                m = re.search(r'https?://[^\s\)]+', s or ''); return m.group(0) if m else ''
            def _cl(s):
                return '' if (s or '').strip() in ('', '-', '—', '–') else s.strip()
            result = {'ru': ru[:200], 'author': _cl(author)[:200], 'composed': _cl(composed)[:200],
                      'desc': desc[:700], 'env': _cl(env)[:250], 'eval': _cl(evl)[:300],
                      'wiki_author': _url(wa), 'wiki_book': _url(wb)}
            saved = None
            if desc:
                try: saved = {"new": True, "total": await loop.run_in_executor(None, binfo_put, key, result)}
                except Exception: saved = None
            await loop.run_in_executor(None, usage_log, user, "описание книги", True, len(title), "", "")
            await _notify_usage(user, "описание книги", True, "", "", saved)
            out = dict(result); out['cached'] = False
            return _cors(web.json_response(out))
        except Exception as e:
            return _cors(web.json_response({'error': str(e)}))

    async def structure_results(r):
        # «Помочь с результатами»: ИИ структурирует/осмысляет текущую выдачу поиска (без накопления).
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('structure:' + _uid(user, r), 8, 60):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        try:
            q = (d.get('q') or '').strip()[:200]
            items = d.get('items') or []
            items = [str(x)[:200] for x in items if str(x).strip()][:18]
            if not items:
                return _cors(web.json_response({'text': ''}))
            numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(items))
            sysm = ("Ты помогаешь пользователю осмыслить результаты поиска по хадисам/книгам. Дан запрос и список "
                    "найденного. Кратко и структурированно по-русски:\n"
                    "• что в целом нашлось (1-2 фразы),\n"
                    "• сгруппируй по смыслу/источнику (короткими пунктами),\n"
                    "• подскажи, что выбрать под запрос и как уточнить поиск.\n"
                    "Без воды, маркированно. Не выдумывай того, чего нет в списке.")
            txt = await loop.run_in_executor(None, ask_deepseek, "Запрос: " + q + "\nНайдено:\n" + numbered, sysm) or ""
            await loop.run_in_executor(None, usage_log, user, "структурировать", True, len(q), "", "")
            return _cors(web.json_response({'text': txt.strip()[:2500]}))
        except Exception as e:
            return _cors(web.json_response({'text': '', 'error': str(e)}))

    async def narrator_rijal(r):
        # Разбор ПЕРЕДАТЧИКА (ильм риджаль): что говорят учёные — джарх/тадиль. Кэш data/narrators.json.
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('narr_rijal:' + _uid(user, r), 12, 60):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        try:
            name = (d.get('name') or '').strip()[:160]
            if len(name) < 2:
                return _cors(web.json_response({}))
            cache = _data_get("narrators.json", {}) or {}
            key = name.lower()
            force = bool(d.get('force'))
            if not force and key in cache:
                out = dict(cache[key]); out['cached'] = True
                return _cors(web.json_response(out))
            sysm = ("Ты — специалист по ильм ар-риджаль (оценка передатчиков хадисов, джарх ва тадиль). "
                    "Дан передатчик (рус. транскрипция или арабский). Ответь СТРОГО строками (метки точно так):\n"
                    "ИМЯ_АР: <полное арабское имя передатчика, как в книгах риджаль>\n"
                    "ЭПОХА: <век/годы, поколение (сахаби/табии/…), если знаешь; иначе ->\n"
                    "ОЦЕНКА: <итоговая степень: сикъа/садукъ/слабый/матрук/… кратко>\n"
                    "УЧЁНЫЕ: <что сказали имамы джарха-тадиля: напр. «Ибн Маин: сикъа; Ахмад: …; Абу Хатим: …» — кратко, по делу>\n"
                    "ГДЕ_ИСКАТЬ: <в каких трудах риджаль смотреть (Тахзиб, аль-Джарх ва-т-Тадиль, аль-Камиль и т.п.)>\n"
                    "ЗАМЕТКА: <1 фраза по-русски>\n"
                    "Если это НЕ передатчик хадисов (а тема/слово) — выведи только: НЕ_ПЕРЕДАТЧИК\n"
                    "Будь точен, не выдумывай. Выведи только метки.")
            txt = await loop.run_in_executor(None, ask_deepseek, "Передатчик: " + name, sysm) or ""
            if 'НЕ_ПЕРЕДАТЧИК' in txt or 'НЕ ПЕРЕДАТЧИК' in txt:
                return _cors(web.json_response({'is_narrator': False}))
            def _grab(lbl):
                m = re.search(lbl + r'\s*[:：]\s*(.+)', txt); return m.group(1).strip() if m else ''
            def _cl(s):
                return '' if (s or '').strip() in ('', '-', '—', '–') else s.strip()
            result = {'is_narrator': True, 'ar': _cl(_grab('ИМЯ_АР'))[:160], 'era': _cl(_grab('ЭПОХА'))[:120],
                      'grade': _cl(_grab('ОЦЕНКА'))[:160], 'scholars': _cl(_grab('УЧЁНЫЕ'))[:600],
                      'where': _cl(_grab('ГДЕ_ИСКАТЬ'))[:300], 'note': _cl(_grab('ЗАМЕТКА'))[:200]}
            saved = None
            if result.get('grade') or result.get('scholars'):
                try:
                    cache[key] = {k: v for k, v in result.items() if k != 'is_narrator'}
                    await loop.run_in_executor(None, _data_put, "narrators.json", cache, f"narrator: {name[:40]}")
                    saved = {"new": True, "total": len(cache)}
                except Exception: pass
            await loop.run_in_executor(None, usage_log, user, "разбор передатчика", True, len(name), "", "")
            await _notify_usage(user, "разбор передатчика", True, "", "", saved)
            out = dict(result); out['cached'] = False
            return _cors(web.json_response(out))
        except Exception as e:
            return _cors(web.json_response({'error': str(e)}))

    async def errlog(r):
        # Журнал ошибок приложения: клиент шлёт ошибку → data/errors.json (с дедупом) + уведомление владельцу.
        try:
            d = await _body(r)
            user = verify_init_data(d.get('initData'))
            msg = (d.get('msg') or '').strip()[:300]
            if not msg:
                return _cors(web.json_response({'ok': False}))
            where = (d.get('where') or '').strip()[:120]
            ver = (d.get('ver') or '').strip()[:20]
            stack = (d.get('stack') or '').strip()[:600]
            uid = _uid(user, r)
            if not rate_ok('errlog:' + uid, 8, 60):
                return _cors(web.json_response({'ok': False, 'rate': True}))
            cur = _data_get("errors.json", []) or []
            if not isinstance(cur, list): cur = []
            key = (msg + '|' + where + '|' + ver)[:200]
            existing = None
            for e in cur:
                if e.get('key') == key: existing = e; break
            if existing:
                existing['count'] = (existing.get('count', 1)) + 1
                existing['last_ver'] = ver
            else:
                # M304: сквозной номер ошибки приложения — A-001, A-002… (A = App). Не повторяется.
                _seq = max([e.get('seq', 0) for e in cur] or [0]) + 1
                _eid = 'A-%03d' % _seq
                cur.append({'key': key, 'msg': msg, 'where': where, 'ver': ver, 'stack': stack,
                            'uid': str(uid)[:24], 'count': 1, 'fixed': False, 'seq': _seq, 'eid': _eid})
                cur = cur[-400:]
                try:
                    await _notify(f"🐞 НОВАЯ ОШИБКА {_eid} (app {ver})\n{where}: {msg}\n(открыта; всего в журнале: {len(cur)} · решить: «ошибка решена {_eid}»)")
                except Exception: pass
            await loop.run_in_executor(None, _data_put, "errors.json", cur, f"errlog: {msg[:40]}")
            return _cors(web.json_response({'ok': True}))
        except Exception as e:
            return _cors(web.json_response({'ok': False, 'error': str(e)}))

    async def qaudio(r):
        # Прокси quran.com (qurancdn): пословные тайминги суры для интерактивной подсветки чтения.
        # Возвращает {audio_url, timings:[{a, from, to, segs:[[word,startMs,endMs]...]}]}. Кэш в памяти процесса.
        user = verify_init_data(r.query.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        try:
            rec = re.sub(r'[^0-9]', '', r.query.get('reciter') or '7') or '7'
            ch = re.sub(r'[^0-9]', '', r.query.get('chapter') or '')
            if not ch or not (1 <= int(ch) <= 114):
                return _cors(web.json_response({'error': 'bad chapter'}))
            ck = rec + '_' + ch
            global _QAUDIO_CACHE
            try: _QAUDIO_CACHE
            except NameError: _QAUDIO_CACHE = {}
            if ck in _QAUDIO_CACHE:
                return _cors(web.json_response(_QAUDIO_CACHE[ck]))
            url = f"https://api.qurancdn.com/api/qdc/audio/reciters/{rec}/audio_files?chapter={ch}&segments=true"
            def _fetch():
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
                return json.loads(urllib.request.urlopen(req, timeout=25).read().decode('utf-8'))
            d = await loop.run_in_executor(None, _fetch)
            af = (d.get('audio_files') or [{}])[0]
            timings = []
            for v in (af.get('verse_timings') or []):
                vk = v.get('verse_key') or ''
                a = vk.split(':')[1] if ':' in vk else ''
                timings.append({'a': int(a) if a.isdigit() else 0,
                                'from': v.get('timestamp_from') or 0,
                                'to': v.get('timestamp_to') or 0,
                                'segs': v.get('segments') or []})
            out = {'audio_url': af.get('audio_url') or '', 'timings': timings}
            if out['audio_url'] and timings:
                _QAUDIO_CACHE[ck] = out
            return _cors(web.json_response(out))
        except Exception as e:
            return _cors(web.json_response({'error': str(e)}))

    async def authorinfo(r):
        # Биография автора (ИИ) + Википедия. Накопление data/bookinfo.json под ключом «author|<имя>».
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('authorinfo:' + _uid(user, r), 15, 60):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        try:
            author = (d.get('author') or '').strip()[:160]
            if not author:
                return _cors(web.json_response({}))
            key = 'author|' + author
            force = bool(d.get('force'))
            cached = None if force else await loop.run_in_executor(None, binfo_get, key)
            if cached:
                out = dict(cached); out['cached'] = True
                return _cors(web.json_response(out))
            sysm = ("Дай краткую справку об исламском учёном/авторе. Ответь СТРОГО 4 строками (метки именно так):\n"
                    "ИМЯ_РУ: <имя по-русски, как принято>\n"
                    "БИО: <3-5 предложений: кто это, эпоха (годы/век по хиджре), мазхаб/специализация, чем известен, главные труды>\n"
                    "ГОДЫ: <годы жизни / век по хиджре, если знаешь; иначе ->\n"
                    "ВИКИ: <URL статьи Википедии об авторе (ru или ar), если уверен; иначе ->\n"
                    "Не выдумывай ссылку. Выведи только эти 4 строки.")
            txt = await loop.run_in_executor(None, ask_deepseek, "Автор: " + author, sysm) or ""
            def _grab(lbl):
                m = re.search(lbl + r'\s*[:：]\s*(.+)', txt); return m.group(1).strip() if m else ''
            ru = _grab('ИМЯ_РУ'); bio = _grab('БИО'); years = _grab('ГОДЫ'); wiki = _grab('ВИКИ')
            def _url(s):
                m = re.search(r'https?://[^\s\)]+', s or ''); return m.group(0) if m else ''
            years = '' if years in ('', '-', '—', '–') else years[:60]
            result = {'ru': ru[:160], 'bio': bio[:800], 'years': years, 'wiki': _url(wiki)}
            saved = None
            if bio:
                try: saved = {"new": True, "total": await loop.run_in_executor(None, binfo_put, key, result)}
                except Exception: saved = None
            await loop.run_in_executor(None, usage_log, user, "биография автора", True, len(author), "", "")
            await _notify_usage(user, "биография автора", True, "", "", saved)
            out = dict(result); out['cached'] = False
            return _cors(web.json_response(out))
        except Exception as e:
            return _cors(web.json_response({'error': str(e)}))

    async def wordai(r):
        # ИИ-перевод/проверка ОДНОГО слова: точный перевод + настоящий корень (надёжнее Arabus).
        # Накопление в data/wordai.json + уведомление владельцу (ИИ vs Arabus — проверь). Гейт = нейро.
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('wordai:' + _uid(user, r), 15, 60):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        try:
            word = (d.get('word') or '').strip()[:60]
            ctx = (d.get('ctx') or '').strip()[:300]
            root_hint = (d.get('root') or '').strip()[:12]
            force = bool(d.get('force'))
            key = _wordai_key(word)
            if not key:
                return _cors(web.json_response({'ru': '', 'root': '', 'gram': ''}))
            cached = None if force else await loop.run_in_executor(None, wordai_get, key)
            if cached:
                await loop.run_in_executor(None, usage_log, user, "слово-ии", False, len(word), "", "")
                out = dict(cached); out['cached'] = True
                return _cors(web.json_response(out))
            sysm = ("Ты — точный арабско-русский словарь. Дано АРАБСКОЕ слово (как в тексте Корана/хадиса), "
                    "возможно с контекстом. Дай перевод ИМЕННО ЭТОГО слова/формы по контексту (НЕ список "
                    "однокоренных, НЕ другое слово того же корня), его НАСТОЯЩИЙ корень и часть речи. "
                    "Ответь СТРОГО 3 строки (метки именно так):\n"
                    "ПЕРЕВОД: <короткий точный перевод этого слова>\n"
                    "КОРЕНЬ: <корень арабскими буквами>\n"
                    "ГРАММ: <часть речи/форма кратко по-русски>\n"
                    "Пример: «لِكُلِّ» (контекст: لكل نبي دعوة) → ПЕРЕВОД: для каждого / КОРЕНЬ: كلل / "
                    "ГРАММ: предлог لـ + имя كل в род. падеже. Выведи ТОЛЬКО эти 3 строки.")
            prompt = "Слово: " + word + (("\nКорень (подсказка): " + root_hint) if root_hint else "") + (("\nКонтекст: " + ctx) if ctx else "")
            txt = await loop.run_in_executor(None, ask_deepseek, prompt, sysm) or ""
            def _g(lbl):
                m = re.search(lbl + r'\s*[:：]\s*(.+)', txt); return m.group(1).strip() if m else ''
            ru = _g('ПЕРЕВОД')[:200]; root = _g('КОРЕНЬ')[:12]; gram = _g('ГРАММ')[:140]
            if not ru:
                return _cors(web.json_response({'ru': '', 'root': '', 'gram': '', 'error': 'no-ai'}))
            val = {'ru': ru, 'root': root, 'gram': gram, 'd': datetime.now().strftime('%d.%m.%Y'), 'w': word}
            total = await loop.run_in_executor(None, wordai_put, key, val)
            await loop.run_in_executor(None, usage_log, user, "слово-ии", True, len(word), "", "")
            # уведомление ВЛАДЕЛЬЦУ: ИИ-перевод слова — проверь (может ИИ ошибся, а Arabus прав)
            if application:
                try:
                    uid = (user or {}).get('id')
                    who = ("@" + user["username"]) if (user and user.get("username")) else (f"[{uid}](tg://user?id={uid})" if uid else "аноним")
                    await application.bot.send_message(
                        OWNER_ID,
                        f"#ии #слово 🔤 ИИ-перевод слова: *{word}*\nПеревод: {ru}\nКорень (ИИ): {root}\n"
                        + (f"Контекст: {ctx}\n" if ctx else "") + f"Кто: {who} · всего слов: {total}\n"
                        "⚠️ Сверь ИИ↔Arabus: если ИИ ошибся — напиши «слово <слово> = <верный перевод>».",
                        parse_mode="Markdown", disable_web_page_preview=True)
                except Exception:
                    pass
            out = dict(val); out['cached'] = False
            return _cors(web.json_response(out))
        except Exception as e:
            return _cors(web.json_response({'ru': '', 'error': str(e)}))

    async def isnad_ai_h(r):
        # M201: ИИ извлекает полную цепочку передатчиков (для перепроверки выделения). Гейт = нейро.
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('isnadai:' + _uid(user, r), 12, 60):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        text = (d.get('text') or '')[:3000]
        if len(text) < 5:
            return _cors(web.json_response({'names': []}))
        res = await loop.run_in_executor(None, isnad_ai, text)
        await loop.run_in_executor(None, usage_log, user, "иснад-ии", not res.get('cached'), len(text), "", "")
        return _cors(web.json_response(res))

    async def book_page(r):
        # M216: читалка любой книги Мактабы через turath (book_id+pg). Гейт = вход в приложение.
        user = verify_init_data(r.headers.get('X-Init-Data') or r.query.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        if not rate_ok('bookpage:' + _uid(user, r), 60, 60):
            return _ratelimited()
        res = await loop.run_in_executor(None, turath_page, r.query.get('id'), r.query.get('pg') or '1')
        return _cors(web.json_response(res))

    async def devfeedback(r):
        # M238: замечание/правка для разработчика от ВЛАДЕЛЬЦА → data/devfeedback.json + LOG-канал (+ скрин).
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not (user and str(user.get('id')) == str(OWNER_ID)):
            return _deny('app')
        text = (d.get('text') or '').strip()[:2000]
        ctx = (d.get('ctx') or '').strip()[:300]
        img = d.get('img') or ''
        if not text and not img:
            return _cors(web.json_response({'ok': False}))
        try:
            fb = _data_get('devfeedback.json', []) or []
            n = len(fb) + 1
            imgkey = ''
            if img and isinstance(img, str) and img.startswith('data:image'):
                imgkey = 'devfb_img/%d.json' % n   # сохраняем САМ скрин (base64) → Claude может открыть
                try:
                    await loop.run_in_executor(None, _data_put, imgkey, {'b64': img, 'd': datetime.now().strftime('%d.%m.%Y %H:%M')}, 'devfb img %d' % n)
                except Exception:
                    imgkey = ''
            fb.append({'text': text, 'ctx': ctx, 'd': datetime.now().strftime('%d.%m.%Y %H:%M'), 'img': bool(img), 'imgkey': imgkey, 'done': False})
            await loop.run_in_executor(None, _data_put, 'devfeedback.json', fb[-500:], 'devfeedback +1')
        except Exception:
            pass
        if application:
            try:
                cap = "#замечание 🛠 От владельца Claude:\n" + text + (("\n📍 " + ctx) if ctx else "")
                if img and isinstance(img, str) and img.startswith('data:image'):
                    import base64
                    from io import BytesIO
                    raw = base64.b64decode(img.split(',', 1)[1])
                    bio = BytesIO(raw); bio.name = 'feedback.jpg'
                    await application.bot.send_photo(LOG_CHAT_ID, photo=bio, caption=cap[:1000])
                else:
                    await application.bot.send_message(LOG_CHAT_ID, cap, disable_web_page_preview=True)
            except Exception:
                pass
        return _cors(web.json_response({'ok': True}))

    async def explain(r):
        # M208: нейро-объяснение «простыми словами» (шарх/тафсир) хадиса/аята. Накопление в expl_<code>. Гейт = нейро.
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('explain:' + _uid(user, r), 8, 60):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        try:
            text = (d.get('text') or '')[:6000]
            source = re.sub(r'[^a-z0-9_]+', '', (d.get('source') or '').lower())[:40] or 'x'
            num = d.get('num'); kind = (d.get('kind') or 'hadith')
            force = bool(d.get('force'))
            store_src = 'expl_' + source
            if len(text) < 4:
                return _cors(web.json_response({'explanation': ''}))
            if not force and num not in (None, ''):
                stored = await loop.run_in_executor(None, lambda: (_coll_load(store_src) or {}).get(str(num)))
                if stored and stored.get('ru'):
                    await loop.run_in_executor(None, usage_log, user, "объяснение", False, len(text), source, str(num or ""))
                    await _notify_usage(user, "объяснение", False, source, num, None)
                    return _cors(web.json_response({'explanation': stored['ru'], 'cached': True}))
            ref = ("Коран " + str(num)) if kind == 'quran' else ((source.capitalize() if source != 'x' else "хадис") + (" №" + str(num) if num not in (None, '') else ""))
            sysm = ("Ты — знающий и осторожный исламский учитель. Объясни СУПЕР-ЛАКОНИЧНО и ясно смысл этого "
                    + ("аята Корана" if kind == 'quran' else "хадиса") + " простым русским языком: 3-6 предложений — "
                    "главный смысл + польза/урок + краткий довод. ОБЯЗАТЕЛЬНО начни с источника (" + ref + "). "
                    "Не пересказывай весь текст, без длинных предисловий и воды. НЕ выдумывай факты/хадисы; "
                    "если спорно — отметь одним словом. Только объяснение, коротко.")
            ex = await loop.run_in_executor(None, ask_deepseek, "Источник: " + ref + "\n" + text, sysm)
            ex = re.sub(r'\s*⚡.*$', '', (ex or ''), flags=re.S).strip()
            if not ex:
                return _cors(web.json_response({'explanation': '', 'error': 'no-ai'}))
            saved = None
            if num not in (None, ''):
                saved = await loop.run_in_executor(None, coll_add_translation, store_src, num, text, ex)
            await loop.run_in_executor(None, usage_log, user, "объяснение", True, len(text), source, str(num or ""))
            await _notify_usage(user, "объяснение", True, source, num, saved)
            return _cors(web.json_response({'explanation': ex, 'cached': False}))
        except Exception as e:
            return _cors(web.json_response({'explanation': '', 'error': str(e)}))

    async def translate(r):
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('translate', user):
            return _deny('translate')
        if not rate_ok('translate:' + _uid(user, r)):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        try:
            text = (d.get('text') or '')[:12000]   # длинные хадисы (напр. №1671 ~8000 симв., 2 риваята) — не резать на входе
            source = re.sub(r'[^a-z0-9_]+', '', (d.get('source') or '').lower())[:40]
            num = d.get('num')
            force = bool(d.get('force'))   # «🔄 обновить перевод» — переперевести заново (минуя кэш), чинит оборванный перевод
            # 1) УЖЕ переведено? (постоянный файл-сборник по номеру — переживает рестарты/инстансы). При force — пропускаем кэш.
            stored = None
            if not force and source and num not in (None, ''):
                stored = await loop.run_in_executor(None, lambda: (_coll_load(source) or {}).get(str(num)))
            if stored and stored.get('ru') and not _is_mostly_arabic(stored['ru']):   # битый арабский кэш игнорируем → переведём заново через DeepSeek
                await loop.run_in_executor(None, usage_log, user, "перевод", False, len(text), source, str(num or ""))
                await _notify_usage(user, "перевод", False, source, num, None)   # ♻️ из базы, ключ НЕ потрачен
                return _cors(web.json_response({'translation': stored['ru'], 'cached': True}))
            # 2) нет в базе (или force) → переводим заново и копим (перезаписываем оборванный)
            tr = await loop.run_in_executor(None, translate_matn, text, "", True, force)
            tr = re.sub(r'\s*⚡.*$', '', (tr or ''), flags=re.S).strip()
            saved = None
            if tr and source and num not in (None, ''):
                saved = await loop.run_in_executor(None, coll_add_translation, source, num, text, tr)
            await loop.run_in_executor(None, usage_log, user, "перевод", True, len(text), source, str(num or ""))
            await _notify_usage(user, "перевод", True, source, num, saved)
            return _cors(web.json_response({'translation': tr, 'cached': False}))
        except Exception as e:
            return _cors(web.json_response({'translation': '', 'error': str(e)}))

    async def search(r):
        # dorar-поиск: initData в заголовке X-Init-Data или в query (?initData=...); гейт = вход в приложение
        user = verify_init_data(r.headers.get('X-Init-Data') or r.query.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        if not rate_ok('search:' + _uid(user, r)):
            return _ratelimited()
        try:
            q = (r.query.get('q') or '')[:200]
            res = await loop.run_in_executor(None, search_hadith, q) if q else []
            return _cors(web.json_response({'results': res or []}))
        except Exception as e:
            return _cors(web.json_response({'results': [], 'error': str(e)}))

    async def wide(r):
        # M127: широкий поиск (sunnah.one) — гейт = вход в приложение, без траты нашего ключа
        user = verify_init_data(r.headers.get('X-Init-Data') or r.query.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        if not rate_ok('wide:' + _uid(user, r)):
            return _ratelimited()
        q = (r.query.get('q') or '')[:200]
        try:
            page = max(1, min(200, int(r.query.get('page') or 1)))
        except Exception:
            page = 1
        res = await loop.run_in_executor(None, wide_search, q, page) if q else {'count': 0, 'data': [], 'page': 1}
        return _cors(web.json_response(res))

    async def maktaba(r):
        # ОСНОВНОЙ поиск по всей Мактабе (turath): 40 первоисточников → избранное → كتب السنة → тафсир → остальное
        user = verify_init_data(r.headers.get('X-Init-Data') or r.query.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        if not rate_ok('maktaba:' + _uid(user, r)):
            return _ratelimited()
        q = (r.query.get('q') or '')[:200]
        try:
            page = max(1, min(200, int(r.query.get('page') or 1)))
        except Exception:
            page = 1
        res = await loop.run_in_executor(None, maktaba_search, q, page) if q else {'count': 0, 'data': [], 'page': 1}
        return _cors(web.json_response(res))

    async def rijal(r):
        # НейроМухаддис: поиск передатчика по 150 трудам ильм-риджаля (джарх/тадиль)
        user = verify_init_data(r.headers.get('X-Init-Data') or r.query.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        if not rate_ok('rijal:' + _uid(user, r)):
            return _ratelimited()
        name = (r.query.get('name') or r.query.get('q') or '')[:80]
        try:
            page = max(1, min(50, int(r.query.get('page') or 1)))
        except Exception:
            page = 1
        res = await loop.run_in_executor(None, rijal_search, name, page) if name else {'count': 0, 'data': [], 'page': 1}
        return _cors(web.json_response(res))

    async def balance(r):
        # только владелец: остаток DeepSeek + краткая статистика журналов для рабочего стола
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not (user and str(user.get('id')) == str(OWNER_ID)):
            return _deny('app')
        b = await loop.run_in_executor(None, deepseek_balance)
        j = await loop.run_in_executor(None, _journal_load)
        # GPT (OpenAI) — накопленный расход из gpt_spend.json (внутренняя кухня R30)
        gpt_data = {}
        try:
            if os.path.exists(GPT_SPEND_FILE):
                gpt_data = json.load(open(GPT_SPEND_FILE, encoding="utf-8"))
        except Exception:
            gpt_data = {}
        gpt_info = {
            'enabled': bool(OPENAI_API_KEY),
            'model': OPENAI_MODEL,
            'spent': round(float(gpt_data.get('total', 0.0)), 4),
            'calls': int(gpt_data.get('calls', 0)),
            'last': (gpt_data.get('log') or [{}])[-1] if gpt_data.get('log') else {},
        }
        # Gemini — бесплатный лимит Google (биллинга нет); показываем статус/модель
        gemini_info = {'enabled': bool(GEMINI_API_KEY), 'model': GEMINI_MODEL, 'free': True}
        return _cors(web.json_response({
            'balance': b,
            'gpt': gpt_info,
            'gemini': gemini_info,
            'usage': {'totals': j.get('usage', {}).get('totals', {}), 'recent': (j.get('usage', {}).get('recent') or [])[:25]},
            'translations': {'totals': j.get('translations', {}).get('totals', {}), 'recent': (j.get('translations', {}).get('recent') or [])[:25]},
            'feedback': (j.get('feedback') or [])[:25],
            'searches': {'total': j.get('searches', {}).get('total', 0),
                         'top': sorted(j.get('searches', {}).get('top', {}).items(), key=lambda x: -x[1].get('n', 0))[:25]},
            'app': {'opens': j.get('app', {}).get('opens', 0),
                    'users': len(j.get('app', {}).get('by_user', {})),
                    'by_day': dict(sorted(j.get('app', {}).get('by_day', {}).items())[-14:])},
        }))

    async def feedback(r):
        # отзыв/ошибка от тестера → журнал комментариев + пост в канал (#отзыв)
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        if not rate_ok('fb:' + _uid(user, r), limit=6, window=120):
            return _ratelimited()
        txt = (d.get('text') or '').strip()[:1000]
        ctx = (d.get('context') or '')[:200]
        img = d.get('img') or ''
        has_img = bool(img and isinstance(img, str) and img.startswith('data:image'))
        if not txt and not has_img:
            return _cors(web.json_response({'ok': False}))
        fid = await loop.run_in_executor(None, feedback_add, user, ctx, txt, has_img)
        if has_img:   # сохраняем САМ скрин (base64) → Claude может открыть data/fb_img/<id>.json
            try:
                await loop.run_in_executor(None, _data_put, 'fb_img/%s.json' % fid,
                                           {'b64': img, 'd': datetime.now().strftime('%d.%m.%Y %H:%M')}, 'fb img %s' % fid)
            except Exception:
                pass
        name = ("@" + user["username"]) if (user and user.get("username")) else str((user or {}).get("id") or "аноним")
        cap = f"#отзыв 💬 №{fid} от {name}{(' · ' + ctx) if ctx else ''}:\n{txt}"
        if has_img and application:
            try:
                import base64
                from io import BytesIO
                raw = base64.b64decode(img.split(',', 1)[1])
                bio = BytesIO(raw); bio.name = 'feedback.jpg'
                await application.bot.send_photo(LOG_CHAT_ID, photo=bio, caption=cap[:1000])
            except Exception:
                await _notify(cap)
        else:
            await _notify(cap)
        return _cors(web.json_response({'ok': True, 'id': fid}))

    async def tashkeel(r):
        # ИИ-огласовки (تشكيل) арабского текста; гейт — нейро (это DeepSeek)
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('tashkeel:' + _uid(user, r)):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        text = (d.get('text') or '')[:2000]
        source = re.sub(r'[^a-z0-9_]+', '', (d.get('source') or '').lower())[:40]
        num = d.get('num')
        if not text:
            return _cors(web.json_response({'text': ''}))
        # уже расставляли? (накопление, без повторной траты ключа)
        cached = None
        if source and num not in (None, ''):
            cached = await loop.run_in_executor(None, lambda: (_tk_load(source) or {}).get(str(num)))
        if cached:
            await loop.run_in_executor(None, usage_log, user, "огласовки", False, len(text), source, str(num or ""))
            await _notify_usage(user, "огласовки", False, source, num, None)
            return _cors(web.json_response({'text': cached, 'cached': True}))
        sysm = ("Ты расставляешь огласовки (تشكيل) в арабском тексте. "
                "Верни ТОТ ЖЕ текст с полной огласовкой. Без перевода, без пояснений, без кавычек — только огласованный текст.")
        out = await loop.run_in_executor(None, ask_deepseek, text, sysm) or ""
        out = re.sub(r'\s*⚡.*$', '', out, flags=re.S).strip()
        if out and source and num not in (None, ''):
            await loop.run_in_executor(None, tashkeel_add, source, num, out)
        await loop.run_in_executor(None, usage_log, user, "огласовки", True, len(text), source, str(num or ""))
        await _notify_usage(user, "огласовки", True, source, num, None)
        return _cors(web.json_response({'text': out, 'cached': False}))

    async def searchlog(r):
        # аналитика: что ищут (тихо, агрегируем); гейт — вход в приложение
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('app', user):
            return _cors(web.json_response({'ok': False}))
        if not rate_ok('slog:' + _uid(user, r), limit=40, window=60):
            return _cors(web.json_response({'ok': False}))
        q = (d.get('q') or '')[:60]; tab = (d.get('tab') or '')[:10]
        try: cnt = int(d.get('count') or 0)
        except Exception: cnt = 0
        if q:
            await loop.run_in_executor(None, searchlog_add, q, tab, cnt)
        return _cors(web.json_response({'ok': True}))

    async def takhrij_read(r):
        # M67h: отдать накопленный تخريج (взаимосвязь) по source+num; гейт = вход в приложение
        user = verify_init_data(r.headers.get('X-Init-Data') or r.query.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        source = re.sub(r'[^a-z0-9_]+', '', (r.query.get('source') or '').lower())[:40]
        num = r.query.get('num')
        if not source or num in (None, ''):
            return _cors(web.json_response({'cached': False}))
        data = await loop.run_in_executor(None, takhrij_get, source, num)
        return _cors(web.json_response({'cached': bool(data), 'takhrij': data} if data else {'cached': False}))

    async def takhrij_save(r):
        # M67h: сохранить найденный تخريج в нашу базу (накопление); гейт = вход в приложение
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        if not rate_ok('takhsave:' + _uid(user, r), limit=20, window=120):
            return _ratelimited()
        source = re.sub(r'[^a-z0-9_]+', '', (d.get('source') or '').lower())[:40]
        num = d.get('num')
        saved = await loop.run_in_executor(None, takhrij_put, source, num, d.get('sci'), d.get('local'), d.get('muh'))
        return _cors(web.json_response({'ok': bool(saved), 'saved': saved}))

    async def narrator(r):
        # M26: карточка передатчика — поиск равия в موسوعة رواة الحديث (hawramani); гейт = вход в приложение
        user = verify_init_data(r.headers.get('X-Init-Data') or r.query.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        if not rate_ok('narr:' + _uid(user, r), limit=30, window=60):
            return _ratelimited()
        q = (r.query.get('q') or '').strip()[:80]
        if not q:
            return _cors(web.json_response({'results': []}))
        res = await loop.run_in_executor(None, search_transmitters, q, 8)
        return _cors(web.json_response({'results': res or []}))

    async def narrator_ai(r):
        # ИИ-справка о равии (кто это + оценка учёных + источник), с накоплением; гейт — нейро (тратит ключ)
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('rijalai:' + _uid(user, r), limit=12, window=120):
            return _ratelimited()
        name = (d.get('name') or '').strip()[:80]
        if len(name) < 3:
            return _cors(web.json_response({'bio': '', 'cached': False}))
        cached = await loop.run_in_executor(None, rijal_ai_get, name)
        if cached:
            await loop.run_in_executor(None, usage_log, user, "равий-ИИ", False, len(name), "", "")
            return _cors(web.json_response({'bio': cached, 'cached': True}))
        sysm = ("Ты знаток науки о передатчиках хадисов (الجرح والتعديل والرواة). Дай КРАТКУЮ справку о равии по-русски: "
                "полное имя; кунья; когда жил/умер (если известно); кем был (сподвижник/таби'/..); и ОЦЕНКА достоверности "
                "словами имамов (ثقة/صدوق/ضعيف и т.п.) — КТО так оценил и в какой книге (تقريب التهذيب لابن حجر، "
                "الجرح والتعديل لابن أبي حاتم، تهذيب الكمال للمزي). 4-7 строк, без воды. "
                "В конце с новой строки: «⚠️ Справку собрал ИИ — сверяйте с первоисточниками (الجرح والتعديل، تقريب التهذيب).»")
        bio = await loop.run_in_executor(None, ask_deepseek, "Передатчик хадисов: " + name, sysm) or ""
        bio = bio.strip()
        if bio and len(bio) > 15:
            await loop.run_in_executor(None, rijal_ai_put, name, bio)
        await loop.run_in_executor(None, usage_log, user, "равий-ИИ", True, len(name), "", "")
        return _cors(web.json_response({'bio': bio, 'cached': False}))

    async def popular(r):
        # 🔥 Популярное: топ запросов (из накопленного searchlog), гейт = вход в приложение
        user = verify_init_data(r.headers.get('X-Init-Data') or r.query.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        j = await loop.run_in_executor(None, _journal_load)
        top = j.get('searches', {}).get('top', {})
        items = sorted(top.items(), key=lambda x: -x[1].get('n', 0))
        out = [{'q': k, 'tab': v.get('tab', ''), 'n': v.get('n', 0)}
               for k, v in items
               if v.get('n', 0) >= 2 and v.get('cnt', 0) > 0 and len(k) <= 28][:15]   # без длинных вставок хадисов
        return _cors(web.json_response({'items': out}))

    async def hit(r):
        # G3: счётчик запусков приложения (тихо; уникальные пользователи по id)
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not rate_ok('hit:' + _uid(user, r), limit=10, window=60):
            return _cors(web.json_response({'ok': False}))
        await loop.run_in_executor(None, app_hit, user)
        return _cors(web.json_response({'ok': True}))

    async def arabus(r):
        # Arabus: корень+значения слова (прокси+кэш arabus.ru); гейт = вход в приложение
        user = verify_init_data(r.headers.get('X-Init-Data') or r.query.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        if not rate_ok('arabus:' + _uid(user, r), limit=40, window=60):
            return _ratelimited()
        w = (r.query.get('word') or r.query.get('q') or '')[:60]
        root = (r.query.get('root') or '')[:20]
        if not w:
            return _cors(web.json_response({'word': '', 'count': 0, 'entries': []}))
        res = await loop.run_in_executor(None, arabus_fetch, w, root)
        return _cors(web.json_response(res))

    a = web.Application()
    a.add_routes([web.get('/api/health', health), web.post('/api/neuro', neuro),
                  web.post('/api/translate', translate), web.get('/api/search', search), web.get('/api/wide', wide),
                  web.get('/api/maktaba', maktaba), web.get('/api/rijal', rijal),
                  web.post('/api/access', access), web.post('/api/balance', balance),
                  web.post('/api/feedback', feedback), web.post('/api/searchlog', searchlog),
                  web.post('/api/tashkeel', tashkeel),
                  web.get('/api/takhrij', takhrij_read), web.post('/api/takhrij', takhrij_save),
                  web.get('/api/narrator', narrator), web.post('/api/narrator_ai', narrator_ai), web.post('/api/hit', hit),
                  web.get('/api/popular', popular), web.get('/api/arabus', arabus),
                  web.post('/api/wordai', wordai), web.post('/api/explain', explain),
                  web.post('/api/booksearch', booksearch),
                  web.post('/api/booktrans', booktrans), web.post('/api/bookinfo', bookinfo),
                  web.post('/api/authorinfo', authorinfo), web.get('/api/qaudio', qaudio),
                  web.post('/api/errlog', errlog), web.post('/api/narrator_rijal', narrator_rijal),
                  web.post('/api/structure', structure_results),
                  web.get('/api/book_page', book_page), web.post('/api/isnad_ai', isnad_ai_h),
                  web.post('/api/devfeedback', devfeedback),
                  web.options('/api/{t:.*}', opt)])
    runner = web.AppRunner(a); await runner.setup()
    port = int(os.environ.get('PORT', '8080'))
    site = web.TCPSite(runner, '0.0.0.0', port); await site.start()
    try:
        await loop.run_in_executor(None, load_access)   # прогреть правила доступа на старте
    except Exception:
        pass
    print("API server on port", port)

async def _setup(application):
    try:
        from telegram import MenuButtonWebApp, WebAppInfo
        btn = MenuButtonWebApp(text="𝗠𝗨𝗦𝗟𝗜𝗠𝗢𝗢𝗡-𝗔𝗣𝗣", web_app=WebAppInfo(url=WEBAPP_URL))   # имя кнопки приложения — вариант владельца
        # кнопка «🔎 Поиск» по умолчанию для ВСЕХ (доступ внутри решает сервер G9)
        await application.bot.set_chat_menu_button(menu_button=btn)
        await application.bot.set_chat_menu_button(chat_id=OWNER_ID, menu_button=btn)
    except Exception as e:
        print("menu button setup failed:", e)
    try:
        asyncio.create_task(_api_serve(application))
    except Exception as e:
        print("api start failed:", e)
    note = ""
    try:
        try:
            rr = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/update_note.txt",
                              headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}, timeout=8)
            if rr.status_code == 200:
                note = base64.b64decode(rr.json().get("content", "")).decode("utf-8").strip()
        except Exception:
            pass
        j = _journal_load()
        # LOG #деплой — ДЕДУП: при ПОВТОРНЫХ рестартах (частые пуши/пересборки) не дублируем один и тот же деплой.
        if note and note == (j.get("log_deploy") or {}).get("note", ""):
            pass   # этот деплой уже отмечен в LOG — молчим
        else:
            try:
                msg = "#деплой ✅ *Обновление готово!*\n" + (note if note else "Бот снова в эфире.")
                await application.bot.send_message(LOG_CHAT_ID, msg, parse_mode="Markdown")
            except Exception:
                pass
            if note:
                j["log_deploy"] = {"note": note, "d": datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
                _journal_save("log_deploy дедуп")
        # Публичный канал @muslimoonapp: постим, только если note НОВЫЙ. Ошибку — В LOG (чтобы видеть, ПОЧЕМУ молчит).
        if note:
            last = (j.get("app_post") or {}).get("note", "")
            if note != last:
                try:
                    body = (note + "\n\n———\n📲 Приложение: https://t.me/muslimoontt_bot/app\n🤖 Бот: https://t.me/muslimoontt_bot")
                    await application.bot.send_message(APP_CHANNEL_ID, body, disable_web_page_preview=True)
                    j["app_post"] = {"note": note, "d": datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
                    _journal_save("app_post → канал приложения")
                except Exception as e:
                    try:
                        await application.bot.send_message(LOG_CHAT_ID, f"⚠️ Не смог запостить обновление в @muslimoonapp (APP_CHANNEL_ID={APP_CHANNEL_ID}): {e}\nПроверь: бот добавлен АДМИНОМ канала с правом «Публикация сообщений»?")
                    except Exception:
                        pass
    except Exception as e:
        print("deploy notify block failed:", e)
    # Авто-вотчер канала @muslimoonapp: фронт-деплои (GitHub Pages) НЕ рестартят Railway,
    # поэтому стартовый пост выше срабатывает ТОЛЬКО при редеплое бэкенда. Эта фоновая
    # задача каждые 5 мин сама читает КОРНЕВОЙ update_note.txt из репозитория и постит в
    # канал, если нота новее последней опубликованной (дедуп — через journal app_post,
    # тот же, что у стартового блока → двойных постов нет). Канал больше НЕ отстаёт.
    try:
        asyncio.create_task(_app_channel_watcher(application))
    except Exception as e:
        print("app channel watcher start failed:", e)

async def _app_channel_watcher(application):
    """Фон: раз в 5 мин публикует новую update_note.txt в @muslimoonapp (см. _setup)."""
    while True:
        try:
            await asyncio.sleep(300)
            note = ""
            try:
                rr = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/update_note.txt",
                                  headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}, timeout=8)
                if rr.status_code == 200:
                    note = base64.b64decode(rr.json().get("content", "")).decode("utf-8").strip()
            except Exception:
                note = ""
            if not note:
                continue
            j = _journal_load()
            last = (j.get("app_post") or {}).get("note", "")
            if note != last:
                body = (note + "\n\n———\n📲 Приложение: https://t.me/muslimoontt_bot/app\n🤖 Бот: https://t.me/muslimoontt_bot")
                await application.bot.send_message(APP_CHANNEL_ID, body, disable_web_page_preview=True)
                j["app_post"] = {"note": note, "d": datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
                _journal_save("app_post → канал приложения (авто-вотчер, 5 мин)")
        except Exception as e:
            print("app channel watcher error:", e)

async def start_cmd(update, context):
    """/start — приветствие + кнопка открыть мини-апп (работает у всех)."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    try:
        is_private = update.effective_chat and update.effective_chat.type == "private"
        if is_private:
            btn = InlineKeyboardButton("📗 Открыть Muslimoon", web_app=WebAppInfo(url=WEBAPP_URL))
        else:
            btn = InlineKeyboardButton("📗 Открыть Muslimoon", url=WEBAPP_URL)  # web_app-инлайн нельзя в группах
        await update.message.reply_text(
            "Добро пожаловать в *Muslimoon Bot*! 🌙\n\n"
            "🔎 Поиск по хадисам, аятам и базе аль-Мухаймин — жми кнопку ниже.\n"
            "Также прямо в чате: «Бухари 333» · «мухэймин 5» · «коран 2:255» · «искать الصبر».",
            reply_markup=InlineKeyboardMarkup([[btn]]), parse_mode="Markdown")
    except Exception as e:
        try:
            await update.message.reply_text("🔎 Открой поиск: " + WEBAPP_URL)
        except Exception:
            pass

app = ApplicationBuilder().token(TOKEN).post_init(_setup).build()
app.add_handler(CommandHandler("start", start_cmd))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.VIDEO | filters.PHOTO | filters.Document.ALL, handle))
app.add_handler(ChatMemberHandler(track_member, ChatMemberHandler.CHAT_MEMBER))
_seen_chats = set()
async def _chat_seen(update, context):
    try:
        ch = update.effective_chat
        if ch and ch.id not in _seen_chats:
            _seen_chats.add(ch.id)
            await context.bot.send_message(LOG_CHAT_ID, f"📡 Чат/канал: «{ch.title}» | id={ch.id} | type={ch.type}")
    except Exception:
        pass
async def _bot_member(update, context):
    try:
        ch = update.effective_chat; st = update.my_chat_member.new_chat_member.status
        info = f"🤖 Бот: {st} в «{ch.title}» (id={ch.id}, {ch.type})"
        if st in ("member", "administrator") and ch.type in ("group", "supergroup"):
            a = load_access(); ok = a.get("group_open", True) or (str(ch.id) in (a.get("group_wl") or []))
            info += "\n" + ("✅ работает (группы открыты для всех)" if ok else "⛔ НЕ работает тут (режим «только свои группы»)")
            info += f"\n• Разрешить: `группа разреши {ch.id}`\n• Выйти: `покинь {ch.id}`\n• Бан: `бан {ch.id}`"
        await context.bot.send_message(LOG_CHAT_ID, info, parse_mode="Markdown")
    except Exception:
        pass
app.add_handler(MessageHandler(filters.ChatType.CHANNEL, _chat_seen))
app.add_handler(ChatMemberHandler(_bot_member, ChatMemberHandler.MY_CHAT_MEMBER))
async def _on_error(update, context):
    err = str(context.error); print("ERR:", err)
    if 'Conflict' in err:  # две копии бота — не спамим, settle сам
        return
    try:
        await context.bot.send_message(LOG_CHAT_ID, "⚠️ Ошибка бота:\n" + err[:700])
    except Exception:
        pass
app.add_error_handler(_on_error)
app.run_polling(drop_pending_updates=True)
