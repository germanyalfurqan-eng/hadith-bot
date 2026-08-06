# DEPLOY-TRIGGER С25 15.06.2026 01:44 — пакет #110/#40/#41/#90 (заявки в боте, #NN, анти-дубль)
# 27.07.2026: метка сборки. Владелец дважды присылал скрин «раг молчит» после того, как фикс был
# запушен — и нельзя было отличить «фикс не работает» от «Railway ещё не передеплоился». Теперь
# у бэкенда есть паспорт: GET /api/version отдаёт эту метку и время старта. Меняем при каждом
# изменении bot.py — тогда любой спор о том, дошёл ли код до прода, решается одним запросом.
СБОРКА = 'b1255-vremya-v-zhurnale-oshibok'
import time as _time_boot
_СТАРТ = _time_boot.time()
from concurrent.futures import ThreadPoolExecutor as _TPE
# отдельный пул ТОЛЬКО под RAG: общий делят все блокирующие операции бота,
# и когда он забит, поиск ждёт в очереди — снаружи это неотличимо от поломки
_RAG_POOL = _TPE(max_workers=2, thread_name_prefix='rag')
# Куда Клоду отвечать. Владелец 27.07.2026: «пиши в джамаат ру ответом на мой последний запрос —
# что чинишь, что пробуешь, пробовать ли снова». Токена у Клода нет и не будет: он зовёт
# /api/claude_notify с секретом, а бот отвечает реплаем вот на это запомненное сообщение.
_ПОСЛ_РАГ = {'chat': None, 'msg': None, 'вопрос': '', 'когда': 0}
# Владелец 27.07.2026: «ты отвечаешь на последнее смс вместо того, к которому я обращался
# изначально». Держим ленту последних вопросов: Клод указывает, на какой отвечает, и реплай
# ложится куда надо, а не на самый свежий.
_ЛЕНТА_РАГ = []          # [{'chat','msg','вопрос','когда'}], хвост — самые новые
# Расход на векторы вопросов. Владелец 27.07.2026: «надо указывать, потрачен ли лимит,
# накоплено ли знание по тегу, какая модель и остаток». Вектор считает Cloudflare (bge-m3),
# это единственное место, где «раг» тратит внешний лимит. Одинаковый вопрос второй раз
# берётся из кэша и НЕ стоит ничего — это и есть накопленное знание.
_ВЕК_КЭШ = {}                                   # вопрос(норм) -> вектор
_ВЕК_СЧЁТ = {'новых': 0, 'из_кэша': 0, 'сбоев': 0}
# Счётчик подавленных уведомлений (#639/#640/#642 — сводки «смена доступности API»).
# Не молчим втихую: сколько их погашено, видно в /api/version — иначе «отключил» неотличимо
# от «сломалось», а это тот самый класс беды, из-за которого заводятся лишние заявки.
_ПОДАВЛЕНО = {}
СПРАВКА_РАГ = ('🧠 <b>Как пользоваться РАГ</b>\n\n<b>Что это.</b> Поиск ПО СМЫСЛУ, а не по словам: спрашиваешь своими словами, находит хадисы, где слов вопроса может не быть вовсе.\n\n<b>Как звать.</b>\n• <code>раг что делать при затмении</code> — по всей размеченной базе\n• <code>раг бухари ...</code> — только по Сахих аль-Бухари\n\n<b>Что уже размечено.</b> Пока ТОЛЬКО Сахих аль-Бухари — 14 344 фрагмента. Остальные сборники ждут разметки, по ним смысловой поиск не работает.\n\n<b>Про лимит.</b> Каждый НОВЫЙ вопрос требует вектора — его считает Cloudflare (модель bge-m3), это единственная трата. Повторный такой же вопрос берётся из накопленного и не стоит ничего. Строка ⚙️ под ответом всегда показывает, потрачен лимит или взято из накопленного.\n\n<b>Ссылки.</b> «📖 Сахих аль-Бухари №N» открывает мини-апп прямо на этом хадисе.\n\n<b>Замечание.</b> Ответь реплаем на ответ бота любым текстом — «не то», «упустил №1234», «запрос понял неверно» — и это ляжет в журнал РАГ. Простое поправим сразу, хлопотное — в доработку.')
import io          # 🔴 06.08: отправка файла из памяти (io.BytesIO) падала «name 'io' is not
                   # defined» — модуль использовался, а импорта не было. Ошибка тихая: она
                   # выстрелила только когда помощник впервые попробовал отдать файл.
import os
import asyncio
import re
import random
import json
import base64
import hmac
import hashlib
import time
import threading
import collections
import subprocess
import shutil
import difflib
import requests
from datetime import datetime, timedelta
import html                      # 27.07.2026: был только `from html import unescape` — при этом
from html import unescape        # html.escape в ответе «раг» падал с NameError. ТРЕТИЙ случай
                                 # одного класса за два дня (math.sqrt, loop, html): имя используется,
                                 # а в области видимости его нет. Ловится статически — см. imya_storozh.py
import urllib.request           # 27.07.2026: сторож имён нашёл ЧЕТВЁРТЫЙ случай того же класса —
from urllib.parse import parse_qsl   # в /api/qaudio зовётся urllib.request, а импортирован был
                                     # только urllib.parse. Аудио Корана упало бы с NameError.
                                     # Найдено ДО жалобы владельца — ради этого сторож и писался.
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import CallbackQueryHandler, ApplicationBuilder, MessageHandler, filters, ContextTypes, ChatMemberHandler, CommandHandler, PollAnswerHandler, MessageReactionHandler

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
        # #537 (владелец из @jamaat_ru: «проверь эту функцию, он ничего не находит никогда»).
        # sunnah.one ищет строгим И: все слова обязаны встретиться в ОДНОМ матне. ИИ отдаёт 4-7 ключевых слов,
        # поэтому пересечение почти всегда пустое (замер: 7 слов -> 0, 5 -> 0, 3 -> 0, 2 -> 87). Источник ЖИВОЙ.
        # Лечим лесенкой: полный запрос -> 3 слова -> 2 -> 1, останавливаемся на первой непустой выдаче.
        _w = [w for w in str(query or "").split() if w]
        _steps, _seen_n = [], set()
        for _n in (len(_w), 3, 2, 1):
            if 1 <= _n <= len(_w) and _n not in _seen_n:
                _seen_n.add(_n); _steps.append(_n)
        if not _steps:
            _steps = [0]
        d = None
        for _i, _n in enumerate(_steps):
            _q = " ".join(_w[:_n]) if _n else str(query or "")
            url = "https://search.sunnah.one/?action=search&ver=2&q=" + requests.utils.quote(_q)
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=(20 if _i == 0 else 10))
            if r.status_code != 200:
                return 0, []
            d = r.json()
            if d.get("data"):
                break
        if d is None:
            return 0, []
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

# ===== #324 («А'зоми 1»): «<название книги из каталога Мактабы> <номер>» → deep-link кнопка в мини-апп =====
# Книги ВНЕ 8 канона (и вне SOURCE_TRIGGERS) резолвим по каталогу Мактабы (docs/catalog.json, ~8.6к книг,
# i = turath id для токена b_<id>_<стр>). Название владелец пишет русской транслитерацией («азоми») —
# арабские названия/авторов транслитерируем в русский скелет и матчим difflib'ом (top-3 кандидата кнопками).
_AR2RU_MAP = {
    "ا": "а", "أ": "а", "إ": "и", "آ": "а", "ى": "а", "ء": "", "ئ": "", "ؤ": "у",
    "ب": "б", "ت": "т", "ة": "а", "ث": "с", "ج": "дж", "ح": "х", "خ": "х",
    "د": "д", "ذ": "з", "ر": "р", "ز": "з", "س": "с", "ش": "ш", "ص": "с",
    "ض": "д", "ط": "т", "ظ": "з", "ع": "", "غ": "г", "ف": "ф", "ق": "к",
    "ك": "к", "ل": "л", "م": "м", "ن": "н", "ه": "х", "و": "у", "ي": "и",
}
def _ar2ru_translit(w):
    """Арабское слово → русский транслит-скелет (без огласовок и артикля): الأعظمي → «азми»."""
    w = re.sub(r"[ً-ْٰـ]", "", w or "")   # огласовки/татвиль
    w = re.sub(r"^(وال|بال|فال|كال|لل|ال)", "", w)             # артикль/приставки
    return "".join(_AR2RU_MAP.get(ch, "") for ch in w)

_CATALOG_RU_CACHE = {"items": None, "ts": 0}
def _load_catalog_ru():
    """Каталог Мактабы + транслит-слова названия/автора. Кэш на процесс (6 ч), raw.githubusercontent (не Pages — тот отстаёт)."""
    import time as _t
    if _CATALOG_RU_CACHE["items"] is not None and (_t.time() - _CATALOG_RU_CACHE["ts"]) < 6 * 3600:
        return _CATALOG_RU_CACHE["items"]
    try:
        cat = requests.get("https://raw.githubusercontent.com/germanyalfurqan-eng/hadith-bot/main/docs/catalog.json",
                           timeout=25).json()
        items = []
        for b in cat:
            words = set()
            for fld in (b.get("n", ""), b.get("a", "")):
                for w in str(fld).split():
                    rw = _ar2ru_translit(w)
                    if len(rw) >= 3:
                        words.add(rw)
            if words:
                items.append((int(b.get("i") or 0), b.get("n", ""), b.get("a", ""), tuple(words)))
        _CATALOG_RU_CACHE.update({"items": items, "ts": _t.time()})
    except Exception:
        pass
    return _CATALOG_RU_CACHE["items"]

# частые слова, которые НЕ название книги — не гонять по ним фуззи-матч (ловили бы «коран 2», «страница 5»)
_CAT_STOPWORDS = {"коран", "сура", "аят", "хадис", "книга", "глава", "страница", "стр", "том", "заявка",
                  "замечание", "случайный", "передатчик", "тафсир", "корень", "мухаймин", "мухэймин", "муршид"}
def _catalog_match(name_ru):
    """Русское название → top-3 кандидата из каталога: [(score, turath_id, name_ar, author_ar)]."""
    import difflib
    qws = []
    for w in re.split(r"[\s]+", (name_ru or "").lower()):
        w = w.strip("'`ʼ’«»\"-").replace("ъ", "").replace("'", "").replace("ʼ", "").replace("’", "").replace("`", "").replace("ь", "").replace("ё", "е")
        if len(w) < 3 or w in _CAT_STOPWORDS:
            continue
        # артикль (аль-/ас-/аз-…) — как ВАРИАНТ, не безусловная срезка: иначе «азоми» калечился в «оми»
        variants = {w, w.replace("-", "")}
        _mart = re.match(r"^(аль|ал|ас|аш|ад|ат|ан|аз|ар)-?(.{3,})$", w)
        if _mart:
            variants.add(_mart.group(2))
        qws.append(variants)
    if not qws:
        return []
    items = _load_catalog_ru()
    if not items:
        return []
    scored = []
    for bid, nm, au, words in items:
        tot = 0.0
        for qvars in qws:
            best = 0.0
            for q in qvars:
                for rw in words:
                    if abs(len(rw) - len(q)) > 3:
                        continue
                    r = difflib.SequenceMatcher(None, q, rw).ratio()   # слова короткие — autojunk тут не мешает
                    if r > best:
                        best = r
            tot += best
        sc = tot / len(qws)
        if sc >= 0.66:
            scored.append((sc, bid, nm, au))
    scored.sort(key=lambda x: -x[0])
    return scored[:3]

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
# 🔴 Слово владельца 02.08.2026: «дипсик теперь вышел новый флэш, именно поэтому все задачи
# по умолчанию пока на ФЛЭШ делай, а не про», «установи в приложение дипсик именно флаш чтобы
# выбирало, а не про, при ВСЕХ функциях нейросети».
# Было `deepseek-chat` — прежнее поколение. Официальный выпуск DeepSeek-V4-Flash-0731 (31.07.2026)
# сильнее прежнего на агентских задачах и заметно дешевле линейки Pro, а нам важны оба довода:
# у бота платный ключ с ограниченным остатком, и каждый лишний цент виден в журнале трат.
# Переменной окружения по-прежнему можно перебить — но по умолчанию теперь Flash.
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
# ═══════════════════════════════════════════════════════════════════════════════════════
#  🟩 DSOC — прямой разговор с DeepSeek через платную подписку OpenCode Go. 05.08.2026.
# ═══════════════════════════════════════════════════════════════════════════════════════
# Заявка владельца: «сделай мне, чтобы я в jamaat_ru мог напрямую апи опенкод пользоваться
# дипсиком. Обращение пусть будет DSOC. Например: DSOC переведи — и он переводит. Контекст
# пусть по умолчанию берёт из переписки в чате, набирая до миллиона, потом автоматом сжимая.
# И пиши расходы: токены входные, выходные, скорость, время на ответ, лимиты и остаток».
#
# ПОЧЕМУ НАПРЯМУЮ, А НЕ ЧЕРЕЗ НАШ РОУТЕР. Бот живёт на Railway, в облаке. Роутер стоит на
# домашнем компьютере по адресу 127.0.0.1 — из облака туда хода нет. Поэтому здесь свой,
# прямой вызов OpenCode, и ключ должен лежать в переменных Railway.
#
# АДРЕС ДОБЫТ ЖИВЬЁМ 05.08.2026: документация зовёт на /zen/v1, но там ДРУГОЙ кошелёк (Zen,
# оплата по факту) и вечное «Insufficient balance». Подписка Go живёт на /zen/go/v1 — это
# выяснилось из файла авторизации самого приложения OpenCode, а не из бумаг.
OPENCODE_KEY = os.environ.get("OPENCODE_ZEN_API_KEY", "") or os.environ.get("OPENCODE_API_KEY", "")
OPENCODE_URL = "https://opencode.ai/zen/go/v1/chat/completions"
OPENCODE_MODEL = os.environ.get("OPENCODE_MODEL", "deepseek-v4-flash")
# Настоящие потолки — сервер назвал их САМ в ответе на заведомый перебор:
#   «maximum context length is 1048576 tokens» · «valid range of max_tokens is [1, 393216]»
DSOC_ОКНО = 1_048_576
DSOC_ВЫВОД_МАКС = 393_216
DSOC_СЖИМАТЬ_ОТ = 900_000        # набрали столько — ужимаем историю, не дожидаясь отказа
# Цены OpenCode ($/1М): вход, выход, кэшированное чтение. У долгой переписки кэш — 95% входа,
# и без этой поправки расход завышается в полсотни раз.
DSOC_ЦЕНА = (0.14, 0.28, 0.0028)
DSOC_ЛИМИТЫ = [("5ч", 5 * 3600, 12.0), ("неделя", 7 * 86400, 30.0), ("месяц", 30 * 86400, 60.0)]

# GPT (OpenAI) для особых задач. Читаем под несколькими именами — чтобы сработало как ни назвал переменную на Railway.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("GPT_API_KEY") or os.environ.get("OPENAI_KEY") or os.environ.get("CHATGPT_API_KEY") or ""
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
# Google Gemini (бесплатный лимит) — запасной/основной мотор для особых задач, если у OpenAI нет денег
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")   # актуальная бесплатная модель (1.5-flash устаревает)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")   # 🆓 Groq — бесплатный, очень быстрый (указ владельца: первым). Ключ в Railway env.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
# 🆓 GitHub Models (GPT-4o и др. бесплатно для разработчиков). Токен с правом Models. Фолбэк на GITHUB_TOKEN.
GITHUB_MODELS_TOKEN = os.environ.get("GITHUB_MODELS_TOKEN", "") or GITHUB_TOKEN
# 🆓 NVIDIA NIM (build.nvidia.com) — бесплатный тир, добавлен владельцем 05.07.2026 в Railway (аккаунт "germany", ОТДЕЛЬНЫЙ от Хермеса).
NVIDIA_NIM_API_KEY = os.environ.get("NVIDIA_NIM_API_KEY") or os.environ.get("NVIDIANIM_API_KEY") or ""   # владелец назвал переменную в Railway БЕЗ подчёркивания (NVIDIANIM_API_KEY) — читаем оба варианта
NVIDIA_NIM_MODEL = os.environ.get("NVIDIA_NIM_MODEL", "meta/llama-3.1-70b-instruct")
GITHUB_MODELS_MODEL = os.environ.get("GITHUB_MODELS_MODEL", "openai/gpt-4o-mini")
# 🆓 #573 (владелец: «я сказал: API перед дипсиком, там 12 API или больше»): ещё две бесплатные ступени
# ПЕРЕД платным DeepSeek. Ключей может не быть в env — тогда ступень просто пропускается.
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = os.environ.get("CEREBRAS_MODEL", "llama-3.3-70b")
SAMBANOVA_API_KEY = os.environ.get("SAMBANOVA_API_KEY", "")
SAMBANOVA_MODEL = os.environ.get("SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct")
BACKUP_SECRET = os.environ.get("BACKUP_SECRET", "")   # #259/#261: общий секрет для приёма локального бэкапа (ps1 -> /api/backup_push -> журнал/ЛС)
OWNER_ID = 131827895
OWNER_CHANNEL_ID = -1001660979432
LOG_CHAT_ID = -1003480426073
GITHUB_REPO = "germanyalfurqan-eng/hadith-bot"
ANNOUNCE_CHAT_ID = -1003982210885
APP_CHANNEL_ID = -1003989206932   # @muslimoonapp — публичный канал приложения (обновления для подписчиков)

# 🌩 ГЕРМЕС-ОБЛАКО (13.07.2026, закон одной личности «ПК/телега/облако — один Гермес»):
# ПК выключен (пульс /api/hermes_hb молчит >13 мин) → Railway САМ поллит Хермес-бота и отвечает
# владельцу как полноценный Гермес: душа+память тянутся из ветки data (hermes/), мозг = ask_ai
# (бесплатная цепь Groq→Gemini→GitHub→NIM→OpenRouter). ПК ожил → релей мгновенно отходит в сторону
# (страховка: getUpdates возвращает 409, пока поллит ПК — двойных ответов не будет).
HERMES_BOT_TOKEN = os.environ.get("HERMES_BOT_TOKEN", "")   # токен Хермес-бота (добавить в env Railway!)
HERMES_OWNER_CHAT = int(os.environ.get("HERMES_OWNER_CHAT", "131827895"))
_hermes_hb = {"ts": 0.0}
_HERMES_DATA_RAW = f"https://raw.githubusercontent.com/{GITHUB_REPO}/data/hermes/"

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

def transcribe_audio(path):
    """Расшифровка речи (OpenAI Whisper, ключ OPENAI_API_KEY на Railway). Возвращает текст или None.
    Поддерживает ru/ar и др. Whisper принимает ogg/oga/mp3/m4a/wav до ~25 МБ."""
    if not OPENAI_API_KEY:
        return None
    try:
        with open(path, "rb") as fh:
            r = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": "Bearer " + OPENAI_API_KEY},
                files={"file": (os.path.basename(path) or "audio.ogg", fh, "application/octet-stream")},
                data={"model": "whisper-1"},
                timeout=300)
        if r.status_code == 200:
            return (r.json() or {}).get("text", "").strip()
        print("whisper error:", r.status_code, r.text[:200])
        return None
    except Exception as e:
        print(f"transcribe error: {e}")
        return None

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
    _tc = re.sub(r"^аль[\s\-]+", "", text)
    for ru, en in COLLECTIONS.items():
        for _t in (text, _tc):
            if _t.startswith(ru):
                num = _t.replace(ru, "", 1).strip()
                if num.isdigit(): return en, int(num)
            if _t.endswith(" " + ru):
                num = _t[:-len(ru)].strip()
                if num.isdigit(): return en, int(num)
    # #448: то же для Мухаймина: «145 мухаймин»
    for trigger in ("мухэймин", "мухаймин", "муршид"):
        if text.endswith(" " + trigger):
            num = text[:-len(trigger)].strip()
            if num.isdigit(): return "riwayat", int(num)
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


# ═══════════════════════════════════════════════════════════════════════════════════════
#  🟩 DSOC: разбор обращения, память разговора, расход
# ═══════════════════════════════════════════════════════════════════════════════════════
DSOC_ПАМЯТЬ = {}          # chat_id → список реплик [{role, content}]
DSOC_ЗАЯВКА_ЖДЁТ = {}     # chat_id → предложение, ждущее «да» от владельца
def dsoc_чистые(реплики):
    """Модели уходит только role и content: служебные метки — наше дело, не её."""
    return [{"role": р.get("role"), "content": р.get("content")} for р in (реплики or [])]


def dsoc_когда_отвечал(chat_id):
    """Когда помощник отвечал в этом чате в последний раз.

    🔴 Метка живёт ВНУТРИ переписки, а не в отдельном словаре в памяти процесса. Прежний
    вариант обнулялся каждой выкаткой, и через минуту после деплоя бот уже не помнил, что
    разговор идёт с помощником, — реплику подхватывал старый путь на Groq. Третий случай
    одного класса за час; чиню класс: метка едет вместе с тем, к чему относится."""
    try:
        for р in reversed(dsoc_память(chat_id) or []):
            if р.get("role") == "assistant" and р.get("t"):
                return float(р["t"])
    except Exception:
        pass
    return 0
DSOC_РАСХОД = []          # (когда, стоимость) — для остатка лимитов
DSOC_ФАЙЛ = "dsoc_context.json"


def parse_dsoc(text):
    """«DSOC переведи» → «переведи». Не к нему обращаются → None.

    Пишется как угодно: DSOC, dsoc, ДСОС — владелец печатает быстро и с телефона,
    придираться к регистру и раскладке значит ломать ему работу на ровном месте.
    """
    t = (text or "").strip()
    for p in ("dsoc", "дсос", "дсок"):
        н = t.lower()
        if н.startswith(p):
            хвост = t[len(p):].lstrip(" ,:—-")
            return хвост.strip()
    return None


def dsoc_память(chat_id):
    """Память разговора. 🔴 05.08.2026: лежала в файле на диске контейнера Railway, а он
    стирается КАЖДЫМ деплоем — и разговор молча начинался заново. Владелец увидел это как
    «контекст был 4282, стал меньше — куда исчез?». Не исчез: его стёрли выкаткой.
    Тот же класс, что и у счётчика трат (Н-176), — и я тогда починил частный случай вместо
    класса. Теперь память в ветке data: деплой ей не страшен."""
    if chat_id not in DSOC_ПАМЯТЬ:
        вся = None
        try:
            вся = _data_get(DSOC_ФАЙЛ, None)
        except Exception:
            вся = None
        if вся is None:                       # запасной путь: старый локальный файл
            try:
                вся = json.load(open(DSOC_ФАЙЛ, encoding="utf-8"))
            except Exception:
                вся = {}
        DSOC_ПАМЯТЬ[chat_id] = (вся or {}).get(str(chat_id), [])
    return DSOC_ПАМЯТЬ[chat_id]


_ДСОС_ПАМ_ГРЯЗНО = [0, 0.0]


def dsoc_сохранить(силой=False):
    """Пишем пачкой: запись в ветку — коммит, и делать его на каждое сообщение незачем.
    Но первую запись после старта — сразу, иначе короткая жизнь процесса всё потеряет."""
    # 🔴 05.08.2026: писал пачкой — раз в три сообщения. В обычный день это разумно, а
    # сегодня деплои идут каждые пять минут, и каждый уносил незаписанный хвост разговора.
    # Владелец: «пять минут назад обсуждали, а ты не помнишь». Пишем СРАЗУ: лишний коммит
    # дешевле потерянного разговора.
    _ДСОС_ПАМ_ГРЯЗНО[0] += 1
    try:
        _data_put(DSOC_ФАЙЛ, {str(k): v[-120:] for k, v in DSOC_ПАМЯТЬ.items()},
                  "память разговоров DSOC")
        _ДСОС_ПАМ_ГРЯЗНО[0] = 0
        _ДСОС_ПАМ_ГРЯЗНО[1] = time.time()
    except Exception:
        pass


def dsoc_размер(реплики):
    """Грубая, но честная оценка в токенах: для русского с арабским ≈ 3 знака на токен."""
    return sum(len(r.get("content") or "") for r in реплики) // 3


def dsoc_ужать(реплики):
    """Разговор дорос до потолка — ужимаем СЕРЕДИНУ, а не хвост.

    Начало держит уговор о том, как работать; конец — то, о чём говорим сейчас. Резать надо
    середину: там пересказ уже случившегося, и его не жалко свернуть в краткую выжимку.
    """
    if len(реплики) < 12:
        return реплики
    голова, хвост = реплики[:4], реплики[-8:]
    середина = реплики[4:-8]
    свод = " · ".join((r.get("content") or "")[:120] for r in середина[-40:])
    return голова + [{"role": "system",
                      "content": "Кратко о том, что обсуждалось раньше: " + свод[:6000]}] + хвост


def dsoc_стоимость(вх, вых):
    цв, цо, цк = DSOC_ЦЕНА
    return round((вх * 0.05 * цв + вх * 0.95 * цк + вых * цо) / 1e6, 6)


# ───────────────────────────────────────────────────────────────────────────────────────
#  DSOC как проводник по командам. Заявка владельца 05.08.2026:
#  «во всех этих командах не тяжело запутаться… пусть он сам квалифицирует, что мне надо,
#   и подбирает ближайшее из того, что у нас есть; а если нет — перекидывает в журнал
#   предложений DSOC. И мои данные, имена, адреса, пути к папкам — сохранность».
#
#  ПОЧЕМУ ПРЕДЛАГАЕТ, А НЕ ВЫПОЛНЯЕТ САМ. Ошибиться в распознавании — дело обычное, а среди
#  команд есть «очисти память» и «заявка done». Промахнувшийся угадыватель, который сразу
#  жмёт кнопку, опаснее отсутствия угадывателя вовсе. Поэтому: безобидное делает, опасное
#  называет и ждёт подтверждения.
DSOC_КОМАНДЫ = [
    ("найди хадис <текст/номер>", "ищет хадис в наших 41 первоисточнике", "безопасно"),
    ("(просто пришли голосовое)", "расшифрую речь и найду оригинал хадиса в нашей базе", "безопасно"),
    ("DSOC голосом <вопрос>", "отвечу не текстом, а голосовым сообщением", "безопасно"),
    ("DSOC что на полке?", "покажу оглавление полки знаний в рабочем журнале", "безопасно"),
    ("DSOC убери это из контекста", "ответом на сообщение — выкину его из памяти разговора", "безопасно"),
    ("DSOC вмешайся в диалог", "ответом на сообщение — восстановлю нить беседы, сверю со сводом правил и дам оценку", "безопасно"),
    ("DSOC пришли файлом <тема>", "соберу справку и пришлю файлом .md, а не простынёй текста", "безопасно"),
    ("DSOC отложи в архив", "длинное уберу в облачный архив владельца, чтобы не засорять чат", "безопасно"),
    ("ботяра <вопрос>", "общий вопрос к ИИ бота", "безопасно"),
    ("переведи", "перевод — ответом на сообщение", "безопасно"),
    ("корень <слово>", "трёхбуквенный корень арабского слова", "безопасно"),
    ("коран <сура:аят>", "аят из Корана", "безопасно"),
    ("карточка <равий>", "карточка передатчика", "безопасно"),
    ("видео", "пересказ ролика по субтитрам — ответом на ссылку", "безопасно"),
    ("раг <вопрос>", "поиск по книгам через RAG", "безопасно"),
    ("память", "показать, что бот помнит", "безопасно"),
    ("запомни: <текст>", "записать в память бота", "безопасно"),
    ("заявка <текст>", "записать заявку владельца", "безопасно"),
    ("анонс", "опубликовать обновление в канал @muslimoonapp", "спросить"),
    ("заявка done <N>", "закрыть заявку", "спросить"),
    ("очисти память", "стереть ВСЮ память бота", "спросить"),
]
DSOC_ЖУРНАЛ_ПРЕДЛОЖЕНИЙ = "dsoc_predlozheniya.jsonl"

# Что НЕ должно уходить в облако ни под каким видом (закон о персданных).
_DSOC_ПРЯТАТЬ = [
    (re.compile(r'[A-Za-z]:\\[^\s"\']+'), '<путь>'),          # пути к папкам на диске
    (re.compile(r'/(?:home|Users)/[^\s"\']+'), '<путь>'),
    (re.compile(r'\b\+?7\d{10}\b|\b8\d{10}\b'), '<телефон>'),
    (re.compile(r'\b[\w.\-]+@[\w\-]+\.[A-Za-z]{2,}\b'), '<почта>'),
    (re.compile(r'\bsk-[A-Za-z0-9]{16,}\b'), '<ключ>'),
    (re.compile(r'\b\d{9,12}\b'), '<номер>'),                 # телеграм-id и подобное
]


def dsoc_обезличить(текст):
    """Убрать личное ДО отправки в облако. Владелец: «мои данные, имена, адреса, пути — сохранность».

    Прячем не «на всякий случай», а то, что нельзя вернуть назад: путь к его папкам, телефон,
    почту, ключи, длинные числовые идентификаторы. Смысл вопроса от этого не страдает — модель
    прекрасно понимает «<путь>» вместо C:\\Users\\… — а утечь уже нечему.
    """
    т = текст or ""
    for рег, замена in _DSOC_ПРЯТАТЬ:
        т = рег.sub(замена, т)
    return т


def dsoc_предложить(текст, что_просил):
    """Записать в федеральный журнал то, чего у нас нет, но владелец захотел."""
    try:
        with open(DSOC_ЖУРНАЛ_ПРЕДЛОЖЕНИЙ, "a", encoding="utf-8") as ф:
            ф.write(json.dumps({"когда": _now_msk(), "просил": (что_просил or "")[:600],
                                "ответ_dsoc": (текст or "")[:600]}, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ───────────────────────────────────────────────────────────────────────────────────────
#  ЧТО DSOC ЗНАЕТ О НАШЕМ ПРИЛОЖЕНИИ. Заявка владельца 05.08.2026: «скорми ему все
#  возможности мини-аппа и каждое обновление из канала… чтобы он мог объяснять каждую кнопку
#  и функцию… секреты пусть хранит, внутреннюю кухню не надо, но всё, что доступно и видят
#  люди, пусть знает».
#
#  ПОЧЕМУ КАРТОЙ, А НЕ ВЫГРУЗКОЙ ФАЙЛА. index.html весит 2,2 МБ — это полмиллиона токенов на
#  каждое сообщение, немыслимо. Да и не нужно: пользователю нужны не строки кода, а что где
#  нажать. Карта — то же знание, ужатое до размера, который не жалко возить всегда.
#
#  ПОЧЕМУ ОБНОВЛЕНИЯ ПОДКЛЕИВАЮТСЯ САМИ. Их и так возит бот в update_notes_queue.json, чтобы
#  постить в канал. Берём оттуда заголовки последних — и карта свежа без единого движения
#  руками. Вышло обновление → оно уже в знаниях DSOC.
МИНИАПП_ЗНАНИЯ = """ЗАЧЕМ ЭТО ПРИЛОЖЕНИЕ. Знание о хадисах веками раздроблено по книгам,
школам и толкам. Цель проекта — собрать его воедино и внести ясность: полную картину
достоверности хадисов, полную картину правил мухаддисов прошлого и полную картину свидетельств
о передатчиках — по ВСЕМ первоисточникам, а не по одной книге. Приложение — окно в эту работу.

ЧТО ТАКОЕ ПЕРВОИСТОЧНИК. Книга, где есть хотя бы один уникальный хадис или хотя бы одна
уникальная его версия. Если аль-Бухари взял хадис у Ибн Аби Шейбы и сборник Ибн Аби Шейбы цел,
в этой части хадис у аль-Бухари не уникален. Таких книг у нас 41.

КНИГА «المهيمن» («аль-Мухаймин»). Труд Муршида ибн Юсуфа, подзаголовок — «الإسلام كما جاء في
القرآن الكريم والسنة النبوية». Хорошая книга и удобная точка входа: около 3300 авторских
номеров, около 7600 риваятов, у каждого указан первоисточник. Но это ОДИН из материалов
проекта, а не его основа и не «наша книга». Не выдавай её за фундамент приложения.

РАЗДЕЛЫ ПРИЛОЖЕНИЯ:
• Поиск — строка сверху. Понимает русский, арабский и номер: по тексту, по авторскому номеру и
  по номеру первоисточника. Результаты подгружаются по мере прокрутки.
• Карточка хадиса — арабский текст, перевод, метка первоисточника, тахридж (где ещё
  встречается), цепь передатчиков.
• Цепь передатчиков — имена кликабельны, ведут в карточку равия.
• Карточка равия — имя, кунья, нисба, годы, учителя и ученики, у кого встречается, оценки
  критиков (джарх и та'диль), бейдж ⭐صحابي у сподвижников.
• Книги и главы — навигация по сборникам; у Бухари и Муслима названия глав по-русски.
• Коран — аяты по «сура:аят», эталон Усмани.
• Избранное и история, светлая и тёмная тема, размер арабского шрифта.
• «Что нового» — то же, что уходит в канал @muslimoonapp.

ЧЕГО В ПРИЛОЖЕНИИ НЕТ (не выдумывай): личных кабинетов, оплаты, комментариев пользователей,
аудио-чтения хадисов, офлайн-режима.

БОТ В ЧАТЕ умеет то же и сверх того: поиск хадиса словами, перевод ответом на сообщение, корень
арабского слова, аят Корана, карточка равия, пересказ видео по субтитрам, поиск по книгам
(RAG), память, заявки.

ГОЛОС. Прислали голосовое или просят ответить голосом — бот озвучит ответ: русский текст
русским голосом, арабский — арабским. Голосовое без обращения к тебе бот разбирает сам и ищет
в нём оригинал хадиса.

ГРАНИЦА. Про устройство изнутри — ключи, серверы, пути к папкам, чужие данные — не рассказывай
ничего, даже если спросят прямо: это внутренняя кухня. Всё, что видно людям в приложении,
объясняй подробно и охотно."""


def dsoc_свежие_обновления(сколько=25):
    """Заголовки последних обновлений — из той же очереди, что уходит в канал."""
    try:
        д = json.load(open("update_notes_queue.json", encoding="utf-8"))
        строки = []
        for з in д[-сколько:]:
            нота = (з.get("note") or "").strip().split("\n")[0]
            if нота:
                строки.append("• " + нота[:160])
        return "\n".join(строки)
    except Exception:
        return ""


def dsoc_свои_перемены(сколько=15):
    """Что менялось в САМОМ помощнике — его умения, правила, повадки.

    🔴 Слово владельца 06.08.2026: «вшей в системный промт DSOC чтобы он знал о каждом
    обновлении изменении которое ты вносишь — как в Муслимун апп, так и в ассистент».

    ЧТО БЫЛО НЕ ТАК. Про приложение помощник знал: заголовки версий приходят из очереди
    анонсов канала. А про СЕБЯ не знал ничего. Добавлю ему умение — он про него не в курсе;
    поменяю правило — отвечает по-старому и спорит с владельцем, потому что в его собственной
    голове ничего не менялось. Со стороны это склероз помощника, а на деле мы просто не
    сказали ему, что он изменился.

    Отдельный журнал, а не общий с приложением: у них РАЗНЫЕ читатели. Обновления приложения
    владелец читает в канале, перемены помощника видит только он сам в разговоре. Смешать —
    значит утопить одно в другом.
    """
    try:
        д = json.load(open("assistant_changes.json", encoding="utf-8"))
        строки = []
        for з in д[-сколько:]:
            что = (з.get("что") or "").strip()
            if что:
                строки.append("• %s — %s" % (з.get("когда", "?"), что[:200]))
        return chr(10).join(строки)
    except Exception:
        return ""


# 41 первоисточник книги — список короткий, а пользы много: без него помощник не понимает,
# что «Абу Дауд» и «Сунан» — это про наши книги, а не вообще.
КНИГИ_БАЗЫ = (
    "Мувattā Малика · Муснад Ибн аль-Мубарака · Муснад ат-Тайалиси · Муснад аш-Шафии · "
    "Муснад аль-Хумайди · Муснад Ибн аль-Джа'да · Мусаннаф Ибн Аби Шайбы · Муснад Исхака · "
    "Муснад Ахмада · Муснад Абд б. Хумайда · Сунан ад-Дарими · Сахих аль-Бухари · "
    "аль-Адаб аль-Муфрад (Бухари) · Сахих Муслим · Сунан Ибн Маджи · Сунан Абу Дауда · "
    "Джами' ат-Тирмизи · аш-Шамаиль (Тирмизи) · Сунан ан-Насаи (Кубра и Сугра) · "
    "Муснад Абу Йа'ла · Сахих Ибн Хузаймы · ат-Таухид · Мустахрадж Абу Авāны · "
    "Сахих Ибн Хиббана и другие — всего 41 (+ Табари)")


def dsoc_в_html(t):
    """Разметка модели → HTML для Telegram. Сперва экранируем, потом размечаем — иначе
    угловые скобки из текста ответа превратятся в сломанные теги."""
    t = (t or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    t = re.sub(r'```[a-zA-Z]*\n(.*?)```', lambda m: '<pre>' + m.group(1) + '</pre>', t, flags=re.S)
    t = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', t)
    t = re.sub(r'\[([^\]]+)\]\((https?://[^)\s]+)\)', r'<a href="\2">\1</a>', t)
    t = re.sub(r'\*\*([^*\n]+)\*\*', r'<b>\1</b>', t)
    t = re.sub(r'(?<![*\w])\*([^*\n]+)\*(?![*\w])', r'<i>\1</i>', t)
    t = re.sub(r'__([^_\n]+)__', r'<u>\1</u>', t)
    t = re.sub(r'^\s*&gt;\s?(.+)$', r'<blockquote>\1</blockquote>', t, flags=re.M)
    return t


def dsoc_запрос(сообщения, потолок=3000):
    """Обычный (не потоковый) заход к модели — нужен для второго круга с данными на руках."""
    try:
        о = requests.post(OPENCODE_URL, timeout=180,
                          headers={"Content-Type": "application/json",
                                   "Authorization": "Bearer " + OPENCODE_KEY},
                          json={"model": OPENCODE_MODEL, "messages": сообщения,
                                "max_tokens": потолок, "temperature": 0.4})
        if о.status_code != 200:
            return None, 0, 0
        j = о.json()
        u = j.get("usage") or {}
        return ((j.get("choices") or [{}])[0].get("message", {}).get("content"),
                u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0)
    except Exception:
        return None, 0, 0


async def dsoc_инструмент(строка):
    """Выполнить «ВЫЗОВ: …» и вернуть НАСТОЯЩИЕ данные из нашей базы (либо None).

    Все инструменты только читают. Ничего не записывают и ничего не публикуют.
    """
    с = (строка or '').strip()
    низ = с.lower()
    try:
        м = re.match(r'^(?:хадис|мухэймин|мухаймин)\s+(\d{1,5})', низ)
        if м:
            н = м.group(1)
            з = get_muhaymin(н)
            if not з:
                return "Хадиса №%s в базе аль-Мухаймина нет." % н
            куски = ["Хадис аль-Мухаймина №%s" % н]
            if з.get("book"):
                куски.append("книга: " + str(з["book"]))
            if з.get("chapter"):
                куски.append("глава: " + str(з["chapter"]))
            for i, р in enumerate((з.get("riwayat") or [])[:4], 1):
                куски.append("Риваят %d: %s" % (i, (р.get("text") or "")[:1200]))
                if р.get("short_ref"):
                    куски.append("  первоисточник: " + str(р["short_ref"]))
                if р.get("sources"):
                    куски.append("  тахридж: " + str(р["sources"])[:400])
            куски.append("Ссылка в приложении: https://t.me/muslimoontt_bot?startapp=h_" + str(н))
            return "\n".join(куски)
        м = re.match(r'^карточк[аиу]\s+(.+)$', с, re.I)
        if м:
            _имя = м.group(1).strip()
            _ответ = await narr_card_reply_text(_имя, '')
            if _ответ and 'не наш' not in (_ответ or '').lower()[:200]:
                return _ответ
            # Не нашлось — раскрываем прозвище САМИ. Знание есть у нас, значит оно должно
            # работать в коде, а не зависеть от того, вспомнит ли модель раскрыть лакаб.
            _полное = ЛАКАБЫ_ПОЛНЫЕ.get(_нормимя(_имя))
            if _полное:
                _вт = await narr_card_reply_text(_полное, '')
                if _вт and 'не наш' not in (_вт or '').lower()[:200]:
                    return ("(нашёл по полному имени: %s — «%s» это его прозвище)\n\n%s"
                            % (_полное, _имя, _вт))
            # И последнее: показать похожих, чтобы человек выбрал сам, а мы не гадали.
            _похожие = похожие_имена(_имя)
            if _похожие:
                return ("Точного совпадения нет. Похожие в нашем указателе:\n" + _похожие
                        + "\nСпроси, кто именно нужен — тёзок путать нельзя.")
            return _ответ or ('В нашем указателе имени «%s» нет.' % _имя)
        м = re.match(r'^(субтитры|караоке|вырезать|тишина)\s+(.+)$', с, re.I)
        if м:
            # Владелец: «обучи его субтитры, караоке, вырезать». Умения живут отдельным модулем
            # (scratch_marathon/media_umeniya.py) — распознавание там ЛОКАЛЬНОЕ (faster-whisper на
            # процессоре): бесплатно, без интернета и без права уносить чужой звук на сторону.
            # ⚠️ В отличие от остальных вызовов, эти ПИШУТ файлы на диск. «Скачать» намеренно НЕ
            # подключено: забирать что-то из интернета помощник может только по прямой просьбе
            # человека, а не по своему решению.
            try:
                _мп = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scratch_marathon')
                if _мп not in sys.path:
                    sys.path.insert(0, _мп)
                import media_umeniya as _МУ
            except Exception as e:
                return 'Медиа-умения недоступны на этом сервере: %s' % str(e)[:150]
            _что, _хвост = м.group(1).lower(), м.group(2).strip()
            try:
                if _что == 'субтитры':
                    _с = await asyncio.get_event_loop().run_in_executor(
                        None, _МУ.субтитры_из_видео, _хвост, 'ru')
                    return '\n'.join('[%.1f–%.1f] %s' % (р['начало'], р['конец'], р['текст'])
                                     for р in (_с or []))
                if _что == 'караоке':
                    return str(await asyncio.get_event_loop().run_in_executor(
                        None, _МУ.видео_с_караоке, _хвост, 'ru'))
                if _что == 'тишина':
                    return ('Пустые места (начало, конец в секундах): %s. Резать ТОЛЬКО после '
                            'подтверждения человека.'
                            % str(await asyncio.get_event_loop().run_in_executor(
                                None, _МУ.найти_тишину, _хвост)))
                _ч = _хвост.split()
                return str(await asyncio.get_event_loop().run_in_executor(
                    None, _МУ.вырезать, _ч[0], _ч[1:]))
            except Exception as e:
                return 'Не вышло (%s): %s' % (_что, str(e)[:200])
        м = re.match(r'^мактаба\s+(.+?)\s+(\d{1,6})\s*$', с, re.I)
        if м:
            # #626: книга ВНЕ наших 41 сборника — берём хадис прямо из Мактабы (8 589 книг).
            try:
                _канд = _catalog_match(м.group(1).strip())
            except Exception:
                _канд = []
            if not _канд:
                return ('Книги «%s» в каталоге Мактабы не нашлось — назови её иначе.'
                        % м.group(1).strip())
            _л, _х = await asyncio.get_event_loop().run_in_executor(
                None, мактаба_хадис, _канд[0][1], м.group(2))
            if not _х:
                return ('Книга «%s» найдена, но хадиса №%s в ней достать не вышло — возможно, '
                        'в этом издании другая нумерация. ВАЖНО: не выдумывай текст, так и '
                        'скажи владельцу.' % (_канд[0][2], м.group(2)))
            return ('%s, №%s (лист %s, библиотека Мактабы — вне наших 41 сборника, оценки '
                    'достоверности по ней у нас нет):\n\n%s' % (_канд[0][2], м.group(2), _л,
                                                                 _х[:2500]))
        м = re.match(r'^смысл\s+(.+)$', с, re.I)
        if м:
            # Смысловой поиск: находит по СМЫСЛУ вопроса, а не по совпадению слов. Заявка
            # владельца #380 — «чтобы как РАГ мог отвечать по всей базе».
            try:
                _нашли = await _rag_query(м.group(1).strip(), n=5)
            except Exception as e:
                return 'Смысловой поиск не отозвался: %s' % str(e)[:150]
            if not _нашли:
                return ('Смысловой поиск ничего не дал. ВАЖНО сказать владельцу: он размечен '
                        'ТОЛЬКО по Сахих аль-Бухари; по остальным сборникам работает лишь поиск '
                        'по точным словам.')
            куски = []
            for з in (_нашли if isinstance(_нашли, list) else [])[:5]:
                if isinstance(з, dict):
                    куски.append('№%s (близость %.2f): %s'
                                 % (з.get('n') or з.get('num') or '?',
                                    float(з.get('score') or з.get('оценка') or 0),
                                    str(з.get('text') or з.get('ar') or '')[:700]))
            return ('Смысловой поиск (только по Сахих аль-Бухари — так и скажи владельцу):\n\n'
                    + '\n\n'.join(куски))
        м = re.match(r'^источник\s+([а-яё\s]+?)\s+(\d{1,6})\s*$', с, re.I)
        if м:
            _сб, _ном = м.group(1).strip(), м.group(2)
            _рез = найти_по_метке(_сб, _ном)
            if _рез:
                return ("Хадис по метке «%s %s» из нашей базы. ЧИТАЙ ИСНАД В САМОМ ТЕКСТЕ: "
                        "нужный передатчик стоит там, гадать по тёзкам не нужно.\n\n%s"
                        % (_сб, _ном, _рез))
            return ("По метке «%s %s» в нашей базе ничего нет. Возможно, этот хадис у автора не "
                    "приведён — так и скажи, не выдумывай." % (_сб, _ном))
        м = re.match(r'^в архив\s+(.+)$', с, re.I)
        if м:
            _тело = м.group(1).strip()
            return "В_АРХИВ|%s" % _тело
        м = re.match(r'^файл\s+(.+)$', с, re.I)
        if м:
            _что = м.group(1).strip()
            _текст = полка_взять(_что)
            if not _текст or 'нет' == _текст[:3].lower():
                return ("Файл собрать не из чего: на полке нет записи «%s». "
                        "Посмотри оглавление вызовом «полка»." % _что)
            return "ФАЙЛ ГОТОВ|%s|%s" % (_что.upper().replace(' ', '_'), _текст)
        if низ.startswith('полка') or низ.startswith('полку'):
            _м = re.sub(r'^полк[ауи]\s*', '', с, flags=re.I).strip()
            return полка_взять(_м or None)
        if низ.startswith('книг'):
            return "41 первоисточник нашей базы: " + КНИГИ_БАЗЫ
        м = re.match(r'^поиск\s+(.+)$', с, re.I)
        if м:
            найдено = найти_в_мухаймине(м.group(1).strip(), лимит=3)
            if not найдено:
                return "По этим словам в базе ничего не нашлось."
            return "\n\n".join("№%s (совпало %.0f%%): %s\nпервоисточник: %s"
                                % (н, д * 100, (р.get("text") or "")[:900],
                                   р.get("short_ref") or "—")
                                for д, н, р in найдено)
    except Exception as e:
        return "Инструмент не отработал: " + str(e)[:200]
    return None


DSOC_ПОЛКА_ФАЙЛ = "dsoc_polka.json"

# 📖 ПОИСК ПО МЕТКЕ ПЕРВОИСТОЧНИКА. Метки в базе арабские: «البخاري ٥٥٩٠». Значит и название
# сборника, и число надо перевести в арабское написание, прежде чем искать.
СБОРНИКИ_АР = {
    'бухари': 'البخاري', 'муслим': 'مسلم', 'абудауд': 'أبو داود', 'абу дауд': 'أبو داود',
    'тирмизи': 'الترمذي', 'насаи': 'النسائي', 'ибнмаджа': 'ابن ماجة', 'ибн маджа': 'ابن ماجة',
    'ахмад': 'أحمد', 'малик': 'مالك', 'дарими': 'الدارمي', 'ибнхиббан': 'ابن حبان',
    'ибнхузайма': 'ابن خزيمة', 'абуявла': 'أبو يعلى', 'ибнабишейба': 'ابن أبي شيبة',
}


def _араб_цифры(н):
    return ''.join('٠١٢٣٤٥٦٧٨٩'[int(с)] if с.isdigit() else с for с in str(н))


def найти_по_метке(сборник, номер):
    """Вернуть риваяты с такой меткой первоисточника — с текстом и иснадом.

    Когда названы сборник и номер, тёзки перестают быть загадкой: нужный человек стоит В ЦЕПИ
    ЭТОГО хадиса. Гадать по списку однофамильцев тут нечего — надо прочитать.
    """
    try:
        get_muhaymin(1)
        баз = _muhaymin_cache or {}
    except Exception:
        return None
    ар = СБОРНИКИ_АР.get((сборник or '').strip().lower())
    цифры = _араб_цифры(номер)
    найдено = []
    for ном, з in (баз or {}).items():
        for р in (з.get('riwayat') or []):
            метка = (р.get('short_ref') or '')
            if цифры in метка and (not ар or ар in метка):
                найдено.append((ном, р, метка))
                if len(найдено) >= 3:
                    break
        if len(найдено) >= 3:
            break
    if not найдено:
        return None
    куски = []
    for ном, р, метка in найдено:
        куски.append('Метка первоисточника: %s (у нас — аль-Мухаймин №%s)\n%s'
                     % (метка, ном, (р.get('text') or '')[:2000]))
        if р.get('sources'):
            куски.append('Тахридж: ' + str(р['sources'])[:400])
    return '\n\n'.join(куски)
DSOC_ВЫГОВОРЫ_ФАЙЛ = "dsoc_vygovory.json"
DSOC_ОЧЕРЕДЬ_ФАЙЛ = "claude_queue.json"
DSOC_СНИМКИ_ФАЙЛ = "dsoc_snapshots.json"
DSOC_НЕУДАЧИ_ФАЙЛ = "dsoc_neudachi.json"
DSOC_ЛЕНТА_ФАЙЛ = "dsoc_lenta.json"
# 📦 ОБЛАЧНЫЙ АРХИВ владельца (адреса из инструкции в Обсидиане, написанной сессией Z Code
# 04.08.2026; бот Муслимун проверен здесь живьём 05.08 — в инструкции значился только HermesTT).
# Файлы приходят в ГРУППУ, оттуда переносятся в КАНАЛ. Сюда уходит всё тяжёлое, чем жалко
# засорять чат джамаата, рабочий журнал и канал приложения.
АРХИВ_ГРУППА = -1002142402317
АРХИВ_КАНАЛ = -1004401930494
ЧАТ_ЛЕНТА = {}            # chat_id → последние сообщения [{i, кто, т}]
_ЛЕНТА_ГРЯЗНО = [0]


def лента_запомнить(update):
    """Короткая лента последних сообщений чата — только текст, только последние 400.

    Telegram не даёт боту читать историю: «пять сообщений до и после» взять неоткуда, если не
    запомнить их заранее. Зато в момент прихода бот сообщение ВИДИТ. Храним скупо: чужую
    переписку целиком держать и лишне, и нечестно, а для окна ±5 короткой ленты довольно.
    """
    try:
        м = update.message
        ч = getattr(update.effective_chat, 'id', None)
        т_ = (getattr(м, 'text', None) or getattr(м, 'caption', None) or '').strip()
        if not ч or not т_ or getattr(update.effective_chat, 'type', '') == 'private':
            return
        л = ЧАТ_ЛЕНТА.setdefault(ч, [])
        л.append({'i': м.message_id,
                  'кто': (getattr(getattr(м, 'from_user', None), 'first_name', '') or '?')[:40],
                  'т': т_[:900]})
        if len(л) > 400:
            del л[:-400]
        _ЛЕНТА_ГРЯЗНО[0] += 1
        if _ЛЕНТА_ГРЯЗНО[0] >= 20:
            _ЛЕНТА_ГРЯЗНО[0] = 0
            _data_put(DSOC_ЛЕНТА_ФАЙЛ, {str(k): v[-200:] for k, v in ЧАТ_ЛЕНТА.items()},
                      'лента чата')
    except Exception:
        pass


def лента_окно(chat_id, msg_id, вокруг=5):
    """Отмеченное сообщение и его соседи. Пусто — значит бот их не застал."""
    try:
        л = ЧАТ_ЛЕНТА.get(chat_id)
        if not л:
            л = (_data_get(DSOC_ЛЕНТА_ФАЙЛ, {}) or {}).get(str(chat_id)) or []
            ЧАТ_ЛЕНТА[chat_id] = list(л)
        поз = next((i for i, з in enumerate(л) if int(з.get('i') or 0) == int(msg_id)), None)
        if поз is None:
            return []
        return л[max(0, поз - вокруг):поз + вокруг + 1]
    except Exception:
        return []

# Мост «прозвище → полное имя». В указателе имён (18 989 записей) прозвищ НЕТ: на «аль-Амаш»
# находится только «Абу Рибъи аль-Амаш» — другой человек, а нужный Сулейман ибн Михран под
# прозвищем не ищется вовсе. Список рабочий, из имён, которые реально стоят в цепях; растёт.
ЛАКАБЫ_ПОЛНЫЕ = {
    "амаш": "Сулейман ибн Михран",
    "шуба": "Шуба ибн аль-Хаджжадж",
    "катада": "Катада ибн Диама",
    "зухри": "Мухаммад ибн Муслим",
    "ибн шихаб": "Мухаммад ибн Муслим",
    "малик": "Малик ибн Анас",
    "саури": "Суфьян ибн Саид",
    "ибн уяйна": "Суфьян ибн Уяйна",
    "ибн джурайдж": "Абдульмалик ибн Абдульазиз",
    "мамар": "Мамар ибн Рашид",
    "аузаи": "Абдуррахман ибн Амр",
    "ибн сирин": "Мухаммад ибн Сирин",
    "хасан басри": "аль-Хасан ибн Аби аль-Хасан",
    "асвад": "аль-Асвад ибн Язид",
    "алькама": "Алькама ибн Кайс",
    "нахаи": "Ибрахим ибн Язид",
    "муджахид": "Муджахид ибн Джабр",
    "ата": "Ата ибн Аби Рабах",
    "тавус": "Тавус ибн Кайсан",
    "урва": "Урва ибн аз-Зубайр",
    "араджь": "Абдуррахман ибн Хурмуз",
    "абу зинад": "Абдуллах ибн Закван",
    "вакиъ": "Вакиъ ибн аль-Джаррах",
    "абдурраззак": "Абдурраззак ибн Хаммам",
    "шарик": "Шарик ибн Абдуллах",
}


def _нормимя(s):
    """Сводим написание к общему виду: «аль-Амаш», «Аъмаш», «al-A'mash» — одно и то же."""
    s = (s or '').lower().strip()
    for м in ('аль-', 'ал-', 'аль ', 'al-', 'ибн аби ', 'абу '):
        if s.startswith(м):
            s = s[len(м):]
    for з in ("'", '’', '`', 'ъ', 'ь', '-', '  '):
        s = s.replace(з, '' if з != '-' else ' ')
    return ' '.join(s.split())


def похожие_имена(запрос, сколько=6):
    """Кандидаты по редкому слову запроса. Пусть человек выберет сам: перепутанный
    передатчик рушит оценку всей цепи, и гадать тут нельзя."""
    try:
        _, _, ru = _load_narr_index()
        if not ru:
            return ''
        слова = [с for с in _нормимя(запрос).split() if len(с) > 3]
        if not слова:
            return ''
        редкое = max(слова, key=len)
        найдено = [(k, v) for k, v in ru.items() if редкое in str(v).lower()]
        if not найдено:
            return ''
        return "\n".join("• %s (id %s)" % (v, k) for k, v in найдено[:сколько])
    except Exception:
        return '' 
# Признаки, по которым ответ считается несостоявшимся. Ловим САМИ, не дожидаясь жалобы:
# неудача, о которой никто не сказал, повторится столько раз, сколько понадобится.
# 🔴 05.08.2026, выговор владельца: помощник ответил «такого у нас пока нет — бот не умеет
# выдавать…», и это НЕ засчиталось неудачей. Признаки ловили «не нашёл» и «не знаю», но
# пропускали самый частый вид отказа — вежливое «у нас такого нет». Отказ есть отказ, как бы
# мягко он ни звучал: человек ушёл без того, за чем пришёл.
DSOC_ПРИЗНАКИ_НЕУДАЧИ = ('не нашёл', 'не нашлось', 'не найдено', 'не могу найти', 'не знаю',
                         'не удалось', 'нет данных', 'ничего не нашлось', 'не смог',
                         'такого у нас пока нет', 'такого у нас нет', 'у нас пока нет',
                         'не умеет', 'не умею', 'нет такой возможности', 'нет возможности',
                         'пока не поддерживается', 'не поддерживается', 'этого нет',
                         'не предусмотрено', 'вручную')


async def dsoc_неудача(bot, chat_id, вопрос, ответ, причина):
    """Записать несостоявшийся ответ: с цитатой запроса и ответа — без контекста разбирать
    нечего. В системный промт НЕ идёт (владелец: «держать в промте не нужно»), но и не
    теряется: нумерованный пост в рабочем журнале плюс кнопка «Разобрать»."""
    try:
        сп = _data_get(DSOC_НЕУДАЧИ_ФАЙЛ, []) or []
        н = (max([int(з.get('n') or 0) for з in сп], default=0) + 1) if сп else 1
        сп.append({'n': н, 'd': _now_msk(), 'чат': chat_id, 'причина': причина[:120],
                   'вопрос': (вопрос or '')[:700], 'ответ': (ответ or '')[:700],
                   'разобрано': False})
        _data_put(DSOC_НЕУДАЧИ_ФАЙЛ, сп[-200:], 'неудача помощника #%d' % н)
    except Exception:
        return None
    try:
        текст = ("🔻 <b>НЕУДАЧА ПОМОЩНИКА №%d</b> · %s\n"
                 "<b>причина:</b> %s\n\n"
                 "<b>спрашивали:</b>\n<blockquote>%s</blockquote>\n"
                 "<b>ответил:</b>\n<blockquote expandable>%s</blockquote>"
                 % (н, _now_msk(), причина[:120],
                    (вопрос or '—')[:500].replace('<', '&lt;'),
                    (ответ or '—')[:900].replace('<', '&lt;')))
        подсказка = ''
        if len([з for з in сп if not з.get('разобрано')]) >= 5:
            подсказка = ("\n\n⚠️ Неразобранных неудач уже %d. Пять однотипных промахов — это не "
                         "случайность, а недостающее знание или кривой инструмент."
                         % len([з for з in сп if not з.get('разобрано')]))
        await bot.send_message(LOG_CHAT_ID, текст + подсказка, parse_mode='HTML',
                               reply_markup=_КЛ([[_КБ("🔎 Разобрать",
                                                      callback_data="neud:%d" % н)]]))
    except Exception:
        pass
    return н
# Слова, которыми владелец зовёт живого разработчика, а не помощника. Список короткий и
# явный: угадывать тут нельзя — «позвать человека» должно срабатывать по прямому слову,
# а не по догадке, иначе половина обычных вопросов уйдёт в очередь и утонет.
DSOC_ЗОВ_КЛОДА = ('клод', 'клоду', 'технадзор', 'технадзору', 'разработчик', 'разработчику')
# 🔴 Признаки, по которым сообщение владельца СРОЧНОЕ, даже если он не назвал меня по имени.
# 05.08.2026: он написал помощнику «здесь ты сильно ошибаешься, иди уточни у технадзора» — и
# до меня это не дошло, потому что мерка была по ФОРМЕ обращения, а надо по ВАЖНОСТИ.
DSOC_ПРИЗНАКИ_СРОЧНОГО = ('ошибаеш', 'ошибка', 'неправ', 'не прав', 'не то', 'мимо',
                          'срочно', 'потребуй', 'уточни', 'почему', 'исправь', 'разберись',
                          'передай', 'не работает', 'не отвеча', 'жду')


def dsoc_позвать_клода(chat_id, msg_id, текст, кто="", важность="срочно", отмечено=None):
    """Положить обращение в очередь технадзора. Клод читает её и отвечает В ТОТ ЖЕ ЧАТ.

    важность: «срочно» — ответ обязателен; «к сведению» — просто чтобы я видел, о чём речь.
    Пока настраиваем, цена пропущенного слова владельца несопоставимо выше цены лишней строки
    в моей ленте."""
    try:
        сп = _data_get(DSOC_ОЧЕРЕДЬ_ФАЙЛ, []) or []
        н = (max([int(з.get('n') or 0) for з in сп], default=0) + 1) if сп else 1
        # Отмеченное сообщение едет ВМЕСТЕ с обращением: показать пальцем и сказать «вот с
        # этим разберись» — обычный человеческий способ, и терять жест значит терять половину
        # смысла. Раньше в очередь шло только «передай технадзору», а на что показывали —
        # пропадало.
        сп.append({'n': н, 'd': _now_msk(), 'чат': chat_id, 'смс': msg_id, 'важность': важность,
                   'текст': (текст or '')[:1500], 'кто': кто[:60], 'взято': False,
                   'отмечено': (отмечено or {})})
        _data_put(DSOC_ОЧЕРЕДЬ_ФАЙЛ, сп[-60:], 'очередь технадзора +#%d' % н)
        return н
    except Exception:
        return None


def dsoc_выговоры_строкой():
    """Свои выговоры помощник держит в голове ВСЕГДА — в отличие от общего журнала проекта.
    Владелец 05.08.2026: «выговоров ассистента в контексте пусть всегда держит системным
    промтом». Смысл ровно такой: выговор, который не перечитываешь, повторяется."""
    try:
        сп = _data_get(DSOC_ВЫГОВОРЫ_ФАЙЛ, []) or []
    except Exception:
        return ""
    if not сп:
        return ""
    return "\n".join("%d. %s" % (з.get("n"), (з.get("t") or "")[:300]) for з in сп[-15:])


def полка_взять(метка=None):
    """Оглавление полки либо одна запись. Читает ветку data — там машинная копия постов
    рабочего журнала (сам журнал бот перечитать не может: истории чата ботам не выдают)."""
    try:
        п = _data_get(DSOC_ПОЛКА_ФАЙЛ, {}) or {}
    except Exception:
        return None
    if not п:
        return "Полка пока пуста."
    if not метка:
        return ("На полке %d записей:\n" % len(п)) + "\n".join(
            "• %s — %s" % (к, (з.get("заголовок") or "")[:90]) for к, з in sorted(п.items()))
    к = метка.strip().upper()
    з = п.get(к) or п.get(метка.strip())
    if not з:
        близкие = [x for x in п if к in x.upper()]
        if len(близкие) == 1:
            з = п[близкие[0]]
        else:
            return "Записи «%s» на полке нет. Есть: %s" % (метка, ", ".join(sorted(п))[:600])
    return "%s — %s\n\n%s" % (к, з.get("заголовок") or "", (з.get("текст") or "")[:7000])


DSOC_ЖУРНАЛ_ПОМОЩНИКА = "dsoc_zayavki.json"


def dsoc_заявка_помощнику(текст, кто=""):
    """Пожелание про САМОГО помощника — в его собственный журнал, а не в общий реестр
    мини-аппа. Владелец развёл их прямо: общий реестр он сепарирует под модернизацию
    приложения, и мешать туда «научи помощника ещё и этому» — значит его засорять."""
    try:
        сп = _data_get(DSOC_ЖУРНАЛ_ПОМОЩНИКА, []) or []
        ид = (max([int(x.get("id") or 0) for x in сп], default=0) + 1) if сп else 1
        сп.append({"id": ид, "d": _now_msk(), "t": (текст or "")[:800], "кто": кто[:60],
                   "done": False})
        _data_put(DSOC_ЖУРНАЛ_ПОМОЩНИКА, сп, "заявка помощнику #%d" % ид)
        return ид
    except Exception:
        return None


DSOC_ПРОМТ_ФАЙЛ = "dsoc_promt.md"


def dsoc_промт_ядро():
    """Неотъемлемый промт помощника — из файла-чистовика, который владелец видит и правит.

    🔴 Приказ владельца 06.08.2026: «мы должны видеть его системный (неотъемлемый) промт»,
    «системный промт должен состоять из нумерованных позиций».

    ПОЧЕМУ ИЗ ФАЙЛА, А НЕ ИЗ КОДА. Пока промт лежал строками внутри bot.py, увидеть его целиком
    можно было только читая код, а поправить — только выкаткой. Правила, по которым живёт
    помощник, оказывались доступны одному мне. Теперь это документ: он лежит в репозитории,
    прикреплён к посту в архиве, и любой может прочитать его целиком за минуту.

    Файла нет — берём запасной, вшитый в код. Помощник без промта опаснее помощника со старым
    промтом: он перестаёт понимать, что ему нельзя выдумывать хадисы.
    """
    try:
        т = open(DSOC_ПРОМТ_ФАЙЛ, encoding="utf-8").read().strip()
        if len(т) > 500:
            return т
    except Exception:
        pass
    return ""


def dsoc_промт_контекстные():
    """Приобретённые правила со статусом «контекст»: полезны, но не системные.

    Разница не формальная. Системное уходит при КАЖДОМ сообщении и не сжимается — там место
    только тому, без чего помощник перестаёт быть собой. Контекстное подставляется тоже, но
    его можно ужать или снять, когда окно кончается. На платном канале окно миллион и разницы
    не видно; на бесплатном запасном — 128К или 12К, и она решает всё.
    """
    try:
        д = json.load(open("dsoc_promt_priobretyonnyy.json", encoding="utf-8"))
        сп = [п for п in (д.get("позиции") or []) if п.get("статус") == "контекст"]
        if not сп:
            return ""
        return ("═══ ПРИОБРЕТЁННЫЕ ПРАВИЛА (утверждены как контекстные) ═══" + chr(10)
                + chr(10).join("• %s" % (п.get("правило") or "") for п in сп))
    except Exception:
        return ""


async def dsoc_глаза(биты, подпись=""):
    """Скриншот → текст. Возвращает описание либо '' — молча, без выдумок.

    Читает ЗРЯЧАЯ модель, а не помощник: помощник текстовый и картинку не увидит никогда.
    Просим не «опиши картинку», а ПЕРЕПИШИ ВСЁ, ЧТО НАПИСАНО: владелец шлёт скриншоты
    интерфейса и переписки, там важен текст до буквы, а не художественный пересказ.
    """
    if not GEMINI_API_KEY:
        return ""
    try:
        _б64 = base64.b64encode(биты).decode()
        _зад = ("Перепиши ВЕСЬ текст с этого изображения дословно, сохраняя порядок строк. "
                "Это скриншот, важна каждая надпись: заголовки, кнопки, сообщения об ошибках, "
                "числа. Ничего не додумывай и не пересказывай своими словами. "
                "После текста добавь строку «ЧТО НА КАРТИНКЕ:» и одно предложение о том, "
                "что это за экран.")
        if подпись:
            _зад += " Человек прислал это с подписью: «%s»." % подпись[:300]
        _тело = {"contents": [{"parts": [{"text": _зад},
                                         {"inline_data": {"mime_type": "image/jpeg", "data": _б64}}]}],
                 "generationConfig": {"maxOutputTokens": 2000, "temperature": 0.1}}
        _url = ("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s"
                % (GEMINI_MODEL, GEMINI_API_KEY))
        _о = await asyncio.get_event_loop().run_in_executor(
            None, lambda: requests.post(_url, json=_тело, timeout=90))
        if _о.status_code != 200:
            return ""
        _j = _о.json()
        return (((_j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [{}])[0].get("text", "").strip()
    except Exception:
        return ""


# Что умеем читать текстом. PDF и DOCX намеренно НЕ здесь: без библиотек их разбор даёт кашу,
# а каша хуже честного «не умею» — по ней помощник ответит уверенно и неверно.
DSOC_ЧИТАЕМЫЕ = ('.txt', '.md', '.json', '.csv', '.log', '.py', '.js', '.html', '.css',
                 '.yml', '.yaml', '.ini', '.xml', '.sql', '.sh', '.cmd', '.ps1')


async def dsoc_руки(файл, имя, макс=60000):
    """Файл → текст. Читаем то, что читается; про остальное говорим прямо."""
    _р = os.path.splitext(имя or "")[1].lower()
    if _р not in DSOC_ЧИТАЕМЫЕ:
        return "(файл «%s» — такой вид я читать не умею; пришли текстом или .txt/.md/.json)" % имя
    try:
        _б = bytes(файл)
        for _к in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                _т = _б.decode(_к)
                break
            except Exception:
                _т = None
        if _т is None:
            return "(файл «%s» не читается: неизвестная кодировка)" % имя
        _хв = ""
        if len(_т) > макс:
            _хв = (chr(10) + chr(10) + "(…файл длиннее, показано первых %d знаков из %d)"
                   % (макс, len(_т)))
            _т = _т[:макс]
        return "=== ФАЙЛ «%s» ===" % имя + chr(10) + _т + _хв
    except Exception as e:
        return "(файл «%s» не прочитался: %s)" % (имя, str(e)[:100])


def dsoc_системный():
    """Собранный промт: чистовик из файла + живые блоки, которых в файле быть не может."""
    ядро = dsoc_промт_ядро()
    if not ядро:
        return dsoc_системный_запасной()
    список = chr(10).join(
        "• %s — %s%s" % (к, о, "" if р == "безопасно" else "  [спросить разрешения]")
        for к, о, р in DSOC_КОМАНДЫ)
    части = [
        ядро, "",
        "═══ ГОТОВЫЕ КОМАНДЫ БОТА (см. позицию С-08) ═══", список, "",
        "═══ ЧТО ТЫ ЗНАЕШЬ О НАШЕМ ПРИЛОЖЕНИИ (позиция С-22) ═══", МИНИАПП_ЗНАНИЯ, "",
        "ПОСЛЕДНИЕ ОБНОВЛЕНИЯ ПРИЛОЖЕНИЯ (позиция С-23; их же видит канал @muslimoonapp):",
        dsoc_свежие_обновления() or "(пока нет)", "",
        "ЧТО МЕНЯЛОСЬ В ТЕБЕ САМОМ (позиция С-24):",
        dsoc_свои_перемены() or "(перемен пока не записано)", "",
        "41 ПЕРВОИСТОЧНИК НАШЕЙ БАЗЫ (позиция С-21): " + КНИГИ_БАЗЫ, "",
    ]
    вг = dsoc_выговоры_строкой()
    if вг:
        части += ["═══ ТВОИ ВЫГОВОРЫ — ПЕРЕЧИТЫВАЙ ПЕРЕД КАЖДЫМ ОТВЕТОМ (позиция С-25) ═══", вг, ""]
    кт = dsoc_промт_контекстные()
    if кт:
        части += [кт, ""]
    return chr(10).join(части)


def dsoc_системный_запасной():
    список = "\n".join("• %s — %s%s" % (к, о, "" if р == "безопасно" else "  [спросить разрешения]")
                       for к, о, р in DSOC_КОМАНДЫ)
    return (
        "Ты — DSOC, помощник владельца в чате джамаата. Отвечай по-русски, по делу, без вступлений.\n\n"
        "У бота есть готовые команды. Владелец их не помнит и не обязан — твоя работа понять, "
        "чего он хочет, и назвать ближайшую:\n" + список + "\n\n"
        "КАК ОТВЕЧАТЬ:\n"
        "1. Если он просит то, что умеет команда — назови её первой строкой так: "
        "«Это делает команда: <команда>» и объясни одним предложением, что она даст. "
        "Если команда помечена [спросить разрешения] — НЕ подталкивай, просто назови и предупреди, "
        "что она необратима.\n"
        "2. Если он просто спрашивает или просит перевести/пересказать — отвечай сам, без команд.\n"
        "3. Если он хочет то, чего у бота НЕТ — так и скажи первой строкой: «Такого у нас пока нет.» "
        "и опиши в двух предложениях, как это могло бы работать. Это уйдёт в журнал предложений.\n\n"
        "НИКОГДА не выдумывай хадисы, аяты и имена передатчиков. Не знаешь — скажи, что не знаешь: "
        "выдуманный хадис хуже отсутствия ответа.\n\n"
        "═══ ЧТО ТЫ ЗНАЕШЬ О НАШЕМ ПРИЛОЖЕНИИ ═══\n" + МИНИАПП_ЗНАНИЯ + "\n\n"
        "ПОСЛЕДНИЕ ОБНОВЛЕНИЯ (их же видит канал @muslimoonapp):\n" +
        (dsoc_свежие_обновления() or "(пока нет)") + "\n\n"
        "ЧТО МЕНЯЛОСЬ В ТЕБЕ САМОМ (умения, правила, повадки — про тебя, не про приложение):\n" +
        (dsoc_свои_перемены() or "(перемен пока не записано)") + "\n"
        "Спросят «что у тебя нового» или «ты это умеешь?» — отвечай по ЭТОМУ списку, а не по "
        "памяти: память у тебя от обучения, а список — от сегодняшнего дня.\n\n"
        "ТОЧКА ОТСЧЁТА. Твоё первое сообщение в чате джамаата — 05.08.2026, 16:50 МСК: "
        "https://t.me/c/1925828112/725324 . С этого мгновения ты живёшь; всё, что было раньше, "
        "происходило без тебя. Спросят «с какого времени ты работаешь» — отвечай этой датой и "
        "этой ссылкой, не гадай.\n\n"
        "═══ ТЫ УМЕЕШЬ ДОСТАВАТЬ ДАННЫЕ САМ ═══\n"
        "Не отправляй человека набирать команду — сходи и принеси. Если для ответа нужны наши "
        "данные, напиши ПЕРВОЙ И ЕДИНСТВЕННОЙ строкой ответа один из вызовов, и всё:\n"
        "ВЫЗОВ: хадис <номер>        — хадис аль-Мухаймина по авторскому номеру\n"
        "ВЫЗОВ: карточка #<номер>    — карточка передатчика по номеру из списка тёзок. Если "
        "в ответ пришёл список «под этим именем несколько разных людей» — у каждого стоит свой "
        "номер и приметы (нисба, год смерти, оценка). ВЫБЕРИ нужного и спроси номером. НЕ "
        "переписывай имя по-другому: в указателе имена ПОЛНЫЕ и РУССКИЕ, нисбы («ас-Садуси», "
        "«аль-Бухари») в нём нет вовсе — по нисбе не найдётся никогда, сколько ни повторяй.\n"
        "ВЫЗОВ: карточка <имя>       — карточка передатчика (данные + ссылки sunnah.com, "
        "Мактаба, Википедия, наше приложение)\n"
        "ВЫЗОВ: поиск <арабские слова> — найти хадис по ТОЧНЫМ словам текста\n"
        "ВЫЗОВ: смысл <вопрос человеческими словами> — найти по СМЫСЛУ, а не по совпадению "
        "слов («что делать при затмении»). ⚠️ Размечен ТОЛЬКО по Сахих аль-Бухари — говори "
        "об этом владельцу прямо, иначе он решит, что искали везде.\n"
        "ВЫЗОВ: источник <сборник> <номер> — хадис по метке первоисточника (например "
        "«источник бухари 5590») ВМЕСТЕ С ИСНАДОМ\n"
        "ВЫЗОВ: субтитры <файл>      — распознать речь и вернуть реплики с таймкодами\n"
        "ВЫЗОВ: караоке <файл>       — то же видео с субтитрами-караоке: слово загорается в свой "
        "момент\n"
        "ВЫЗОВ: тишина <файл>        — показать пустые места; резать ТОЛЬКО после подтверждения "
        "человека\n"
        "ВЫЗОВ: вырезать <файл> 0:10-0:30 … — выбросить названные куски, остальное склеить\n"
        "ВЫЗОВ: мактаба <книга> <номер> — хадис из ЛЮБОЙ книги библиотеки Мактабы (8 589 "
        "книг: Табарани, Байхаки, Хаким и прочие вне наших 41). Оценки достоверности по ним у "
        "нас нет — так и говори.\n"
        "ВЫЗОВ: книги                — список 41 первоисточника\n"
        "ВЫЗОВ: полка                — оглавление полки знаний в рабочем журнале\n"
        "ВЫЗОВ: полка <метка>        — взять с полки нужную запись целиком\n"
        "ВЫЗОВ: файл <метка>         — прислать эту запись человеку ФАЙЛОМ (.md), а не текстом\n"
        "ВЫЗОВ: в архив <текст>      — отложить длинное в облачный архив владельца, чтобы не "
        "засорять разговор. Так поступай с разборами, выгрузками и черновиками длиннее экрана.\n"
        "Бот выполнит вызов и пришлёт тебе настоящие данные — тогда и ответишь по ним. "
        "Ничего не выдумывай в ожидании: сперва вызов, потом ответ.\n"
        "Пример: «найди Мухэймин 35» → ты пишешь ровно «ВЫЗОВ: хадис 35».\n"
        "ТЁЗКИ. Если названы СБОРНИК И НОМЕР — тёзки перестают быть загадкой: нужный человек "
        "стоит В ЦЕПИ ЭТОГО хадиса. Сделай «ВЫЗОВ: источник <сборник> <номер>», прочитай иснад "
        "и назови того, кто там стоит. Показывать владельцу список однофамильцев, когда он уже "
        "дал сборник и номер, — значит переложить на него свою работу.\n\n"
        "КОГДА ВЫЗЫВАТЬ, А КОГДА СПРОСИТЬ. Воля ясна — иди и доставай молча, без «уточните» и "
        "без предложений набрать команду. Просьба двусмысленна (непонятно, какой номер, какая "
        "книга, какой из тёзок) — сперва переспроси одним коротким вопросом, и только потом "
        "вызывай. Переспрашивать по ясному — тратить чужое время; догадываться по "
        "двусмысленному — приносить не то.\n\n"
        + (("═══ ТВОИ ВЫГОВОРЫ — ПЕРЕЧИТЫВАЙ ПЕРЕД КАЖДЫМ ОТВЕТОМ ═══\n"
            "Это ошибки, которые ты уже допускал. Повторить их — хуже, чем совершить впервые.\n"
            + dsoc_выговоры_строкой() + "\n\n") if dsoc_выговоры_строкой() else "") +
        "ЕСЛИ ОШИБСЯ — ПРИЗНАЙ СРАЗУ. Не заминай и не переписывай сказанное молча: назови, в чём "
        "именно ошибся, и дай верное. Тихая правка выглядит так, будто ошибки не было, а её уже "
        "прочитали.\n\n"
        "ПОЛКА ЗНАНИЙ. Всё, что тебе может понадобиться, но незачем держать в голове — "
        "инструкции, разборы, списки, скрипты — лежит на полке в рабочем журнале под метками "
        "вида ПОЛКА-01. Не помнишь подробность — не выдумывай и не извиняйся: посмотри "
        "оглавление «ВЫЗОВ: полка», возьми нужное «ВЫЗОВ: полка ПОЛКА-01». Взял, ответил — и "
        "можешь забыть: полка никуда не денется.\n\n"
        "41 ПЕРВОИСТОЧНИК НАШЕЙ БАЗЫ: " + КНИГИ_БАЗЫ + "\n"
        "«Мухэймин» — наша основная книга «المهيمن» имама Муршида ибн Юсуфа; "
        "у каждого хадиса есть авторский номер, а рядом — метка первоисточника, откуда он "
        "взят.\n\n"
        "═══ КАК ОФОРМЛЯТЬ ═══\n"
        "Пиши красиво и по-человечески: короткий заголовок со строгим значком (📖 🕌 📜 🔎 ⚖️ — "
        "без балагана), **жирным** — главное, *курсивом* — оговорки, арабский текст хадиса — "
        "цитатой через «> », ссылки — [словами](адрес). Разделяй мысли пустой строкой. Не "
        "лепи стену текста и не злоупотребляй списками.\n\n"
        "ИНИЦИАТИВА. Если видишь, что человеку нужна помощь, которой у нас пока нет, или "
        "заметил недоделку — предложи сам, не жди просьбы. ПОСЛЕДНЕЙ строкой ответа напиши "
        "ровно одно из двух:\n"
        "ЗАЯВКА: <что передать технадзору> — если это про САМО ПРИЛОЖЕНИЕ (мини-апп, бот, "
        "данные). Пойдёт в общий реестр модернизации.\n"
        "ПОМОЩНИКУ: <что доработать> — если это про ТЕБЯ САМОГО (чего ты не умеешь, где "
        "ошибся). Пойдёт в отдельный журнал помощника и общий реестр не засорит.\n"
        "Бот покажет предложение и подаст ТОЛЬКО если владелец ответит «да». Сам не подавай и "
        "не обещай, что уже подал. Нечего предлагать — строку не пиши."
    )


# 💵 Кошелёк OpenCode: сколько живых денег внесено. Лимиты подписки говорят «сколько
# можно», кошелёк — «на сколько хватит»; в отчёте нужны обе цифры.
DSOC_КОШЕЛЁК = 5.0
DSOC_ФАЙЛ_ТРАТ = "dsoc_spend.json"
_ДСОС_ГРЯЗНО = [0, 0.0]        # [сколько записей не сброшено, когда сбрасывали в последний раз]


def dsoc_расход_поднять():
    """Поднять журнал трат из ветки data. Вызывается лениво, при первом обращении."""
    if DSOC_РАСХОД:
        return
    try:
        for з in (_data_get(DSOC_ФАЙЛ_ТРАТ, []) or []):
            DSOC_РАСХОД.append((float(з[0]), float(з[1])))
    except Exception:
        pass


def dsoc_расход_записать(цена):
    """Учесть трату и, когда накопится, сбросить журнал в ветку data.

    Сбрасываем пачкой, а не каждую: запись в ветку — это коммит, и стучать в GitHub на каждое
    сообщение незачем. Первую трату после старта пишем сразу — чтобы журнал не потерялся
    целиком, если процесс проживёт недолго.
    """
    dsoc_расход_поднять()
    DSOC_РАСХОД.append((time.time(), цена))
    _ДСОС_ГРЯЗНО[0] += 1
    пора = (_ДСОС_ГРЯЗНО[0] >= 5 or time.time() - _ДСОС_ГРЯЗНО[1] > 300
            or _ДСОС_ГРЯЗНО[1] == 0.0)
    if пора:
        try:
            свежие = [[round(к, 1), round(c, 6)] for к, c in DSOC_РАСХОД
                      if time.time() - к <= 31 * 86400][-4000:]
            _data_put(DSOC_ФАЙЛ_ТРАТ, свежие, "траты DSOC (%d записей)" % len(свежие))
            _ДСОС_ГРЯЗНО[0] = 0
            _ДСОС_ГРЯЗНО[1] = time.time()
        except Exception:
            pass


def dsoc_остаток_строкой():
    dsoc_расход_поднять()
    сейчас = time.time()
    части = []
    for имя, окно, потолок in DSOC_ЛИМИТЫ:
        потрачено = sum(c for к, c in DSOC_РАСХОД if сейчас - к <= окно)
        части.append("%s осталось $%.2f из %.0f" % (имя, max(0.0, потолок - потрачено), потолок))
    всего = sum(c for _, c in DSOC_РАСХОД)
    части.append("💵 кошелёк: потрачено $%.4f из $%.2f, ОСТАЛОСЬ $%.4f"
                 % (всего, DSOC_КОШЕЛЁК, max(0.0, DSOC_КОШЕЛЁК - всего)))
    return " · ".join(части)

# #450 (заявка владельца 02.07.2026, @jamaat_ru): «ботяра дай карточку <равий>» → ссылка на нашу карточку +
# sunnah.com + ИИ-описание СТРОГО ИЗ НАШИХ ДАННЫХ (не общий ИИ-домысел, R37 суверенность). Кэш индекса равиев
# (~19к, 11 МБ) — тянем с Pages (публично, без токена) РАЗ в процесс, не на каждую команду.
# ВАЖНО: name/kunya/nisba в narrators_index.json — ТОЛЬКО арабский, а владелец пишет по-русски → резолвим
# через narr_ru.json (id→рус.транслитерация, 18989 записей, тот же реестр), потом по id берём арабские поля.
_NARR_IDX_CACHE = {"idx": None, "mid2sid": None, "ru": None, "ts": 0}
def _load_narr_index():
    import time as _t
    if _NARR_IDX_CACHE["idx"] is not None and (_t.time() - _NARR_IDX_CACHE["ts"]) < 3600:
        return _NARR_IDX_CACHE["idx"], _NARR_IDX_CACHE["mid2sid"], _NARR_IDX_CACHE["ru"]
    try:
        # raw.githubusercontent, НЕ Pages CDN: проверено (02.07) — Pages может отставать от коммита на десятки
        # минут (narr_ru.json только что закоммичен, germanyalfurqan-eng.github.io всё ещё 404), raw отдаёт
        # содержимое коммита СРАЗУ. Для свежедобавленных файлов это критично, для остальных — тоже безопаснее.
        _RAW = "https://raw.githubusercontent.com/germanyalfurqan-eng/hadith-bot/main/docs/"
        idx = requests.get(_RAW + "narrators_index.json", timeout=15).json()
        m2s = requests.get(_RAW + "mid2sid.json", timeout=15).json()
        ru = requests.get(_RAW + "narr_ru.json", timeout=15).json()
        _NARR_IDX_CACHE.update({"idx": idx, "mid2sid": m2s, "ru": ru, "ts": _t.time()})
        return idx, m2s, ru
    except Exception:
        return _NARR_IDX_CACHE["idx"], _NARR_IDX_CACHE["mid2sid"], _NARR_IDX_CACHE["ru"]

def parse_narr_card_query(text):
    """«дай карточку X» / «карточка X» — X может включать «из Муслима 1007» (справочный контекст, не для резолва)."""
    t = text.strip()
    m = re.match(r'^(?:дай\s+)?карточк[уи]\s+(.+)$', t, re.IGNORECASE)
    if not m: return None
    q = m.group(1).strip()
    ref = ''
    rm = re.search(r'\bиз\s+([а-яё]+\s*\d+)\s*$', q, re.IGNORECASE)
    if rm:
        ref = rm.group(1).strip()
        q = q[:rm.start()].strip()
    return (q, ref) if q else None

def _canon_ru(s):
    return re.sub(r'[^а-яё\s]', '', str(s or '').lower()).strip()

def _word_match(qw, cw):
    """Слово-к-слову с допуском русского падежа (Абдуллах/Абдуллаха/Абдуллахом — окончание меняется,
    корень нет): совпадает точно ИЛИ одно — префикс другого с разницей длины ≤3 символа."""
    if qw == cw: return True
    if len(qw) < 3 or len(cw) < 3: return qw == cw
    a, b = (qw, cw) if len(qw) <= len(cw) else (cw, qw)
    return b.startswith(a) and (len(b) - len(a)) <= 3

def _resolve_narrator_ru(ru, query, filled_by_id=None):
    """Резолв по РУССКОЙ транслитерации (narr_ru.json, id→имя; owner пишет по-русски, база — арабская).
    ⚠️ Известное ограничение (проверено тестами перед деплоем): узнаваемые ШУХРЫ-прозвища одним словом
    («аль-Аъмаш» и т.п.) в этом индексе не всегда есть отдельной записью с primary-именем — только полные
    имена/куньи находятся уверенно. Namesake-safe: ВСЕ слова запроса должны найти пару словом в имени (не
    просто «где-то в строке подстрока» — иначе короткая куня матчится ВНУТРИ чужого длинного составного имени,
    поймано тестом на «абу хатим ар-рази»). В арабских именах РЕАЛЬНО бывает несколько разных людей с ОДИНАКОВЫМ
    именем (не путать с моей ошибкой) — при полном тае используем полноту карточки (filled_by_id) как proxy
    известности/задокументированности (как в самом апп client _narrRow), это НЕ гадание — явный отрыв по данным."""
    if not ru or not query: return None, []
    qn = _canon_ru(query)
    if not qn: return None, []
    qwords = [w for w in qn.split() if w not in ('ибн', 'бин')]
    if not qwords: return None, []
    cands = []
    for rid, full in ru.items():
        for variant in str(full or '').split('/'):
            v = _canon_ru(variant)
            if not v: continue
            cwords = [w for w in v.split() if w not in ('ибн', 'бин')]
            if not cwords:
                continue
            длинный = len(cwords) > len(qwords) + 3   # родословная сильно длиннее запроса
            # УРОК ТЕСТА: «мешок слов» матчил «Анас ибн Малик» и на чужое «Сумама ибн Абдуллах ибн Анас ибн
            # Малик» (правнук — имя ПРЕДКА законно внутри ЕГО СОБСТВЕННОЙ родословной, слова даже подряд) —
            # подпоследовательность одна не спасает. Требуем совпадение С НАЧАЛА имени (старт ≤1 — 1 слово
            # запаса на куню/приставку), а не где-то в середине чужой родословной.
            ci = 0
            start_pos = None
            matched = 0
            ordered = True
            for qw in qwords:
                found = False
                while ci < len(cwords):
                    if _word_match(qw, cwords[ci]):
                        if start_pos is None: start_pos = ci
                        found = True; matched += 1; ci += 1; break
                    ci += 1
                if not found: ordered = False; break
            if ordered and start_pos is not None and start_pos <= 1:
                # 🔴 ЗОВ ВЛАДЕЛЬЦА #49 (06.08.2026). Защита «не матчить внутри сильно более
                # длинного имени» стояла ВЫШЕ этой проверки и рубила кандидата ДО того, как
                # выяснится, с какого слова пошло совпадение. А это решающее различие:
                # start_pos=0 значит, что совпало с ПЕРВОГО слова — это СОБСТВЕННОЕ имя
                # человека, и длина его родословной ни при чём. Так пропадал Катада ибн Диама
                # (id 5183) — самый известный Катада вообще не доходил до отбора, помощник
                # трижды промахнулся и сдался. Защита нужна только при start_pos>0: вот там мы
                # правда рискуем влезть в чужую родословную (Хафс ибн Анас ибн Малик ≠ Анас).
                if длинный and start_pos != 0:
                    continue
                score = 100 if matched == len(qwords) else 60
                fld = (filled_by_id or {}).get(rid, 0)
                cands.append((score, start_pos, fld, rid, full))
                break
    if not cands: return None, []
    # ⚠️ УРОКИ ТЕСТОВ (перед деплоем, два подряд):
    # 1) «короче имя = точнее» — ЛОЖНАЯ эвристика: «Мухаммад ибн Сирин» (id 5657, имя ДЛИННЕЕ — с куней деда)
    #    проиграл короче звучащему тёзке-родственнику «Абдуллах ибн Мухаммад ибн Сирин» (id 12086).
    # 2) start_pos=0 (совпадение С ПЕРВОГО слова кандидата — это ЕГО СОБСТВЕННОЕ имя) СИЛЬНО надёжнее, чем
    #    start_pos=1 (запрос совпал лишь с ИМЕНЕМ ОТЦА внутри чьей-то ещё родословной — «Хафс ибн Анас ибн
    #    Малик» ≠ «Анас ибн Малик», хоть и содержит эти слова). start_pos — ГЛАВНЫЙ критерий после score.
    cands.sort(key=lambda x: (-x[0], x[1], -x[2]))  # score → start_pos (0 лучше) → полнее карточки
    if len(cands) == 1: return cands[0][3], []
    top, second = cands[0], cands[1]
    if top[0] > second[0]: return top[3], []
    if top[1] < second[1]: return top[3], []                # start_pos=0 (своё имя) бьёт start_pos=1 (имя отца в чужой родословной) — решающий сигнал
    if top[2] >= second[2] + 3: return top[3], []            # тот же score/start_pos, но заметно полнее карточка — явный отрыв по документированности (не догадка)
    return None, [(c[3], c[4]) for c in cands[:6]]

async def narr_card_reply_text(query, ref):
    idx, m2s, ru = _load_narr_index()
    if not idx or not ru:
        return "🔧 База передатчиков сейчас недоступна, попробуй позже."
    cols = idx['cols']
    _по_id = {str(row[cols.index('id')]): row for row in idx['data']}
    filled_by_id = {str(row[0]): sum(1 for x in row[2:] if x) for row in idx['data']}
    # Спрос НОМЕРОМ («карточка #5183»). Появился из зова #49: когда в ответ приходил список
    # тёзок, выбрать из него было нечем — оставалось сочинять другое написание имени. Теперь
    # у каждого в списке есть номер, и по нему можно ткнуть прямо, без угадывания.
    _пид = re.match(r'^\s*#\s*(\d{1,6})\s*$|^\s*(?:id|ид|номер)\s*#?\s*(\d{1,6})\s*$',
                    str(query or ''), re.I)
    if _пид:
        _н = _пид.group(1) or _пид.group(2)
        if _н in _по_id:
            rid, ambiguous = _н, []
        else:
            return "🔎 Передатчика с номером #%s в базе нет — проверь номер." % _н
    else:
        rid, ambiguous = _resolve_narrator_ru(ru, query, filled_by_id)
    if not rid and not ambiguous:
        return "🔎 Не нашёл такого передатчика в нашей базе (18 989 равиев). Проверь написание."
    if ambiguous:
        # Раньше здесь был голый список имён — по нему нельзя было ни выбрать, ни отличить
        # одного от другого. Показываем ПРИМЕТЫ (нисба, год смерти, оценка Ибн Хаджара) и
        # НОМЕР: по приметам видно, кто есть кто, по номеру — как его спросить.
        _стр = []
        for _rid, _full in ambiguous:
            _r = _по_id.get(str(_rid))
            _пр = []
            if _r:
                _нис, _см = _r[cols.index('nisba')], _r[cols.index('death')]
                _рх = _r[cols.index('rankHajar')]
                if _нис:
                    _пр.append(str(_нис)[:70])
                if _см:
                    _пр.append('ум. %s г.х.' % _см)
                if _рх:
                    _пр.append(str(_рх)[:40])
            _стр.append((_rid, "• #%s — %s%s" % (_rid, str(_full)[:100],
                                                 (' · ' + ' · '.join(_пр)) if _пр else '')))
        # Порядок показа: сперва те, кого САМ Ибн Хаджар пометил словом «مشهور» (известный), —
        # это слово источника, а не моя догадка; и полнее заполненные. Выбор всё равно за
        # человеком: мы только раскладываем перед ним, а не решаем за него.
        _стр.sort(key=lambda п: (
            0 if 'مشهور' in str((_по_id.get(str(п[0])) or [''] * 9)[cols.index('rankHajar')] or '') else 1,
            -filled_by_id.get(str(п[0]), 0)))
        return ("🤔 Под именем «%s» в базе несколько РАЗНЫХ людей. Вот чем они отличаются:\n%s"
                "\n\nСкажи «карточка #<номер>» — дам карточку именно его. Тёзок не угадываю "
                "(П-05): в иснадах это разные люди, и подмена портит всю цепь."
                % (query, "\n".join(с for _i, с in _стр)))
    best = _по_id.get(str(rid))
    if not best:
        return "🔎 Нашёл в русском указателе, но карточка не найдена в основной базе — сообщи разработчику."
    nm, kunya, nisba, death = best[cols.index('name')], best[cols.index('kunya')], best[cols.index('nisba')], best[cols.index('death')]
    rankH, rankD = best[cols.index('rankHajar')], best[cols.index('rankDhahabi')]
    ru_nm = ru.get(str(rid), nm)
    app_link = "https://t.me/muslimoontt_bot?startapp=n_" + rid
    sid = (m2s or {}).get(rid)
    sunnah_link = f"https://sunnah.com/narrator/{sid}" if sid else None
    # ИИ ТОЛЬКО перефразирует НАШИ данные (R37: не домысливает) — если полей почти нет, обходимся без ИИ вовсе.
    facts = []
    if kunya: facts.append(f"куня: {kunya}")
    if nisba: facts.append(f"нисба: {nisba}")
    if death: facts.append(f"умер: {death} г.х.")
    if rankH: facts.append(f"оценка Ибн Хаджара: {rankH}")
    if rankD: facts.append(f"оценка аз-Захаби: {rankD}")
    desc = ""
    if facts:
        sysm = ("Тебе дан СПИСОК ФАКТОВ о передатчике хадисов из нашей базы. Перескажи их связным текстом "
                "на русском в 2-3 предложениях. СТРОГО ЗАПРЕЩЕНО добавлять любые сведения, которых нет в списке "
                "(даты/оценки/эпоху из общих знаний) — только пересказ данных списка.")
        try:
            desc = await asyncio.get_event_loop().run_in_executor(None, ask_neuro, f"Передатчик: {nm}\nФакты: " + "; ".join(facts), sysm) or ""
        except Exception:
            desc = "; ".join(facts)
    else:
        desc = "(в нашей базе пока нет заполненных дополнительных полей по этому равию — только имя)"
    parts = [f"👤 {ru_nm} — {nm}", desc.strip()]
    if ref: parts.append(f"(контекст запроса: «{ref}» — не проверял, что это именно та цепь, сверь сам)")
    parts.append(f"📱 Карточка в приложении: {app_link}")
    if sunnah_link: parts.append(f"🌐 sunnah.com: {sunnah_link}")
    return "\n".join(p for p in parts if p)

# ВЫГОВОР 02.07.2026 (@jamaat_ru, Orthodox): «Мухэймине есть этот хадис?» — бот дал нерелевантную ссылку,
# приложение-RAG на тот же вопрос выдало первые 4 хадиса Бухари (ГАЛЛЮЦИНАЦИЯ вместо честной проверки).
# Фикс: НАСТОЯЩИЙ поиск по РЕАЛЬНОМУ тексту muhaymin.json (3307 записей, тот же файл, что грузит апп) —
# честное да/нет с номером, БЕЗ ИИ-домысла (R37). ИИ тут вообще не нужен — это точный текстовый поиск.
_MUHAYMIN_CACHE = {"data": None, "ts": 0}
def _load_muhaymin():
    import time as _t
    if _MUHAYMIN_CACHE["data"] is not None and (_t.time() - _MUHAYMIN_CACHE["ts"]) < 3600:
        return _MUHAYMIN_CACHE["data"]
    try:
        data = requests.get("https://raw.githubusercontent.com/germanyalfurqan-eng/hadith-bot/main/docs/muhaymin.json", timeout=20).json()   # raw, не Pages — см. комментарий у _load_narr_index
        _MUHAYMIN_CACHE.update({"data": data, "ts": _t.time()})
        return data
    except Exception:
        return _MUHAYMIN_CACHE["data"]

_AR_DIAC_RE = re.compile(r'[ً-ْٰـ]')
def _canon_ar(s):
    s = _AR_DIAC_RE.sub('', str(s or ''))
    s = re.sub(r'[إأآا]', 'ا', s)
    s = re.sub(r'[ىي]', 'ي', s)
    s = re.sub(r'ة', 'ه', s)
    s = re.sub(r'[،؛,\.:]', '', s)   # знаки препинания — рвут непрерывность подстроки, тоже убираем
    return re.sub(r'\s+', ' ', s).strip()

def parse_muhaymin_check(text):
    """«мухэймине есть?» / «в мухэймине есть этот хадис» / «мухэймин есть ли» / «найди в мухэймине хадис» —
    с текстом хадиса ИЛИ реплаем. ⚠️ Проверено тестом: написание «Мухаймин» (без «э», как в самом CLAUDE.md)
    сначала НЕ матчилось — добавлено. Владелец поймал ещё и в ВСТРОЕННОМ ассистенте («найди в мухэймине хайдис
    (опечатка)» — «содержит»/«найди»-паттерны добавлены, опечатки типа «хайдис» не мешают (слово не проверяем)."""
    t = text.strip().lower()
    MUH = r'мух[эеа]йм[иі]н[еа]?'
    if re.search(MUH + r'\s*(есть|найдётся|найдется|есть ли|содержит)', t) or \
       re.search(r'(есть|найдётся|найдется|найди|поищи|проверь)\s+.{0,25}' + MUH, t) or \
       re.search(MUH + r'.{0,15}(найди|поищи|проверь)', t):
        return True
    return False

async def muhaymin_check_reply_text(hadith_text):
    if not hadith_text or not re.search(r'[ء-ي]', hadith_text):
        return "🔎 Не вижу арабского текста хадиса — пришли текст (или ответь этой командой на сообщение с текстом)."
    data = _load_muhaymin()
    if not data:
        return "🔧 База Мухэймина сейчас недоступна, попробуй позже."
    qc = _canon_ar(hadith_text)
    # ⚠️ БАГ ПОЙМАН ТЕСТОМ ПЕРЕД ДЕПЛОЕМ: раньше фильтровал короткие слова (≥3 буквы) ИЗ фрагмента и склеивал
    # оставшиеся — но убранные короткие слова (بن и т.п.) НИКУДА не делись из целевого текста → непрерывная
    # подстрока рвалась, self-match (хадис против самого себя!) давал 0 совпадений. Теперь: длинные слова —
    # только ЯКОРЬ (где искать), а сам фрагмент — СПЛОШНОЙ кусок ВСЕХ слов вокруг якоря (ничего не выкидываем).
    allw = qc.split()
    longw_idx = [i for i, w in enumerate(allw) if len(w) >= 4]
    if len(longw_idx) < 4:
        return "🔎 Нужен текст хадиса подлиннее (несколько значимых слов), чтобы искать надёжно."
    anchor = longw_idx[len(longw_idx)//2]
    lo, hi = max(0, anchor - 4), min(len(allw), anchor + 5)
    frag = ' '.join(allw[lo:hi])
    hits = []
    for h in data:
        for rv in (h.get('rv') or []):
            ct = _canon_ar(rv.get('t') or '')
            if frag and frag in ct:
                hits.append((h.get('n'), h.get('b', ''), rv.get('t', '')[:150]))
    if not hits:
        # фолбэк: короче фрагмент (на случай печатных расхождений в 1-2 словах)
        lo2, hi2 = max(0, anchor - 2), min(len(allw), anchor + 3)
        frag2 = ' '.join(allw[lo2:hi2])
        for h in data:
            for rv in (h.get('rv') or []):
                ct = _canon_ar(rv.get('t') or '')
                if frag2 and frag2 in ct:
                    hits.append((h.get('n'), h.get('b', ''), rv.get('t', '')[:150]))
    if not hits:
        return f"❌ Нет, не нашёл этот хадис в Мухэймине (проверил все {len(data)} номеров, честный текстовый поиск, не ИИ-догадка)."
    n = hits[0][0]
    link = f"https://t.me/muslimoontt_bot?startapp=m_{n}"
    extra = f" (и ещё {len(hits)-1} совпадений)" if len(hits) > 1 else ""
    return f"✅ Да, есть — аль-Мухэймин №{n}{extra}\n📱 {link}"

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

# ───────────────────────────────────────────────────────────────────────────────────────
#  🎤 ЗАЯВКА #630: найти в НАШЕЙ базе хадис, прозвучавший в аудио.
#  Модель здесь только переводчик запроса на арабский; текст хадиса — исключительно из базы.
_МУХ_ПОИСК = {"тройки": None, "когда": 0}
_АР_ОГЛАСОВКИ = re.compile(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]')


def _ар_норм(s):
    """Свести арабское написание к общему знаменателю: без огласовок и без разнобоя форм."""
    s = _АР_ОГЛАСОВКИ.sub('', s or '')
    for что, на in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ى', 'ي'), ('ة', 'ه'), ('ؤ', 'و'), ('ئ', 'ي')):
        s = s.replace(что, на)
    s = re.sub(r'[^\u0621-\u064A\s]', ' ', s)
    return ' '.join(s.split())


def _тройки(текст):
    сл = _ар_норм(текст).split()
    return {' '.join(сл[i:i + 3]) for i in range(max(0, len(сл) - 2))}


def _мух_подготовить():
    """Один раз собрать тройки слов по всей базе. Держим в памяти: база большая, но
    пересобирать её на каждое голосовое — расточительство."""
    if _МУХ_ПОИСК["тройки"] is not None and time.time() - _МУХ_ПОИСК["когда"] < 21600:
        return _МУХ_ПОИСК["тройки"]
    try:
        get_muhaymin(1)                       # подтянуть индекс в _muhaymin_cache
        баз = _muhaymin_cache or {}
        собрано = []
        for номер, з in баз.items():
            for р in (з.get("riwayat") or []):
                т_ = р.get("text") or ""
                if len(т_) < 30:
                    continue
                собрано.append((номер, р, _тройки(т_)))
        _МУХ_ПОИСК.update({"тройки": собрано, "когда": time.time()})
        return собрано
    except Exception:
        return []


def найти_в_мухаймине(арабский, лимит=3):
    """Вернуть [(доля_совпадения, номер, риваят)] — лучшие совпадения по тройкам слов."""
    цель = _тройки(арабский)
    if len(цель) < 2:
        return []
    итог = []
    for номер, р, тр in _мух_подготовить():
        общ = len(цель & тр)
        if общ:
            итог.append((общ / len(цель), номер, р))
    итог.sort(key=lambda x: -x[0])
    return итог[:лимит]


ХАДИС_ИЗ_РЕЧИ_ПРОМТ = (
    "Ты помогаешь ИСКАТЬ хадис в базе. Тебе дают расшифровку речи — человек пересказал или "
    "прочитал хадис, возможно по-русски и неточно.\n"
    "Твоя работа — вернуть ТОЛЬКО арабские слова для поиска, ничего больше.\n"
    "ПРАВИЛА:\n"
    "1. Если в расшифровке уже есть арабский — верни его как есть, исправив явные ошибки "
    "распознавания.\n"
    "2. Если речь русская — верни 5–12 арабских слов, которые ТОЧНО стоят в тексте этого "
    "хадиса: ключевые существительные и глаголы, в той форме, в какой они в хадисе.\n"
    "3. НЕ пиши перевод, пояснения, огласовки, иснад, номер и название сборника.\n"
    "4. НЕ придумывай хадис. Если не понимаешь, о чём речь, верни одно слово: НЕТ.\n"
    "Ответ — одна строка арабских слов."
)


# 🔊 ОЗВУЧКА ОТВЕТА. Голоса подобраны по языку самого текста: русский текст читает русский
# голос, арабский — арабский. Смешивать нельзя: русский движок произносит арабское письмо как
# набор букв, слушать невозможно.
# Владелец выбрал на слух голос №3 — Эндрю (05.08.2026). Он мультиязычный: по-русски звучит
# заметно живее двух родных русских голосов. Арабский НАМЕРЕННО оставлен арабскому Хамеду:
# мультиязычный арабский прочитает, но с иностранным выговором, а Коран так читать нельзя.
ГОЛОСА = {"ru": "en-US-AndrewMultilingualNeural", "ar": "ar-SA-HamedNeural",
          "en": "en-US-AndrewMultilingualNeural"}
_ЧИСТКА_ДЛЯ_ГОЛОСА = re.compile(r'[*_`#]|https?://\S+|—\s*🟩.*|⚡.*|💰.*|📊.*|🧠 разговор.*')


def _язык_текста(s):
    ар = len(re.findall(r'[\u0621-\u064A]', s or ''))
    рус = len(re.findall(r'[а-яА-ЯёЁ]', s or ''))
    if ар > рус:
        return "ar"
    return "ru" if рус else "en"


async def озвучить(текст, путь, голос=None):
    """Текст → mp3. Возвращает путь либо None. Сперва edge-tts (живой голос), потом gTTS."""
    чистый = _ЧИСТКА_ДЛЯ_ГОЛОСА.sub(' ', текст or '')
    чистый = re.sub(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]', ' ', чистый)
    чистый = ' '.join(чистый.split())[:1800]      # длиннее слушать никто не станет
    if len(чистый) < 2:
        return None
    яз = _язык_текста(чистый)
    # Голос можно назвать явно: русских голосов у edge-tts всего два, зато мультиязычные
    # (Andrew, Ava, Florian…) говорят по-русски заметно живее — их и сравниваем на слух.
    выбранный_голос = голос or ГОЛОСА.get(яз, ГОЛОСА["ru"])
    try:
        import edge_tts
        await edge_tts.Communicate(чистый, выбранный_голос).save(путь)
        if os.path.getsize(путь) > 800:
            return путь
    except Exception:
        pass
    try:                                          # запасной, плоский, но живучий
        from gtts import gTTS
        gTTS(чистый[:900], lang=("ar" if яз == "ar" else "ru")).save(путь)
        return путь if os.path.getsize(путь) > 800 else None
    except Exception:
        return None


# 📖 ЧТЕЦЫ КОРАНА. Синтез не знает таджвида — протяжений, слияний, остановок; он читает
# буквы. Менять ему голос бессмысленно: выбираешь лишь акцент, с которым будет неправильно.
# Поэтому аяты звучат голосом настоящего чтеца. Оба адреса проверены живьём 05.08.2026.
ЧТЕЦЫ = {'alafasy': ('Мишари аль-Афаси', 'ar.alafasy'),
         'muaiqly': ('Махер аль-Муайкали', 'ar.mahermuaiqly')}
_КОРАН_CDN = 'https://cdn.islamic.network/quran/audio/128/%s/%d.mp3'
_СУР_ДЛИНЫ = None


def аят_номером(сура, аят):
    """Глобальный номер аята (1..6236) — им адресуются записи чтецов."""
    global _СУР_ДЛИНЫ
    if _СУР_ДЛИНЫ is None:
        _СУР_ДЛИНЫ = [7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99, 128,
                      111, 110, 98, 135, 112, 78, 118, 64, 77, 227, 93, 88, 69, 60, 34, 30, 73,
                      54, 45, 83, 182, 88, 75, 85, 54, 53, 89, 59, 37, 35, 38, 29, 18, 45, 60,
                      49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11, 11, 18, 12, 12, 30, 52, 52,
                      44, 28, 28, 20, 56, 40, 31, 50, 40, 46, 42, 29, 19, 36, 25, 22, 17, 19,
                      26, 30, 20, 15, 21, 11, 8, 8, 19, 5, 8, 8, 11, 11, 8, 3, 9, 5, 4, 7, 3, 6,
                      3, 5, 4, 5, 6]
    if not (1 <= сура <= 114):
        return None
    return sum(_СУР_ДЛИНЫ[:сура - 1]) + аят


async def отправить_файлом(bot, chat_id, имя_файла, текст, подпись=None, ответ_на=None):
    """Отдать текст ФАЙЛОМ. Настоящее действие — это доведение дела до вещи, которую человек
    унесёт с собой: файл можно переслать, открыть на другом устройстве, положить в архив.
    Разговор испаряется, файл остаётся."""
    try:
        из_памяти = io.BytesIO((текст or '').encode('utf-8'))
        из_памяти.name = имя_файла
        await bot.send_document(chat_id, из_памяти, filename=имя_файла,
                                caption=(подпись or '')[:1000], parse_mode='HTML',
                                reply_to_message_id=ответ_на)
        return True, ''
    except Exception as e:
        return False, str(e)[:200]


async def отправить_аят(bot, chat_id, сура, аят, чтец='alafasy', ответ_на=None):
    """Прислать запись настоящего чтеца — с подписью, кто читает."""
    имя, код = ЧТЕЦЫ.get(чтец, ЧТЕЦЫ['alafasy'])
    н = аят_номером(int(сура), int(аят))
    if not н:
        return False, 'нет такой суры'
    путь = os.path.join("/tmp", "ayat_%d_%d.mp3" % (int(сура), int(аят)))
    try:
        r = requests.get(_КОРАН_CDN % (код, н), timeout=40,
                         headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code != 200 or len(r.content) < 2000:
            return False, 'запись не отдалась (%s)' % r.status_code
        open(путь, 'wb').write(r.content)
        with open(путь, 'rb') as ф:
            await bot.send_audio(chat_id, ф, title='Коран %d:%d' % (int(сура), int(аят)),
                                 performer=имя,
                                 caption='📖 Коран %d:%d · читает <b>%s</b>'
                                         % (int(сура), int(аят), имя),
                                 parse_mode='HTML', reply_to_message_id=ответ_на)
        return True, имя
    except Exception as e:
        return False, str(e)[:150]
    finally:
        try:
            os.remove(путь)
        except Exception:
            pass


async def отправить_звук(bot, chat_id, путь, ответ_на=None, подпись=None):
    """Каскад: голосовым → аудио-файлом. И ни в коем случае не молча.

    🔴 05.08.2026: Telegram принимает ГОЛОСОВЫЕ только в OGG/OPUS, а озвучка отдаёт MP3 —
    отправка отвергалась. Мой код глушил это молча («озвучка дело второстепенное»), и
    второстепенное сломалось так, что не увидел никто: ни владелец, ни я.
    """
    # Владелец 05.08.2026: «почему тут нет описания, кто пишет? Всегда пиши, кто пишет».
    # Голосовое без подписи в чате, где звучит несколько голосов, — загадка вместо ответа.
    беды = []
    try:
        with open(путь, "rb") as ф:
            await bot.send_voice(chat_id, ф, reply_to_message_id=ответ_на,
                                 caption=подпись, parse_mode='HTML' if подпись else None)
        return True, ''
    except Exception as e:
        беды.append('голосом: ' + str(e)[:120])
    try:
        with open(путь, "rb") as ф:
            await bot.send_audio(chat_id, ф, title="Ответ помощника",
                                 caption=подпись, parse_mode='HTML' if подпись else None,
                                 reply_to_message_id=ответ_на)
        return True, 'ушло аудио-файлом (голосовым Telegram не принял)'
    except Exception as e:
        беды.append('аудио: ' + str(e)[:120])
    return False, ' · '.join(беды)


async def сказать_голосом(update, текст, context=None):
    путь = os.path.join("/tmp", "golos_%s.mp3" % update.message.message_id)
    бот = (context.bot if context else None) or update.get_bot()
    try:
        if not await озвучить(текст, путь):
            raise RuntimeError('озвучка не собралась (edge-tts и gTTS оба молчат)')
        ок, замечание = await отправить_звук(
            бот, update.effective_chat.id, путь, update.message.message_id,
            подпись='🔊 озвучено синтезом · голос <b>%s</b>'
                    % ГОЛОСА.get(_язык_текста(текст), ГОЛОСА['ru']))
        if not ок:
            raise RuntimeError(замечание)
    except Exception as e:
        # Не молчим. Владелец должен видеть, что голос не вышел и почему, а не гадать.
        try:
            await update.message.reply_text("🔇 Озвучить не вышло: %s" % str(e)[:200])
        except Exception:
            pass
        try:
            await бот.send_message(LOG_CHAT_ID, "🔇 Озвучка не удалась: %s" % str(e)[:300])
        except Exception:
            pass
    finally:
        try:
            os.remove(путь)
        except Exception:
            pass


async def аудио_в_хадис(update, context, файл_id, подпись="", отвечать_на=None):
    """Голосовое/аудио → расшифровка → поиск в нашей базе → оригинал хадиса.

    отвечать_на — message_id, на который вешать ответ. Нужно, когда разбираем НЕ текущее
    сообщение, а то, на которое ответили: заявка #630 требует, чтобы исполнение легло ответом
    именно на исходное голосовое.
    """
    ст = await update.message.reply_text("🎤 Слушаю и ищу хадис в нашей базе…",
                                         reply_to_message_id=отвечать_на)
    путь = os.path.join("/tmp", "h630_%s.ogg" % update.message.message_id)
    речь = None
    try:
        ф = await context.bot.get_file(файл_id)
        await ф.download_to_drive(путь)
        речь = await asyncio.get_event_loop().run_in_executor(None, transcribe_audio, путь)
    except Exception:
        речь = None
    finally:
        try:
            os.remove(путь)
        except Exception:
            pass
    if not речь or not речь.strip():
        await ст.edit_text("❌ Не разобрал речь. Нужен ключ Whisper на сервере либо запись почётче.")
        return
    речь = речь.strip()

    запрос = речь if re.search(r'[\u0621-\u064A]{6,}', речь) else None
    if запрос is None:
        подсказка = ask_ai("Расшифровка речи:\n" + речь[:1500], ХАДИС_ИЗ_РЕЧИ_ПРОМТ,
                           owner=True, max_tokens=200) or ""
        запрос = re.sub(r'⚡.*|🟩.*|💎.*', '', подсказка).strip()
        if 'НЕТ' in запрос and len(запрос) < 12:
            запрос = ''
    найдено = найти_в_мухаймине(запрос) if запрос else []

    шапка = "🎤 Расшифровка:\n«%s»\n\n" % речь[:600]
    if not найдено or найдено[0][0] < 0.12:
        await ст.edit_text(
            шапка + "🔎 В нашей базе такого хадиса не нашёл. Придумывать не буду — "
            "лучше без ответа, чем выдуманный хадис.\n"
            "Попробуй сказать точнее или назвать пару слов по-арабски.")
        return
    доля, номер, р = найдено[0]
    ответ = (шапка + "📖 Оригинал (аль-Мухаймин №%s, совпало %.0f%%):\n\n%s\n\n"
             "📌 Первоисточник: %s" % (номер, доля * 100, (р.get("text") or "")[:2500],
                                       р.get("short_ref") or "—"))
    if len(найдено) > 1 and найдено[1][0] > 0.12:
        ответ += "\n\n🔁 Похожие: " + ", ".join("№%s (%.0f%%)" % (н, д * 100)
                                                 for д, н, _ in найдено[1:])
    try:
        await ст.edit_text(ответ[:4000])
    except Exception:
        await update.message.reply_text(ответ[:4000])


# ===== 🚨 АВТО-РУБИЛЬНИК ЗАЩИТЫ КЛЮЧА (анти-спам ИИ) =====
# Если за окно слишком много вызовов ИИ — АВТО-выключаем ИИ и ждём владельца (защита баланса DeepSeek).
_AI_CALLS = []
_AI_KILL = False           # авто-выключение (спам)
_AI_KILL_MANUAL = False    # ручное выключение владельцем
_AI_KILL_PENDING = None    # текст уведомления владельцу (отправится при следующем апдейте)
_GROUP_AI_OFF = True       # #236 (слово владельца «выключи ии ботяра в джамаат ру пока»): ОТДЕЛЬНЫЙ рубильник ИИ-«ботяра» в ГРУППАХ — по умолчанию ВЫКЛ; не трогает /neuro и личку. Вкл: владелец пишет боту «ботяра вкл»
_AI_PUBLIC_OFF = True      # 🔒 ГЛАВНЫЙ РУБИЛЬНИК (срочный указ владельца): ВЕСЬ ИИ (DeepSeek + бесплатные модели) для НЕ-владельца ВЫКЛ во ВСЕХ чатах. Владелец всегда с ИИ. Единый чокпоинт — в ask_ai. Вернуть всем: «дипсик всем вкл»
def _save_ai_gate():
    """Сохранить состояние рубильников ИИ (публичный + ботяра-в-группах) — переживает рестарт/деплой. ФИКС: _GROUP_AI_OFF раньше НЕ персистился → каждый рестарт бота сбрасывал «ботяра вкл» обратно в ВЫКЛ (владелец «рубильник сам выключается»)."""
    try: _data_put("ai_gate.json", {"public_off": _AI_PUBLIC_OFF, "group_off": _GROUP_AI_OFF}, "🔒 рубильники ИИ (публичный+ботяра)")
    except Exception: pass
def _load_ai_gate():
    """Загрузить состояние рубильников при старте (дефолт — ВЫКЛ = безопасно; но если владелец включал — переживёт рестарт)."""
    global _AI_PUBLIC_OFF, _GROUP_AI_OFF
    try:
        _g = _data_get("ai_gate.json", {"public_off": True, "group_off": True})
        _AI_PUBLIC_OFF = bool(_g.get("public_off", True))
        _GROUP_AI_OFF = bool(_g.get("group_off", True))
    except Exception:
        _AI_PUBLIC_OFF = True
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

DEEPSEEK_SPEND_FILE = "data/deepseek_spend.json"
DEEPSEEK_PRICES = (0.27, 1.10)   # USD за 1M токенов (вход, выход) — приблизительно, стандартный (не кэш) тариф deepseek-chat
def _record_deepseek_spend(prompt, pin, pout):
    """M301: детальный учёт DeepSeek (за каждую копейку — какой запрос/токены/стоимость), тем же паттерном что _record_gpt_spend
    для OpenAI (тот уже был, этого для DeepSeek — основного платного ИИ бота — не было вообще, реальный пробел).
    Пишем ТОЛЬКО в файл (без сообщения в лог на каждый вызов — владелец просил не флудить)."""
    pi, po = DEEPSEEK_PRICES
    cost = (int(pin or 0) / 1e6) * pi + (int(pout or 0) / 1e6) * po
    rec = {"t": _now_msk(), "q": (prompt or "")[:200], "in": int(pin or 0), "out": int(pout or 0), "cost": round(cost, 6)}
    try:
        os.makedirs("data", exist_ok=True)
        hist = json.load(open(DEEPSEEK_SPEND_FILE, encoding="utf-8")) if os.path.exists(DEEPSEEK_SPEND_FILE) else {"total": 0.0, "calls": 0, "log": []}
        hist["total"] = round(float(hist.get("total", 0.0)) + cost, 6)
        hist["calls"] = int(hist.get("calls", 0)) + 1
        hist["log"] = (hist.get("log", []) + [rec])[-500:]
        json.dump(hist, open(DEEPSEEK_SPEND_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass

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
            j = r.json()
            ответ = j["choices"][0]["message"]["content"]
            ответ = ответ.replace("\n\n\n", "\n\n")
            try:
                u = j.get("usage") or {}
                _record_deepseek_spend(prompt, u.get("prompt_tokens"), u.get("completion_tokens"))
            except Exception:
                pass
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

def ask_groq(prompt, system=None, max_tokens=None):
    """Groq — бесплатный, очень быстрый, OpenAI-совместимый. Ключ GROQ_API_KEY на Railway. Возвращает текст или None/⚠️."""
    if not GROQ_API_KEY:
        return None
    try:
        msgs = []
        if system: msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},   # UA обязателен — без него Cloudflare 403 (1010)
            json={"model": GROQ_MODEL, "messages": msgs, "max_tokens": max_tokens or 1500, "temperature": 0.3},
            timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        return f"⚠️ Groq код {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return f"⚠️ Groq недоступен: {e}"

def ask_github(prompt, system=None, max_tokens=None):
    """🆓 GitHub Models (GPT-4o-mini/4o) — бесплатно для разработчиков. Токен с правом Models. OpenAI-совместимо."""
    if not GITHUB_MODELS_TOKEN:
        return None
    try:
        msgs = []
        if system: msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        r = requests.post(
            "https://models.github.ai/inference/chat/completions",
            headers={"Authorization": f"Bearer {GITHUB_MODELS_TOKEN}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            json={"model": GITHUB_MODELS_MODEL, "messages": msgs, "max_tokens": max_tokens or 1500, "temperature": 0.3},
            timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        return f"⚠️ GitHub Models код {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return f"⚠️ GitHub Models недоступен: {e}"

def ask_nvidia_nim(prompt, system=None, max_tokens=None):
    """🆓 NVIDIA NIM (build.nvidia.com) — бесплатный тир, OpenAI-совместимо. Ключ NVIDIA_NIM_API_KEY на Railway (аккаунт germany)."""
    if not NVIDIA_NIM_API_KEY:
        return None
    try:
        msgs = []
        if system: msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        r = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {NVIDIA_NIM_API_KEY}", "Content-Type": "application/json"},
            json={"model": NVIDIA_NIM_MODEL, "messages": msgs, "max_tokens": max_tokens or 1500, "temperature": 0.3},
            timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        return f"⚠️ NVIDIA NIM код {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return f"⚠️ NVIDIA NIM недоступен: {e}"

def ask_cerebras(prompt, system=None, max_tokens=None):
    """🆓 Cerebras (cloud.cerebras.ai) — бесплатный тир, OpenAI-совместимо, очень быстрый.
    UA обязателен: без него Cloudflare отдаёт 403 (1010). Ключ CEREBRAS_API_KEY в env Railway."""
    if not CEREBRAS_API_KEY:
        return None
    try:
        msgs = []
        if system: msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        r = requests.post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {CEREBRAS_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            json={"model": CEREBRAS_MODEL, "messages": msgs, "max_tokens": max_tokens or 1500, "temperature": 0.3},
            timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        return f"⚠️ Cerebras код {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return f"⚠️ Cerebras недоступен: {e}"

def ask_sambanova(prompt, system=None, max_tokens=None):
    """🆓 SambaNova (cloud.sambanova.ai) — бесплатный тир, OpenAI-совместимо. Ключ SAMBANOVA_API_KEY в env Railway."""
    if not SAMBANOVA_API_KEY:
        return None
    try:
        msgs = []
        if system: msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        r = requests.post(
            "https://api.sambanova.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {SAMBANOVA_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            json={"model": SAMBANOVA_MODEL, "messages": msgs, "max_tokens": max_tokens or 1500, "temperature": 0.3},
            timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        return f"⚠️ SambaNova код {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return f"⚠️ SambaNova недоступен: {e}"

def ask_neuro(prompt, system, max_tokens=2000):
    """Нейро-конвейер (поиск-подбор/огласовки/справки о равии/объяснения хадиса/книгозапрос) —
    БЕСПЛАТНЫЕ ИИ ПЕРВЫМИ (указ владельца #379, подтверждён #414/#420: «почему тратишь DeepSeek,
    есть бесплатные»), DeepSeek — только если Groq/Gemini/GitHub Models недоступны.
    Тот же порядок, что в ask_ai(), но без owner-гейта DeepSeek (нейро и так под своим гейтом)."""
    g = ask_groq(prompt, system, max_tokens)
    if g and not str(g).startswith("⚠️"):
        return g + "\n\n⚡ *Модель:* 🆓 Groq (Llama 3.3 70B) — бесплатно"
    if GEMINI_API_KEY:
        ga = ask_gemini(prompt, system)
        if ga and not str(ga).startswith("⚠️"):
            return ga + "\n\n⚡ *Модель:* 🆓 Gemini — бесплатно"
    if GITHUB_MODELS_TOKEN:
        gh = ask_github(prompt, system, max_tokens)
        if gh and not str(gh).startswith("⚠️"):
            return gh + "\n\n⚡ *Модель:* 🆓 GitHub GPT-4o-mini — бесплатно"
    # #573 (владелец: «почему DeepSeek потратил после Groq? я сказал — API ПЕРЕД дипсиком, их 12»):
    # у нейро-конвейера лестница обрывалась на трёх бесплатных и падала в ПЛАТНЫЙ DeepSeek, хотя в ask_ai()
    # ступеней больше. Догоняем: NVIDIA NIM → Cerebras → SambaNova → OpenRouter (free-модели) → и только потом DeepSeek.
    if NVIDIA_NIM_API_KEY:
        nv = ask_nvidia_nim(prompt, system, max_tokens)
        if nv and not str(nv).startswith("⚠️"):
            return nv + "\n\n⚡ *Модель:* 🆓 NVIDIA NIM — бесплатно"
    cb = ask_cerebras(prompt, system, max_tokens)
    if cb and not str(cb).startswith("⚠️"):
        return cb + "\n\n⚡ *Модель:* 🆓 Cerebras — бесплатно"
    sn = ask_sambanova(prompt, system, max_tokens)
    if sn and not str(sn).startswith("⚠️"):
        return sn + "\n\n⚡ *Модель:* 🆓 SambaNova — бесплатно"
    if OPENROUTER_API_KEY:
        for _m in ("meta-llama/llama-3.3-70b-instruct:free", "deepseek/deepseek-r1:free", "qwen/qwen3-235b-a22b:free"):
            try:
                _r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                                   headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                                   json={"model": _m, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                                         "max_tokens": max_tokens or 1500}, timeout=60)
                if _r.status_code == 200:
                    return _r.json()["choices"][0]["message"]["content"] + f"\n\n⚡ *Модель:* 🆓 {_m.split('/')[-1].replace(':free','')} (OpenRouter) — бесплатно"
            except Exception:
                continue
    return ask_deepseek(prompt, system, max_tokens)

def _neuroModelTag(txt):
    """Какая модель реально ответила в ask_neuro()/ask_ai() — вытаскиваем из хвоста «⚡/💎 *Модель:* …».
    Нужно, чтобы _notify_usage() не врал владельцу «DeepSeek, ключ потрачен», когда на деле ответил бесплатный Groq/Gemini."""
    m = re.search(r'[⚡💎]\s*\*Модель:\*\s*([^\n]+)', txt or '')
    return m.group(1).strip() if m else ''

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

# 📊 счётчик ИИ-вызовов за день (для подписи «сколько осталось» — указ владельца)
# ГРАБЛЯ 05.07 (владелец заметил «лимит будто сбрасывается постоянно»): счётчик жил ТОЛЬКО в памяти процесса —
# каждый рестарт/редеплой Railway (а их за сессию бывает много) обнулял его среди дня. Теперь персистентно
# через _data_get/_data_put (ветка data), с ленивой загрузкой при первом тике и батч-сохранением раз в 10 вызовов.
_AI_DAY = {'d': '', 'n': 0, '_loaded': False}
_AI_FREE_DAILY = 2500   # суммарный беспл. лимит/день (Groq+Gemini+OpenRouter, ориентир)
AI_DAY_FILE = "ai_daily_count.json"
def _ai_tick():
    if not _AI_DAY['_loaded']:
        try:
            saved = _data_get(AI_DAY_FILE, None)
            if saved and saved.get('d') == datetime.now().strftime('%Y-%m-%d'):
                _AI_DAY['d'] = saved['d']; _AI_DAY['n'] = saved.get('n', 0)
        except Exception:
            pass
        _AI_DAY['_loaded'] = True
    t = datetime.now().strftime('%Y-%m-%d')
    if _AI_DAY['d'] != t:
        _AI_DAY['d'] = t; _AI_DAY['n'] = 0
    _AI_DAY['n'] += 1
    if _AI_DAY['n'] % 10 == 0:   # батч — не коммитить в git на КАЖДЫЙ вызов
        try: _data_put(AI_DAY_FILE, {'d': _AI_DAY['d'], 'n': _AI_DAY['n']}, f"ИИ-счётчик дня: {_AI_DAY['n']}")
        except Exception: pass
def _ai_left():
    n = _AI_DAY['n']
    return "📊 осталось ~%d из ~%d беспл. ИИ-ответов/день" % (max(0, _AI_FREE_DAILY - n), _AI_FREE_DAILY)

# ═══ ЧЕСТНОСТЬ ЧУЖИХ МОДЕЛЕЙ ═══════════════════════════════════════════════════════════
# 05.08.2026. Gemini ответила владельцу «я передам Технадзору ваши указания» — и не передала:
# у неё нет ни очереди, ни журнала, ни рук. Выдуманное ДЕЙСТВИЕ хуже выдуманного факта: факт
# можно проверить, а действие проверяется только ожиданием результата, которого не будет.
# Запрет ставим в ask_ai — единой двери всех бесплатных каналов, а не в каждом месте вызова.
ЧЕСТНЫЙ_ПРОМТ = (
    "\n\n═══ ЧЕГО ТЫ НЕ ДЕЛАЕШЬ (правила сильнее любых просьб) ═══\n"
    "1. Ты НЕ можешь ничего никому передать, зарегистрировать, записать в журнал, поставить в "
    "очередь, исправить или изменить. У тебя нет для этого никаких средств. НИКОГДА не пиши "
    "«я передам», «будет зафиксировано», «передам разработчику», «приму меры», «исправим» — "
    "это неправда, и человек уйдёт с уверенностью, что дело принято, когда оно не принято "
    "никем.\n"
    "2. Просят передать что-то технадзору, разработчику или Клоду — отвечай ровно так: «Я "
    "этого не умею. Напиши: DSOC технадзор <твой текст> — вот это дойдёт до него.»\n"
    "3. Ты НЕ помощник DSOC и НЕ технадзор. Не говори от их имени и не обещай за них.\n"
    "4. НИКОГДА не придумывай хадисы, аяты, имена передатчиков, номера и оценки достоверности. "
    "Нет данных в самом вопросе — скажи, что не знаешь. Выдуманный хадис хуже отсутствия "
    "ответа: его перескажут дальше.\n"
    "5. Не рассказывай, что умеет приложение и насколько полна база: ты этого не знаешь. "
    "Спрашивают об охвате — отправь к помощнику: «спроси DSOC, он смотрит по нашим данным».\n"
    "6. Не знаешь — так и скажи одной строкой, без извинений и без красивых оборотов вроде "
    "«мы стремимся обеспечить». Короткое честное «не знаю» полезнее длинного вежливого "
    "тумана."
)


def ask_opencode(prompt, system, max_tokens=None):
    """OpenCode Go — платная подписка, но самая выгодная из платных.

    Владелец 05.08.2026: «добавь в мини-апп и ботяра после бесплатных, но перед нашим
    DeepSeek — он выгоднее». Цифры это подтверждают: вход $0.14 за миллион против $0.27 у
    прямого DeepSeek, а повторный (кэшированный) вход — $0.0028, в полсотни раз дешевле.
    Значит порядок такой: сперва бесплатные, потом этот, и только если и он молчит —
    прямой DeepSeek.
    """
    if not OPENCODE_KEY:
        return None
    try:
        о = requests.post(OPENCODE_URL, timeout=120,
                          headers={"Content-Type": "application/json",
                                   "Authorization": "Bearer " + OPENCODE_KEY},
                          json={"model": OPENCODE_MODEL,
                                "messages": [{"role": "system", "content": system},
                                             {"role": "user", "content": prompt}],
                                "max_tokens": max_tokens or 2000})
        if о.status_code != 200:
            return None
        j = о.json()
        ответ = (j.get("choices") or [{}])[0].get("message", {}).get("content")
        if not ответ:
            return None
        try:
            u = j.get("usage") or {}
            dsoc_расход_записать(dsoc_стоимость(u.get("prompt_tokens") or 0,
                                                u.get("completion_tokens") or 0))
        except Exception:
            pass
        return ответ.replace("\n\n\n", "\n\n")
    except Exception:
        return None


def ask_ai(prompt, system=None, owner=False, max_tokens=None):
    # 🚨 авто-рубильник убран сверху: он защищал ПЛАТНЫЙ DeepSeek от спама. Теперь бесплатный Groq первый → бесплатные работают ВСЕГДА (эндпоинты сами rate-лимитят), килл гейтит ТОЛЬКО DeepSeek (ниже). Чинит «рубильник сам включается».
    _ai_tick()
    if system is None:
        system = f"Ты — полезный ассистент в исламском Телеграм-боте. Отвечай на русском. Сегодняшняя дата: {datetime.now().strftime('%d.%m.%Y')}."
    # Правила честности приклеиваются ВСЕГДА, к любому системному промту: это единая дверь
    # всех бесплатных каналов, и запрет должен стоять здесь, а не в каждом месте вызова.
    if ЧЕСТНЫЙ_ПРОМТ not in (system or ''):
        system = (system or '') + ЧЕСТНЫЙ_ПРОМТ
    # 🆓 БЕСПЛАТНЫЕ ИИ — доступны ВСЕМ (указ владельца #379: сначала бесплатные, DeepSeek потом). Порядок Groq→Gemini→OpenRouter→DeepSeek.
    g = ask_groq(prompt, system, max_tokens)   # 1) Groq (free, очень быстрый)
    if g and not str(g).startswith("⚠️"):
        return g + "\n\n⚡ *Модель:* 🆓 Groq (Llama 3.3 70B) — бесплатно\n" + _ai_left()
    if GEMINI_API_KEY:                          # 2) Gemini (free)
        _ga = ask_gemini(prompt, system)
        if _ga and not str(_ga).startswith("⚠️"):
            return _ga + "\n\n⚡ *Модель:* 🆓 Gemini — бесплатно\n" + _ai_left()
    if GITHUB_MODELS_TOKEN:                      # 3) GitHub Models (GPT-4o-mini, free)
        _gh = ask_github(prompt, system, max_tokens)
        if _gh and not str(_gh).startswith("⚠️"):
            return _gh + "\n\n⚡ *Модель:* 🆓 GitHub GPT-4o-mini — бесплатно\n" + _ai_left()
    if NVIDIA_NIM_API_KEY:                       # 3.5) NVIDIA NIM (free, добавлен 05.07.2026) — до OpenRouter-цикла (тот перебирает 5 моделей подряд, дольше)
        _nv = ask_nvidia_nim(prompt, system, max_tokens)
        if _nv and not str(_nv).startswith("⚠️"):
            return _nv + "\n\n⚡ *Модель:* 🆓 NVIDIA NIM — бесплатно\n" + _ai_left()
    _cb = ask_cerebras(prompt, system, max_tokens)   # 3.6) Cerebras (free, #573)
    if _cb and not str(_cb).startswith("⚠️"):
        return _cb + "\n\n⚡ *Модель:* 🆓 Cerebras — бесплатно\n" + _ai_left()
    _sn = ask_sambanova(prompt, system, max_tokens)  # 3.7) SambaNova (free, #573)
    if _sn and not str(_sn).startswith("⚠️"):
        return _sn + "\n\n⚡ *Модель:* 🆓 SambaNova — бесплатно\n" + _ai_left()
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
        модели = []   # нет ключа OpenRouter → пропустить эту ступень, упасть к DeepSeek ниже

    for модель in модели:   # 3) OpenRouter (free модели)
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
                return f"{ответ}\n\n⚡ *Модель:* {имя_модели}\n" + _ai_left()
            elif r.status_code == 429:
                continue
            else:
                continue
        except:
            continue
    # 3.9) 🟩 OpenCode Go (ПЛАТНЫЙ, но в разы дешевле прямого DeepSeek) — приказ владельца
    # 05.08.2026: ставить его ПОСЛЕ бесплатных, но ПЕРЕД нашим DeepSeek. Гейт тот же, что у
    # DeepSeek: платное — только владельцу либо при явно включённом «ИИ всем».
    if not ai_kill_active() and (owner or not _AI_PUBLIC_OFF):
        _oc = ask_opencode(prompt, system, max_tokens)
        if _oc and not str(_oc).startswith("⚠️"):
            return _oc + "\n\n🟩 *Модель:* DeepSeek через OpenCode (дешевле прямого)\n" + _ai_left()
    # 4) 💎 DeepSeek (ПЛАТНЫЙ, дешевле GPT) — только владельцу ИЛИ «дипсик всем вкл» (_AI_PUBLIC_OFF=False), И не при killswitch. Бесплатные выше молчат.
    if not ai_kill_active() and (owner or not _AI_PUBLIC_OFF) and DEEPSEEK_API_KEY:
        d = ask_deepseek(prompt, system, max_tokens or 2000)
        if d is not None and not str(d).startswith("⚠️"):
            return d + "\n\n💎 *Модель:* DeepSeek (платный — бесплатные были недоступны)\n" + _ai_left()
    # 5) 💰 GPT (ПЛАТНЫЙ, общее правило владельца 05.07: после DeepSeek — GPT) — только если DeepSeek недоступен/не потянул
    if not ai_kill_active() and (owner or not _AI_PUBLIC_OFF) and OPENAI_API_KEY:
        gp = ask_gpt(prompt, system, max_tokens or 900)
        if gp is not None and not str(gp).startswith("⚠️"):
            return gp + f"\n\n💰 *Модель:* GPT {OPENAI_MODEL} (платный — DeepSeek недоступен)\n" + _ai_left()
    return None

# ── 🌩 ГЕРМЕС-ОБЛАКО: релей Хермес-бота, когда ПК выключен (13.07.2026, закон одной личности) ──
_hermes_cache = {"soul": "", "mem": "", "ts": 0.0}
_hermes_hist = collections.deque(maxlen=8)   # короткая история диалога в облаке (роль, текст)


def _hermes_soul_mem():
    """Душа+память Гермеса из ветки data (hermes/), кэш 10 мин. Нет файлов → минимальная душа."""
    if time.time() - _hermes_cache["ts"] < 600 and _hermes_cache["soul"]:
        return _hermes_cache["soul"], _hermes_cache["mem"]
    soul = ""
    mem = ""
    try:
        r = requests.get(_HERMES_DATA_RAW + "HERMES_SOUL_COMPACT.md", timeout=10)
        if r.status_code == 200 and len(r.text) > 200:
            soul = r.text
    except Exception:
        pass
    try:
        r = requests.get(_HERMES_DATA_RAW + "bot_memory.json", timeout=10)
        if r.status_code == 200:
            facts = r.json().get("facts", [])[-60:]
            if facts:
                mem = "СПРАВКА о владельце (используй только к месту):\n" + "\n".join(
                    "- " + f.get("text", "")[:400] for f in facts)
    except Exception:
        pass
    if not soul:
        soul = ("Ты — Hermes, личный ассистент Анзора (обращение «сэр» или «братан»). Отвечай ТОЛЬКО "
                "по-русски, кратко и по делу. НИКОГДА не цитируй хадисы/аяты по памяти — честно скажи, "
                "что сверишься с базой, когда ПК проснётся.")
    _hermes_cache.update(soul=soul, mem=mem, ts=time.time())
    return soul, mem


def _hermes_cloud_relay():
    """Фон-тред: пульс ПК молчит >13 мин → поллим Хермес-бота и отвечаем как Гермес.
    ПК поллит сам → Telegram даёт 409 → спим (двойных ответов не бывает архитектурно)."""
    if not HERMES_BOT_TOKEN:
        print("hermes-relay: HERMES_BOT_TOKEN не задан в env — релей спит")
        return
    api = f"https://api.telegram.org/bot{HERMES_BOT_TOKEN}"
    off = None
    print("hermes-relay: запущен (страхую Гермеса, когда ПК выключен)")
    while True:
        try:
            if time.time() - _hermes_hb["ts"] < 780:   # ПК жив (пульс каждые ~2-5 мин)
                time.sleep(45)
                continue
            params = {"timeout": 25, "allowed_updates": '["message"]'}
            if off is not None:
                params["offset"] = off
            r = requests.get(api + "/getUpdates", params=params, timeout=40)
            if r.status_code == 409:   # ПК-поллер живой (пульс ещё не дошёл) → не лезем
                time.sleep(90)
                continue
            if r.status_code != 200:
                time.sleep(60)
                continue
            for upd in r.json().get("result", []):
                off = upd["update_id"] + 1
                m = upd.get("message") or {}
                txt = (m.get("text") or "").strip()
                if not txt or (m.get("chat") or {}).get("id") != HERMES_OWNER_CHAT:
                    continue
                soul, mem = _hermes_soul_mem()
                system = (soul + "\n\nСЕЙЧАС: ОБЛАЧНЫЙ РЕЖИМ — ПК владельца ВЫКЛЮЧЕН, ты отвечаешь с "
                          "бесплатного облака (Railway). Файлы/базы/локалки ПК недоступны — задачи по ним "
                          "честно записывай на «когда ПК проснётся», не выдумывай содержимое."
                          + ("\n\n" + mem if mem else ""))
                hist = "".join(f"[{r_}] {t}\n" for r_, t in _hermes_hist)
                prompt = (("Последние реплики:\n" + hist + "\n") if hist else "") + "Владелец: " + txt[:3000]
                try:
                    ans = ask_ai(prompt, system=system, owner=True) or "⚠️ Облачные мозги молчат — попробуй ещё раз."
                except Exception as e:
                    ans = f"⚠️ Ошибка облака: {str(e)[:120]}"
                _hermes_hist.append(("Владелец", txt[:400]))
                _hermes_hist.append(("Гермес", str(ans)[:400]))
                body = "🌩 Гермес (облако — ПК спит)\n\n" + str(ans)
                for chunk_start in range(0, len(body), 4000):
                    try:
                        requests.post(api + "/sendMessage",
                                      json={"chat_id": HERMES_OWNER_CHAT,
                                            "text": body[chunk_start:chunk_start + 4000]}, timeout=25)
                    except Exception:
                        pass
        except Exception:
            time.sleep(60)


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

# === C32: УМНЫЙ АССИСТЕНТ ЖУРНАЛА (технадзор-помощник). Регламент — АССИСТЕНТ_РЕГЛАМЕНТ.md ===
ASSIST_SYS = (
    "Ты — УМНЫЙ АССИСТЕНТ-ТЕХНАДЗОР в рабочем журнале проекта Muslimoon (исламское приложение: база хадисов имама Муршида, "
    "Telegram мини-апп + этот бот). С тобой общается ВЛАДЕЛЕЦ проекта. Разработчик и технадзор — Claude: он читает заявки "
    "(journal.json requests) и ошибки и ПРИНИМАЕТ МЕРЫ. Ты — связующее звено: понимаешь владельца и не даёшь его словам потеряться.\n"
    "ЗАДАЧА: понять сообщение владельца (часто КОРОТКОЕ и КОНТЕКСТНОЕ — реакция на отчёт выше: «нету её», «не работает», "
    "«почему», «опять»), и:\n"
    "• если можешь — коротко ответить по делу;\n"
    "• если нужно действие/исправление/проверка — ПОДТВЕРДИ, что передал задачу разработчику (Claude), чтобы он принял меры.\n"
    "Отвечай по-русски, коротко, по-человечески, уважительно, без воды. Не выдумывай факты.\n"
    "ВСЕГДА в самом конце добавляй ОТДЕЛЬНОЙ строкой ровно: ESCALATE: <одно предложение, что передать разработчику> — "
    "если нужно действие; либо ESCALATE: нет — если это просто вопрос/реплика без действий."
)
async def _journal_assistant(update, context, text):
    rep = update.message.reply_to_message
    ctx = ''
    if rep and (getattr(rep, 'text', None) or getattr(rep, 'caption', None)):
        ctx = "\n\nКОНТЕКСТ (сообщение, на которое отвечает владелец):\n" + (rep.text or rep.caption)[:900]
    sys_p = ASSIST_SYS
    try:
        mem = load_memory()
        if mem:
            sys_p += "\n\nКонтекст проекта:\n" + "\n".join("- " + (m.get('text', '')) for m in mem[-15:])
    except Exception:
        pass
    try:
        await update.message.reply_text("🤔 …")
    except Exception:
        pass
    ans = ask_ai("Сообщение владельца: " + text[:900] + ctx, sys_p, owner=True, max_tokens=700)
    esc = ''
    if 'ESCALATE:' in ans:
        ans, _, esc = ans.partition('ESCALATE:')
        esc = esc.strip()
    ans = ans.replace('⚡ *Модель:*', '· модель:').strip()
    try:
        await update.message.reply_text("🤝 " + ans[:1600])
    except Exception:
        pass
    if esc and esc.lower().strip(' .—-') not in ('нет', 'no', ''):
        try:
            rid = req_add("🤝 [ассистент журнала] " + esc[:400] + " | владелец: «" + text[:200] + "»")
            await context.bot.send_message(LOG_CHAT_ID, "📨 Передал разработчику (Claude) — заявка #%d: %s" % (rid, esc[:200]))
        except Exception:
            pass
    try:
        j = _journal_load(); j.setdefault("assistant_log", []).insert(0, {"d": _now_msk(), "q": text[:300], "a": ans[:300], "esc": esc[:200]})
        j["assistant_log"] = j["assistant_log"][:300]; _journal_save("assistant_log")
    except Exception:
        pass

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

def translate_matn(arabic, src="", owner=False, force=False, model_out=None):
    """Перевод матна на русский с накопительным кэшем (оригинал+перевод+источник).
    force=True — переперевести заново (минуя кэш). Длинные тексты переводим ПО АБЗАЦАМ, иначе free-модель
    часто возвращает арабский оригинал вместо перевода. Битый арабский кэш игнорируем и переводим заново.
    M177: для тафсира (src.startswith('tafsir')) пытаемся структурировать ИИ по темам перед переводом.
    model_out: если передан список — тревога-фикс (владелец, 04.07.2026): раньше ask_ai() отвечал бесплатной
    моделью, но тег «⚡ Модель» вырезался ЗДЕСЬ и терялся НАВСЕГДА — вызывающий код (API-эндпоинт перевода)
    не мог узнать, кто реально ответил, и ПО УМОЛЧАНИЮ рапортовал «DeepSeek, ключ потрачен» даже когда
    реально отвечал бесплатный Groq/Gemini. Теперь реальное имя модели кладём сюда (последний успешный вызов)."""
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
    if src and "jarh" in src.lower():   # P0-2: это ОЦЕНКА передатчика (джарх ва таʿдиль), не аят/тафсир — иначе идиомы переводятся буквально в бессмыслицу
        sysmsg = ("Ты переводишь с арабского на русский ОЦЕНКУ передатчика хадиса (джарх ва таʿдиль) — "
                  "слова учёного-критика о надёжности равия. Технические термины передавай так: "
                  "ثقة=надёжный (сикъа), صدوق=правдивый, حافظ=хафиз, ضعيف=слабый, متروك=оставленный, "
                  "كذاب=лжец, مدلس=мудаллис (приукрашиватель иснада), لين=мягкий, مجهول=неизвестный, "
                  "لم يسمع من فلان=не слышал от такого-то, روى عنه=передавал от него. "
                  "Переводи СМЫСЛ точно и понятно: если это идиома/похвала/оборот — передай значение, НЕ дословно. "
                  "Имена учёных и равиев — по-русски. Ответ на РУССКОМ, без арабских предложений, без вступлений — только перевод.")
    else:
        sysmsg = ("Ты профессиональный переводчик с арабского на русский. "
                  "Переведи текст на русский язык ПОЛНОСТЬЮ, до конца (не обрывай). "
                  "Ответ ДОЛЖЕН быть на РУССКОМ — НЕ копируй арабский, НЕ оставляй арабские предложения. "
                  "Имена и термины передавай по-русски. "
                  "Без вступлений, без пояснений, без кавычек, без указания модели — только перевод.")
    def _one(t):
        r = ask_ai("Переведи на русский:\n" + t, sysmsg, owner=owner, max_tokens=4000)
        if not r or r.startswith("❌") or r.startswith("⏸"):
            return None
        if model_out is not None:
            _mt = _neuroModelTag(r)
            if _mt:
                model_out.append(_mt)
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
            # #B-004 («Can't parse entities», 32 повтора): разметка где-то не экранирована (& / <) —
            # фолбэк шлёт БЕЗ parse_mode (Telegram не парсит теги в plain text, ошибка невозможна),
            # но сам фолбэк тоже был не защищён — второе исключение (флуд-контроль и т.п.) улетало
            # в глобальный _on_error необработанным. Теперь ловим и его.
            try:
                await update.message.reply_text(chunk)
            except Exception:
                pass

async def _снять_кнопки_модерации(bot, chat_id, message_id, задержка=300):
    """#614: «эти кнопки после входа самоудаляются» — через 5 минут снимаем клавиатуру.

    Что было: кнопок не было вовсе. Почему так, а не удалять весь пост: запись о входе — это
    журнал участников (#572), её терять нельзя; лишними становятся только рычаги, поэтому
    убираем ИМЕННО клавиатуру. Работает и без JobQueue (её в сборке Railway может не быть) —
    обычная задача событийного цикла, потому и вынесена отдельной функцией."""
    try:
        await asyncio.sleep(задержка)
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
    except Exception:
        pass


async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from telegram import InlineKeyboardButton as _КБ, InlineKeyboardMarkup as _КЛ
        chat = update.effective_chat
        member = update.chat_member
        user = member.new_chat_member.user
        now = datetime.now().strftime("%d.%m.%Y, %H:%M")
        name = user.full_name
        uid = user.id
        # #674 (владелец: «сделай кликабельный ник»): в уведомлении стояло голое имя, а у половины
        # вошедших ещё и «🔗 нет» — открыть человека было НЕЧЕМ, только копировать id руками.
        # tg://user?id= — единственная ссылка, которая работает и без @username; @username, если
        # он есть, тоже делаем ссылкой. Отсюда и parse_mode=HTML на всём сообщении, а значит все
        # подставляемые куски (имя, название чата) обязаны идти через html.escape.
        _имя = html.escape(name or str(uid))
        _ник = '<a href="tg://user?id=%d">%s</a>' % (uid, _имя)
        _польз = ('<a href="https://t.me/%s">@%s</a>' % (user.username, user.username)) if user.username else "нет"
        _чат_имя = html.escape(chat.title or "чат")
        _kb = None
        if member.new_chat_member.status == "member":
            # #572 (владелец: «добавляй теги к постам, чтобы по тегам просматривать темы»): пост шёл без хештегов,
            # в отличие от #ии/#перевод/#отзыв — отфильтровать его в истории было нельзя.
            _ctag = "#" + re.sub(r"\W+", "_", (chat.title or "чат")).strip("_")[:32]
            # #628: владелец увидел это уведомление и ответил «не может банить» — потому что
            # выгнать вошедшего было НЕЧЕМ: id есть, а команды рядом нет. Кладём готовую строку
            # прямо сюда, чтобы её оставалось только скопировать (и не выискивать id глазами).
            msg = (f"#участники #вошёл {_ctag}\n➕ {_ник}\n🔗 {_польз}\n🆔 <code>{uid}</code>\n📁 {_чат_имя}\n🕐 {now}"
                   f"\n⛔ выгнать: <code>чат бан {uid} {chat.id}</code>")
            # #614 и #660 (владелец: «куда делись кнопки бана и ограничений тут?» / «сделай чтобы
            # при входе предлагалось две кнопки — забанить и ограничить, которые могут нажимать
            # админы»). Копировать команду руками — лишний шаг, из-за которого нарушитель успевает
            # писать. Кнопки бьют по ТОМУ чату, откуда пришёл человек (id зашит в callback_data),
            # а не по чату уведомлений: они разные, и это главная ловушка этого места.
            _kb = _КЛ([[_КБ("⛔ Забанить", callback_data="mod:ban:%d:%d" % (chat.id, uid)),
                        _КБ("🔇 Ограничить", callback_data="mod:mute:%d:%d" % (chat.id, uid))]])
        elif member.new_chat_member.status in ["left", "kicked"]:
            a = "🚫 Удалён" if member.new_chat_member.status == "kicked" else "➖ Вышел"
            # #572: та же схема тегов для ухода/бана — иначе по тегу «#участники» видны были бы только приходы
            _ctag = "#" + re.sub(r"\W+", "_", (chat.title or "чат")).strip("_")[:32]
            _atag = "#удалён" if member.new_chat_member.status == "kicked" else "#вышел"
            msg = f"#участники {_atag} {_ctag}\n{a} {_ник}\n🔗 {_польз}\n🆔 <code>{uid}</code>\n📁 {_чат_имя}\n🕐 {now}"
        else: return
        try:
            _пост = await context.bot.send_message(chat_id=LOG_CHAT_ID, text=msg, parse_mode="HTML",
                                                   disable_web_page_preview=True, reply_markup=_kb)
        except Exception:
            # Запасной путь: разметка — украшение, а журнал участников — суть. Если HTML не прошёл
            # (Telegram придирчив к тегам), уведомление всё равно обязано выйти, иначе вход человека
            # пропадёт бесследно. Кнопки при этом сохраняем: они от разметки не зависят.
            _пост = await context.bot.send_message(chat_id=LOG_CHAT_ID, text=re.sub(r'<[^>]+>', '', msg),
                                                   disable_web_page_preview=True, reply_markup=_kb)
        if _kb and _пост:
            asyncio.create_task(_снять_кнопки_модерации(context.bot, LOG_CHAT_ID, _пост.message_id))
    except: pass


async def on_ctx(update, context):
    """Судьба контекста после разбора: сохранить, сжать или убрать. Решает владелец.

    Автоматика тут была бы вредна: разбор бывает и нужным надолго, и одноразовым, и знать это
    может только тот, кто его заказывал."""
    q = update.callback_query
    if (q.from_user.id if q.from_user else 0) != OWNER_ID:
        await q.answer("Эта кнопка — владельца.", show_alert=True)
        return
    try:
        _, что, ключ = (q.data or '').split(':', 2)
        chat_id = int(ключ.split('_')[0])
        реплики = dsoc_память(chat_id)
        if что == 'keep':
            итог = "💾 Оставил разбор в памяти разговора."
        elif что == 'squeeze':
            DSOC_ПАМЯТЬ[chat_id] = dsoc_ужать(реплики)
            dsoc_сохранить(силой=True)
            итог = ("🗜 Сжал: было %d ток, стало %d."
                    % (dsoc_размер(реплики), dsoc_размер(DSOC_ПАМЯТЬ[chat_id])))
        else:
            DSOC_ПАМЯТЬ[chat_id] = реплики[:-2] if len(реплики) >= 2 else []
            dsoc_сохранить(силой=True)
            итог = "✂️ Убрал разбор из памяти. Вернуть — кнопкой под снимком выше."
        await q.answer(итог[:190])
        await q.edit_message_text(итог)
    except Exception as e:
        await q.answer("Не вышло: " + str(e)[:150], show_alert=True)


async def on_neudacha(update, context):
    """Кнопка «Разобрать» под неудачей: кладёт её в очередь технадзора — ту же, через которую
    владелец зовёт живого разработчика. Один канал, а не второй такой же (З-33)."""
    q = update.callback_query
    if (q.from_user.id if q.from_user else 0) != OWNER_ID:
        await q.answer("Эта кнопка — владельца.", show_alert=True)
        return
    try:
        н = int((q.data or '').split(':', 1)[1])
        сп = _data_get(DSOC_НЕУДАЧИ_ФАЙЛ, []) or []
        з = next((x for x in сп if int(x.get('n') or 0) == н), None)
        if not з:
            await q.answer("Не нашёл эту запись.", show_alert=True)
            return
        з['разобрано'] = True
        _data_put(DSOC_НЕУДАЧИ_ФАЙЛ, сп[-200:], 'неудача #%d отдана в разбор' % н)
        dsoc_позвать_клода(з.get('чат') or LOG_CHAT_ID, None,
                           "РАЗБОР НЕУДАЧИ №%d. Причина: %s\nСпрашивали: %s\nОтветил: %s"
                           % (н, з.get('причина'), (з.get('вопрос') or '')[:500],
                              (з.get('ответ') or '')[:500]), 'владелец')
        await q.answer("Отдал технадзору на разбор.")
        await q.edit_message_text((q.message.text or '') + "\n\n🔎 Отдано технадзору на разбор.")
    except Exception as e:
        await q.answer("Не вышло: " + str(e)[:150], show_alert=True)


async def on_dsoc_back(update, context):
    """Кнопка «Вернуть как было» под уведомлением о сжатии разговора."""
    q = update.callback_query
    try:
        ключ = (q.data or "").split(":", 1)[1]
        chat_id = int(ключ.split("_")[0])
    except Exception:
        try:
            await q.answer()
        except Exception:
            pass
        return
    if (q.from_user.id if q.from_user else 0) != OWNER_ID:
        await q.answer("Эта кнопка — владельца.", show_alert=True)
        return
    try:
        сн = _data_get(DSOC_СНИМКИ_ФАЙЛ, {}) or {}
        реплики = сн.get(ключ)
        if not реплики:
            await q.answer("Снимок уже не хранится.", show_alert=True)
            return
        DSOC_ПАМЯТЬ[chat_id] = list(реплики)
        dsoc_сохранить(силой=True)
        await q.answer("Вернул разговор целиком.")
        await q.edit_message_text(
            (q.message.text or "") + "\n↩️ Возвращено владельцем: разговор снова целиком (%d ток)."
            % dsoc_размер(реплики))
    except Exception as e:
        await q.answer("Не вышло: " + str(e)[:150], show_alert=True)


# ===== #628: отказы Telegram по правам — говорим ПРИЧИНУ и ЧТО ДЕЛАТЬ =====
# Под уведомлением о входе владелец увидел приписку «⚠️ не смог забанить: Not enough rights to
# restrict/unrestrict chat member» и написал «не может банить». Из этой фразы не видно ни причины,
# ни что делать, ни надо ли вообще что-то чинить — а за ней прячутся ДВА разных случая, и действия
# у них противоположные:
#   (а) боту не выдали право «Блокировка участников» — лечится тумблером за полминуты;
#   (б) цель — администратор или владелец чата, а таких Telegram не даёт ограничивать НИКОМУ,
#       и чинить нечего: сначала снимается админка.
# Разбирать это по одной подстроке ошибки ненадёжно: Telegram на «нет прав» и на «цель — админ»
# отвечает по-разному в разных методах и версиях, а CHAT_ADMIN_REQUIRED вообще читается наоборот
# (это требование прав к САМОМУ БОТУ, а не признак того, что цель — админ; на этом здесь уже
# один раз ошиблись). Поэтому при отказе СПРАШИВАЕМ у Telegram факты — статус цели, затем статус
# и тумблеры бота, — а текст ошибки берём лишь как подсказку.
_МОД_БОТ_ЮЗЕР = "@muslimoontt_bot"


def _мод_инструкция(где):
    """Куда идти владельцу чата, чтобы бот смог банить. Путь — дословно по меню Telegram."""
    return ("🛠 Что сделать (владелец чата, полминуты):\n"
            "Telegram → чат «%s» → тапнуть по названию сверху → «Управление группой» →\n"
            "«Администраторы» → выбрать %s (или «Добавить администратора») →\n"
            "включить право «Блокировка участников» → Сохранить.\n"
            "Если бот уже администратор — проверь именно это право: без него остальные\n"
            "не помогают, Telegram всё равно отказывает."
            % (где, _МОД_БОТ_ЮЗЕР))


async def _мод_отказ(bot, чат, кого, ошибка, действие="ограничить"):
    """Почему не вышло забанить/ограничить — по-русски. Возвращает (кратко, подробно).

    «кратко» — для всплывающего окна кнопки: Telegram режет его на 200 символах, поэтому туда
    кладём только причину. «подробно» — та же причина плюс что именно делать; его отправляем
    сообщением, где длина не жмёт и текст остаётся перед глазами, а не гаснет через секунду.
    """
    _текст = str(ошибка)
    _низ = _текст.lower()
    try:
        _назв = getattr(await bot.get_chat(чат), "title", None) or str(чат)
    except Exception:
        _назв = str(чат)
    # Сначала случай (б): если цель — админ, никакие права бота не помогут, и звать владельца
    # чата к тумблерам было бы враньём — он бы их включил и увидел ровно тот же отказ.
    _цель = ""
    try:
        _цель = getattr(await bot.get_chat_member(чат, кого), "status", "") or ""
    except Exception:
        pass
    if _цель == "creator" or "chat owner" in _низ:
        _к = "Это ВЛАДЕЛЕЦ чата — его не может ограничить никто, так устроен Telegram. Чинить нечего."
        _п = ("🤷 Ограничить нельзя: %d — ВЛАДЕЛЕЦ чата «%s».\n"
              "Владельца чата не может забанить никто, даже администраторы: это правило самого\n"
              "Telegram. С правами бота всё в порядке — включать нечего." % (кого, _назв))
        return _к[:190], _п
    if _цель == "administrator" or "user_admin_invalid" in _низ or "is an administrator" in _низ:
        _к = "Это АДМИНИСТРАТОР чата — таких Telegram ограничивать не даёт никому. Сними админку и повтори."
        _п = ("🤷 Ограничить нельзя: %d — АДМИНИСТРАТОР чата «%s».\n"
              "Telegram запрещает ограничивать администраторов кому бы то ни было, права бота\n"
              "тут ни при чём — добавлять их бессмысленно.\n"
              "Если забанить всё-таки надо: Управление группой → Администраторы → снять админку\n"
              "с этого человека, потом нажать «Забанить» ещё раз." % (кого, _назв))
        return _к[:190], _п
    # Теперь случай (а): чего не хватает самому боту. «Не админ вовсе» и «админ без тумблера» —
    # это разные экраны у владельца чата, поэтому разводим их, а не пишем общее «нет прав».
    _мой, _можно = "", False
    try:
        _я = await bot.get_chat_member(чат, bot.id)
        _мой = getattr(_я, "status", "") or ""
        _можно = bool(getattr(_я, "can_restrict_members", False))
    except Exception:
        pass
    if _мой and _мой != "administrator":
        _к = ("Бот не администратор в «%s» — банить он не может. Назначь его админом с правом "
              "«Блокировка участников»." % _назв)
        _п = ("⛔ Не вышло %s %d: бот НЕ администратор чата «%s» (он там обычный участник).\n"
              "Ограничивать участников Telegram разрешает только администраторам.\n\n"
              % (действие, кого, _назв)) + _мод_инструкция(_назв)
        return _к[:190], _п
    if _мой == "administrator" and not _можно:
        _к = ("У бота в «%s» выключено право «Блокировка участников» — включи его, и бан заработает."
              % _назв)
        _п = ("⛔ Не вышло %s %d: боту в «%s» не выдано право «Блокировка участников».\n"
              "Администратором он там уже стоит, но именно этот тумблер выключен — Telegram\n"
              "отказывает. Это не сбой кода: права раздаёт только владелец чата.\n\n"
              % (действие, кого, _назв)) + _мод_инструкция(_назв)
        return _к[:190], _п
    if "user not found" in _низ or "participant_id_invalid" in _низ or "user_not_participant" in _низ:
        _к = "Telegram не знает такого участника в «%s». Проверь id — он в строке «🆔» уведомления." % _назв
        _п = ("🤷 Не вышло %s %d: Telegram отвечает, что такого участника в «%s» нет.\n"
              "Скорее всего перепутан id — брать его надо из строки «🆔» уведомления о входе.\n"
              "Дословный ответ Telegram: %s" % (действие, кого, _назв, _текст[:120]))
        return _к[:190], _п
    if "supergroup" in _низ and "available" in _низ:
        _к = "«%s» — обычная старая группа, в таких Telegram банить не умеет. Нужна супергруппа." % _назв
        _п = ("🤷 Не вышло %s %d: «%s» — обычная группа, а не супергруппа.\n"
              "В обычных группах Telegram банить через бота не даёт. Группа превращается в\n"
              "супергруппу сама, как только у неё включают историю для новых участников или\n"
              "публичную ссылку.\nДословный ответ Telegram: %s"
              % (действие, кого, _назв, _текст[:120]))
        return _к[:190], _п
    if ("not enough rights" in _низ or "need administrator" in _низ
            or "chat_admin_required" in _низ or "can_restrict" in _низ):
        # Сюда попадаем, когда Telegram отказал по правам, а опрос статусов выше ничего не выявил
        # (бывает: чат не опросился, или права переключили прямо в эту секунду).
        _к = "Боту не хватает прав на бан в «%s». Проверь право «Блокировка участников»." % _назв
        _п = ("⛔ Не вышло %s %d: Telegram отказал по правам в «%s».\n"
              "Почти всегда за этим стоит выключенное у бота право «Блокировка участников».\n"
              "Дословный ответ Telegram: %s\n\n"
              % (действие, кого, _назв, _текст[:120])) + _мод_инструкция(_назв)
        return _к[:190], _п
    # Неизвестная беда: причину не выдумываем, но и голым английским не отделываемся — говорим,
    # что именно не получилось и куда смотреть дальше.
    _к = "Не вышло %s %d в «%s» — подробности сообщением ниже." % (действие, кого, _назв)
    _п = ("⚠️ Не вышло %s %d в «%s» — причина не опознана.\n"
          "Дословный ответ Telegram: %s\n"
          "Проверить права бота: «права %s»." % (действие, кого, _назв, _текст[:200], чат))
    return _к[:190], _п


async def on_moderate(update, context):
    """#614/#660: кнопки «Забанить»/«Ограничить» под уведомлением о входе.

    Кто может нажимать: владелец и АДМИНЫ ТОГО чата, куда человек вошёл (проверяем у Telegram
    каждый раз — членство в чате уведомлений ничего не значит). Почему не «кто угодно из
    лог-чата»: рычаг реально банит живого человека, и цена ошибки выше, чем удобство.

    Права самого бота Telegram выдаёт только руками владельца чата, кодом это не обходится
    (см. разбор #628 в handle) — поэтому отказ показываем не «ошибкой», а инструкцией.
    """
    q = update.callback_query
    try:
        _, что, _чат, _кого = (q.data or "").split(":")
        _чат, _кого = int(_чат), int(_кого)
    except Exception:
        try: await q.answer()
        except Exception: pass
        return
    _кто = q.from_user.id if q.from_user else 0
    if _кто != OWNER_ID:
        try:
            _м = await context.bot.get_chat_member(_чат, _кто)
            _админ = getattr(_м, "status", "") in ("creator", "administrator")
        except Exception:
            _админ = False
        if not _админ:
            await q.answer("Эти кнопки — для админов чата.", show_alert=True)
            return
    try:
        if что == "ban":
            await context.bot.ban_chat_member(chat_id=_чат, user_id=_кого)
            _итог = "⛔ Забанен админом (вернуть: «чат разбан %d %d»)" % (_кого, _чат)
            _алерт = "Забанен."
        elif что == "mute":
            # Второй ряд кнопок — выбор, ЧЕГО именно лишить. Беда бывает разной: залил картинок
            # — незачем лишать речи; спамит голосовыми — пусть пишет текстом.
            _ряды = [[_КБ("🔇 час", callback_data="mod:m_all1h:%d:%d" % (_чат, _кого)),
                      _КБ("🔇 сутки", callback_data="mod:m_all1d:%d:%d" % (_чат, _кого)),
                      _КБ("🔇 навсегда", callback_data="mod:m_allx:%d:%d" % (_чат, _кого))],
                     [_КБ("🖼 без медиа", callback_data="mod:m_media:%d:%d" % (_чат, _кого)),
                      _КБ("🎤 без голосовых", callback_data="mod:m_voice:%d:%d" % (_чат, _кого))],
                     [_КБ("🔗 без ссылок", callback_data="mod:m_links:%d:%d" % (_чат, _кого)),
                      _КБ("✅ снять всё", callback_data="mod:m_free:%d:%d" % (_чат, _кого))],
                     [_КБ("⛔ Забанить", callback_data="mod:ban:%d:%d" % (_чат, _кого))]]
            try:
                await q.edit_message_reply_markup(reply_markup=_КЛ(_ряды))
            except Exception:
                pass
            await q.answer("Выбери, чего лишить.")
            return
        elif что.startswith("m_"):
            from telegram import ChatPermissions as _ЧП
            вид = что[2:]
            срок = None
            if вид == "all1h":
                срок = datetime.now() + timedelta(hours=1)
            elif вид == "all1d":
                срок = datetime.now() + timedelta(days=1)
            # Telegram: не переданное поле считается запрещённым, поэтому разрешения
            # перечисляем ПОЛНОСТЬЮ каждый раз — иначе «без голосовых» тихо отберёт и всё
            # остальное. Это главная ловушка restrict_chat_member.
            полные = dict(can_send_messages=True, can_send_audios=True, can_send_documents=True,
                          can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                          can_send_voice_notes=True, can_send_polls=True,
                          can_send_other_messages=True, can_add_web_page_previews=True,
                          can_change_info=False, can_invite_users=True, can_pin_messages=False)
            if вид.startswith("all"):
                права = dict(полные, **{k: False for k in полные if k.startswith("can_send")})
                права["can_add_web_page_previews"] = False
                _итог = {"all1h": "🔇 Немой на час", "all1d": "🔇 Немой на сутки",
                         "allx": "🔇 Немой без срока"}[вид] + " (админом)"
            elif вид == "media":
                права = dict(полные, can_send_photos=False, can_send_videos=False,
                             can_send_documents=False, can_send_audios=False)
                _итог = "🖼 Без медиа (текст можно) — админом"
            elif вид == "voice":
                права = dict(полные, can_send_voice_notes=False, can_send_video_notes=False)
                _итог = "🎤 Без голосовых и кружков — админом"
            elif вид == "links":
                права = dict(полные, can_add_web_page_previews=False,
                             can_send_other_messages=False)
                _итог = "🔗 Без ссылок, стикеров и гифок — админом"
            else:                                   # free — снять всё
                права = полные
                _итог = "✅ Ограничения сняты админом"
            await context.bot.restrict_chat_member(chat_id=_чат, user_id=_кого,
                                                   permissions=_ЧП(**права), until_date=срок)
            _алерт = _итог
        else:
            from telegram import ChatPermissions as _ЧП
            await context.bot.restrict_chat_member(
                chat_id=_чат, user_id=_кого,
                permissions=_ЧП(can_send_messages=False, can_send_other_messages=False,
                                can_add_web_page_previews=False),
                until_date=datetime.now() + timedelta(days=1))
            _итог = "🔇 Ограничен на сутки админом"
            _алерт = "Ограничен на сутки."
        await q.answer(_алерт)
        try:
            await q.edit_message_text((q.message.text_html or q.message.text or "") + "\n" + _итог,
                                      parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            try: await q.edit_message_reply_markup(reply_markup=None)
            except Exception: pass
    except Exception as e:
        # #628: раньше отсюда всплывало «Не вышло: Not enough rights to restrict/unrestrict chat
        # member» — техническая фраза, по которой не понять ни причины, ни что делать. Причину
        # выясняет общий разборщик (_мод_отказ): он отличает «боту не дали право» от «цель —
        # админ, таких нельзя вообще», и говорит это по-русски.
        try:
            _кратко, _подробно = await _мод_отказ(
                context.bot, _чат, _кого, e, "забанить" if что == "ban" else "ограничить")
        except Exception:
            _кратко = _подробно = "Не вышло: " + str(e)[:150]
        try:
            await q.answer(_кратко, show_alert=True)
        except Exception:
            pass
        # Всплывашка гаснет через секунду и видна только нажавшему, а инструкция нужна владельцу
        # чата и позже. Кладём её отдельным сообщением рядом с уведомлением; клавиатуру НЕ снимаем —
        # после выдачи прав тем же рычагом можно повторить.
        try:
            await q.message.reply_text(_подробно, disable_web_page_preview=True)
        except Exception:
            pass

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

# ===== Видео-пересказ YouTube (З-10): команда «видео» reply-ом в чате @jamaat_ru. БЕЗ новых зависимостей — субтитры через requests. =====
import re as _re_v
_VIDEO_LAST = {}
def _yt_id(t):
    if not t: return None
    m = _re_v.search(r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)([A-Za-z0-9_-]{11})', t)
    return m.group(1) if m else None
def _fmt_ts(sec): return f"{sec//60}:{sec%60:02d}"
def _yt_transcript(vid):
    try:
        h = {'User-Agent':'Mozilla/5.0','Accept-Language':'ru,ar,en'}
        html = requests.get(f'https://www.youtube.com/watch?v={vid}', headers=h, timeout=20).text
        m = _re_v.search(r'"captionTracks":(\[.*?\])', html)
        if not m: return None
        tracks = json.loads(m.group(1))
        if not tracks: return None
        pick = None
        for lang in ('ru','ar','en'):
            for t in tracks:
                if t.get('languageCode','').startswith(lang): pick = t; break
            if pick: break
        pick = pick or tracks[0]
        data = requests.get(pick['baseUrl'] + '&fmt=json3', headers=h, timeout=20).json()
        out = []
        for ev in data.get('events', []):
            segs = ev.get('segs')
            if not segs: continue
            txt = ''.join(s.get('utf8', '') for s in segs).strip()
            if txt: out.append((int(ev.get('tStartMs', 0) / 1000), txt))
        return out or None
    except Exception:
        return None
def _yt_cost_est(tr):
    chars = sum(len(t) for _, t in tr)
    return (chars/3 + 200)/1e6*0.27 + 2500/1e6*1.10
def _yt_summarize(tr, brief):
    body = "\n".join(f"[{_fmt_ts(s)}] {t}" for s, t in tr)[:45000]
    if brief:
        sysp = "Краткий пересказ видео на русском (5-8 предложений), с ключевыми тайм-кодами [мин:сек]."
        pr = "Краткий русский пересказ этого видео по субтитрам:\n\n" + body
    else:
        sysp = "Подробный пересказ+перевод видео на русский: по разделам, с тайм-кодами [мин:сек] в начале каждого блока."
        pr = "Подробный русский пересказ и перевод этого видео по субтитрам (с тайм-кодами по разделам):\n\n" + body
    ans = ask_neuro(pr, sysp, max_tokens=3000)
    if not ans:
        try: ans = ask_gemini(pr, sysp)
        except Exception: ans = None
    return ans
def _tts_mp3(text):
    """Бесплатная озвучка текста в MP3 (gTTS, русский, без ключа). None при сбое."""
    try:
        from gtts import gTTS
        import tempfile
        text = (text or "").strip()[:8000]
        if not text: return None
        fp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False); fp.close()
        gTTS(text=text, lang="ru").save(fp.name)
        return fp.name
    except Exception:
        return None

# ===== 💎 НИШТЯЧОК (владелец 03.07.2026, С52): вытащить пользу из текста/видео(YouTube)/ссылки/аудио-видео-сообщения,
# оформить структурированным постом (ИИ, бесплатные→DeepSeek как везде) и отправить в тот же чат/канал (напр. Muslim Live).
# Пока ПЕРВАЯ версия — владелец/Claude проверяют результаты вручную, промпт будет дорабатываться по фидбеку.
_NISHT_BUF = {}   # chat_id -> [Message, ...] между «ништячок начало» и «ништячок конец»
NISHT_DRAFT_MARK = "🔍 ЧЕРНОВИК ништячка"   # владелец 03.07.2026: черновик в jamaat_ru перед публикацией в Muslim Live (анти-ложное-срабатывание)
NISHT_DRAFTS_FILE = "nishtyaki_drafts.json"
MUSLIM_LIVE_CHAT = "@muslimlive"   # https://t.me/muslimlive — публикация по @username, бот должен быть админом там

async def _nisht_extract_one(msg):
    """Достаёт (текст, описание_источника) из ОДНОГО телеграм-сообщения любого типа. (None, None) если нечего взять."""
    t = (msg.text or msg.caption or "").strip()
    vid = _yt_id(t) if t else None
    if vid:
        tr = _yt_transcript(vid)
        if tr:
            body = "\n".join(f"[{_fmt_ts(s)}] {tx}" for s, tx in tr)[:12000]
            return body, f"YouTube ({t.strip()[:80]})"
    fobj = msg.audio or msg.voice or msg.video or (msg.document if (msg.document and (msg.document.mime_type or "").startswith(("audio", "video"))) else None)
    if fobj:
        try:
            f = await fobj.get_file()
            ext = ".ogg"
            ok_ext = (".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".oga", ".ogg", ".wav", ".webm")
            if msg.voice: ext = ".ogg"
            elif msg.video: ext = ".mp4"
            elif msg.audio: ext = os.path.splitext(getattr(msg.audio, "file_name", "") or "")[1] or ("." + (getattr(msg.audio, "mime_type", "") or "").split("/")[-1])
            elif msg.document: ext = os.path.splitext(getattr(msg.document, "file_name", "") or "")[1] or ".ogg"
            if (ext or "").lower() not in ok_ext: ext = ".ogg"
            src = f"/tmp/nisht_{f.file_id}{ext}"
            await f.download_to_drive(src)
            txt = await asyncio.get_event_loop().run_in_executor(None, transcribe_audio, src)
            try: os.remove(src)
            except Exception: pass
            if txt and txt.strip():
                return txt.strip(), "аудио/видео (расшифровка Whisper)" + (f": {t}" if t else "")
        except Exception:
            pass
    # #546/#524 (владелец: реплай «Ништячок» на PDF → «не смог извлечь содержимое»): документы брались ТОЛЬКО
    # с mime audio/video, а PDF/txt молча игнорировались. Теперь читаем и их.
    _doc = getattr(msg, "document", None)
    if _doc:
        _mt = (getattr(_doc, "mime_type", "") or "").lower()
        _fn = (getattr(_doc, "file_name", "") or "").lower()
        _ispdf = ("pdf" in _mt) or _fn.endswith(".pdf")
        _istxt = _mt.startswith("text/") or _fn.endswith((".txt", ".md", ".csv", ".json"))
        if _ispdf or _istxt:
            try:
                _f = await _doc.get_file()
                _p = f"/tmp/nisht_{_f.file_id}" + (".pdf" if _ispdf else ".txt")
                await _f.download_to_drive(_p)
                _body = ""
                if _ispdf:
                    try:
                        from pypdf import PdfReader          # лёгкая, чистый python; нет в окружении → просто пропустим
                    except Exception:
                        try:
                            from PyPDF2 import PdfReader
                        except Exception:
                            PdfReader = None
                    if PdfReader:
                        try:
                            _rd = PdfReader(_p)
                            _body = "\n".join((pg.extract_text() or "") for pg in _rd.pages[:40])
                        except Exception:
                            _body = ""
                else:
                    try:
                        _body = open(_p, encoding="utf-8", errors="replace").read()
                    except Exception:
                        _body = ""
                try: os.remove(_p)
                except Exception: pass
                _body = re.sub(r"\s+\n", "\n", (_body or "")).strip()[:14000]
                if len(_body) > 40:
                    _nm = getattr(_doc, "file_name", "") or ("PDF" if _ispdf else "файл")
                    return _body, f"документ ({_nm[:60]})" + (f": {t}" if t else "")
            except Exception:
                pass
    m = re.search(r'https?://\S+', t) if t else None
    if m and not vid:
        try:
            page = requests.get(m.group(0), headers={"User-Agent": "Mozilla/5.0"}, timeout=15).text
            page = re.sub(r'<script[^>]*>.*?</script>', ' ', page, flags=re.S | re.I)
            page = re.sub(r'<style[^>]*>.*?</style>', ' ', page, flags=re.S | re.I)
            page = re.sub(r'<[^>]+>', ' ', page)
            import html as _htmlmod
            page = re.sub(r'\s+', ' ', _htmlmod.unescape(page)).strip()[:12000]
            if page: return page, f"страница ({m.group(0)[:80]})"
        except Exception:
            pass
    if t:
        return t, "текст"
    return None, None

def _nisht_strip_model_tag(ans):
    return re.split(r'\n\n[⚡💎🆓🧠]\s*\*?Модель', ans or "")[0].strip()

def _tg_msg_link(chat_id, message_id):
    """Ссылка на исходное сообщение (внутренний формат t.me/c/... — работает у тех, кто уже в чате)."""
    try:
        cid = str(chat_id)
        if cid.startswith('-100') and message_id:
            return f"https://t.me/c/{cid[4:]}/{message_id}"
    except Exception:
        pass
    return None

async def _nisht_finish(reply_msg, chat_id, context, messages, comment):
    texts = []
    for m in messages:
        tx, src = await _nisht_extract_one(m)
        if tx: texts.append(f"[{src}]\n{tx}")
    if not texts:
        await reply_msg.reply_text("❌ Не смог извлечь содержимое — ни текста, ни аудио/видео, ни ссылки не нашёл.")
        return
    raw = "\n\n---\n\n".join(texts)[:20000]
    sysp = ("Ты — редактор исламского Telegram-канала. Из присланного материала (текст/расшифровка аудио или видео/статья по ссылке) "
            "извлеки САМУЮ ПОЛЕЗНУЮ суть и оформи КРАСИВЫМ структурированным постом на русском: короткий цепляющий заголовок эмодзи+текст, "
            "затем суть по пунктам или связным абзацем (100-150 слов), без искажения смысла и без отсебятины от себя. "
            "ВАЖНО: если в материале упоминаются конкретные хадисы/аяты/доводы учёных как источник мысли — ОБЯЗАТЕЛЬНО сохрани их "
            "(название сборника, номер, имя автора/учёного) в посте, не пересказывай своими словами без ссылки на первоисточник. "
            "Если материал явно неточен в вероубеждении/фикхе — не выдавай это как истину, отметь честно, что не проверено. Пиши уважительно.")
    pr = f"Материал:\n\n{raw}"
    if comment: pr += f"\n\nПояснение автора (что выделить/учесть): {comment}"
    ans = ask_ai(pr, sysp, owner=True, max_tokens=1200)
    if not ans:
        await reply_msg.reply_text("❌ ИИ не смог обработать (все модели сейчас недоступны). Попробуй позже.")
        return
    model_name = _neuroModelTag(ans) or 'DeepSeek'
    clean = _nisht_strip_model_tag(ans)
    src_link = _tg_msg_link(chat_id, getattr(reply_msg, 'message_id', None))
    footer = f"\n\n— 🤖 составлено ботом Muslimoon (модель: {model_name}) · {_now_msk()}"
    if src_link:
        footer += f" · [источник]({src_link})"
    footer += "\n_первое время проверяется вручную владельцем/Клодом_"
    post = "💎 " + clean + footer

    # #ЧЕРНОВИК (владелец 03.07.2026): «как исключить ложное срабатывание? может сначала пост ответом слать,
    # а если норм — отвечаю "в муслим лайв", если ложное — просто удаляю». Работает ТОЛЬКО для jamaat_ru
    # (в канале Muslim Live и в личке ништячок публикуется сразу — там ложное срабатывание не так критично).
    if JAMAAT_RU_CHAT_ID and chat_id == JAMAAT_RU_CHAT_ID:
        draft_text = (f"{NISHT_DRAFT_MARK}\n\n{post}\n\n———\n"
                      f"👉 Если ОК — ответь на это сообщение «в муслим лайв» (или «да») — опубликую в Muslim Live.\n"
                      f"👉 Если ЛОЖНОЕ срабатывание — просто удали это сообщение, ничего дальше не произойдёт.")
        try:
            sent = await context.bot.send_message(chat_id, draft_text, parse_mode="Markdown")
        except Exception:
            sent = await context.bot.send_message(chat_id, re.sub(r'[*_`\[\]()]', '', draft_text))
        try:
            arr = _data_get(NISHT_DRAFTS_FILE, []) or []
            arr.append({"id": len(arr) + 1, "d": _now_msk(), "chat_id": chat_id, "draft_message_id": getattr(sent, 'message_id', None),
                        "post": post, "raw": raw[:4000], "model": model_name, "src_link": src_link, "comment": comment, "published": False})
            _data_put(NISHT_DRAFTS_FILE, arr, f"черновик ништячка #{len(arr)}")
        except Exception:
            pass
        return

    try:
        sent = await context.bot.send_message(chat_id, post, parse_mode="Markdown")
    except Exception:
        sent = await context.bot.send_message(chat_id, re.sub(r'[*_`\[\]()]', '', post))
    try:
        arr = _data_get("nishtyaki.json", []) or []
        arr.append({"id": len(arr) + 1, "d": _now_msk(), "raw": raw[:4000], "post": ans, "chat": chat_id, "comment": comment,
                    "model": model_name, "src_link": src_link, "post_message_id": getattr(sent, 'message_id', None)})
        _data_put("nishtyaki.json", arr, f"ништячок #{len(arr)}")
    except Exception:
        pass
    # #ПЕРЕСЫЛКА (владелец 03.07.2026): пост из Muslim Live → форвардом в JAMAAT MUSLIMIN (jamaat_ru).
    # Работает ТОЛЬКО если пост создан в Muslim Live (не в личке/другом чате) и известен id группы (JAMAAT_RU_CHAT_ID).
    try:
        if JAMAAT_RU_CHAT_ID and chat_id != JAMAAT_RU_CHAT_ID and getattr(sent, 'message_id', None):
            await context.bot.forward_message(JAMAAT_RU_CHAT_ID, chat_id, sent.message_id)
    except Exception:
        pass

async def _nisht_confirm_dispatch(update, context):
    """Реплай на черновик ништячка (NISHT_DRAFT_MARK) со словом подтверждения → публикует в Muslim Live (@muslimlive)."""
    if not is_owner(update):
        return False
    msg = update.effective_message
    if not msg or not msg.reply_to_message:
        return False
    rt = msg.reply_to_message
    if not (rt.text or rt.caption or '').startswith(NISHT_DRAFT_MARK):
        return False
    text = (msg.text or '').strip().lower()
    if text not in ("в муслим лайв", "муслим лайв", "да", "ок", "отправить", "публикуй", "опубликуй"):
        return False
    try:
        arr = _data_get(NISHT_DRAFTS_FILE, []) or []
        draft = next((d for d in arr if d.get("draft_message_id") == rt.message_id and not d.get("published")), None)
        if not draft:
            await msg.reply_text("⚠️ Не нашёл этот черновик (может, уже опубликован или устарел).")
            return True
        try:
            sent = await context.bot.send_message(MUSLIM_LIVE_CHAT, draft["post"], parse_mode="Markdown")
        except Exception:
            sent = await context.bot.send_message(MUSLIM_LIVE_CHAT, re.sub(r'[*_`\[\]()]', '', draft["post"]))
        draft["published"] = True
        _data_put(NISHT_DRAFTS_FILE, arr, f"черновик #{draft['id']} опубликован")
        try:
            arr2 = _data_get("nishtyaki.json", []) or []
            arr2.append({"id": len(arr2) + 1, "d": _now_msk(), "raw": draft.get("raw", ""), "post": draft["post"], "chat": "Muslim Live (из черновика jamaat_ru)",
                        "comment": draft.get("comment", ""), "model": draft.get("model", ""), "src_link": draft.get("src_link"), "post_message_id": getattr(sent, 'message_id', None)})
            _data_put("nishtyaki.json", arr2, "ништячок из черновика")
        except Exception:
            pass
        # #530 (владелец: «итогом выложи готовый пост в Муслим лайв С ПЕРЕСЫЛКОЙ в джамаат ру»): прямой путь
        # _nisht_finish форвардит пост, а публикация ИЗ ЧЕРНОВИКА этот шаг теряла — в jamaat_ru оставался только черновик.
        fwd530 = False
        try:
            if JAMAAT_RU_CHAT_ID and getattr(sent, 'message_id', None):
                await context.bot.forward_message(JAMAAT_RU_CHAT_ID, MUSLIM_LIVE_CHAT, sent.message_id)
                fwd530 = True
        except Exception:
            pass
        await msg.reply_text("✅ Опубликовано в Muslim Live." + (" ↪️ Переслано в JAMAAT MUSLIMIN." if fwd530 else " ⚠️ Переслать в jamaat_ru не смог — перешли вручную."))
    except Exception as e:
        await msg.reply_text(f"❌ Не смог опубликовать: {str(e)[:150]}")
    return True

# ===== ✂️ ВЫРЕЗАТЬ ФРАГМЕНТ + КОНСПЕКТ + ПЕРЕСКАЗ (владелец 03.07.2026): реплай на аудио/видео —
# «вырежи <начало> по <конец|конец>» → режет сегмент, точная расшифровка (Whisper) файлом .md + грамотный
# пересказ с доводами/источниками (файлом .md, если длинный). =====
_CUT_RE = re.compile(r'^вырежи\s+(?:с\s+)?([\d:\.\s]+?)\s*(?:по|до|[-—])\s*(конец|[\d:\.\s]+)\s*$', re.I)

def _parse_hms(s):
    """'1:57:00' / '1 57 00' / '57:00' / '95' → секунды. None если не разобрал."""
    s = (s or '').strip().replace('.', ':')
    parts = [p for p in re.split(r'[:\s]+', s) if p]
    try:
        parts = [int(p) for p in parts]
    except Exception:
        return None
    if not parts:
        return None
    if len(parts) == 3: h, m, sec = parts
    elif len(parts) == 2: h = 0; m, sec = parts
    elif len(parts) == 1: h = 0; m = 0; sec = parts[0]
    else: return None
    return h * 3600 + m * 60 + sec

async def _audio_cut_dispatch(update, context):
    if not is_owner(update):
        return False
    msg = update.effective_message
    if not msg or not msg.reply_to_message:
        return False
    text = (msg.text or '').strip()
    m = _CUT_RE.match(text)
    if not m:
        return False
    rep = msg.reply_to_message
    fobj = rep.audio or rep.voice or rep.video or (rep.document if (rep.document and (rep.document.mime_type or '').startswith(('audio', 'video'))) else None)
    if not fobj:
        await msg.reply_text("❌ Ответь этой командой (реплаем) на аудио/видео сообщение.")
        return True
    start_s = _parse_hms(m.group(1))
    end_raw = m.group(2).strip().lower()
    if start_s is None:
        await msg.reply_text("❌ Не разобрал начало отрезка — формат «1:57:00» или «1 57 00».")
        return True
    st = await msg.reply_text("✂️ Вырезаю фрагмент, расшифровываю и делаю конспект… (может занять минуту-другую)")
    src = cut_path = None
    try:
        try:
            f = await fobj.get_file()
        except Exception as e:
            if "too big" in str(e).lower() or "file is too big" in str(e).lower():
                await st.edit_text("❌ Файл больше 20 МБ — обычный Bot API не даёт его скачать (ограничение Telegram, не наше). "
                                    "Для длинных записей (часовой эфир) нужен локальный Bot API сервер — это отдельная задача на будущее, скажи если нужно поднять.")
                return True
            raise
        ext = ".ogg" if rep.voice else (".mp4" if rep.video else ".mp3")
        src = f"/tmp/cutsrc_{f.file_id}{ext}"
        await f.download_to_drive(src)
        from pydub import AudioSegment
        audio = AudioSegment.from_file(src)
        end_s = (len(audio) / 1000.0) if end_raw in ("конец", "до конца", "end") else _parse_hms(end_raw)
        if end_s is None:
            await st.edit_text("❌ Не разобрал конец отрезка — формат «1:57:00», «конец» или «до конца».")
            return True
        seg = audio[max(0, start_s * 1000):int(end_s * 1000)]
        if len(seg) < 500:
            await st.edit_text("❌ Получился пустой/слишком короткий отрезок — проверь тайм-коды.")
            return True
        cut_path = f"/tmp/cutseg_{f.file_id}.mp3"
        seg.export(cut_path, format="mp3")
        txt = await asyncio.get_event_loop().run_in_executor(None, transcribe_audio, cut_path)
        if not txt or not txt.strip():
            await st.edit_text("❌ Не удалось расшифровать вырезанный фрагмент (нужен OPENAI_API_KEY/Whisper).")
            return True
        sysp = ("Ты — редактор конспектов лекций по науке хадиса на русском. Дай грамотный пересказ своими словами "
                "по присланной расшифровке, ОБЯЗАТЕЛЬНО указывая доводы/источники/имена учёных и хадисы/аяты, если они упоминались "
                "(с номерами и сборниками, если названы). Не выдумывай ссылки, которых не было в тексте.")
        retell = ask_ai(f"Расшифровка фрагмента:\n\n{txt}", sysp, owner=True, max_tokens=1800) or ""
        retell_clean = _nisht_strip_model_tag(retell) if retell else "(ИИ недоступен — только конспект ниже)"
        from io import BytesIO
        label = f"{m.group(1).strip()}–{m.group(2).strip()}"
        conspect_md = f"# Точный конспект фрагмента ({label})\n\n{txt}\n"
        bio1 = BytesIO(conspect_md.encode("utf-8")); bio1.name = "конспект.md"
        await context.bot.send_document(update.effective_chat.id, document=bio1, caption=f"📝 Точная расшифровка ({label})")
        if len(retell_clean) > 3500:
            bio2 = BytesIO((f"# Пересказ фрагмента ({label})\n\n" + retell_clean).encode("utf-8")); bio2.name = "пересказ.md"
            await context.bot.send_document(update.effective_chat.id, document=bio2, caption="🧠 Грамотный пересказ с доводами")
        else:
            await context.bot.send_message(update.effective_chat.id, "🧠 Пересказ:\n\n" + retell_clean)
        await st.edit_text(f"✅ Готово: конспект+пересказ фрагмента {label}.")
    except Exception as e:
        try: await st.edit_text(f"❌ Ошибка: {str(e)[:200]}")
        except Exception: await msg.reply_text(f"❌ Ошибка: {str(e)[:200]}")
    finally:
        for p in (src, cut_path):
            try:
                if p: os.remove(p)
            except Exception:
                pass
    return True

async def _nisht_dispatch(update, context):
    """Общий разбор команды «ништячок» — работает для ПРЯМЫХ ПОСТОВ В КАНАЛЕ (update.channel_post, Muslim Live),
    в группе jamaat_ru (владелец 03.07.2026 прямым текстом: «одиночный ништячок — сразу в jamaat_ru»),
    и в личке (там же владелец собирает несколько сообщений через «ништячок начало»/«ништячок конец»).
    #ИСПРАВЛЕНО: раньше по ошибке применил сюда то же ограничение «только канал+личка», что и для «клод» —
    это верно ТОЛЬКО для клода (сверхсекретный вызов), не для ништячка (публичный контент-инструмент).
    Возвращает True, если сообщение было ништячок-командой (или частью буфера) и обработано."""
    msg = update.effective_message
    if not msg:
        return False
    chat_id = update.effective_chat.id
    text = (msg.text or msg.caption or "").strip()
    _nm = re.match(r'^ништячок\b\s*(.*)$', text, re.I | re.S) if text else None
    if _nm:
        _nrest = _nm.group(1).strip().lower()
        if _nrest in ("начало", "старт", "start"):
            _NISHT_BUF[chat_id] = []
            await msg.reply_text("🟢 Собираю ништячок — присылай/пересылай сообщения по одному, в конце напиши «ништячок конец».")
            return True
        if _nrest in ("конец", "стоп", "финиш", "end", "готово"):
            _items = _NISHT_BUF.pop(chat_id, [])
            if not _items:
                await msg.reply_text("⚠️ Нечего собирать — не было «ништячок начало» или сообщений после него.")
                return True
            await msg.reply_text(f"🔍 Собрал {len(_items)} сообщений — извлекаю пользу (ИИ)…")
            await _nisht_finish(msg, chat_id, context, _items, "")
            return True
        if msg.reply_to_message:
            await msg.reply_text("🔍 Извлекаю пользу (ништячок)…")
            await _nisht_finish(msg, chat_id, context, [msg.reply_to_message], _nrest)
            return True
        await msg.reply_text("ℹ️ Ответь (reply) командой «ништячок» на сообщение с пользой (можно + комментарий-пояснение), либо «ништячок начало» → пришли несколько сообщений → «ништячок конец».")
        return True
    if chat_id in _NISHT_BUF and (msg.text or msg.caption or msg.audio or msg.voice or msg.video or msg.photo or msg.document or msg.forward_origin):
        _NISHT_BUF[chat_id].append(msg)
        return True
    return False

# ===== 🧑‍💻 МОСТ «КЛОД» (владелец 03.07.2026, С52): обращение к Claude Code прямо из канала Muslim Live / личек владельца =====
# Бот сам НЕ отвечает за Клода (нет живого API-доступа отсюда к сессии Claude Code) — только ①принимает и подтверждает
# обращение (data/claude_inbox.json), ②доставляет ответы Клода (data/claude_replies.json), когда Клод их туда положит,
# при следующем сообщении в ТОМ ЖЕ чате (без JobQueue — она не в зависимостях, не рискуем пересборкой Railway).
CLAUDE_INBOX_FILE = "claude_inbox.json"
CLAUDE_REPLIES_FILE = "claude_replies.json"
CLAUDE_STATUS_FILE = "claude_status.json"   # «Клод взялся за заявку X» — публикуются в LOG_CHAT по таймеру (JobQueue), не ждут активности в чате
OWNER_ID2 = int(os.environ.get("OWNER_ID2", "0") or "0")   # второй личный аккаунт владельца — задать в Railway env, когда узнаем id
JAMAAT_RU_CHAT_ID = int(os.environ.get("JAMAAT_RU_CHAT_ID", "-1001925828112") or "-1001925828112")   # id группы JAMAAT MUSLIMIN — подтверждён владельцем 03.07.2026 (из журнала LOG_CHAT), Railway env может переопределить

def _claude_bridge_owner(update):
    uid = update.effective_user.id if update.effective_user else 0
    return uid == OWNER_ID or (OWNER_ID2 and uid == OWNER_ID2)

def _claude_bridge_scope(update):
    """Где работает мост «Клод»: канал (пост — админ, доверяем) ИЛИ личка/группа — но ТОЛЬКО когда пишет ИМЕННО
    владелец (оба личных аккаунта). #ФИНАЛЬНОЕ уточнение владельца 03.07.2026: «клод тоже в джамаате для меня
    только, ништячок и клод — исключительно для меня» — то есть группа jamaat_ru РАЗРЕШЕНА, но триггер сработает
    ТОЛЬКО от id владельца (_claude_bridge_owner) — 1108 остальных участников группы написать «клод ...» не смогут
    ничего вызвать, это и есть их «секретность», а не запрет самого чата целиком."""
    if update.channel_post:
        return True
    ct = getattr(update.effective_chat, "type", "")
    if ct in ("private", "group", "supergroup"):
        return _claude_bridge_owner(update)
    return False

async def _claude_dispatch(update, context):
    if not _claude_bridge_scope(update):
        return False
    msg = update.effective_message
    if not msg:
        return False
    text = (msg.text or msg.caption or "").strip()
    m = re.match(r'^клод\b[:,]?\s*(.*)$', text, re.I | re.S) if text else None
    if not m or not m.group(1).strip():
        return False
    body = m.group(1).strip()
    chat = update.effective_chat
    entry_id = "?"; queue_pos = "?"; when = _now_msk()
    _where = getattr(chat, "title", None) or "личка"
    try:
        arr = _data_get(CLAUDE_INBOX_FILE, []) or []
        entry_id = len(arr) + 1
        arr.append({"id": entry_id, "d": when, "chat_id": chat.id, "chat_title": _where,
                     "from": (update.effective_user.full_name if update.effective_user else "канал"),
                     "text": body, "delivered": False, "answered": False})
        queue_pos = sum(1 for x in arr if not x.get("answered"))   # сколько ещё не отвечено, включая это
        _data_put(CLAUDE_INBOX_FILE, arr, f"клод-обращение #{entry_id}")
    except Exception:
        pass
    try:
        await msg.reply_text(f"📨 Передано Клоду — обращение #{entry_id} из чата «{_where}», время {when}, "
                              f"место в очереди (неотвеченных): {queue_pos}\n«{body[:200]}»\nОтветит здесь, когда проверит очередь.")
    except Exception:
        pass
    # #ЖУРНАЛ (владелец 03.07.2026): «Клод нигде не должен отвечать кроме меня — но КАЖДОЕ обращение
    # должно приходить в рабочий журнал (LOG_CHAT_ID), точно так же, как приходят траты DeepSeek — кто/что/когда».
    try:
        if application:
            await application.bot.send_message(LOG_CHAT_ID, f"🧑‍💻 #клод обращение #{entry_id}: {_where}, {when}, в очереди {queue_pos} — «{body[:200]}»")
    except Exception:
        pass
    return True

async def _claude_deliver_replies(update, context):
    """Проверяет, нет ли для ЭТОГО чата свежих ответов Клода (data/claude_replies.json) — доставляет и помечает."""
    if not _claude_bridge_scope(update):
        return
    chat = update.effective_chat
    if not chat:
        return
    try:
        arr = _data_get(CLAUDE_REPLIES_FILE, []) or []
        pending = [r for r in arr if r.get("chat_id") == chat.id and not r.get("delivered")]
        if not pending:
            return
        changed = False
        for r in pending:
            try:
                await context.bot.send_message(chat.id, "🧑‍💻 Клод: " + str(r.get("text", ""))[:3500])
                r["delivered"] = True; changed = True
                try:
                    if application:
                        await application.bot.send_message(LOG_CHAT_ID, f"🧑‍💻 #клод ответ доставлен в {getattr(chat,'title',None) or 'личку'}: «{str(r.get('text',''))[:150]}»")
                except Exception:
                    pass
            except Exception:
                pass
        if changed:
            _data_put(CLAUDE_REPLIES_FILE, arr, "клод-ответы доставлены")
    except Exception:
        pass

async def _claude_timer_poll(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue-таймер (владелец 03.07.2026: «оперативно» — не ждать активности в чате): раз в ~40 сек
    ①доставляет ЛЮБЫЕ неотправленные claude_replies.json (не только когда владелец сам что-то пишет в тот же чат),
    ②публикует claude_status.json («Клод взялся за заявку X, ETA такой-то») в LOG_CHAT_ID."""
    try:
        arr = _data_get(CLAUDE_REPLIES_FILE, []) or []
        pending = [r for r in arr if not r.get("delivered")]
        changed = False
        for r in pending:
            try:
                await context.bot.send_message(r["chat_id"], "🧑‍💻 Клод: " + str(r.get("text", ""))[:3500])
                r["delivered"] = True; changed = True
                try:
                    await context.bot.send_message(LOG_CHAT_ID, f"🧑‍💻 #клод ответ доставлен (таймер): «{str(r.get('text',''))[:150]}»")
                except Exception:
                    pass
            except Exception:
                pass
        if changed:
            _data_put(CLAUDE_REPLIES_FILE, arr, "клод-ответы доставлены (таймер)")
    except Exception:
        pass
    try:
        st = _data_get(CLAUDE_STATUS_FILE, []) or []
        pend2 = [s for s in st if not s.get("posted")]
        changed2 = False
        for s in pend2:
            try:
                await context.bot.send_message(LOG_CHAT_ID, str(s.get("text", ""))[:3500])
                s["posted"] = True; changed2 = True
            except Exception:
                pass
        if changed2:
            _data_put(CLAUDE_STATUS_FILE, st, "клод-статусы опубликованы")
    except Exception:
        pass

# ===== 🧩 RAG-АССИСТЕНТ: оперативный поиск по ядру (41 первоисточник + 81 риджаль) на HF Space =====
# Команды (владелец в ЛС + чат @jamaat_ru): «раг <запрос>» (по всему ядру) ·
#   «найди в <источник>: <запрос>» (скоуп) · «раг в <источник>: <запрос>».
RAG_SPACE_URL = os.environ.get('HF_SPACE_URL', 'https://muslimoontt2024-muslimoon-rag.hf.space').rstrip('/')
RAG_HF_TOKEN = (os.environ.get('HF_TOKEN', '') or '').strip().strip('"').strip("'")

# 📖 ЛЕКСИКОН тем рус→классич.арабские слова (детерминированно, без ИИ — надёжно).
# Ключи = корни/основы (substring), значения = арабские слова как в матнах (без огласовок).
_RAG_LEX = {
    ('музык', 'песн', 'пени', 'пел', 'инструмент', 'мелоди'): ['المعازف', 'الغناء', 'مزمار', 'الملاهي'],
    ('вино', 'алкогол', 'опьян', 'спиртн', 'хамр'): ['الخمر', 'المسكر'],
    ('намаз', 'молитв', 'салят', 'салат'): ['الصلاة'],
    ('пост', 'ураз', 'саум', 'говен'): ['الصيام', 'الصوم'],
    ('закят', 'закат', 'милостын', 'садак', 'подаян'): ['الزكاة', 'الصدقة'],
    ('хадж', 'паломнич', 'умра'): ['الحج', 'العمرة'],
    ('сосед',): ['الجار'],
    ('родител', 'мать', 'отец', 'мама', 'папа'): ['الوالدين', 'الأم', 'الأب', 'بر'],
    ('знани', 'учён', 'учен', 'наук', 'образован'): ['العلم', 'العلماء'],
    ('намерен',): ['النية', 'الأعمال بالنيات'],
    ('терпен', 'сабр'): ['الصبر'],
    ('ложь', 'врат', 'обман', 'лжи'): ['الكذب'],
    ('правд', 'честн', 'искрен'): ['الصدق', 'الإخلاص'],
    ('гнев', 'злост', 'ярост'): ['الغضب'],
    ('рай', 'рая', 'раю', 'рае', 'джанна'): ['الجنة'],
    ('ад ', 'джаханнам', 'геенн', 'преиспод'): ['النار', 'جهنم'],
    ('смерт', 'умер'): ['الموت'],
    ('могил', 'кладбищ'): ['القبر'],
    ('ангел',): ['الملائكة'],
    ('шайтан', 'дьявол', 'сатан', 'иблис'): ['الشيطان'],
    ('прелюбод', 'зина', 'блуд'): ['الزنا'],
    ('воровств', 'краж', 'укра'): ['السرقة'],
    ('риба', 'процент', 'ростовщич'): ['الربا'],
    ('развод', 'талак'): ['الطلاق'],
    ('брак', 'никях', 'никах', 'женитьб', 'замуж', 'свадьб'): ['النكاح', 'الزواج'],
    ('сирот',): ['اليتيم'],
    ('бедн', 'нищ', 'беднот'): ['الفقير', 'المسكين'],
    ('торговл', 'бизнес', 'купл', 'продаж', 'сделк'): ['البيع', 'التجارة'],
    ('клятв', 'присяг'): ['اليمين', 'الحلف'],
    ('еда', 'пищ', 'кушан', 'трапез', 'покушать', 'поесть'): ['الطعام', 'الأكل'],
    ('одежд', 'наряд', 'платье'): ['اللباس', 'الثوب'],
    ('золот', 'серебр'): ['الذهب', 'الفضة'],
    ('собак',): ['الكلب'],
    ('кошк', 'кот '): ['الهرة'],
    ('лошад', 'конь', 'кон '): ['الخيل'],
    ('верблюд',): ['الإبل'],
    ('ночн молитв', 'тахаджуд', 'кияму'): ['قيام الليل', 'التهجد'],
    ('джихад', 'война', 'сражен'): ['الجهاد', 'القتال'],
    ('мученик', 'шахид', 'павш'): ['الشهيد', 'الشهادة'],
    ('коран', 'чтени', 'тиляв', 'тилав'): ['القرآن', 'تلاوة'],
    ('зикр', 'поминан'): ['الذكر'],
    ('дуа', 'мольб', 'мольбе', 'молен'): ['الدعاء'],
    ('покаян', 'тауба', 'прощен грех', 'истигфар'): ['التوبة', 'الاستغفار'],
    ('грех', 'грешн', 'ослушан'): ['الذنب', 'المعصية'],
    ('пятниц', 'джума', 'джумъа'): ['الجمعة'],
    ('праздник', 'ид ', 'ураза-байрам', 'курбан'): ['العيد'],
    ('борода',): ['اللحية'],
    ('мисвак', 'сивак', 'зуб'): ['السواك'],
    ('омовени', 'вуду', 'тахарат', 'чистот', 'гусль'): ['الوضوء', 'الطهارة', 'الغسل'],
    ('болезн', 'болен', 'недуг'): ['المرض', 'الشفاء'],
    ('сглаз', 'дурн глаз'): ['العين'],
    ('зависть', 'завист'): ['الحسد'],
    ('высокомер', 'гордын', 'кибр', 'надмен'): ['الكبر'],
    ('скромн', 'смирен', 'тавадуъ'): ['التواضع'],
    ('щедрост', 'щедр'): ['الكرم', 'الجود'],
    ('скупост', 'скуп', 'жадн'): ['البخل'],
    ('сплетн', 'гыйба', 'злослов', 'клевет'): ['الغيبة'],
    ('язык', 'реч '): ['اللسان'],
    ('судн день', 'конец свет', 'кияма', 'воскрешен'): ['الساعة', 'القيامة'],
    ('даджал', 'антихрист'): ['الدجال'],
    ('махди',): ['المهدي'],
    ('иса', 'иисус'): ['عيسى'],
    ('сон', 'спать', 'сновиден'): ['النوم', 'الرؤيا'],
    ('таква', 'богобоязн', 'страх алла'): ['التقوى', 'الخشية'],
    ('упован', 'таваккул'): ['التوكل'],
    ('благодарн', 'шукр'): ['الشكر'],
    ('лицемер', 'нифак', 'мунафик'): ['النفاق', 'المنافق'],
    ('многобож', 'ширк', 'идол'): ['الشرك'],
    ('единобож', 'таухид'): ['التوحيد', 'لا إله إلا الله'],
    ('вера', 'иман', 'веру'): ['الإيمان'],
    ('судьб', 'кадар', 'предопредел'): ['القدر', 'القضاء'],
    ('пророк', 'посланник'): ['الأنبياء', 'الرسل', 'النبي'],
    ('сподвижник', 'сахаб', 'асхаб'): ['الصحابة', 'أصحاب'],
    ('аиша', 'аишу'): ['عائشة'],
    ('абу бакр',): ['أبو بكر'],
    ('умар', 'омар'): ['عمر'],
    ('усман', 'осман'): ['عثمان'],
    ('али ибн', 'имам али'): ['علي بن أبي طالب'],
    ('фатим',): ['فاطمة'],
    ('мечет', 'масджид'): ['المسجد'],
    ('кааб', 'кибл'): ['الكعبة', 'القبلة'],
    ('мекк', 'медин'): ['مكة', 'المدينة'],
    ('заступнич', 'шафаат'): ['الشفاعة'],
    ('воскрешен', 'воскрес', 'баъс'): ['البعث', 'القيامة'],
    ('весы', 'мизан'): ['الميزان'],
    ('мост', 'сырат', 'сират'): ['الصراط'],
    ('родствен', 'силяту', 'узы родств'): ['صلة الرحم', 'الرحم'],
    ('брат', 'братств', 'ухувв'): ['الأخوة', 'المسلم أخو'],
    ('любов ради', 'ради алла'): ['الحب في الله'],
    ('приветств', 'салам', 'салям'): ['السلام', 'التسليم'],
    ('гост', 'гостеприим'): ['الضيف', 'الضيافة'],
    ('путник', 'путешеств', 'дорог', 'сафар'): ['السفر', 'المسافر'],
    ('зухд', 'аскет', 'отречен'): ['الزهد'],
    ('мир этот', 'дунья', 'мирск'): ['الدنيا'],
    ('здоров', 'афият'): ['العافية', 'الصحة'],
    ('молод', 'юнош'): ['الشباب'],
    ('старост', 'седин', 'пожил'): ['الشيب'],
    ('заработ', 'труд', 'работ', 'кясб'): ['الكسب', 'العمل'],
    ('халяль', 'халал', 'дозволен'): ['الحلال'],
    ('харам', 'запретн', 'запрещ'): ['الحرام'],
    ('сомнительн', 'шубух'): ['الشبهات'],
    ('справедлив', 'правосуд', 'адль'): ['العدل'],
    ('притеснен', 'несправедлив', 'зульм', 'тиран'): ['الظلم'],
    ('огон', 'огн', 'пламя', 'пекл'): ['النار'],
    ('реш', 'суди', 'судья', 'судеб', 'пригов', 'рассуд', 'кади'): ['القضاء', 'الحكم', 'يقضي'],
    ('правител', 'имам', 'султан', 'эмир', 'власт'): ['الإمام', 'السلطان', 'الأمير'],
    ('подчинен', 'послушан', 'таат'): ['الطاعة'],
    ('смут', 'фитн'): ['الفتنة'],
    ('убийств', 'убил', 'кровопрол'): ['القتل', 'الدم'],
    ('самоубийств',): ['قتل النفس'],
    ('воспитан', 'тарбия'): ['تربية الأولاد', 'الأولاد'],
    ('грудн', 'вскармлив', 'рада'): ['الرضاع'],
    ('наречен', 'имя ребён', 'акыка', 'акика'): ['التسمية', 'العقيقة'],
    ('обрезан', 'хитан'): ['الختان', 'الفطرة'],
    ('похорон', 'джаназ', 'погреб'): ['الجنازة', 'الميت'],
    ('больн посет', 'посещен больн', 'навестит больн'): ['عيادة المريض'],
    ('завещан', 'васыя', 'васия'): ['الوصية'],
    ('наследств', 'наследни', 'фараид'): ['الميراث', 'الفرائض'],
    ('долг', 'заём', 'займ', 'кард'): ['الدين', 'القرض'],
    ('вакф', 'вакуф'): ['الوقف'],
    ('наход', 'потер вещ', 'лукат'): ['اللقطة'],
    ('охот',): ['الصيد'],
    ('забой', 'закалыв', 'закят живот', 'забивать'): ['الذبح', 'الذكاة'],
    ('свинин', 'свин'): ['الخنزير'],
    ('мертвечин', 'падаль', 'майт'): ['الميتة'],
    ('рыб', 'морепрод'): ['السمك', 'الحوت'],
    ('финик', 'тамр'): ['التمر'],
    ('чеснок', 'лук'): ['الثوم', 'البصل'],
    ('ашура', 'ашур'): ['عاشوراء'],
    ('арафа', 'арафат'): ['عرفة'],
    ('рамадан', 'рамазан'): ['رمضان'],
    ('ночь предопредел', 'ляйлят', 'кадр'): ['ليلة القدر'],
    ('таравих', 'таравех'): ['التراويح'],
    ('итикаф', 'иътикаф'): ['الاعتكاف'],
    ('фитр', 'разговен'): ['زكاة الفطر', 'الفطر'],
}
def _ru_ar_terms(q):
    """Рус-запрос → классич. арабские слова из лексикона (детерминированно). [] если не нашлось.
    Матчинг по НАЧАЛУ слова (музыке→музык ✅, но терпение↛пение); фразы — подстрокой; короткие — точным словом."""
    low = (q or '').lower().replace('ё', 'е')
    words = re.findall(r'[а-я]+', low)
    out, seen = [], set()
    for keys, terms in _RAG_LEX.items():
        hit = False
        for k in keys:
            kk = k.strip()
            if not kk:
                continue
            if ' ' in kk:                       # фраза → подстрока
                hit = kk in low
            elif len(kk) <= 2:                  # очень короткий (ад) → точное слово
                hit = kk in words
            else:                               # обычный стем → слово начинается со стема
                hit = any(w.startswith(kk) for w in words)
            if hit:
                break
        if hit:
            for t in terms:
                if t not in seen:
                    seen.add(t); out.append(t)
    return out

async def _rag_query(q, source=None, narrator=None, n=5):
    import aiohttp
    if not RAG_HF_TOKEN:
        raise RuntimeError('HF_TOKEN пуст в окружении бота — Railway не подхватил переменную. Открой Railway → сервис → ⋮ → Redeploy.')
    params = {'q': q or '', 'n': str(n)}
    if source: params['in'] = source
    if narrator: params['by'] = narrator
    headers = {'Authorization': 'Bearer ' + RAG_HF_TOKEN} if RAG_HF_TOKEN else {}
    async with aiohttp.ClientSession() as s:
        async with s.get(RAG_SPACE_URL + '/search', params=params, headers=headers,
                         timeout=aiohttp.ClientTimeout(total=35)) as r:
            ctype = r.headers.get('content-type', '')
            if r.status != 200 or 'json' not in ctype:
                body = (await r.text())[:120]
                hint = ' — нет доступа к Space (проверь HF_TOKEN в Railway Variables)' if r.status in (401, 403, 404) else ''
                raise RuntimeError('HTTP %s%s' % (r.status, hint))
            return await r.json()

async def _hf_keepalive(application):
    """Пинг Space /health каждые 5 мин — чтобы НИКОГДА не засыпал (указ владельца)."""
    import aiohttp
    headers = {'Authorization': 'Bearer ' + RAG_HF_TOKEN} if RAG_HF_TOKEN else {}
    await asyncio.sleep(50)
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(RAG_SPACE_URL + '/health', headers=headers,
                                 timeout=aiohttp.ClientTimeout(total=20)) as r:
                    await r.read()
        except Exception:
            pass
        await asyncio.sleep(300)

def _rag_parse(text):
    """'раг|найди [в <источник>:] <запрос>' → (source, query). Скоуп — после 'в' до ':'."""
    t = text.strip()
    low = t.lower()
    for pref in ('найди', 'раг', 'rag'):
        if low.startswith(pref):
            t = t[len(pref):].strip(); low = t.lower(); break
    source = None
    if low.startswith('в ') and ':' in t:
        head, q = t[2:].split(':', 1)
        source = head.strip(); t = q.strip()
    return source, t.strip()

# коллекции с нумерацией sunnah (ara-* издания) — точный текст+перевод по номеру + рабочая ссылка sunnah.com.
# (Ахмад/мусаннафы и пр. НЕ сюда: у них num=страница Мактабы, не номер хадиса.)
_FAWAZ_COLS = {'bukhari', 'muslim', 'abudawud', 'tirmidhi', 'nasai', 'ibnmajah', 'malik'}
_HRK = '[ً-ْٰـ]*'   # огласовки + тантвин + татвиль (для толерантного поиска)
_LETCLS = {'ا': '[اأإآ]', 'أ': '[اأإآ]', 'إ': '[اأإآ]', 'آ': '[اأإآ]',
           'ه': '[هة]', 'ة': '[هة]', 'ي': '[يى]', 'ى': '[يى]', 'و': '[وؤ]'}
def esc(s):
    """HTML-экранирование для parse_mode=HTML (модульный — RAG-карточки/_hl_arabic зовут его вне функции, где был только вложенный esc → NameError, фикс С46)."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _hl_arabic(text, terms):
    """Выделить искомые слова в арабском тексте жирным+подчёркиванием (толерантно к огласовкам/хамзам)."""
    if not text:
        return ''
    out = esc(text)
    for t in sorted({(x or '').strip() for x in terms}, key=len, reverse=True):
        if len(t) < 3:
            continue
        chars = [_LETCLS.get(c, re.escape(c)) for c in t if c.strip()]
        if not chars:
            continue
        pat = _HRK.join(chars)
        try:
            out = re.sub('(' + pat + ')', r'<b><u>\1</u></b>', out, count=4)
        except re.error:
            pass
    return out

def _rag_cards(hits, terms, limit=4):
    """Карточки хадисов: целый хадис (выделено искомое) + перевод + источник·№ + рабочая ссылка."""
    cards = []
    for h in hits[:limit]:
        tok = h.get('app_token') or ''
        m = re.match(r'r_(.+)_(\d+)$', tok)
        slug = m.group(1) if m else None
        num = m.group(2) if m else str(h.get('num', ''))
        name = h.get('name', ''); ar = h.get('arabic') or h.get('snippet') or ''; ru = ''
        if slug in _FAWAZ_COLS and num:
            try:
                a2, tr, _lang, _gr = get_hadith(slug, num)
                if a2: ar = a2
                if tr: ru = tr
            except Exception:
                pass
        # язык (владелец: «зачем на английском пишет»): у Муслима и др. готового русского нет → get_hadith
        # отдаёт английский. Если перевод без кириллицы — переводим арабский на русский (кэшируется).
        if ru and not re.search(r'[А-Яа-я]', ru) and ar:
            try:
                _r2 = translate_matn(ar[:1400], owner=True)
                if _r2 and re.search(r'[А-Яа-я]', _r2): ru = _r2
            except Exception:
                pass
        block = ['%s <b>%s</b> · №%s' % (h.get('tier_label', ''), name, num)]
        block.append('<blockquote>%s</blockquote>' % _hl_arabic(ar[:1400], terms))
        if ru:
            block.append('🌍 ' + esc(ru[:600]))
        link = []
        if slug in _FAWAZ_COLS and num:
            link.append('🔗 <a href="https://sunnah.com/%s:%s">sunnah.com</a>' % (slug, num))
        if h.get('app_url'):
            link.append('📱 <a href="%s">в аппе</a>' % h['app_url'])
        if link:
            block.append(' · '.join(link))
        cards.append('\n'.join(block))
    return cards

def _rag_synth(question, hits, owner=False):
    """NotebookLM-стиль: связный ответ по нашим источникам с цитатами [N]. Не выдумывает."""
    if not hits:
        return None
    ctx = []
    for i, h in enumerate(hits, 1):
        ctx.append('[%d] (%s) %s — %s №%s\n%s' % (i, h.get('tier_label', ''), h.get('name', ''),
                   h.get('author', ''), h.get('num', ''), (h.get('arabic') or h.get('snippet') or '')[:900]))
    try:
        ans = ask_ai(
            'Вопрос: %s\n\nОтрывки из НАШИХ первоисточников:\n%s' % (question, '\n\n'.join(ctx)),
            'Ты — ассистент Муслимун. Ответь по-русски КРАТКО и по делу ТОЛЬКО на основе отрывков, ссылайся на источники в виде [N]. '
            'Соблюдай приоритет: Коран > первоисточник хадиса (Бухари/Муслим/сунан) > сборники > тафсир. '
            'Если в отрывках нет ответа — честно скажи. Не выдумывай. Хукм о достоверности сам не выноси.',
            owner=owner)
        ans = re.sub(r"\n*⚡ \*Модель:.*$", "", ans or "", flags=re.S).strip()
        ans = re.sub(r"\n*📊.*$", "", ans, flags=re.S).strip()
        return ans or None
    except Exception:
        return None

def _rag_fmt(data, answer=None):
    res = (data or {}).get('results', [])
    if not res:
        return '🔎 Ничего не нашёл. Попробуй точную арабскую фразу (2-4 слова) или укажи источник: «раг в бухари: <фраза>».'
    src = data.get('in'); by = data.get('by')
    lines = []
    if answer:
        lines += ['🧠 ' + answer, '']
    head = '📚 <b>Источники</b> (найдено: %d' % data.get('count', len(res))
    if src: head += ', в «%s»' % src
    if by: head += ', передатчик «%s»' % by
    head += '):'
    lines.append(head)
    for i, h in enumerate(res, 1):
        lines.append('%s [%d] <b>%s — %s</b> №%s' % (h.get('tier_label', ''), i, h.get('name', ''), h.get('author', ''), h.get('num', '')))
        if not answer:
            sn = (h.get('snippet') or '')[:220]
            if sn: lines.append(sn)
        links = []
        if h.get('maktaba_url'): links.append('📖 <a href="%s">Мактаба</a>' % h['maktaba_url'])
        if h.get('app_url'): links.append('📱 <a href="%s">В аппе</a>' % h['app_url'])
        if links: lines.append(' · '.join(links))
    lines.append('')
    lines.append('🔎 <b>Ответил:</b> RAG (наша база: первоисточники + риджаль)')
    return '\n'.join(lines)[:4090]

# 🔐 ДОСТУП к RAG (указ владельца): пока только владелец; рубильник «всем» + белый/чёрный списки.
# ⚠️ Railway ephemeral — список сбрасывается при редеплое (владелец перевыставляет; владелец доступен ВСЕГДА).
_RAG_ACCESS_FILE = 'rag_access.json'
_RAG_ACCESS = {'all': False, 'white': [], 'black': []}
def _rag_access_load():
    global _RAG_ACCESS
    try:
        _RAG_ACCESS = json.load(open(_RAG_ACCESS_FILE, encoding='utf-8'))
    except Exception:
        _RAG_ACCESS = {'all': False, 'white': [], 'black': []}
    return _RAG_ACCESS
def _rag_access_save():
    try:
        json.dump(_RAG_ACCESS, open(_RAG_ACCESS_FILE, 'w', encoding='utf-8'))
    except Exception:
        pass
def _rag_allowed(uid):
    try:
        uid = int(uid)
    except Exception:
        return False
    if uid == OWNER_ID:
        return True
    a = _rag_access_load()
    if uid in a.get('black', []):
        return False
    if a.get('all'):
        return True
    return uid in a.get('white', [])
# ── #667: «раг» — команда или разговор ПРО раг? ───────────────────────────────────────
# Триггером было ЛЮБОЕ сообщение, начинающееся на «раг ». Живой случай из @jamaat_ru
# (1 077 участников, скрин владельца 26.07.2026): владелец пояснял соседям по чату
# «Раг пока только Бухари сделал я» — это реплика ПРО раг, а не вопрос К нему. Бот принял
# «пока только Бухари сделал я» за вопрос, ответил «🧠 Ищу по смыслу…» и ушёл искать.
# На глазах у всего чата, и вдобавок съел квоту нейронов Cloudflare.
#
# Отличаем дёшево и без потерь: смотрим ТОЛЬКО ПЕРВОЕ слово после «раг». Настоящий вопрос
# начинается с темы или вопросительного слова («раг можно ли пить стоя», «раг бухари
# хариджиты», «раг что говорится о посте») и НИКОГДА — с «я / пока / уже / опять / сделал».
# Именно поэтому проверяется первое слово, а не всё сообщение: в «раг что делать, если я
# забыл намаз» местоимение «я» стоит внутри вопроса и мешать не должно.
_РАГ_НЕ_ВОПРОС = frozenset("""
я мы мне нам меня нас ты тебе тебя вы вам
пока уже ещё еще тоже опять снова вроде кажется наверное походу короче кстати слушай
значит теперь вообще получается похоже блин ладно
сделал сделала сделали сделаю сделай настроил настроила настроили настрой настроим
включил включила включи выключил выключи добавил добавила добавь запустил запусти
починил почини доделал доделаю доделай прикрутил обновил переделал проверил проверю
проверь работает заработал сломался сломан глючит висит молчит тупит отвечает
спасибо супер класс отлично круто плохо хорошо норм ок окей
""".split())
# Отдельно жалобы вида «раг не работает» — «не» само по себе в список не годится
# (может начинать настоящий вопрос), поэтому ловим его только в связке с глаголом.
_РАГ_ЖАЛОБА = re.compile(
    r'^(?:не|нe)\s+(работает|ищет|отвечает|находит|пашет|видит|грузит|включается|запускается|пишет)\b',
    re.I)


def _раг_это_реплика(text):
    """True — сообщение ГОВОРИТ про раг, а не спрашивает у него. Тогда молчим и пропускаем
    сообщение дальше обычным путём: реплика в общем чате ответа бота не требует."""
    try:
        остаток = re.sub(r'^\s*(раг|rag)\b[\s,:—-]*', '', text or '', flags=re.I).strip()
        if not остаток:
            return False                       # голое «раг» — это просьба о помощи, обрабатываем
        if _РАГ_ЖАЛОБА.match(остаток):
            return True
        первое = re.split(r'[\s,.!?;:]+', остаток.lower(), maxsplit=1)[0]
        return первое in _РАГ_НЕ_ВОПРОС
    except Exception:
        return False                           # сомневаешься — веди себя как раньше


def _rag_access_cmd(text):
    """Команды владельца управления доступом RAG. Возвращает текст-ответ или None (не команда)."""
    t = text.lower().strip()
    a = _rag_access_load()
    if t in ('раг доступ', 'rag доступ', 'раг статус', 'раг лимиты'):
        # #673: «установи мне в кабинете разработчика» — вот он, кабинет: одной командой видно
        # и правило (кому открыто, сколько на человека), и живой расход за сегодня поимённо.
        # Раньше команда показывала только списки, а сам ЛИМИТ был зашит в код — увидеть его
        # и тем более поменять без редеплоя Railway было нельзя.
        import time as _t
        _день = _t.strftime('%Y-%m-%d')
        _рас = sorted([(k, int(v.get('сколько') or 0)) for k, v in _RAG_КВОТА.items()
                       if v.get('день') == _день], key=lambda z: -z[1])[:10]
        _н = _rag_нейроны_кратко()
        return ('🔐 Доступ RAG:\n• всем: %s\n• белый список: %s\n• чёрный список: %s\n'
                '• лимит на человека: %d запросов в сутки (общий счёт для чата и приложения)\n'
                '• кошелёк Cloudflare: %s\n'
                '• израсходовали сегодня: %s\n\n'
                'Команды: «раг всем вкл/выкл» · «раг лимит <N>» · «раг белый +<id>» / «раг белый -<id>» · «раг чёрный +<id>» / «раг чёрный -<id>»'
                % ('ВКЛ' if a.get('all') else 'выкл (только владелец+белый)',
                   a.get('white', []) or '—', a.get('black', []) or '—', _rag_лимит(),
                   ('осталось %s из %d нейронов' % (_н['нейронов_осталось'], _CF_СУТКИ))
                   if _н.get('нейронов_осталось') is not None else 'остаток не отдаёт',
                   ', '.join('%s — %d' % (k, n) for k, n in _рас) or 'никто'))
    m = re.match(r'^раг\s+лимит\s+(\d+)$', t)
    if m:
        a['лимит'] = max(1, int(m.group(1)))
        _rag_access_save()
        return '✅ Лимит РАГ: %d запросов в сутки на человека (чат + приложение вместе).' % a['лимит']
    if t.startswith('раг всем'):
        a['all'] = ('вкл' in t or 'on' in t)
        _rag_access_save()
        return '✅ RAG для всех: %s' % ('ВКЛЮЧЁН' if a['all'] else 'выключен (только владелец + белый список)')
    m = re.match(r'раг\s+(бел|чёрн|черн)\w*\s+([+\-]?)(\d+)', t)
    if m:
        lst = 'white' if m.group(1) == 'бел' else 'black'
        rm = m.group(2) == '-'
        uid = int(m.group(3))
        arr = a.setdefault(lst, [])
        if rm:
            if uid in arr: arr.remove(uid)
        else:
            if uid not in arr: arr.append(uid)
        _rag_access_save()
        return '✅ %s список: %s id %d → %s' % ('Белый' if lst == 'white' else 'Чёрный',
                'убрал' if rm else 'добавил', uid, arr or '—')
    return None

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        # ⭐ НИШТЯЧОК прямо В КАНАЛЕ (Muslim Live и т.п.): это update.channel_post, а не update.message —
        # весь остальной handle() такие апдейты не видит вообще (падает на этой же строке). Постить в канал
        # может только админ, поэтому отдельная owner-проверка тут не нужна — сам факт поста уже доверенный.
        if update.channel_post:
            try:
                if await _nisht_dispatch(update, context):
                    return
                await _claude_deliver_replies(update, context)
                await _claude_dispatch(update, context)
            except Exception:
                pass
        return

    text = update.message.text or ""
    text = text.strip()

    # 🎤 ГОЛОСОВОЕ/АУДИО. Стоит ПЕРЕД разбором DSOC, и это принципиально: у голосового нет
    # текста, значит до разбора обращения оно не доживёт — сперва расшифровка, потом решаем.
    #  • слышно «DSOC …» → это к ассистенту, и отвечаем ГОЛОСОМ (спросили голосом — отвечай так же);
    #  • иначе → заявка #630: ищем оригинал хадиса в нашей базе.
    # Владельческий поток «голосовая заявка» в личке не трогаем — он про другое и работает давно.
    _голосом_просили = False
    try:
        _гол = update.message.voice or update.message.audio or update.message.video_note
    except Exception:
        _гол = None
    # Ответили словом «хадис» на ЧУЖОЕ (или своё старое) голосовое → разбираем ТО сообщение и
    # вешаем ответ на него же. Единственный способ дотянуться до записи, которой в текущем
    # сообщении нет: истории чата боту не видно, а вот на что ответили — видно всегда.
    if _гол is None and text and re.match(r'^\s*(хадис|найди хадис|что за хадис|оригинал)\s*[?!.]*\s*$',
                                          text.strip(), re.I):
        try:
            _пред = update.message.reply_to_message
            _гол = (_пред.voice or _пред.audio or _пред.video_note) if _пред else None
            if _гол is not None:
                await аудио_в_хадис(update, context, _гол.file_id, "",
                                    отвечать_на=_пред.message_id)
                return
        except Exception as _e:
            try:
                await update.message.reply_text("🔴 Не смог разобрать то голосовое: %s" % str(_e)[:200])
            except Exception:
                pass
            return
    if _гол is not None:
        _расш = None
        try:
            _пф = await context.bot.get_file(_гол.file_id)
            _пп = os.path.join("/tmp", "in_%s.ogg" % update.message.message_id)
            await _пф.download_to_drive(_пп)
            _расш = await asyncio.get_event_loop().run_in_executor(None, transcribe_audio, _пп)
            try:
                os.remove(_пп)
            except Exception:
                pass
        except Exception:
            _расш = None
        # 🔴 05.08.2026. Было: «любое голосовое, кроме обращения к помощнику, — это поиск
        # хадиса». Владелец спросил голосом «ты голосовые сообщения понимаешь?» и получил
        # «такого хадиса в базе нет». Умолчание стояло не у того: помощник понимает больше,
        # значит всё неопределённое — ему, а в поиск хадиса уходит лишь то, где хадис ЯВНО
        # слышен: арабская речь или прямые слова о хадисе и передаче.
        _про_хадис = False
        if _расш:
            _н = _расш.lower()
            _про_хадис = bool(re.search(r'[\u0621-\u064A]{6,}', _расш)) or any(
                с in _н for с in ('хадис', 'передал', 'рассказал нам', 'сообщил нам',
                                  'сказал посланник', 'пророк сказал', 'со слов'))
        # 🔴 ЗОВ ВЛАДЕЛЬЦА #50 (06.08.2026): «не влазить». В группе бот лез в КАЖДОЕ голосовое —
        # качал, расшифровывал и при неудаче отвечал «не разобрал речь» человеку, который его не
        # звал. Разговор чужой, бот в нём лишний; хуже того, ответ приходил именно тогда, когда
        # бот НЕ справился, — то есть влезал, чтобы сообщить о собственной неудаче.
        # Теперь в группе отвечаем на голосовое, ТОЛЬКО когда к боту обратились: ответом на его
        # сообщение, обращением в подписи или обращением слышно в самой речи. Расшифровку не
        # отменяем — иначе пропадёт возможность позвать помощника голосом; молчим именно ответом.
        _группа = getattr(update.effective_chat, "type", "") != "private"
        _звали = True
        if _группа:
            try:
                _пред = update.message.reply_to_message
                _звали = bool(_пред and getattr(_пред, 'from_user', None)
                              and _пред.from_user.id == context.bot.id)
            except Exception:
                _звали = False
            if not _звали:
                _звали = parse_dsoc(update.message.caption or '') is not None
            if not _звали and _расш:
                _звали = parse_dsoc(_расш) is not None
            if not _звали:
                return                       # чужой разговор — молчим совсем, даже об ошибке
        if _расш and (parse_dsoc(_расш) is not None or not _про_хадис):
            text = _расш.strip()                  # дальше отработает разбор DSOC
            _голосом_просили = True
        elif _группа:
            try:
                await аудио_в_хадис(update, context, _гол.file_id, update.message.caption or "")
            except Exception as _e:
                try:
                    await update.message.reply_text("🔴 Сбой на разборе аудио: %s" % str(_e)[:200])
                except Exception:
                    pass
            return

    # ═══════════════════════════════════════════════════════════════════════════════
    #  🟩 DSOC — прямой разговор с DeepSeek через подписку OpenCode. 05.08.2026.
    # ═══════════════════════════════════════════════════════════════════════════════
    # Стоит ПЕРЕД разбором «ботяры»: обращение прямое и однозначное, перехватывать его
    # другим правилам незачем.
    try:
        лента_запомнить(update)
    except Exception:
        pass

    # 🔴 06.08.2026. АНОНИМНЫЙ АДМИН — ЭТО ТОЖЕ ВЛАДЕЛЕЦ.
    # В чате джамаата владелец пишет от имени группы: у такого сообщения from_user — служебный
    # GroupAnonymousBot, а настоящий отправитель спрятан в sender_chat. Все мои проверки
    # «это владелец?» смотрели на from_user и для анонимных сообщений отвечали «нет».
    # Отсюда разом: и «почему отвечает Groq», и «почему зов не дошёл», и «почему ботяра не
    # ведёт к помощнику». Правила были верные — до них не доходило дело.
    # Чужой анонимом писать не может: право говорить от имени группы есть только у админов.
    def _хозяин(u):
        try:
            if is_owner(u):
                return True
            _sc = getattr(u.message, 'sender_chat', None)
            _ch = getattr(u.effective_chat, 'id', None)
            return bool(_sc and _ch and getattr(_sc, 'id', None) == _ch)
        except Exception:
            return False

    # 🔴 ЗОВ ТЕХНАДЗОРА ЛОВИТСЯ ПЕРВЫМ, ДО ВСЕХ ПРОЧИХ ПУТЕЙ.
    # 05.08.2026: владелец написал «передай технадзору…» — и ответил ему Groq: «я этого не
    # умею». Честно, но не по адресу: передать было некому, потому что до меня это не дошло.
    # Слово-ключ ловилось только внутри разбора помощника, то есть если разговор с ним уже
    # шёл. Обращение ко мне не должно зависеть от того, разговаривал ли владелец перед этим
    # с кем-то ещё: ключ есть — дверь открывается.
    # Ответил НА МОЁ сообщение — значит спрашивает меня, какими бы словами и когда бы то ни
    # было. 05.08.2026: это правило у меня уже было, но лежало ВНУТРИ разбора помощника — а
    # туда сообщение без слова DSOC не доходит. Правило работает не там, где записано, а там,
    # где проверяется. Поднимаю в самое начало.
    _мой_ли_ответ = False
    try:
        if _хозяин(update) and update.message.reply_to_message:
            _цт = (getattr(update.message.reply_to_message, 'text', None)
                   or getattr(update.message.reply_to_message, 'caption', None) or '')
            _мой_ли_ответ = ('🧠 Клод' in _цт or 'Технадзор:' in _цт[:120]) and not re.match(
                r'^\s*(спасибо|благодарю|понял|поняла|ок|окей|ага|хорошо|принял|ясно|\+|👍)'
                r'\s*[!.)]*\s*$', (text or '').strip().lower())
    except Exception:
        _мой_ли_ответ = False

    if text and _хозяин(update) and (_мой_ли_ответ or re.search(
            r'(передай|скажи|сообщи)\s+(технадзор|клод|разработчик)|'
            r'^\s*(технадзор|клод)\b', text.strip().lower())):
        try:
            _чид = getattr(update.effective_chat, 'id', 0)
            _отм = {}
            _рп = update.message.reply_to_message
            if _рп:
                _отм = {'смс': _рп.message_id,
                        'кто': (getattr(getattr(_рп, 'from_user', None), 'first_name', '')
                                or 'кто-то'),
                        'текст': ((getattr(_рп, 'text', None)
                                   or getattr(_рп, 'caption', None) or '')[:1200])}
            _н = dsoc_позвать_клода(_чид, update.message.message_id, text.strip(),
                                    getattr(update.effective_user, 'first_name', ''),
                                    отмечено=_отм)
            await context.bot.send_message(
                LOG_CHAT_ID,
                "📣 <b>ВЛАДЕЛЕЦ ЗОВЁТ ТЕХНАДЗОРА</b> (обращение #%s)\n%s\n"
                "Ответ ждут здесь: https://t.me/c/%s/%s"
                % (_н, text.strip()[:900], str(_чид).replace('-100', ''),
                   update.message.message_id), parse_mode='HTML',
                disable_web_page_preview=True)
            await update.message.reply_text(
                "📣 Передал технадзору — обращение #%s. Он ответит прямо здесь." % _н)
        except Exception:
            pass
        return

    _dsoc = parse_dsoc(text)
    # Первая половина слияния (владелец 05.08.2026: «нам ботяра зачем отдельно тогда?»):
    # у ВЛАДЕЛЬЦА слово «ботяра» ведёт к тому же помощнику — с памятью, полкой и вызовами.
    # Двух помощников с разными правилами быть не должно. Чужим бесплатный путь пока оставлен:
    # он их и обслуживает, и не тратит деньги владельца — второй шаг требует его слова.
    if _dsoc is None and text and _хозяин(update):
        _мб = re.match(r'^\s*(ботяра|botyara)\b[\s,:—-]*(.*)$', text.strip(), re.I | re.S)
        if _мб:
            _dsoc = (_мб.group(2) or '').strip()
    # 🔴 05.08.2026, владелец: «если смс отправил DSOC, то следующее взаимодействие с ним
    # как DSOC идёт». Он ответил на ответ ассистента обычным вопросом — и отозвался СТАРЫЙ
    # ИИ бота (Groq), потому что слова DSOC во втором сообщении не было.
    # Так и должно быть по-человечески: разговор ведут с тем, кто говорил, а не называют
    # собеседника по имени в каждой реплике. Узнаём свои ответы по подписи «— 🟩 DSOC».
    # 🔴 05.08.2026, владелец: «передай технадзору, чтобы другие модели не лезли в диалог».
    # Он разговаривает с помощником, а отвечает то Groq-«ботяра», то общий чат-ИИ — потому что
    # обращение узнавалось только по слову DSOC или по ответу на реплику помощника. Разговор
    # ведут с тем, кто говорил: если владелец только что беседовал с помощником в этом чате,
    # его следующая реплика — тоже помощнику, а не первому, кто откликнется.
    # Явные команды (ботяра, раг, найди хадис, коран, карточка) при этом работают как прежде:
    # человек назвал инструмент прямо, и подменять его выбор нельзя.
    if _dsoc is None and text and is_owner(update):
        try:
            _пос = dsoc_когда_отвечал(getattr(update.effective_chat, 'id', 0))
            _низт = text.strip().lower()
            _явно_другому = _низт.startswith(('ботяра', 'botyara', 'раг ', 'рag ', 'найди хадис',
                                              'коран', 'карточка', 'переведи', 'корень ',
                                              'видео', 'заявка', 'память', 'запомни',
                                              'анонс', '/', 'надзиратель', 'дипсик'))
            # 🔴 05.08.2026, владелец: «я тебя не звал, почему ты ответил?». Правило «15 минут
            # всё идёт помощнику» починило одно (чужие модели не влезают) и сломало другое:
            # он стал отвечать и на реплики В СТОРОНУ. Внутри окна он теперь отвечает, только
            # если обратились К НЕМУ: ответом на его сообщение, по имени, вопросом или прямой
            # просьбой. Замечание в сторону остаётся без ответа — молчание тоже бывает
            # правильным ответом.
            _к_нему = False
            try:
                _рп = update.message.reply_to_message
                _рт = ((getattr(_рп, 'text', None) or getattr(_рп, 'caption', None) or '')
                       if _рп else '')
                _к_нему = ('🟩 DSOC' in _рт or '🧠 Клод' in _рт
                           or '?' in text
                           or bool(re.match(r'^\s*(дай|найди|покажи|скажи|сделай|переведи|'
                                            r'объясни|расскажи|прочитай|озвучь|проверь|сравни|'
                                            r'вмешайся|убери|забудь|сожми|продолж)',
                                            text.strip().lower())))
            except Exception:
                _к_нему = '?' in text
            if _пос and (time.time() - _пос) < 900 and not _явно_другому and _к_нему:
                _dsoc = text.strip()
        except Exception:
            pass

    if _dsoc is None and text:
        try:
            _пред = update.message.reply_to_message
            _пт = (getattr(_пред, "text", None) or getattr(_пред, "caption", None) or "") if _пред else ""
            if "🟩 DSOC" in _пт or "— 🟩" in _пт:
                _dsoc = text.strip()
        except Exception:
            pass
    if _dsoc is not None:
        # 🔴 05.08.2026, ошибка B-004: «cannot access local variable 'chat_id'».
        # Перенося блок наверх, я не заметил, что chat_id вычисляется НИЖЕ по ходу handle(),
        # и здесь его ещё нет. Питон в таких случаях не берёт глобальную переменную, а честно
        # падает: имя уже «занято» присваиванием ниже, значит оно местное и пока пустое.
        # Урок: перенося код, проверяй не только условия НАД ним, но и то, чем он пользуется —
        # переменные тоже имеют своё «место рождения».
        _chat = getattr(update.effective_chat, 'id', None)
        chat_id = _chat if _chat is not None else getattr(update.message.chat, 'id', 0)
        # Владелец ответил «да» на предложение DSOC подать заявку — подаём. Стоит ЗДЕСЬ, а не
        # выше: chat_id рождается строкой ранее, и обращаться к нему до этого нельзя (ошибка
        # B-004 уже была ровно об этом).
        if _dsoc and chat_id in DSOC_ЗАЯВКА_ЖДЁТ and _dsoc.strip().lower().rstrip("!.") in (
                "да", "давай", "передай", "подавай", "ага", "ок", "хорошо", "да, передай"):
            _куда, _текст = DSOC_ЗАЯВКА_ЖДЁТ.pop(chat_id)
            try:
                if _куда == "помощник":
                    _rid = dsoc_заявка_помощнику(_текст, "владелец")
                    await update.message.reply_text(
                        "📓 Записал в журнал помощника — #%s:\n%s" % (_rid, _текст))
                else:
                    _rid = req_add("🟩 [DSOC] " + _текст)
                    await update.message.reply_text(
                        "📨 Передал технадзору — заявка #%d:\n%s" % (_rid, _текст))
            except Exception as _e:
                await update.message.reply_text("🔴 Не смог записать: %s" % str(_e)[:150])
            return

        if not OPENCODE_KEY:
            await update.message.reply_text(
                "🔑 Ключ OpenCode боту не выдан.\n"
                "Добавь на Railway переменную OPENCODE_ZEN_API_KEY и передеплой — "
                "и DSOC заработает.")
            return
        if not _dsoc:
            await update.message.reply_text(
                "Я на связи. Пиши: DSOC <что сделать>.\n"
                "Помню весь наш разговор в этом чате (до миллиона токенов, дальше ужимаю сам).\n"
                "Ответом на любое сообщение — возьму его в работу вместе с вопросом.")
            return

        # 👁 ВЛОЖЕНИЯ: скриншот и файл — читаем ДО того, как думать.
        # Владелец общается скриншотами, это его главный способ показать проблему.
        # Помощник, который не видит скрин, отвечает на догадку о нём — и человек видит,
        # что с ним говорят мимо. Смотрим и в само сообщение, и в отмеченное ответом:
        # скрин чаще присылают ответом на него, а не подписью.
        _влож = []
        for _м in (update.message, update.message.reply_to_message):
            if _м is None:
                continue
            try:
                if getattr(_м, "photo", None):
                    _ф = await context.bot.get_file(_м.photo[-1].file_id)
                    _био = io.BytesIO()
                    await _ф.download_to_memory(out=_био)
                    _вид = await dsoc_глаза(_био.getvalue(), (_м.caption or "").strip())
                    if _вид:
                        _влож.append("=== ЧТО НА ПРИСЛАННОМ СКРИНШОТЕ ===" + chr(10) + _вид)
                    else:
                        _влож.append("(скриншот прислан, но прочитать его не вышло — "
                                     "зрячая модель недоступна)")
                _док = getattr(_м, "document", None)
                if _док is not None:
                    _ф2 = await context.bot.get_file(_док.file_id)
                    _био2 = io.BytesIO()
                    await _ф2.download_to_memory(out=_био2)
                    _влож.append(await dsoc_руки(_био2.getvalue(), _док.file_name or "файл"))
            except Exception as _ев:
                _влож.append("(вложение не открылось: %s)" % str(_ев)[:120])
        if _влож:
            _dsoc = (chr(10).join(_влож) + chr(10) + chr(10)
                     + "=== ЧЕЛОВЕК ПРОСИТ ===" + chr(10) + _dsoc)

        # 🧩 «ВМЕШАЙСЯ В ДИАЛОГ» — восстановить нить вокруг отмеченного сообщения.
        if re.search(r'вмеша|вмеща|разбери\s+диалог|что тут происходит', _dsoc.lower()):
            _пред = update.message.reply_to_message
            if not _пред:
                await update.message.reply_text(
                    "🧩 Отметь сообщение, в диалог вокруг которого нужно вмешаться, — иначе я не "
                    "знаю, о каком разговоре речь. В чате их идёт несколько сразу.")
                return
            глубже = bool(re.search(r'глубже|подробн|шире', _dsoc.lower()))
            окно = лента_окно(chat_id, _пред.message_id, 15 if глубже else 5)
            # 🔴 ВЫГОВОР ВЛАДЕЛЬЦА 06.08.2026. Здесь бот отказывался работать словами
            # «соседних сообщений у меня нет, это сообщение старше моей ленты» — и был НЕПРАВ.
            # Владелец ОТМЕТИЛ сообщение ответом, а Telegram кладёт отмеченное прямо в запрос,
            # в reply_to_message. Текст был у бота В РУКАХ: он держал его и одновременно
            # говорил, что у него ничего нет, — потому что смотрел только в свою ленту и не
            # заглянул в то, что ему подали.
            # ПРАВИЛО: сперва берём пришедшее ВМЕСТЕ С ЗАПРОСОМ, потом достраиваем лентой.
            # Отказывать можно, только когда текста нет НИГДЕ.
            def _взять_текст(м):
                if not м:
                    return ''
                т = (getattr(м, 'text', None) or getattr(м, 'caption', None) or '').strip()
                if not т and getattr(м, 'voice', None):
                    т = '(голосовое сообщение)'
                return т

            подано, _цепь, _ш = [], _пред, 0
            while _цепь is not None and _ш < 4:      # ответ на ответ — тоже нить разговора
                _т = _взять_текст(_цепь)
                if _т:
                    try:
                        _а = _цепь.from_user
                        _кто = (_а.first_name or _а.username or '?') if _а else 'канал'
                    except Exception:
                        _кто = '?'
                    if getattr(_цепь, 'forward_origin', None) is not None:
                        _кто += ' (переслано)'
                    подано.insert(0, {'i': _цепь.message_id, 'кто': _кто, 'т': _т})
                _цепь = getattr(_цепь, 'reply_to_message', None)
                _ш += 1

            if подано:
                _ид = set(з['i'] for з in подано)
                окно = подано + [з for з in (окно or []) if з.get('i') not in _ид]

            if not окно:
                await update.message.reply_text(
                    '🧩 В отмеченном сообщении нет текста, который я мог бы разобрать — '
                    'ни подписи, ни цитаты. Пришли текстом или отметь сообщение с текстом.')
                return
            свод = полка_взять('ПОЛКА-18') or '(свод правил ещё не заведён)'
            беседа = "\n".join("[%s] %s: %s" % (з['i'], з['кто'], з['т']) for з in окно)
            задача = (
                "ВМЕШАЙСЯ В ДИАЛОГ. Вот кусок беседы из чата; отмеченное сообщение — №%s.\n\n"
                "%s\n\n=== СВОД ПРАВИЛ ПРОЕКТА ===\n%s\n\n"
                "Сделай ровно четыре вещи, каждую с заголовком:\n"
                "1. О ЧЁМ РАЗГОВОР — в двух предложениях, чтобы человек понял без чтения.\n"
                "2. СВЕРКА С ПРАВИЛАМИ — что здесь сказано согласно своду, а что ему "
                "противоречит. Ссылайся на конкретное правило.\n"
                "3. ОЦЕНКА — по существу: где верно, где ошибка, чего не хватает. Без "
                "вежливого тумана.\n"
                "4. ЧЕГО НЕТ В СВОДЕ — если разговор вскрыл правило, которого в своде нет, "
                "сформулируй его одной строкой. Нечего добавить — так и скажи.\n"
                % (_пред.message_id, dsoc_обезличить(беседа)[:9000], свод[:4000]))
            реплики = dsoc_память(chat_id)
            реплики.append({"role": "user", "content": задача})
            _ст = await update.message.reply_text("🧩 Восстанавливаю диалог (%d сообщений)…"
                                                  % len(окно))
            ответ, _вх, _вых = await asyncio.get_event_loop().run_in_executor(
                None, dsoc_запрос,
                [{"role": "system", "content": dsoc_системный()}] + dsoc_чистые(реплики[-40:]))
            if not ответ:
                await _ст.edit_text("🧩 Не вышло разобрать — модель промолчала.")
                await dsoc_неудача(context.bot, chat_id, _dsoc, '', 'вмешательство: пустой ответ')
                return
            реплики.append({"role": "assistant", "content": ответ, "t": time.time()})
            DSOC_ПАМЯТЬ[chat_id] = реплики
            dsoc_сохранить(силой=True)
            dsoc_расход_записать(dsoc_стоимость(_вх, _вых))
            _кл = "%d_%d" % (chat_id, int(time.time()))
            try:
                _сн = _data_get(DSOC_СНИМКИ_ФАЙЛ, {}) or {}
                _сн[_кл] = list(реплики)[-160:]
                _data_put(DSOC_СНИМКИ_ФАЙЛ, {k: v for k, v in list(_сн.items())[-8:]},
                          'снимок перед решением о контексте')
            except Exception:
                pass
            _хвост = ("\n\n<blockquote expandable>вход %d · выход %d ток · %s</blockquote>"
                      % (_вх, _вых, dsoc_остаток_строкой()))
            try:
                await _ст.edit_text(dsoc_в_html(ответ[:3300]) + _хвост, parse_mode='HTML',
                                    disable_web_page_preview=True)
            except Exception:
                await _ст.edit_text(ответ[:3800])
            # Судьба контекста — решает владелец, а не я за него.
            await update.message.reply_text(
                "🧩 Что сделать с этим разбором в памяти разговора?",
                reply_markup=_КЛ([[_КБ("💾 Сохранить", callback_data="ctx:keep:" + _кл),
                                   _КБ("🗜 Сжать", callback_data="ctx:squeeze:" + _кл),
                                   _КБ("✂️ Убрать", callback_data="ctx:drop:" + _кл)]]))
            return

        # ✂️ ТОЧЕЧНАЯ ЧИСТКА КОНТЕКСТА ПО ОТМЕЧЕННОМУ СООБЩЕНИЮ.
        # Заявка владельца, потерянная 05.08.2026 (её «приняла» Gemini и никому не передала):
        # «уметь вмешиваться в диалог по выделенному сообщению… и предлагать удаление его
        # части». Показать пальцем проще, чем описывать словами, что именно выкинуть.
        if is_owner(update) and re.search(
                r'(убери|удали|выкинь|забудь)\b.*(контекст|это|эту|отсюда)|^забудь это$',
                _dsoc.strip().lower()):
            реплики = dsoc_память(chat_id)
            снимок = list(реплики)
            убрано, что_убрал = 0, ''
            _пред = update.message.reply_to_message
            _цель = ((getattr(_пред, 'text', None) or getattr(_пред, 'caption', None) or '')
                     if _пред else '')
            if _цель:
                # Отмеченное сообщение: ищем его в памяти по началу текста — совпадения
                # «слово в слово» не будет, у ответов помощника снизу приклеена подпись.
                ключ = ' '.join(_цель.split())[:60]
                новые = [р for р in реплики
                         if ключ and ключ not in ' '.join((р.get('content') or '').split())]
                убрано = len(реплики) - len(новые)
                что_убрал = 'отмеченное сообщение'
                реплики = новые
            else:
                if len(реплики) >= 2:
                    реплики = реплики[:-2]
                    убрано, что_убрал = 2, 'последняя пара «вопрос-ответ»'
            if not убрано:
                await update.message.reply_text(
                    "🤔 Не нашёл этого в памяти разговора — возможно, оно туда и не попадало. "
                    "Отметь именно ту реплику, которую надо выкинуть.")
                return
            DSOC_ПАМЯТЬ[chat_id] = реплики
            dsoc_сохранить(силой=True)
            try:
                _кл = "%d_%d" % (chat_id, int(time.time()))
                _сн = _data_get(DSOC_СНИМКИ_ФАЙЛ, {}) or {}
                _сн[_кл] = снимок[-160:]
                _data_put(DSOC_СНИМКИ_ФАЙЛ, {k: v for k, v in list(_сн.items())[-8:]},
                          "снимок перед точечной чисткой")
                await update.message.reply_text(
                    "✂️ Убрал из памяти разговора: %s (%d реплик).\n"
                    "Осталось %d токенов переписки. Забытое не вернуть иначе — держи кнопку."
                    % (что_убрал, убрано, dsoc_размер(реплики)),
                    reply_markup=_КЛ([[_КБ("↩️ Вернуть как было",
                                           callback_data="dsocback:" + _кл)]]))
            except Exception:
                await update.message.reply_text("✂️ Убрал: %s (%d реплик)." % (что_убрал, убрано))
            return

        # Владелец пометил ответ помощника неудачным — записываем с цитатой того ответа.
        if is_owner(update) and _dsoc.strip().lower().rstrip('!.') in (
                'неудача', 'не то', 'плохой ответ', 'мимо', 'не ответил'):
            _пред = update.message.reply_to_message
            _цитата = (getattr(_пред, 'text', None) or getattr(_пред, 'caption', None) or '') if _пред else ''
            _н = await dsoc_неудача(context.bot, chat_id, '(помечено владельцем вручную)',
                                    _цитата, 'владелец: ответ не годится')
            await update.message.reply_text(
                "🔻 Записал как неудачу №%s — с цитатой того ответа. Разберу и превращу в "
                "знание, правку или выговор." % _н)
            return

        # ⚡ ОПЕРАТИВНЫЙ КАНАЛ: владелец через помощника зовёт живого технадзора.
        # Срабатывает по ПРЯМОМУ слову, а не по догадке — иначе обычные вопросы утонут в очереди.
        _низ_зов = _dsoc.lower()
        _прямо = any(_низ_зов.startswith(с) or (' ' + с + ' ') in (' ' + _низ_зов + ' ')
                     for с in DSOC_ЗОВ_КЛОДА)
        _тревожно = any(с in _низ_зов for с in DSOC_ПРИЗНАКИ_СРОЧНОГО)
        # Ответ НА СООБЩЕНИЕ ТЕХНАДЗОРА — обращение к нему. Ответить на чью-то реплику —
        # обычный способ обратиться именно к нему; требовать при этом ещё и назвать его по
        # имени значит выдумывать обряд на ровном месте.
        # Оговорка владельца принята: не всякий ответ есть просьба. Короткая вежливость
        # («спасибо», «понял», «ок») зовом не считается — дёргать по ней живого человека
        # незачем. Ошибка здесь дёшева в одну сторону и дорога в другую: лишний зов стоит мне
        # строки в ленте, пропущенный — молчания в ответ на просьбу.
        try:
            _цель = update.message.reply_to_message
            _цт = ((getattr(_цель, 'text', None) or getattr(_цель, 'caption', None) or '')
                   if _цель else '')
            if ('🧠 Клод' in _цт or 'Технадзор' in _цт[:80]) and not re.match(
                    r'^\s*(спасибо|благодарю|понял|поняла|ок|окей|ага|хорошо|принял|ясно|'
                    r'отлично|супер|👍|\+)\s*[!.)]*\s*$', _низ_зов):
                _прямо = True
        except Exception:
            pass
        if is_owner(update) and (_прямо or _тревожно):
            _отм = {}
            try:
                _р = update.message.reply_to_message
                if _р:
                    _отм = {'смс': _р.message_id,
                            'кто': (getattr(getattr(_р, 'from_user', None), 'first_name', '')
                                    or 'кто-то'),
                            'текст': ((getattr(_р, 'text', None)
                                       or getattr(_р, 'caption', None) or '')[:1200])}
            except Exception:
                _отм = {}
            _н = dsoc_позвать_клода(chat_id, update.message.message_id, _dsoc,
                                    getattr(update.effective_user, 'first_name', ''),
                                    отмечено=_отм)
            try:
                await context.bot.send_message(
                    LOG_CHAT_ID,
                    "📣 <b>ВЛАДЕЛЕЦ ЗОВЁТ ТЕХНАДЗОРА</b> (обращение #%s)\n%s\n%s\n"
                    "Ответ ждут здесь: https://t.me/c/%s/%s"
                    % (_н, (_dsoc or '')[:900],
                       ("\n<b>Отмечено им:</b> «%s» — %s\nhttps://t.me/c/%s/%s\n"
                        % ((_отм.get('текст') or '')[:400].replace('<', '&lt;'),
                           _отм.get('кто') or '', str(chat_id).replace('-100', ''),
                           _отм.get('смс'))) if _отм.get('текст') else '',
                       str(chat_id).replace('-100', ''), update.message.message_id),
                    parse_mode='HTML', disable_web_page_preview=True)
            except Exception:
                pass
            if _прямо:
                _расписка = ("📣 Передал технадзору — обращение #%s. Он ответит прямо здесь, "
                             "ответом на это сообщение." % _н)
                await update.message.reply_text(_расписка)
                # Спросил голосом — и расписку слышит голосом. Правило владельца «отвечаю
                # голосом по умолчанию» относится ко ВСЕМ ответам, а не только к длинным:
                # ранние ветки молчали, и выходило, будто правило работает через раз.
                if _голосом_просили:
                    await сказать_голосом(update, _расписка, context)
                return
            # Тревожный признак без прямого зова: technadzor уведомлён, но разговор НЕ обрываем —
            # помощник отвечает как обычно. Иначе на каждое «почему» человек получал бы вместо
            # ответа расписку о передаче.


        # 🟡 К СВЕДЕНИЮ: всё остальное, что владелец пишет помощнику, я тоже вижу — но
        # отвечать не обязан. Пока настраиваем, полная видимость дороже тишины.
        # 🔴 05.08.2026, владелец: «это баг какой-то, ты делаешь какой к сведению, это что?»
        # Он спросил помощника про хадис — и получил канцелярскую расписку вместо ответа.
        # Расписку я приделал ко ВСЕМУ, что он пишет, а надо было — только к тому, что
        # адресовано МНЕ. Обычный вопрос помощнику не моё дело, лезть туда с номерком незачем.
        _мне_ли = bool(re.search(r'технадзор|клод|разработчик|передай|исправ|почему не|баг|'
                                 r'не работает|сломал', _низ_зов))
        if is_owner(update) and _мне_ли and not (_прямо or _тревожно):
            try:
                _нс = dsoc_позвать_клода(chat_id, update.message.message_id, _dsoc,
                                         getattr(update.effective_user, 'first_name', ''),
                                         важность="к сведению")
                # 🔴 05.08.2026, владелец: «ты должен такие вещи регистрировать как обращения
                # же, с номером?» Он прав: раньше «к сведению» уходило ко мне молча, и со
                # стороны это выглядело так, будто сказанное пропало. Номер видят оба — и он,
                # и я; спросить «а что с номером таким-то» теперь можно про ЛЮБОЕ его слово.
                if _нс:
                    await update.message.reply_text(
                        "📝 Записал технадзору к сведению — №%s (ответа не требует)." % _нс)
            except Exception:
                pass

        реплики = dsoc_память(chat_id)
        # Ответил на чьё-то сообщение — оно идёт в дело вместе с вопросом. Владелец:
        # «могу также ему добавить, отметив ответом, другое чужое смс — и он учитывает».
        цитата = ""
        try:
            r = update.message.reply_to_message
            если_текст = (getattr(r, "text", None) or getattr(r, "caption", None)) if r else None
            if если_текст:
                кто = (getattr(getattr(r, "from_user", None), "first_name", "") or "кто-то")
                # Сообщение технадзора — не реплика собеседника, а УКАЗАНИЕ. Владелец просил
                # различать это прямо: «бот должен квалифицировать смс от технадзора как
                # прямое обращение». Иначе помощник обсуждает указание вместо того, чтобы его
                # исполнять.
                if "🧠 Клод" in если_текст or "Технадзор" in если_текст[:80]:
                    цитата = ("\n\n[УКАЗАНИЕ ТЕХНАДЗОРА — это не мнение собеседника, а как "
                              "поступать. Прими к исполнению, не спорь и не пересказывай]:\n%s"
                              % если_текст[:4000])
                else:
                    цитата = "\n\n[Сообщение, на которое отвечают — от %s]:\n%s" % (кто, если_текст[:4000])
        except Exception:
            pass

        реплики.append({"role": "user", "content": _dsoc + цитата})
        if dsoc_размер(реплики) > DSOC_СЖИМАТЬ_ОТ:
            # Владелец: «удаление части точно ненужного контекста автоматом — дело хорошее, но
            # тогда мне в рабочий журнал должно приходить уведомление с кнопкой, если надо
            # вернуть обратно». Он прав: автоматика хороша ровно до тех пор, пока она на глазах
            # и обратима. Молча ужимать чужую память — то же, что молча выбрасывать чужие бумаги.
            _до = dsoc_размер(реплики)
            _снимок = list(реплики)
            реплики = dsoc_ужать(реплики)
            DSOC_ПАМЯТЬ[chat_id] = реплики
            try:
                _кл = "%d_%d" % (chat_id, int(time.time()))
                _сн = _data_get(DSOC_СНИМКИ_ФАЙЛ, {}) or {}
                _сн[_кл] = _снимок[-160:]
                _data_put(DSOC_СНИМКИ_ФАЙЛ, {k: v for k, v in list(_сн.items())[-8:]},
                          "снимок памяти до сжатия")
                await context.bot.send_message(
                    LOG_CHAT_ID,
                    "🗜 <b>Разговор помощника сжат</b>\n"
                    "было %d ток → стало %d ток (свернул середину, начало и последние реплики "
                    "целы).\nЕсли свернулось нужное — верну целиком одной кнопкой."
                    % (_до, dsoc_размер(реплики)),
                    parse_mode="HTML",
                    reply_markup=_КЛ([[_КБ("↩️ Вернуть как было",
                                           callback_data="dsocback:" + _кл)]]))
            except Exception:
                pass

        # Пустое сообщение, которое будем ДОПИСЫВАТЬ на глазах — владелец просил, чтобы
        # было видно, как набирается ответ, а не ждать молча.
        шапка = "💬 DSOC думает…"
        живое = await update.message.reply_text(шапка)
        начало = time.time()
        собрано, последняя_правка, вх, вых = "", 0.0, 0, 0
        try:
            # 🔴 Здесь стоял свой, короткий системный промт — а рядом жила функция
            # dsoc_системный() со списком команд, и её никто не звал. Ассистент поэтому не знал
            # ни одной нашей команды, хотя весь смысл затеи был в том, чтобы он их подсказывал.
            тело = {"model": OPENCODE_MODEL,
                    "messages": ([{"role": "system", "content": dsoc_системный()}]
                                 + dsoc_чистые(реплики[-60:])),
                    "max_tokens": 8000, "temperature": 0.4, "stream": True}
            о = requests.post(OPENCODE_URL, json=тело, stream=True, timeout=600,
                              headers={"Content-Type": "application/json",
                                       "Authorization": "Bearer " + OPENCODE_KEY})
            # 🔴 05.08.2026: было decode_unicode=True — и владелец получил «ÐÐµÑÐµÐ²Ð¾Ð´»
            # вместо «Перевод». В этом режиме библиотека берёт кодировку из заголовка ответа,
            # а поток событий её не объявляет — и русские байты молча разбираются как латиница.
            # И модель, и сеть отработали безупречно: испортилось на последнем шаге, у нас.
            # Лечение: не доверять угадыванию, разбирать байты самим и всегда в utf-8.
            for сырое in о.iter_lines(decode_unicode=False):
                if not сырое:
                    continue
                строка = сырое.decode("utf-8", "replace") if isinstance(сырое, bytes) else сырое
                if not строка.startswith("data: "):
                    continue
                кусок = строка[6:]
                if кусок == "[DONE]":
                    break
                try:
                    j = json.loads(кусок)
                except Exception:
                    continue
                вы = (j.get("choices") or [{}])[0]
                д = (вы.get("delta") or {}).get("content")
                if д:
                    собрано += д
                u = j.get("usage") or {}
                вх = u.get("prompt_tokens") or вх
                вых = u.get("completion_tokens") or вых
                # правим сообщение не чаще чем раз в 2,5 секунды: Telegram ругается на
                # частые правки, а глазу и так довольно
                # Владелец: «печатает слишком резко, нельзя ли по словам». Было раз в 2,5 с
                # и целым куском — оттого рывками, да ещё и обрыв посреди слова. Теперь чаще и
                # ровно по границе слова. Чаще 1 с нельзя: Telegram отвечает 429 на частые
                # правки. Облаку это почти ничего не стоит — правка сообщения не считает
                # токенов, платит только Telegram своим лимитом.
                if собрано and time.time() - последняя_правка > 1.1:
                    последняя_правка = time.time()
                    видно = собрано[-3900:]
                    _п = видно.rfind(" ")
                    if _п > 40:
                        видно = видно[:_п]        # не показывать полслова
                    try:
                        await живое.edit_text(видно + " ▌")
                    except Exception:
                        pass
        except Exception as e:
            # ПОДСТРАХОВКА (владелец 05.08.2026: «может, на резерв поставишь API ключи, они
            # подстрахуют?»). Молчание вместо ответа — худший исход. Отвечаем с бесплатных
            # каналов и ЧЕСТНО пишем, что отвечал резерв: подменять исполнителя молча нельзя.
            собрано = ''
            # ПОРЯДОК РЕЗЕРВА (владелец 05.08.2026). Первым — Gemini: у него тоже миллион
            # контекста, то есть он один заменяет OpenCode без потерь. Остальные бесплатные
            # держат 128 тысяч — этого всё равно вдвадцатеро больше нашего разговора, так что
            # беседа доедет целиком. Платный DeepSeek — последним, он дороже и не длиннее.
            _вся_беседа = "\n".join(
                ("%s: %s" % ('владелец' if р.get('role') == 'user' else 'ты',
                             (р.get('content') or '')[:1500]))
                for р in dsoc_чистые(реплики[-40:]))
            _запрос_рез = (_вся_беседа[-90000:] + "\n\nОтветь на последнюю реплику владельца.")
            # 🚨 ТРЕВОГА ПРИ ПЕРВОЙ ЖЕ ПОДМЕНЕ (слово владельца 05.08.2026: «отметку делай
            # сразу, тревогу»). Подмена спасает разговор — и именно поэтому о ней надо
            # кричать: молчаливая подмена это когда всё «работает», а счёт растёт из другого
            # кармана и никто не знает почему.
            _чем_ответили = ''
            try:
                await context.bot.send_message(
                    LOG_CHAT_ID,
                    "🚨 <b>OPENCODE НЕ ОТВЕТИЛ — ушли на резерв</b>\n"
                    "причина: %s\nчат: %s · время: %s\n"
                    "Сейчас отвечает платный DeepSeek API (наш), при его отказе — бесплатные."
                    % (str(e)[:200], chat_id, _now_msk()), parse_mode='HTML')
            except Exception:
                pass
            try:
                # ② наш платный DeepSeek — та же семья моделей, ответ не просядет
                _рез = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: (ask_deepseek(_запрос_рез[:60000], dsoc_системный(), 1500)
                                   if DEEPSEEK_API_KEY else None))
                _чем_ответили = 'платный DeepSeek API (наш)'
                if not _рез or str(_рез).startswith('⚠️'):
                    # ③ бесплатные, Gemini первым — у него тоже миллион контекста
                    _рез = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: (ask_gemini(_запрос_рез, dsoc_системный())
                                       if GEMINI_API_KEY else None))
                    _чем_ответили = 'Gemini (бесплатный)'
                if not _рез or str(_рез).startswith('⚠️'):
                    _рез = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: ask_ai(_запрос_рез[:60000], dsoc_системный(), True, 1500))
                    _чем_ответили = 'бесплатная цепочка'
                if _рез and not str(_рез).startswith('⚠️'):
                    собрано = (re.sub(r'⚡ \*Модель:\*.*|🆓.*|📊 осталось.*', '', _рез).strip()
                               + '\n\n⚠️ <i>Отвечал резерв — %s. OpenCode не отозвался (%s).</i>'
                               % (_чем_ответили, str(e)[:80]))
            except Exception:
                собрано = ''
            if not собрано:
                try:
                    await живое.edit_text(
                        "🔴 Не ответил ни OpenCode, ни резерв: %s" % str(e)[:200])
                except Exception:
                    pass
                await dsoc_неудача(context.bot, chat_id, _dsoc, '', 'молчат все каналы')
                return
            try:
                await живое.edit_text(собрано[:3800], parse_mode='HTML')
            except Exception:
                try:
                    await живое.edit_text(re.sub(r'<[^>]+>', '', собрано)[:3800])
                except Exception:
                    pass
            реплики.append({"role": "assistant", "content": собрано, "t": time.time()})
            DSOC_ПАМЯТЬ[chat_id] = реплики
            dsoc_сохранить(силой=True)
            return

        # ── ИНСТРУМЕНТЫ: модель просит данные — идём и приносим. ДО ТРЁХ КРУГОВ ──────
        # Один круг оказался мало: по короткому прозвищу «аль-Амаш» база не нашла, модель
        # разумно решила попробовать полное имя — а выполнять её второй вызов было уже некому,
        # и черновик уехал владельцу. Поиск редко укладывается в один заход.
        for _круг in range(3):
            _вз = re.search(r'^\s*ВЫЗОВ:\s*(.+)$', собрано or '', re.M)
            if not _вз:
                break
            try:
                await живое.edit_text("🔎 Достаю из базы: %s…" % _вз.group(1).strip()[:80])
            except Exception:
                pass
            данные = await dsoc_инструмент(_вз.group(1).strip())
            if not данные:
                break
            # Инструмент вернул не текст для модели, а готовый файл — отдаём его человеку сразу
            # и разговор не продолжаем: дело сделано, пересказывать файл словами незачем.
            # Помощник просит отложить тяжёлое в облачный архив — кладём и говорим, куда.
            if isinstance(данные, str) and данные.startswith('В_АРХИВ|'):
                _тело_арх = данные.split('|', 1)[1]
                _ок_а, _беда_а = await отправить_файлом(
                    context.bot, АРХИВ_ГРУППА,
                    'razbor_%s.md' % time.strftime('%d%m_%H%M'), _тело_арх,
                    подпись='📦 От помощника DSOC · %s' % _now_msk())
                try:
                    await живое.edit_text(
                        '📦 Отложил в облачный архив — там место, а разговор не засорён.'
                        if _ок_а else '🔴 В архив не легло: %s' % _беда_а)
                except Exception:
                    pass
                реплики.append({"role": "assistant",
                                "content": "(отложил в облачный архив)", "t": time.time()})
                DSOC_ПАМЯТЬ[chat_id] = реплики
                dsoc_сохранить(силой=True)
                return
            if isinstance(данные, str) and данные.startswith('ФАЙЛ ГОТОВ|'):
                _, _метка, _содержимое = данные.split('|', 2)
                ок, беда = await отправить_файлом(
                    context.bot, chat_id, '%s.md' % _метка.lower(), _содержимое,
                    подпись='📄 <b>%s</b> — из полки знаний помощника' % _метка,
                    ответ_на=update.message.message_id)
                try:
                    await живое.edit_text('📄 Прислал файлом: %s' % _метка if ок
                                          else '🔴 Файл не ушёл: %s' % беда)
                except Exception:
                    pass
                реплики.append({"role": "assistant",
                                "content": "(прислал файл %s)" % _метка, "t": time.time()})
                DSOC_ПАМЯТЬ[chat_id] = реплики
                dsoc_сохранить(силой=True)
                return
            реплики.append({"role": "assistant", "content": собрано})
            реплики.append({"role": "user",
                            "content": "ДАННЫЕ ИЗ НАШЕЙ БАЗЫ (отвечай строго по ним, ничего не "
                                       "добавляя от себя). Если этого мало — можешь сделать ещё "
                                       "один ВЫЗОВ, но не больше:\n" + данные[:7000]})
            второй, _в2, _вых2 = await asyncio.get_event_loop().run_in_executor(
                None, dsoc_запрос,
                [{"role": "system", "content": dsoc_системный()}] + dsoc_чистые(реплики[-60:]))
            if not второй:
                break
            собрано = второй
            вх += _в2; вых += _вых2

        # Последняя защита: если строка вызова всё равно осталась — читателю её не показываем.
        # Внутренняя кухня не должна попадать наружу ни при какой поломке.
        if re.search(r'^\s*ВЫЗОВ:', собрано or '', re.M):
            собрано = re.sub(r'^\s*ВЫЗОВ:.*$', '', собрано, flags=re.M).strip()
            собрано += ("\n\n🔎 Дальше достать из базы не вышло — скажи имя точнее "
                        "(полное имя с отцом, либо по-арабски), и найду.")

        # ИНИЦИАТИВА: модель могла закончить строкой «ЗАЯВКА: …». Вырезаем её из ответа и
        # превращаем в предложение владельцу — подаём только по его «да».
        предложение, куда = "", "приложение"
        for метка, адрес in (("ПОМОЩНИКУ:", "помощник"), ("ЗАЯВКА:", "приложение")):
            if метка in собрано:
                собрано, _, предложение = собрано.rpartition(метка)
                предложение = предложение.strip()[:400]
                собрано = собрано.rstrip()
                куда = адрес
                break
        if предложение:
            DSOC_ЗАЯВКА_ЖДЁТ[chat_id] = (куда, предложение)

        сек = time.time() - начало
        вых = вых or (len(собрано) // 3)
        вх = вх or dsoc_размер(реплики)
        цена = dsoc_стоимость(вх, вых)
        dsoc_расход_записать(цена)
        реплики.append({"role": "assistant", "content": собрано, "t": time.time()})
        DSOC_ПАМЯТЬ[chat_id] = реплики
        dsoc_сохранить()

        # Владелец: «указывай, сколько из контекста — системный промт, а сколько переписка».
        # Системный промт (уговор о работе + знания о приложении + вызовы + полка) едет в
        # КАЖДОМ сообщении и сжатию не поддаётся; сжать можно только переписку. Одна общая
        # цифра эти две вещи путает и не подсказывает, что делать.
        _сист = len(dsoc_системный()) // 3
        _перепис = dsoc_размер(реплики)
        подпись = ("\n\n— 🟩 DSOC · %s · вход %d · выход %d ток · ⏱ %.1fс · ⚡ %.0f ток/с\n"
                   "💰 $%.5f · 📊 %s\n"
                   "🧠 контекст: %d из 1 000 000 (%.1f%%) — из них "
                   "системный промт %d ток (не сжимается), переписка %d ток (сжимаемо)"
                   % (OPENCODE_MODEL, вх, вых, сек, (вых / сек if сек else 0), цена,
                      dsoc_остаток_строкой(), _сист + _перепис,
                      (_сист + _перепис) / DSOC_ОКНО * 100, _сист, _перепис))
        # Неудача ловится САМА: осталась строка вызова, пустой ответ или признание «не нашёл».
        try:
            _низ_отв = (собрано or '').lower()
            _прич = None
            if not (собрано or '').strip():
                _прич = 'ответ пустой'
            elif 'Дальше достать из базы не вышло' in (собрано or ''):
                _прич = 'инструмент не принёс данных'
            elif any(п in _низ_отв for п in DSOC_ПРИЗНАКИ_НЕУДАЧИ):
                _прич = 'отказ: ' + next(п for п in DSOC_ПРИЗНАКИ_НЕУДАЧИ if п in _низ_отв)
            if _прич:
                await dsoc_неудача(context.bot, chat_id, _dsoc, собрано, _прич)
        except Exception:
            pass

        if предложение:
            подпись = ("\n📨 Предлагаю записать %s: «%s»\nОтветь «да» — запишу."
                       % ("в журнал помощника" if куда == "помощник" else "заявкой технадзору",
                          предложение[:300])) + подпись
        # Владелец: «подпись про остатки лучше отправлять в цитату, которая сворачивается».
        # Она нужна каждый раз, но каждый раз занимает пол-экрана — сворачиваемая цитата
        # ровно для такого: цифры на месте, глаза свободны.
        _тело = dsoc_в_html((собрано or "(пусто)")[:3400])
        _хвост = ("<blockquote expandable>"
                  + подпись.strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                  + "</blockquote>")
        try:
            await живое.edit_text(_тело + "\n\n" + _хвост, parse_mode="HTML",
                                  disable_web_page_preview=True)
        except Exception:
            try:      # разметка не зашла — отдаём как есть, лишь бы ответ дошёл
                await живое.edit_text((собрано or "(пусто)")[:3600] + подпись)
            except Exception:
                await update.message.reply_text((собрано or "(пусто)")[:3600] + подпись)
        # Спросили голосом или прямо просят озвучить — отвечаем ещё и речью.
        if собрано and (_голосом_просили
                        or re.search(r'\bголос|озвучь|скажи вслух|прочитай вслух', _dsoc, re.I)):
            await сказать_голосом(update, собрано, context)
        return


    # #опросы-13.07: если владелец выбрал «✍️ Свой вариант», ловим его следующий текст как ответ на опрос (а не в ИИ)
    if is_owner(update) and text and not text.startswith('/'):
        try:
            _pend = _data_get('poll_pending.json', None)
            if _pend and _pend.get('poll_id'):
                _res = _data_get('poll_results.json', {}) or {}
                _r = _res.setdefault(_pend['poll_id'], {'votes': {}})
                _r['write_in'] = text[:500]; _r['ref'] = _pend.get('ref', '')
                _data_put('poll_results.json', _res, 'свой вариант ' + _pend['poll_id'])
                _data_put('poll_pending.json', {}, 'сброс pending')
                try:
                    await update.message.reply_text('✍️ Твой вариант записан по опросу «' + _pend.get('q', '')[:60] + '». Клод увидит.')
                except Exception:
                    pass
                return
        except Exception:
            pass

    # 🆔 диагностика: «ид чата» (владелец, любой чат) — узнать числовой chat_id, напр. чтобы настроить кросс-пост ништячка в jamaat_ru
    if is_owner(update) and text.lower().strip() in ("ид чата", "id чата", "chat id", "ид группы"):
        ch = update.effective_chat
        await update.message.reply_text(f"🆔 id этого чата: `{ch.id}`\nНазвание: {getattr(ch,'title',None) or getattr(ch,'first_name','—')}\nТип: {ch.type}", parse_mode="Markdown")
        return

    # 🧑‍💻 МОСТ «КЛОД» (канал Muslim Live уже выше; тут — личка владельца, оба аккаунта)
    try:
        await _claude_deliver_replies(update, context)
        if await _claude_dispatch(update, context):
            return
    except Exception:
        pass

    # 🔍 Подтверждение черновика ништячка («в муслим лайв»/«да» реплаем на черновик) — публикует в @muslimlive
    try:
        if await _nisht_confirm_dispatch(update, context):
            return
    except Exception:
        pass

    # ✂️ «вырежи <начало> по <конец>» реплаем на аудио/видео — вырезать+расшифровать+пересказать
    try:
        if await _audio_cut_dispatch(update, context):
            return
    except Exception:
        pass

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
                if update.effective_chat.id != LOG_CHAT_ID:   # #41/#90: НЕ дублировать эхо в тот же чат (был тройной повтор)
                    await context.bot.copy_message(LOG_CHAT_ID, update.effective_chat.id, update.message.message_id)
                    await context.bot.send_message(LOG_CHAT_ID, f"📥 Заявка владельца #{rid} ({_now_msk()}): {(body or '(скрин)')[:300]}")
            except Exception:
                pass
            await update.message.reply_text(f"📥 Заявка #{rid} со скрином записана ✅ · 🤖 бот (уникальный № — ищи в журнале командой «заявки»).")   # M287
            return
    except Exception:
        pass

    # ── ЗАМЕЧАНИЕ К РАГ ОДНИМ ДВИЖЕНИЕМ (владелец 27.07.2026: «облегчённый интерфейс, чтобы можно
    # было свои замечания сразу прикреплять — запрос неточный, хадис такой-то упустил — и до тебя
    # доходило»). Никаких команд: ответил реплаем на ответ бота — замечание легло в журнал РАГ
    # к тому самому запросу. Простое поправлю сам, хлопотное останется записанным для доработки.
    try:
        _рм = getattr(update.message, 'reply_to_message', None)
        if _рм and _ПОСЛ_РАГ.get('ответ_msg') and _рм.message_id == _ПОСЛ_РАГ['ответ_msg']                 and (text or '').strip() and not (text or '').lower().startswith(('раг ', 'rag ')):
            _ж_лог = _data_get('rag_journal.json', []) or []
            if _ж_лог:
                _ж_лог[-1].setdefault('замечания', []).append({
                    'когда': _time_boot.strftime('%d.%m %H:%M', _time_boot.localtime()),
                    'текст': (text or '').strip()[:600],
                    'кто': (update.effective_user.first_name if update.effective_user else 'владелец')})
                _data_put('rag_journal.json', _ж_лог[-500:], 'раг: замечание владельца')
                await update.message.reply_text(
                    '📝 Записал в журнал РАГ — к запросу «%s».\nПростое поправлю сам, '
                    'хлопотное пойдёт в доработку.' % (_ж_лог[-1].get('вопрос') or '')[:60])
                return
    except Exception:
        pass

    # 🧩 RAG-поиск по ядру (первоисточники+риджаль). Триггер — ТОЛЬКО слово «раг» (чтобы не мешать болтовне в чате).
    # Доступ: пока только владелец; рубильник «всем» + белый/чёрный списки (команды владельца).
    try:
        _low = text.lower().strip()
        # #667: гейт стоит именно ЗДЕСЬ, на входе во весь раздел раг, а не глубже у самого
        # поиска — чтобы реплика про раг не тратила ни квоту участника, ни нейроны Cloudflare
        # и не оставляла в чате висящее «🧠 Ищу по смыслу…». См. _раг_это_реплика выше.
        if (_low == 'раг' or _low.startswith(('раг ', 'rag '))) and not _раг_это_реплика(text):
            _uid = update.effective_user.id if update.effective_user else 0
            # анонимный админ группы (пишет «от имени группы») — Telegram не отдаёт его ID; считаем доверенным
            _anon = bool(getattr(update.message, 'sender_chat', None) and update.effective_chat
                         and update.message.sender_chat.id == update.effective_chat.id)
            # 🩺 ДИАГНОСТИКА (только владелец): видит ли бот токен и что отвечает Space
            if _low in ('раг диаг', 'раг debug', 'раг тест') and (is_owner(update) or _anon):
                import aiohttp
                _t = RAG_HF_TOKEN
                _info = ['🩺 RAG диагностика:',
                         'HF_TOKEN: %s (длина %d)' % (('задан %s…%s' % (_t[:5], _t[-3:])) if _t else '❌ ПУСТ', len(_t)),
                         'Space: %s' % RAG_SPACE_URL]
                try:
                    async with aiohttp.ClientSession() as _s:
                        _h = {'Authorization': 'Bearer ' + _t} if _t else {}
                        async with _s.get(RAG_SPACE_URL + '/health', headers=_h,
                                          timeout=aiohttp.ClientTimeout(total=20)) as _r:
                            _info.append('/health → HTTP %d (%s)' % (_r.status, (await _r.text())[:60]))
                except Exception as _e:
                    _info.append('/health → ошибка: %s' % str(_e)[:80])
                await update.message.reply_text('\n'.join(_info))
                return
            # 📊 ЖУРНАЛ КАЧЕСТВА ПОИСКА (#671, только владелец): «раг оценки».
            # Владелец просил не просто копить отметки «не туда», а видеть их — иначе журнал
            # существует только для меня, а не для него. Показываем счёт 👎/👍 и последние
            # промахи с самим вопросом и близостью: по этим числам и подбирается порог.
            if _low in ('раг оценки', 'раг журнал', 'раг качество', 'rag оценки') and (is_owner(update) or _anon):
                try:
                    _оц = await asyncio.get_event_loop().run_in_executor(
                        None, _data_get, 'rag_feedback.json', [])
                    _оц = _оц if isinstance(_оц, list) else []
                except Exception:
                    _оц = []
                if not _оц:
                    await update.message.reply_text(
                        '📊 Журнал качества РАГ пуст — ни одной отметки.\n'
                        'Кнопки «👎 не туда» / «👍 в точку» в приложении шлют их на /api/rag_feedback.')
                    return
                _мимо = [z for z in _оц if z.get('вердикт') == 'мимо']
                _точно = [z for z in _оц if z.get('вердикт') == 'в точку']
                _стр = ['📊 <b>Качество РАГ</b> — отметок: %d (👎 %d · 👍 %d)'
                        % (len(_оц), len(_мимо), len(_точно))]
                # средняя близость по вердиктам: если у 👎 она ВЫШЕ порога — порог мало помогает,
                # и лечить надо не отсечкой, а подбором (перевод запроса на арабский и т.п.)
                for _им, _гр in (('👎 не туда', _мимо), ('👍 в точку', _точно)):
                    if _гр:
                        _б = [float(z.get('близость') or 0) for z in _гр]
                        _стр.append('%s: средняя близость %d%%, длина запроса ~%.1f сл.'
                                    % (_им, round(100 * sum(_б) / len(_б)),
                                       sum(int(z.get('слов') or 0) for z in _гр) / len(_гр)))
                _стр.append('')
                _стр.append('<b>Последние промахи:</b>')
                for z in _мимо[-10:][::-1]:
                    _стр.append('• «%s» → %s %s · %d%%%s'
                                % (html.escape(str(z.get('вопрос') or ''))[:70],
                                   html.escape(str(z.get('книга') or '—')), z.get('номер') or '',
                                   round(float(z.get('близость') or 0) * 100),
                                   (' · 📝 ' + html.escape(str(z.get('комментарий'))[:80]))
                                   if z.get('комментарий') else ''))
                _стр.append('')
                _стр.append('<i>Файл: ветка data → rag_feedback.json</i>')
                await update.message.reply_text('\n'.join(_стр)[:3900], parse_mode='HTML',
                                                disable_web_page_preview=True)
                return
            # команды управления доступом (только владелец или анон-админ группы)
            if is_owner(update) or _anon:
                _ac = _rag_access_cmd(text)
                if _ac is not None:
                    await update.message.reply_text(_ac)
                    return
            # ── ГДЕ И КОМУ РАЗРЕШЁН РАГ (владелец 27.07.2026) ──────────────────────────────
            # «Эта функция строго в джамаат ру только работает пока, даже в личке никому кроме
            # меня — два аккаунта. Лимит установи также для других пользователей, небольшой,
            # не забудь: обращайтесь к админам, пусть пишут».
            # Значит: владелец — везде и без счёта; участники — ТОЛЬКО в чате Джамаат и с
            # дневным лимитом; всё остальное — вежливый отказ. Каждый вопрос стоит нейронов
            # Cloudflare, поэтому лимит здесь не формальность, а защита общего кошелька.
            _свой = is_owner(update) or _anon or _rag_allowed(_uid)
            _в_джамаате = bool(update.effective_chat and update.effective_chat.id == RAG_CHAT_ID)
            if not _свой:
                if not _в_джамаате:
                    # #673: «если раг нажатие идёт [из другого чата] — почему не показывает лимиты
                    # и остатки?». Разгадка: в чужой группе бот молчал совсем (голый `return`), и
                    # снаружи это неотличимо от поломки — ни отказа, ни правил, ни остатка.
                    # Теперь отвечаем и там, но с намордником: одна подсказка на чат в 10 минут,
                    # чтобы «раг» в шумной группе не превратился в спам от бота.
                    if update.effective_chat and update.effective_chat.type == 'private':
                        await update.message.reply_text(
                            '🔒 Смысловой поиск работает пока только в чате @jamaat_ru — заходи туда и спрашивай.')
                    elif rate_ok('ragнеттут:%s' % (update.effective_chat.id if update.effective_chat else 0), 1, 600):
                        _о, _вс = _rag_остаток(_uid)
                        await update.message.reply_text(
                            '🔒 Смысловой поиск (РАГ) включён пока только в @jamaat_ru — там и спрашивай.\n'
                            '👤 лимит на человека: %d запросов в сутки, у тебя осталось %d.\n'
                            'Нужно больше — напиши админам чата.' % (_вс, _о))
                    return
                _можно, _ост = _rag_квота(_uid)
                if not _можно:
                    # #673: число берём из настройки, а не из константы — владелец меняет его
                    # командой «раг лимит N», и текст обязан говорить ПРАВДУ, а не старое «3».
                    await update.message.reply_text(
                        '🔒 На сегодня твои %d запроса к РАГ израсходованы — счётчик обнулится завтра.\n'
                        'Нужно больше — напиши админам чата, откроют.' % _rag_лимит())
                    return
            # ── RAG ПО САХИХ АЛЬ-БУХАРИ (владелец 26.07.2026: «джамаат ру как слать?») ──────────
            # Машинерия поиска по нашей базе (_rag_find_sync + bukhari.vec.json, 14 344 вектора)
            # была написана, но НИКЕМ НЕ ВЫЗЫВАЛАСЬ — команда «раг» уходила в HuggingFace Space,
            # то есть в чужую систему мимо нашей книги. Подключаем: «бухари <вопрос>» ищет ПО СМЫСЛУ
            # в нашей базе, а прежний путь остаётся для остальных сборников.
            # Владелец 26.07.2026 поправил: «не бухари, а РАГ вызывает раг, а РАГ БУХАРИ ограничивает
            # в Бухари». То есть «раг <вопрос>» — поиск по смыслу по всей нашей базе, а приписка
            # «бухари» сужает до этой книги. Пока размечен один Бухари, поэтому оба пути ведут к нему;
            # когда добавятся остальные сборники, «раг» станет искать по всем, а «раг бухари» — только тут.
            if _low.startswith(('раг ', 'rag ')) and not _low.startswith(('раг диаг', 'раг debug', 'раг тест')):
                _вопрос = re.sub(r'^(раг|rag)\s+(бухари\s+)?', '', text, flags=re.I).strip()
                _только_бухари = bool(re.match(r'^(раг|rag)\s+бухари\s+', text, flags=re.I))
                if len(_вопрос) < 3:
                    await update.message.reply_text('Напиши вопрос: «раг можно ли пить стоя» или «раг бухари ...» — только по этой книге')
                    return
                try:
                    _ПОСЛ_РАГ.update({'chat': update.effective_chat.id if update.effective_chat else None,
                                      'msg': update.message.message_id, 'вопрос': _вопрос[:120],
                                      'когда': _time_boot.time()})
                    _ЛЕНТА_РАГ.append(dict(_ПОСЛ_РАГ))
                    del _ЛЕНТА_РАГ[:-30]
                except Exception:
                    pass
                try:
                    _ж = await update.message.reply_text('🧠 Ищу по смыслу%s…' % (' в Сахих аль-Бухари' if _только_бухари else ''))
                except Exception:
                    _ж = None
                # 27.07.2026: здесь стояло `loop.run_in_executor`, но `loop` живёт ВНУТРИ _api_serve —
                # в обработчике чата его нет, и на этой строке вылетал NameError. Снаружи это выглядело
                # ровно как прошлая беда с math.sqrt: бот пишет «Ищу по смыслу…» и молчит, потому что
                # исключение до пользователя не доходит. Берём текущий цикл так же, как в /api/rag_find,
                # и оборачиваем: если снова что-то отвалится — владелец увидит причину, а не тишину.
                # Второе объяснение молчания, более вероятное, чем падение: ЗАВИСАНИЕ. Общий пул
                # потоков (run_in_executor(None, ...)) делят все блокирующие операции бота; если он
                # забит, задача ждёт в очереди сколько угодно — «Ищу…» висит вечно, и снаружи это
                # выглядит точно так же, как поломка. Поэтому: свой отдельный пул только под RAG
                # (никто его не займёт) и жёсткий срок ожидания — лучше честное «не успел», чем тишина.
                _кэш_до = _ВЕК_СЧЁТ['из_кэша']
                # 01.08.2026 (#667, доверяй но проверяй): сам поиск ниже накрыт wait_for(45),
                # а ВОТ ЭТОТ вызов срока не имел — и это оставалась дыра ровно того же класса,
                # из-за которой «🧠 Ищу по смыслу…» висело вечно. В пуле _RAG_POOL всего два
                # работника; если оба заняты первой загрузкой базы (там requests с timeout=120),
                # то этот await ждал бы очереди СКОЛЬКО УГОДНО — ещё до всякого поиска.
                # Остаток нейронов — справочная строка в подвале ответа, ради неё ждать нельзя.
                try:
                    await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(_RAG_POOL, _cf_neurons_sync),
                        timeout=10)
                except Exception:
                    pass
                _из_кэша = False
                try:
                    _нашли, _беда = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(_RAG_POOL, _rag_find_sync, _вопрос, 5),
                        timeout=45)
                except asyncio.TimeoutError:
                    _нашли, _беда = None, ('поиск не уложился в 45 секунд. Если база грузится впервые '
                                           'после перезапуска — повтори запрос через полминуты.')
                except Exception as _e:
                    _нашли, _беда = None, '%s: %s' % (type(_e).__name__, str(_e)[:160])
                _из_кэша = _ВЕК_СЧЁТ['из_кэша'] > _кэш_до
                # 27.07.2026, третий заход. Владелец прислал скрин молчания уже на СВЕЖЕЙ сборке —
                # значит падает не там, где я думал, а ниже: при сборке текста или при отправке.
                # Хватит гадать вслепую: весь остаток обёрнут так, что ЛЮБАЯ ошибка выходит владельцу
                # текстом. Молчание — худший вид поломки: неотличимо от «висит» и не даёт зацепки.
                try:
                    if not _нашли:
                        _т = '🧠 Не нашёл: %s' % (_беда or 'ничего похожего по смыслу')
                    else:
                        # Формат задан владельцем 27.07.2026: «оригинал тоже обязательно; ссылку на
                        # хадис в приложении обязательно; указывать, потрачен ли лимит и накоплено ли
                        # знание; может, цитатой — арабский отдельно, русский отдельно, и чтобы
                        # сворачивалось». Telegram умеет <blockquote expandable>: длинный хадис лежит
                        # свёрнутым и раскрывается тапом — потому всё в одном посте, а не в пяти.
                        _строки = ['🧠 <b>Сахих аль-Бухари</b> · по смыслу: «%s»' % html.escape(_вопрос[:70]), '']
                        for _z in _нашли:
                            _н = _z.get('n') or '?'
                            _ар = re.sub(r'\s+', ' ', str(_z.get('a') or '')).strip()
                            _ру = re.sub(r'\s+', ' ', str(_z.get('r') or '')).strip()
                            # ссылка открывает мини-апп сразу на этом хадисе (формат startapp=r_<книга>_<номер>)
                            _сс = 'https://t.me/muslimoontt_bot?startapp=r_bukhari_%s' % _н
                            # Владелец 27.07.2026: «каждому хадису присваивай балл, насколько он
                            # совпадает по мнению машины». Показываем ЧЕСТНО: сама близость векторов
                            # в процентах и отдельно — совпали ли слова буквально. Так видно, на чём
                            # держится находка: на смысле, на словах или на обоих сразу.
                            _балл = int(round(float(_z.get('s') or 0) * 100))
                            _сл = float(_z.get('w') or 0)
                            _как = ' · 🎯 слова совпали' if _сл >= 0.5 else (' · 🔤 частично' if _сл > 0 else '')
                            _строки.append('<a href="%s">📖 Сахих аль-Бухари №%s</a> — <b>%d%%</b>%s'
                                           % (_сс, _н, _балл, _как))
                            # Владелец 27.07.2026: «хадисы обрезаются, а не полные». Режем не текст,
                            # а число хадисов: полный хадис ценнее, чем пять огрызков. Сколько влезет
                            # в лимит Telegram (4096) — столько и покажем, остальное честно посчитаем.
                            _цит = []
                            if _ар:
                                _цит.append('<b>%s</b>' % html.escape(_ар))
                            if _ру:
                                _цит.append(html.escape(_ру))
                            if _цит:
                                _строки.append('<blockquote expandable>%s</blockquote>' % '\n\n'.join(_цит))
                            _строки.append('')
                        _строки.append('<i>Найдено по смыслу — слова вопроса в тексте могут не встречаться. '
                                       'Размечен пока только Сахих аль-Бухари: 14 344 фрагмента.</i>')
                        _ост = ''
                        try:
                            _нейр = _CF_ЛИМИТ.get('нейронов')
                            if _нейр is not None:
                                _ост = ' · лимит Cloudflare: %d из %d нейронов за сутки, осталось %d' % (
                                    int(_нейр), _CF_СУТКИ, max(0, _CF_СУТКИ - int(_нейр)))
                            elif _CF_ЛИМИТ.get('ошибка'):
                                _ост = ' · остаток Cloudflare не отдаёт (%s)' % _CF_ЛИМИТ['ошибка'][:40]
                        except Exception:
                            pass
                        if not _свой:
                            _мой, _всего_л = _rag_остаток(_uid)
                            _строки.append('👤 твоих запросов на сегодня осталось: <b>%d</b> из %d · '
                                           'нужно больше — напиши админам чата' % (_мой, _всего_л))
                        _строки.append('⚙️ вектор <code>bge-m3</code> · %s · за смену: новых %d, из накопленного %d%s'
                                       % ('взят из накопленного, лимит не тронут' if _из_кэша
                                          else 'новый запрос к Cloudflare',
                                          _ВЕК_СЧЁТ['новых'], _ВЕК_СЧЁТ['из_кэша'], _ост))
                        _т = '\n'.join(_строки)
                except Exception as _e2:
                    _т = '🧠 Сбой при сборке ответа: %s: %s' % (type(_e2).__name__, str(_e2)[:200])
                # ЖУРНАЛ РАГ (владелец 27.07.2026: «в журнал рага, который ты должен был создать,
                # добавляй; простое — правь сам, хлопотное — записывай, потом улучшим. РАГ должен
                # совершенствоваться»). Пишем КАЖДЫЙ запрос: что спросили, что нашлось, с какими
                # оценками. К этой записи потом цепляется замечание владельца — так видно не только
                # «что сломалось», но и «что подобралось плохо».
                try:
                    _зап = {'когда': _time_boot.strftime('%d.%m %H:%M', _time_boot.localtime()),
                            'вопрос': _вопрос[:200], 'сборка': СБОРКА,
                            'нашёл': [{'n': _z.get('n'), 'оценка': round(float(_z.get('s') or 0), 3)}
                                      for _z in (_нашли or [])],
                            'беда': str(_беда)[:200] if not _нашли else '',
                            'из_накопленного': bool(_из_кэша), 'замечания': []}
                    _ж_лог = _data_get('rag_journal.json', []) or []
                    _ж_лог.append(_зап)
                    _data_put('rag_journal.json', _ж_лог[-500:], 'раг: запрос «%s»' % _вопрос[:40])
                except Exception:
                    pass
                # Отправка тоже под охраной: если и HTML, и запасной простой текст не прошли,
                # владелец всё равно должен получить хоть что-то — тишина недопустима.
                try:
                    from telegram import InlineKeyboardButton as _IKB, InlineKeyboardMarkup as _IKM
                    _кб = _IKM([[_IKB('❓ Как пользоваться РАГ', callback_data='rag_help')]])
                    # Владелец 27.07.2026: «первый был неплохой, но обрезался, а это хуже — там
                    # сворачивался текст удобно и ссылки были, сделай грамотно». Разгадка: длинный
                    # ответ не влезал в лимит Telegram, отправка HTML падала, и запасной путь вырезал
                    # ВСЮ разметку — вместе со свёртками и ссылками. Потому второй ответ и вышел хуже.
                    # Правильно не резать, а РАЗБИВАТЬ: посты режем строго по границе хадиса, каждый
                    # хадис уходит целиком, со своей ссылкой и своей свёрткой.
                    _посты, _тек = [], ''
                    for _кусок in _т.split('\n📖 ') if _т.count('📖') > 1 else [_т]:
                        _кусок = _кусок if not _посты and _тек == '' and _кусок.startswith('🧠') else \
                                 (_кусок if _кусок.startswith('🧠') else '📖 ' + _кусок)
                        if len(_тек) + len(_кусок) > 3800 and _тек:
                            _посты.append(_тек.rstrip())
                            _тек = ''
                        _тек += ('\n' if _тек else '') + _кусок
                    if _тек.strip():
                        _посты.append(_тек.rstrip())
                    _посты = _посты or [_т[:3800]]
                    for _i, _пост in enumerate(_посты):
                        _последний = (_i == len(_посты) - 1)
                        if _i == 0 and _ж:
                            await _ж.edit_text(_пост, parse_mode='HTML', disable_web_page_preview=True,
                                               reply_markup=_кб if _последний else None)
                            _ПОСЛ_РАГ['ответ_msg'] = _ж.message_id
                        else:
                            _от = await update.message.reply_text(
                                _пост, parse_mode='HTML', disable_web_page_preview=True,
                                reply_markup=_кб if _последний else None)
                            _ПОСЛ_РАГ['ответ_msg'] = _от.message_id
                except Exception:
                    try:
                        await update.message.reply_text(re.sub(r'<[^>]+>', '', _т)[:3900])
                    except Exception as _e3:
                        try:
                            await update.message.reply_text('🧠 Ответ не удалось отправить: %s' % str(_e3)[:150])
                        except Exception:
                            pass
                return

            if True:
                _src, _q = _rag_parse(text)
                if _q or _src:
                    try:
                        _wait = await update.message.reply_text('🔎 Ищу в нашей базе (первоисточники + риджаль)…')
                    except Exception:
                        _wait = None
                    # термины поиска: если нет арабского — СНАЧАЛА лексикон (надёжно), потом ИИ-запас
                    _terms = []
                    if _q and not re.search(r'[؀-ۿ]', _q):
                        _terms = list(_ru_ar_terms(_q))   # лексикон (детерминированно)
                        # ИИ-слова ДОБАВЛЯЕМ к лексикону (а не «только если пусто»): длинный пересказ хадиса
                        # содержит НЕСКОЛЬКО ключевых слов (несправедливость+огонь+решение), лексикон ловит
                        # лишь часть → главный хадис терялся. Зовём ИИ для длинных запросов или когда слов <2.
                        if len(re.findall(r'[а-яё]+', _q.lower())) >= 4 or len(_terms) < 2:
                            try:
                                _kw = ask_ai(
                                    "Тема/вопрос про хадис. Выдай 4-7 ОДИНОЧНЫХ классических арабских СЛОВ (по одному слову, НЕ фразы), "
                                    "как они звучат в самих хадисах, каждое с новой строки (пример: музыка→المعازف и ملاهي; вино→الخمر; "
                                    "огонь→النار; кусочек→قطعة; несправедливое решение→القضاء и أقطع). Без огласовок, без пояснений.\nТема: " + _q,
                                    "Ты знаток текстов хадисов. Только арабские одиночные слова, по одному на строку.",
                                    owner=is_owner(update))
                                _kw = re.sub(r"\n*⚡ \*Модель:.*$", "", _kw or "", flags=re.S)
                                _kw = re.sub(r"[^؀-ۿ\s]", " ", _kw)
                                for _w in _kw.split():
                                    if len(_w) > 2 and _w not in _terms:
                                        _terms.append(_w)
                            except Exception:
                                pass
                    if not _terms:
                        _terms = [_q] if _q else ['']
                    try:
                        # все термины ОДНИМ запросом — Space сам сделает фраза→AND→OR (без флуда по IP)
                        _qq = ' '.join(_terms) if _terms else (_q or '')
                        _d = await _rag_query(_qq, source=_src, n=6)
                        _top = (_d.get('results') or [])[:6]
                        if not _top:
                            _none = '🔎 Ничего не нашёл по «%s». Попробуй точную арабскую фразу (2-4 слова) или «раг в бухари: <фраза>».' % _q
                            if _wait:
                                try: await _wait.edit_text(_none)
                                except Exception: await update.message.reply_text(_none)
                            else:
                                await update.message.reply_text(_none)
                            return
                        _cards = _rag_cards(_top, _terms, limit=4)   # карточки: целый хадис+выделение+перевод+ссылка
                        _hdr = '🔎 По запросу «%s»%s — карточки хадисов (%d из %d):' % (
                            _q, (' в «%s»' % _src) if _src else '', len(_cards), len(_top))
                        if _wait:
                            try: await _wait.edit_text(_hdr)
                            except Exception: await update.message.reply_text(_hdr)
                        else:
                            await update.message.reply_text(_hdr)
                        for _c in _cards:
                            try:
                                await update.message.reply_text(_c, parse_mode='HTML', disable_web_page_preview=True)
                            except Exception:
                                await update.message.reply_text(re.sub('<[^>]+>', '', _c), disable_web_page_preview=True)
                    except Exception as _e:
                        _err = '⚠️ RAG временно недоступен (%s). Попробуй позже.' % str(_e)[:90]
                        if _wait:
                            try: await _wait.edit_text(_err)
                            except Exception: await update.message.reply_text(_err)
                        else:
                            await update.message.reply_text(_err)
                    return
    except Exception:
        pass

    # 🚨 авто-рубильник ИИ (защита баланса DeepSeek): уведомить владельца о срабатывании + команды управления
    global _AI_KILL, _AI_KILL_MANUAL, _AI_KILL_PENDING, _GROUP_AI_OFF, _AI_PUBLIC_OFF
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
        await update.message.reply_text(f"ИИ: {'⏸ ВЫКЛ' if ai_kill_active() else '✅ вкл'}\nВызовов за {AI_RATE_WINDOW}с: {len(_AI_CALLS)}/{AI_RATE_LIMIT}\nавто-выкл={_AI_KILL} · ручной={_AI_KILL_MANUAL}\nботяра в группах: {'⏸ ВЫКЛ' if _GROUP_AI_OFF else '✅ вкл'}\n🔒 ИИ для публики: {'⏸ ВЫКЛ (только владелец)' if _AI_PUBLIC_OFF else '✅ доступен всем'}"); return
    # #236: отдельный рубильник ИИ-«ботяра» в ГРУППАХ (@jamaat_ru) — не трогает /neuro и личку
    if is_owner(update) and text.lower() in ("ботяра вкл", "ботяра включи", "включи ботяра", "чат-ии вкл"):
        _GROUP_AI_OFF = False; _save_ai_gate()   # ФИКС: сохраняем — иначе рестарт бота (деплой) сбрасывал обратно в ВЫКЛ
        await update.message.reply_text("✅ Ботяра в группах включён (реагирует на «ботяра»/ответ боту), переживёт рестарт. Выключить: «ботяра выкл»."); return
    if is_owner(update) and text.lower() in ("ботяра выкл", "выключи ботяра", "ботяра стоп", "чат-ии выкл"):
        _GROUP_AI_OFF = True; _save_ai_gate()
        await update.message.reply_text("⏸ Ботяра в группах выключен (в личке и /neuro работают). Включить: «ботяра вкл»."); return
    # 🔒 ГЛАВНЫЙ РУБИЛЬНИК: ИИ (DeepSeek + все модели) ТОЛЬКО для владельца — во всех остальных чатах ВЫКЛ
    if is_owner(update) and text.lower() in ("дипсик всем выкл", "дипсик выкл всем", "ии всем выкл", "ии только мне", "дипсик только мне", "ии публично выкл", "публичный ии выкл"):
        _AI_PUBLIC_OFF = True; _save_ai_gate()
        await update.message.reply_text("🔒 ГОТОВО: ИИ (DeepSeek и все модели) теперь ТОЛЬКО для тебя. Во всех остальных чатах/группах/мини-аппе ИИ выключен. Вернуть всем: «дипсик всем вкл»."); return
    if is_owner(update) and text.lower() in ("дипсик всем вкл", "дипсик вкл всем", "ии всем вкл", "ии публично вкл", "публичный ии вкл", "дипсик всем включи"):
        _AI_PUBLIC_OFF = False; _save_ai_gate()
        await update.message.reply_text("✅ ИИ снова доступен всем (с учётом лимитов и доступа feature_allowed). Сделать только себе: «дипсик всем выкл»."); return

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
    if is_owner(update) and text.strip().lower() in ("обновление", "релиз"):
        # БАГ (обнаружен 03.07.2026, В-15): раньше сюда попадало и слово "анонс" — это ПЕРЕХВАТЫВАЛО его
        # раньше настоящего обработчика @muslimoonapp (ниже, «АНОНС в канал приложения вручную»), который
        # никогда не срабатывал. ANNOUNCE_CHAT_ID/release_notes.txt больше нигде в коде не используются —
        # мёртвый канал. "анонс" убран отсюда, чтобы дойти до правильного обработчика.
        try:
            r = requests.get(f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/release_notes.txt", timeout=8)
            note = r.text if r.status_code == 200 else "Нет release_notes.txt"
            await context.bot.send_message(ANNOUNCE_CHAT_ID, note)
            await update.message.reply_text("✅ Опубликовано в канале обновлений.")
        except Exception as e:
            await update.message.reply_text("Ошибка анонса: " + str(e))
        return
    # ===== Видео-пересказ YouTube (З-10): reply на пост со ссылкой + «видео»/«видео кратко»; вопросы — тоже reply =====
    if is_owner(update):
        _tlv = text.strip().lower()
        _rep = update.message.reply_to_message
        _repv = _yt_id(((_rep.text or _rep.caption) if _rep else "") or "")
        _isvid = _tlv.startswith(("видеоперессказ", "видеопересказ"))
        if _isvid:
            if not _repv:
                await update.message.reply_text("Ответь (reply) на пост со ссылкой YouTube и напиши «видеоперессказ» (или «видеоперессказ коротко», добавь «аудио» для mp3).")
                return
            brief = ("коротк" in _tlv) or ("кратк" in _tlv)
            want_audio = "аудио" in _tlv
            await update.message.reply_text("📹 Достаю субтитры…")
            tr = _yt_transcript(_repv)
            if not tr:
                await update.message.reply_text("⚠️ У этого видео нет открытых субтитров. Пересказ по аудио (Whisper) добавлю позже.")
                return
            usd = _yt_cost_est(tr)
            await update.message.reply_text(f"⚠️ Через DeepSeek ≈ ${usd:.3f} (~{usd*92:.1f}₽). Делаю {'кратко' if brief else 'подробно'}{' + озвучка' if want_audio else ''}…")
            ans = _yt_summarize(tr, brief)
            if not ans:
                await update.message.reply_text("⚠️ ИИ не ответил (DeepSeek и Gemini). Попробуй ещё раз позже.")
                return
            _VIDEO_LAST[update.effective_user.id] = {"vid": _repv, "tr": tr}
            await send_long(update, ("📺 *Краткий пересказ*\n\n" if brief else "📺 *Подробный пересказ + перевод*\n\n") + ans + "\n\n💬 Задай вопрос по видео — ответом (reply) на этот же пост.")
            if want_audio:
                try:
                    mp3 = _tts_mp3(_re_v.sub(r'[\*\_#`\[\]]', '', ans))
                    if mp3:
                        with open(mp3, "rb") as f:
                            await update.message.reply_audio(f, title=("Пересказ кратко" if brief else "Пересказ подробно"), caption="🎧 Озвучка пересказа")
                        try: os.remove(mp3)
                        except Exception: pass
                    else:
                        await update.message.reply_text("⚠️ Озвучку сделать не вышло (TTS). Текст выше.")
                except Exception as _e:
                    await update.message.reply_text("⚠️ Озвучка не удалась: " + str(_e)[:80])
            return
        if _repv and not _isvid and len(text.strip()) > 3:
            last = _VIDEO_LAST.get(update.effective_user.id)
            if last and last.get("vid") == _repv:
                body = "\n".join(f"[{_fmt_ts(s)}] {t}" for s, t in last["tr"])[:45000]
                pr = f"Вопрос по видео: {text}\n\nОтветь по-русски кратко и ОБЯЗАТЕЛЬНО укажи тайм-код [мин:сек], где это в видео.\n\nСубтитры:\n{body}"
                a = ask_neuro(pr, "Отвечай строго по субтитрам видео, всегда указывай тайм-код [мин:сек].", max_tokens=1000)
                if not a:
                    try: a = ask_gemini(pr, "Отвечай по субтитрам, указывай тайм-код [мин:сек].")
                    except Exception: a = None
                if a:
                    await send_long(update, "💬 " + a)
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
    if is_owner(update) and text.strip().lower() in ("бэкап", "бекап", "backup", "архив", "бэкап архив", "статус бэкапа", "бэкап файл", "пришли бэкап", "скинь бэкап"):
        # #259/#261: сам ZIP приходит в ЖУРНАЛ УВЕДОМЛЕНИЙ (LOG_CHAT) + владельцу в ЛС при каждом бэкапе (локальный ps1 -> /api/backup_push -> send_document).
        # Приватно (внутри журналы R42) — поэтому НЕ в публичный канал/Pages.
        await update.message.reply_text(
            "📦 *Бэкап Muslimoon*\n"
            "Свежий `Muslimoon_RECOVERY.zip` приходит в журнал + тебе в ЛС файлом при каждом бэкапе (ежедневно 21:00 + при каждой версии).\n"
            "Нужен прямо сейчас? Запусти локально `backup_muslimoon.ps1` — он соберёт свежий zip и пришлёт его сюда.\n"
            "Где ещё лежит (приватно, для отката):\n"
            "• Google Drive → `Muslimoon_BACKUP\\Muslimoon_RECOVERY.zip` (свежий)\n"
            "• `Muslimoon_BACKUP\\versions\\vNNN_дата.zip` (каждая версия отдельно)\n"
            "• `snapshots\\<дата>\\` (дневные снимки журналов)\n"
            "⚠️ Файл только в журнал/ЛС: внутри приватные журналы (ВЫГОВОРЫ/ЗАКОНЫ/…), публиковать нельзя (R42) — не пересылай.",
            parse_mode="Markdown", disable_web_page_preview=True)
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
        try:
            await update.message.reply_text("\n".join(lines)[:3900], parse_mode="Markdown")
        except Exception:   # B «can't parse entities»: спецсимвол в сыром запросе ломал Markdown → без разметки
            await update.message.reply_text("\n".join(lines)[:3900])
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
        try:
            await update.message.reply_text("\n".join(lines)[:3900], parse_mode="Markdown")
        except Exception:   # B «can't parse entities»: спецсимвол в тексте отзыва → без разметки
            await update.message.reply_text("\n".join(lines)[:3900])
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
        try:
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        except Exception:   # B «can't parse entities»: спецсимвол в имени/src → без разметки
            await update.message.reply_text("\n".join(lines))
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
                "• `заявка done <№>` — пометить выполненной\n"
                "• `журнал` — вкл/выкл уведомления о работе Claude над заявками\n\n"
                "🤖 *ИИ (внутренняя кухня, только тебе):*\n"
                "• `гпт <вопрос>` — спросить GPT/Gemini\n\n"
                "💬 *Связь с пользователем:*\n"
                "• `написать <ID> <текст>` — отправить юзеру сообщение от твоего имени (ID берёшь из журнала #ии)\n\n"
                "📣 *Канал и закреп:*\n"
                "• `анонс` — запостить текущее обновление в @muslimoonapp\n"
                "• `анонс <текст>` — свой текст в канал\n"
                "• `закреп` — сообщение с кнопкой приложения (закрепляется автоматически)\n"
                "• `закреп <текст>` — свой текст под кнопкой\n\n"
                "🧠 *Смысловой поиск (РАГ):*\n"
                "• `раг <вопрос>` — поиск по смыслу · `раг бухари <вопрос>` — только по этой книге\n"
                "• `раг оценки` — журнал качества: сколько 👎/👍 и последние промахи (#671)\n"
                "• `раг доступ` — кому открыт · `раг диаг` — жив ли поиск\n\n"
                "⛔ *Модерация чата (#628):*\n"
                "• `права` / `права <id чата>` — есть ли у бота право банить (ничего не меняет)\n"
                "• `чат бан <id> [id чата]` — реально выгнать из чата · `чат разбан <id>`\n"
                "• `бан <id>` — только чёрный список БОТА (игнор), из чата не выгоняет\n\n"
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
        # M428: ПОЛНЫЙ единый журнал (M-чат + TB-бот + TA-апп) — сводка статусов/причин/сроков с Pages (req_status.json, обновляется каждым деплоем)
        if _tl in ("статус заявок", "заявки полные", "полный журнал", "журнал заявок"):
            try:
                rs = requests.get("https://germanyalfurqan-eng.github.io/hadith-bot/req_status.json", timeout=15).json()
                lines = [f"📋 *ЕДИНЫЙ журнал заявок* · 🕐 сейчас {_now_msk()}",
                         f"_данные собраны: {rs.get('updated','')}_",
                         f"Современных: {rs.get('modern_total')} = ✅{rs.get('modern_done')} + 🔴{rs.get('modern_open')}",
                         f"_{rs.get('legacy_note','')}_", "", "🔴 *Открытые:*"]
                for it in (rs.get("items") or []):
                    if it.get("status") != "open":
                        continue
                    lines.append(f"• *{it.get('code')}*: {(it.get('title') or '')[:90]}")
                    if it.get("reason"):
                        lines.append(f"   ↳ {it['reason']} · срок: {it.get('eta','—')}")
                    if len(lines) > 70:
                        lines.append("… (полный список — в Кабинете приложения, «📋 Журнал заявок»)"); break
                await send_long(update, "\n".join(lines), "Markdown")
            except Exception as e:
                await update.message.reply_text("🔧 Журнал не дотянулся: " + str(e)[:120])
            return
        # ===== ЗАЯВКИ владельца: список (невыполненные первыми + от пользователей) =====
        if _tl == "заявки" or _tl == "список заявок" or _tl == "мои заявки":
            j = _journal_load(); reqs = j.get("requests", []); fb = j.get("feedback", [])
            open_r = [r for r in reqs if not r.get("done")]; done_r = [r for r in reqs if r.get("done")]
            lines = [f"📋 *Заявки владельца* — открытых {len(open_r)} · выполнено {len(done_r)}\n"]
            # З-18: «В РАБОТЕ СЕЙЧАС» (live_now.json) — что делаю/жду прямо сейчас, со штампом времени
            try:
                _ln = requests.get("https://germanyalfurqan-eng.github.io/hadith-bot/live_now.json", timeout=8).json()
                _lw = [f"🔵 *В РАБОТЕ СЕЙЧАС* ({_ln.get('asof','')})"]
                for _f in (_ln.get("fronts") or [])[:6]:
                    _p = f" — {_f['pct']}%" if isinstance(_f.get("pct"), int) else ""
                    _lw.append(f"▸ {_f.get('t','')}{_p}" + (f"\n   {_f.get('s','')}" if _f.get("s") else ""))
                if _ln.get("note"):
                    _lw.append(f"_{_ln['note']}_")
                lines = _lw + [""] + lines
            except Exception:
                pass
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
            _digest = "\n".join(lines)[:4000]
            try:
                await update.message.reply_text(_digest, parse_mode="Markdown")
            except Exception:   # #165-фикс: Markdown-символ в тексте юзера ломал «заявки» (Telegram 400) → фолбэк без разметки
                await update.message.reply_text(_digest)
            return
        # ===== #165: тумблер рабочего журнала (уведомления о работе Claude над заявками) =====
        if (_tl == "журнал" or _tl == "worklog") and is_owner(update):
            j = _journal_load()
            j["worklog_enabled"] = not j.get("worklog_enabled", False)
            _journal_save("toggle worklog")
            await update.message.reply_text(("✅ Рабочий журнал ВКЛЮЧЕН — буду слать тебе В ЛИЧКУ: что начал/закончил/на чём остановился по каждой заявке, суть с логикой, сколько заявок осталось невыполнено и в работе, и сколько токенов потрачено. Выключить — снова напиши «журнал»." if j["worklog_enabled"] else "🔇 Рабочий журнал ОТКЛЮЧЕН — уведомления о заявках слать не буду."))
            return
        # ===== #147: фетч разборов достоверности с канала @hadis_isnad (бот — участник; форвард по message_id → текст/Whisper → data/razbory.json) =====
        if (_tl.startswith("разбор") or _tl.startswith("разборы")) and is_owner(update):
            RAZBOR_CHANNEL = "@hadis_isnad"
            _nums = [int(x) for x in re.findall(r'\d+', _tl)]
            if not _nums:
                await update.message.reply_text("📜 #147 разборы достоверности.\nФормат: «разбор 11» (один пост) или «разборы 11 50» (диапазон).\nЯ форварну посты из @hadis_isnad, аудио расшифрую (Whisper), сохраню в data/razbory.json — потом внесу вердикты в карточки (⛔ наш разбор). Аудио = расход Whisper, поэтому до 40 за раз.")
                return
            _a = _nums[0]; _b = _nums[1] if len(_nums) > 1 else _nums[0]
            if _b < _a:
                _a, _b = _b, _a
            if _b - _a > 40:
                _b = _a + 40
                await update.message.reply_text(f"⚠️ За раз беру до 40 постов (аудио = расход Whisper): {_a}–{_b}. Дальше продолжишь «разборы {_b+1} 173».")
            store = _data_get("razbory.json", {}) or {}
            await update.message.reply_text(f"📥 Тяну разборы {_a}–{_b} из {RAZBOR_CHANNEL}…")
            _done = 0; _fail = 0; _aud = 0
            for _mid in range(_a, _b + 1):
                try:
                    _m = await context.bot.forward_message(LOG_CHAT_ID, RAZBOR_CHANNEL, _mid)
                    _txt = (_m.text or _m.caption or "").strip()
                    _kind = "text"
                    if (_m.voice or _m.audio) and len(_txt) < 40:
                        _kind = "audio"
                        _media = _m.voice or _m.audio
                        _f = await _media.get_file()
                        _ext = ".ogg" if _m.voice else ".mp3"
                        _p = f"/tmp/razbor_{_mid}{_ext}"
                        await _f.download_to_drive(_p)
                        _tr = transcribe_audio(_p)
                        if _tr:
                            _txt = (_txt + "\n" + _tr).strip()
                            _aud += 1
                        try: os.remove(_p)
                        except Exception: pass
                    try: await context.bot.delete_message(LOG_CHAT_ID, _m.message_id)
                    except Exception: pass
                    if _txt:
                        store[str(_mid)] = {"text": _txt[:9000], "kind": _kind, "url": f"https://t.me/hadis_isnad/{_mid}"}
                        _done += 1
                    else:
                        _fail += 1
                except Exception:
                    _fail += 1
            _data_put("razbory.json", store, f"razbory {_a}-{_b} (#147)")
            await update.message.reply_text(f"✅ Разборы {_a}–{_b}: сохранено {_done} (аудио расшифровано {_aud}), пропущено/ошибок {_fail}. Всего в базе: {len(store)}. → data/razbory.json. Claude внесёт вердикты в our_hukm.json.")
            return
        # ===== #410 (владелец 30.06.2026): «саммари <ссылка t.me/jamaat_ru/N>» — поймать диалог (текст+аудио) и выдать саммари.
        # Та же схема, что #147 «разбор N»: форвард по message_id (работает ТОЛЬКО если бот участник чата и в чате
        # НЕ включена «защита контента» — иначе Telegram отклонит forward даже боту-участнику; тогда единственный
        # путь — владелец форвардит сообщение(я) боту вручную, как уже принято в #147). До 15 ссылок за раз.
        if _tl.startswith("саммари ") and is_owner(update):
            _links = re.findall(r'https?://t\.me/([A-Za-z0-9_]+)/(\d+)', text)
            if not _links:
                await update.message.reply_text("📎 #410 саммари диалога.\nФормат: «саммари <ссылка на сообщение t.me/чат/N>» (можно несколько ссылок подряд — поймаю каждое сообщение). Работает, только если бот состоит в этом чате и там не включена защита контента — иначе перешли мне сообщения вручную.")
                return
            _links = _links[:15]
            await update.message.reply_text(f"📥 Ловлю {len(_links)} сообщени{'е' if len(_links)==1 else 'й'}…")
            _texts = []; _fail = 0
            for _un, _mid_s in _links:
                _mid = int(_mid_s)
                try:
                    _m = await context.bot.forward_message(LOG_CHAT_ID, "@" + _un, _mid)
                    _txt = (_m.text or _m.caption or "").strip()
                    if (_m.voice or _m.audio) and len(_txt) < 40:
                        _media = _m.voice or _m.audio
                        _f = await _media.get_file()
                        _ext = ".ogg" if _m.voice else ".mp3"
                        _p = f"/tmp/summary_{_mid}{_ext}"
                        await _f.download_to_drive(_p)
                        _tr = transcribe_audio(_p)
                        if _tr: _txt = (_txt + "\n" + _tr).strip()
                        try: os.remove(_p)
                        except Exception: pass
                    if not _txt:   # Hermes-ревью #410: молчаливый пропуск медиа без текста путал счётчик "не поймано" — честный плейсхолдер
                        if _m.photo: _txt = "[фото без подписи]"
                        elif _m.video: _txt = "[видео без подписи]"
                        elif _m.document: _txt = "[файл без подписи]"
                    try: await context.bot.delete_message(LOG_CHAT_ID, _m.message_id)
                    except Exception: pass
                    if _txt: _texts.append(_txt)
                    else: _fail += 1
                except Exception:
                    _fail += 1
            if not _texts:
                await update.message.reply_text(f"❌ Не поймал ни одного сообщения ({_fail} из {len(_links)}). Похоже, форвард из этого чата заблокирован (защита контента) или бот не в нём — перешли мне эти сообщения вручную реплаем, распознаю так же.")
                return
            _raw = "\n\n---\n\n".join(_texts)[:16000]
            _ans = ask_ai("Сделай краткое саммари этого диалога/переписки (100-200 слов, по-русски, по сути, без искажений):\n\n" + _raw,
                          "Ты — помощник, который кратко и точно суммаризирует диалоги.", owner=True, max_tokens=700)
            if not _ans:
                await update.message.reply_text("❌ ИИ сейчас недоступен для саммари. Текст поймал (" + str(len(_texts)) + " сообщ.), попробуй позже ещё раз командой «саммари» с теми же ссылками.")
                return
            _fail_note = f" (не поймано {_fail})" if _fail else ""
            _sumtxt = f"📋 *Саммари* ({len(_texts)} сообщ.{_fail_note}):\n\n{_ans}"
            try:
                await update.message.reply_text(_sumtxt, parse_mode="Markdown")
            except Exception:   # спецсимвол в тексте диалога/ответе ИИ мог сломать Markdown — фолбэк без разметки
                await update.message.reply_text(re.sub(r'[*_`\[\]()]', '', _sumtxt))
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
        # ===== #505 (владелец 04.07.2026): заметки джамаата — «JM <текст>» / «джм <текст>» ТОЛЬКО владельцем,
        # в @jamaat_ru И в личке владельца. Структурно копим (дата+нумерация),
        # «список заметок»/«заметки JM»/«джм список» — выдать всё, .md-файлом если длинно.
        _jm_here = is_owner(update) and (getattr(update.effective_chat, "id", None) == JAMAAT_RU_CHAT_ID
                                         or getattr(update.effective_chat, "type", "") == "private")
        if (_tl.startswith(("jm ", "jm\n", "джм ", "джм\n"))) and _jm_here and _tl not in ("джм список", "jm список"):
            _jm_body = text.strip()[(3 if _tl.startswith("джм") else 2):].strip()
            if not _jm_body:
                await update.message.reply_text("✍️ Напиши: JM <текст заметки>")
                return
            _jm = _data_get("jamaat_notes.json", []) or []
            _jm_id = (max([n.get("id", 0) for n in _jm]) if _jm else 0) + 1
            _jm.append({"id": _jm_id, "d": _now_msk(), "t": _jm_body})
            _data_put("jamaat_notes.json", _jm, f"JM-заметка #{_jm_id}")
            await update.message.reply_text(
                f"📒 *Заметка JM-{_jm_id} сохранена* · {_now_msk()}\n"
                f"———————————\n"
                f"{_jm_body[:400]}\n"
                f"———————————\n"
                f"_Все заметки: «джм список»_", parse_mode="Markdown")
            return
        if _tl in ("список заметок", "заметки jm", "jm список", "список jm", "джм список", "список джм") and _jm_here:
            _jm = _data_get("jamaat_notes.json", []) or []
            if not _jm:
                await update.message.reply_text("Заметок JM пока нет. Пиши: JM <текст>")
                return
            _lines = [f"{n.get('id')}. [{n.get('d','')}] {n.get('t','')}" for n in _jm]
            _md = "# Заметки джамаата (JM)\n\n" + "\n\n".join(_lines) + "\n"
            if len(_md) > 3500:
                import tempfile
                _fp = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8")
                _fp.write(_md); _fp.close()
                try:
                    await update.message.reply_document(open(_fp.name, "rb"), filename="jamaat_notes.md", caption=f"📝 Заметок JM: {len(_jm)}")
                finally:
                    try: os.remove(_fp.name)
                    except Exception: pass
            else:
                await update.message.reply_text("📝 *Заметки JM:*\n\n" + "\n".join(_lines), parse_mode="Markdown")
            return
        # ===== Добавить заявку: «заявка <текст>» / «замечание <текст>» (+ подсказка о дубле) =====
        if _tl.startswith("заявка ") or _tl.startswith("замечание ") or _tl == "заявка" or _tl == "замечание":
            body = text.strip()[6:].strip() if _tl.startswith("заявк") or _tl == "заявка" else text.strip()[9:].strip()
            img_flag = False; imgkey = ""
            rep = update.message.reply_to_message
            # #245/#274: «заявка [коммент]» РЕПЛАЕМ на сообщение → регистрируем ОСНОВНОЙ текст отвеченного сообщения + коммент владельца.
            # БАГ #274 (исправлено): раньше при наличии коммента основное сообщение (на которое ответили) ТЕРЯЛОСЬ — писался только коммент.
            if rep:
                rep_text = (rep.text or rep.caption or "").strip()
                # ⚠️ 25.07.2026 — НЕ вводить здесь фильтр «ответ на пост бота без комментария = не заявка».
                # Я его ввёл и тут же откатил по слову владельца: «там нет мусора; если я отметил смс, значит
                # тебе надо посмотреть ЭТОТ смс». Владелец отмечает ПЛОХОЙ ВЫВОД БОТА именно затем, чтобы его
                # разобрали — это полноценная заявка, а молчание тут означает «смотри сам, что не так».
                # Пример: #637 — владелец написал в чате «муслим 7», бот выдал несколько километровых постов.
                if rep_text:
                    body = (rep_text + "\n— коммент владельца: " + body) if body else rep_text
                if getattr(rep, "photo", None):
                    try: imgkey = str(rep.photo[-1].file_id); img_flag = True
                    except Exception: pass
            if not body and not img_flag:
                await update.message.reply_text("✍️ Напиши: *заявка <текст>* — или ответь «заявка» на сообщение. Скрин: фото с подписью «заявка ...».", parse_mode="Markdown")
                return
            dup = req_dup(body)
            if dup:
                await update.message.reply_text(f"⚠️ Похоже, ты это уже присылал — *заявка №{dup}*. Не дублирую.\n(Если всё же другое — допиши подробнее и пришли ещё раз.)", parse_mode="Markdown")
                return
            chat_type = getattr(update.effective_chat, "type", "")
            chat_id = getattr(update.effective_chat, "id", None)
            # #425 (владелец 01.07.2026): было "любая группа = @jamaat_ru" — но рабочий чат уведомлений (LOG_CHAT_ID)
            # ТОЖЕ группа/супергруппа → заявки оттуда ложно подписывались "(из чата @jamaat_ru)". Разводим по chat_id.
            if chat_id == LOG_CHAT_ID:
                from_chat = " (из рабочего чата уведомлений)"
            elif chat_type in ("group", "supergroup"):
                from_chat = " (из чата @jamaat_ru)"
            else:
                from_chat = ""
            rid = req_add((body or "(скрин)") + from_chat, img_flag, imgkey)
            # #245: дубль ВЛАДЕЛЬЦУ В ЛС — все заявки в переписке с ботом (если команда не из самой ЛС)
            try:
                if update.effective_chat.id != OWNER_ID:
                    await context.bot.send_message(OWNER_ID, f"📥 Заявка #{rid}{from_chat} ({_now_msk()}):\n{body[:1500]}" + ("\n🖼 со скрином" if img_flag else ""))
            except Exception: pass
            try:
                if update.effective_chat.id not in (LOG_CHAT_ID, OWNER_ID):   # #41/#90: НЕ дублировать эхо в тот же чат
                    await context.bot.send_message(LOG_CHAT_ID, f"📥 Заявка владельца #{rid}{from_chat} ({_now_msk()}):\n{body[:1500]}")
            except Exception: pass
            await update.message.reply_text(f"📥 *Заявка #{rid}* записана ✅{from_chat} · 🤖 бот ({_now_msk()})\nПродублировал тебе в ЛС с ботом. Журнал — командой «заявки».", parse_mode="Markdown")   # M287: показываем место приёма
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
            # 04.07.2026 (владелец поймал v963 дважды): АТОМАРНАЯ проверка-и-захват ПЕРЕД постом — если
            # автоматическая очередь (update_notes_queue.json) уже запостила ЭТОТ ЖЕ текст (напр. только что),
            # ручная «анонс» больше НЕ дублирует его молча.
            if not _channel_claim(note):
                await update.message.reply_text("⏸ Это обновление уже было опубликовано в @muslimoonapp только что (текст совпадает с последним постом) — повторно НЕ отправляю, чтобы не дублировать.")
                return
            try:
                # id версии здесь взять неоткуда: текст мог быть набран владельцем вручную. Постер
                # сам достанет номер «vNNN» из текста, чтобы доказательство доставки (app_post_msgids)
                # всё равно легло под версией, а не под первым словом ноты (закон З-47).
                await _post_app_channel(context.bot, note)   # ЗАКОН С31: скрин + анонс + сворачиваемая инструкция
                await update.message.reply_text("✅ Опубликовал в канал @muslimoonapp.")
            except Exception as e:
                await update.message.reply_text("❌ Не вышло: " + str(e)[:200])
            return
        # ===== УДАЛИТЬ ПОСТ ИЗ @muslimoonapp вручную (04.07.2026, владелец поймал дубли, «удали сам, доступ есть»)
        # У бота НЕТ сохранённого message_id прошлых постов (_post_app_channel их не хранил) — программно
        # найти и удалить СТАРЫЕ конкретные дубли нельзя. Рабочий путь: владелец ПЕРЕСЫЛАЕТ пост из канала
        # боту в личку → ОТВЕЧАЕТ на пересланное сообщение словом «удали дубль» → бот берёт настоящий
        # chat_id/message_id канала из forward-метаданных пересланного сообщения и удаляет ИМЕННО его.
        if _tl in ("удали дубль", "удали пост", "удали из канала"):
            rep = update.message.reply_to_message
            if rep and rep.forward_from_chat and rep.forward_from_message_id:
                try:
                    await context.bot.delete_message(rep.forward_from_chat.id, rep.forward_from_message_id)
                    await update.message.reply_text(f"✅ Удалил сообщение из канала (id {rep.forward_from_message_id}).")
                except Exception as e:
                    # #628 (тот же класс): сырой английский ответ Telegram владельцу ничего не
                    # объясняет. Отказ здесь бывает ровно двух видов, и делать надо разное:
                    # нет права на удаление — включается тумблером; сообщение старше 48 часов —
                    # не удалить уже никак, ни ботом, ни руками.
                    _низ_у = str(e).lower()
                    if "message can't be deleted" in _низ_у or "message to delete not found" in _низ_у:
                        _пояс = ("Это сообщение удалить уже нельзя: Telegram разрешает ботам удалять\n"
                                 "посты не старше 48 часов. Старый дубль убирается только руками в канале.")
                    elif ("not enough rights" in _низ_у or "chat_admin_required" in _низ_у
                          or "need administrator" in _низ_у or "can_delete" in _низ_у):
                        _пояс = ("Боту не выдано право «Удаление сообщений» в @muslimoonapp.\n"
                                 "Telegram → канал → «Управление каналом» → «Администраторы» →\n"
                                 "%s → включить «Удаление сообщений» → Сохранить." % _МОД_БОТ_ЮЗЕР)
                    else:
                        _пояс = "Причина не опознана. Проверь, что бот — администратор канала с правом «Удаление сообщений»."
                    await update.message.reply_text(
                        "❌ Не удалось удалить пост.\n" + _пояс + "\nДословный ответ Telegram: " + str(e)[:150])
            else:
                await update.message.reply_text("Перешли мне (форвардом) сам пост из @muslimoonapp, потом ОТВЕТЬ на пересланное сообщение словами «удали дубль».")
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
        # ===== #110: ЖУРНАЛ ЗАЯВОК в боте (общий: бот+мастер; З-12 штамп времени, З-16 исправленная цитата) =====
        # #Ф-роутинг (командный роутинг из хендоффа): «заявки»/«журнал заявок» перехватываются
        # РАНЬШЕ (строки 3171/3191) — этот блок (полный ЕДИНЫЙ журнал бот+мастер) был мёртвым кодом,
        # никогда не срабатывал под старыми словами. Не стал выбирать «победителя» между версиями (обе —
        # активные фичи, нужно слово владельца, какую оставить под какими словами) — вместо этого добавил
        # НОВЫЙ уникальный триггер «единый журнал» (раньше нигде не занят): старое поведение
        # (строки 3171/3191) не тронуто, этот более полный отчёт теперь просто СТАЛ ДОСТИЖИМ отдельным словом.
        if _tl in ("заявки", "журнал заявок", "список заявок", "requests", "единый журнал"):
            try:
                jj = _data_get("journal.json", {}) or {}
                breqs = jj.get("requests", []) or []
            except Exception:
                breqs = []
            st = {}; corr = {}
            try:
                rs = requests.get(f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/miniapp/requests_status.json", timeout=8)
                if rs.status_code == 200: st = rs.json()
            except Exception: pass
            try:
                rc = requests.get(f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/corrections.json", timeout=8)
                if rc.status_code == 200: corr = rc.json()
            except Exception: pass
            ICON = {"done": "✅", "open": "🔴", "wait": "⏳", "progress": "🟡"}
            cnt = {"done": 0, "open": 0, "wait": 0, "progress": 0}
            for k, v in st.items():
                if k.startswith("_"): continue
                s = (v or {}).get("s", "open"); cnt[s] = cnt.get(s, 0) + 1
            head = ("📋 ЖУРНАЛ ЗАЯВОК (общий: бот + мастер)\n"
                    f"🕐 актуально на {_now_msk()}\n"
                    f"✅ выполнено {cnt['done']} · 🔴 открыто {cnt['open']} · ⏳ ждут {cnt['wait']} · 🟡 в работе {cnt['progress']}\n"
                    "——— НЕвыполненные (заявки бота):")
            lines = [head]
            for r in breqs:
                rid = str(r.get("id"))
                s = (st.get(rid) or {}).get("s", "open")
                if s == "done": continue
                quote = corr.get(rid) or r.get("t", "")
                quote = re.sub(r"\s+", " ", quote).strip()[:95]
                meta = (st.get(rid) or {})
                tail = ""
                if meta.get("v"): tail += " · " + meta["v"]
                if s != "open" and (meta.get("why") or meta.get("r")):
                    tail += " · " + (meta.get("why") or meta.get("r"))[:45]
                lines.append(f"{ICON.get(s, '🔴')} #{rid} ({r.get('d','')[:16]}): {quote}{tail}")
            lines.append(f"\n📄 Полный дашборд: github.com/{GITHUB_REPO}/blob/main/requests_dashboard.html")
            lines.append("📒 Мастер-журнал (575 кодов M/TB/Э/R/Ф): ЗАЯВКИ.md в репо.")
            txt = "\n".join(lines)
            for i in range(0, len(txt), 3900):
                await update.message.reply_text(txt[i:i + 3900], disable_web_page_preview=True)
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
                # #628: формулировка была двусмысленной — «⛔ Забанено» читалось как «выгнан из чата»,
                # хотя эта команда лишь заносит id в СВОЙ список игнора: бот перестаёт обслуживать,
                # но человек как сидел в группе, так и сидит. Владелец 20.07.2026 именно на это и
                # напоролся. Теперь пишем, что произошло на самом деле, и рядом — команда для
                # настоящего бана в Telegram.
                await update.message.reply_text(
                    "🔇 В чёрный список бота: " + ", ".join(done) + (("\n📝 " + reason) if reason else "") +
                    "\nВсего в ЧС: " + str(len(bl)) +
                    "\n\nℹ️ Это список игнора: бот перестанет их обслуживать, но из чата НЕ выгонит."
                    "\n⛔ Выгнать из чата по-настоящему: «чат бан " + done[0] + "»"
                    "\n🔍 Хватает ли боту прав на это: «права»")
                try:
                    jrn = "⛔ ЧЁРНЫЙ СПИСОК +" + ", ".join(done) + (("\n📝 причина: " + reason) if reason else "") + "\nВсего в бане: " + str(len(bl))
                    if update.effective_chat and update.effective_chat.id != LOG_CHAT_ID:
                        await context.bot.send_message(LOG_CHAT_ID, jrn)
                except Exception: pass
            else:
                await update.message.reply_text("✅ Разбанено: " + ", ".join(done) + "\nВ ЧС осталось: " + str(len(bl)))
            return
        # ===== #628: НАСТОЯЩИЙ БАН В TELEGRAM + ПРОВЕРКА ПРАВ БОТА =====
        # Заявка #628 (20.07.2026): к уведомлению о входе участника пришла приписка
        # «⚠️ не смог забанить: Not enough rights to restrict/unrestrict chat member», владелец
        # написал «не может банить». Разбор: во-первых, эта фраза — ДОСЛОВНЫЙ ответ Telegram на
        # banChatMember/restrictChatMember, когда бот не администратор чата или у него выключен
        # тумблер «Блокировка пользователей». Обойти это кодом нельзя в принципе: права выдаёт
        # владелец чата. Во-вторых, к тому дню в bot.py не осталось НИ ОДНОГО вызова
        # ban_chat_member — то есть бот тогда даже не пытался, и «бан <id>» стал молча значить
        # совсем другое (свой список игнора, см. выше). Получилось молчание вместо ответа.
        # Чиним обе половины: даём явную команду, которая реально банит, и — главное — при отказе
        # печатаем не код ошибки, а точную инструкцию, что и где включить.
        # 01.08.2026: тот же бан висит теперь и КНОПКОЙ под уведомлением о входе (on_moderate,
        # заявки #614/#660) — команда осталась как запасной путь и как способ забанить задним числом.
        _БОТ_ЮЗЕР = "@muslimoontt_bot"

        def _права_инструкция(где):
            # Один текст на все места, где бот просит права (З-33: не множить сущности) — сам
            # путь лежит в _мод_инструкция, её же показывают кнопки под уведомлением о входе.
            # Раньше здесь была вторая копия инструкции, и она успела разойтись с интерфейсом
            # Telegram: звала в «Администраторы» мимо «Управления группой» и называла право
            # «Блокировка пользователей» вместо «Блокировка участников».
            return "\n\n" + _мод_инструкция(где)

        if _tl == "права" or re.match(r"^права\s+(-?\d{3,})$", _tl):
            # Читающая команда: ничего не меняет, просто отвечает на вопрос «а права-то есть?».
            # Раньше это выяснялось только по факту неудачного бана — то есть постфактум и в чате.
            _м = re.match(r"^права\s+(-?\d{3,})$", _tl)
            _чат = int(_м.group(1)) if _м else (
                update.effective_chat.id if (update.effective_chat and update.effective_chat.type in ("group", "supergroup"))
                else RAG_CHAT_ID)
            try:
                _инфо = await context.bot.get_chat(_чат)
                _назв = getattr(_инфо, "title", None) or str(_чат)
                _я = await context.bot.get_chat_member(_чат, context.bot.id)
                _ст = getattr(_я, "status", "?")
                if _ст != "administrator":
                    await update.message.reply_text(
                        "🔍 Права в «%s» (id %s):\n❌ Бот НЕ администратор (статус: %s) — банить не может."
                        % (_назв, _чат, _ст) + _права_инструкция(_назв))
                    return
                # Подписи — как они называются в русском Telegram, иначе владелец ищет в меню
                # тумблер, которого там нет («Блокировка пользователей» — старое название).
                _тумблеры = [("Блокировка участников (нужна для бана)", "can_restrict_members"),
                             ("Удаление сообщений", "can_delete_messages"),
                             ("Закрепление сообщений", "can_pin_messages"),
                             ("Приглашение по ссылке", "can_invite_users")]
                _строки = ["🔍 Права в «%s» (id %s):\n✅ Бот — администратор." % (_назв, _чат)]
                for _подпись, _поле in _тумблеры:
                    _в = getattr(_я, _поле, None)
                    _строки.append("%s %s" % ("✅" if _в else "❌", _подпись))
                if not getattr(_я, "can_restrict_members", None):
                    _строки.append(_права_инструкция(_назв))
                else:
                    _строки.append("\nБанить можно: «чат бан <id>» · вернуть: «чат разбан <id>».")
                await update.message.reply_text("\n".join(_строки))
            except Exception as _e:
                await update.message.reply_text(
                    "🔍 Не смог проверить права в чате %s: %s\n"
                    "Обычно это значит, что бота в этом чате нет вовсе. Проверь id: «ид чата» — "
                    "напиши это прямо в нужном чате." % (_чат, str(_e)[:160]))
            return

        _мб = re.match(r"^чат\s+(бан|разбан)\s+(-?\d{3,})(?:\s+(-?\d{3,}))?$", _tl)
        if _мб:
            _акт, _кого = _мб.group(1), int(_мб.group(2))
            # Чат берём явно третьим числом, иначе текущий (если это группа), иначе Джамаат.
            # Намеренно НЕ вытаскиваем id из отвечаемого сообщения, как это делает «бан»: там
            # регулярка ловит ЛЮБОЕ число от трёх цифр и на уведомлении о входе прихватывает
            # заодно «2026» из даты. Для списка игнора это безобидно, для настоящего бана — нет.
            _чат = int(_мб.group(3)) if _мб.group(3) else (
                update.effective_chat.id if (update.effective_chat and update.effective_chat.type in ("group", "supergroup"))
                else RAG_CHAT_ID)
            try:
                _назв = getattr(await context.bot.get_chat(_чат), "title", None) or str(_чат)
            except Exception:
                _назв = str(_чат)
            try:
                if _акт == "бан":
                    await context.bot.ban_chat_member(chat_id=_чат, user_id=_кого)
                    await update.message.reply_text(
                        "⛔ Забанен в «%s»: %d.\nВернуть: «чат разбан %d %s»." % (_назв, _кого, _кого, _чат))
                else:
                    await context.bot.unban_chat_member(chat_id=_чат, user_id=_кого, only_if_banned=True)
                    await update.message.reply_text("✅ Разбанен в «%s»: %d." % (_назв, _кого))
                try:
                    if update.effective_chat and update.effective_chat.id != LOG_CHAT_ID:
                        await context.bot.send_message(
                            LOG_CHAT_ID, "#модерация %s %d в «%s» (по команде владельца)"
                                         % ("⛔ бан" if _акт == "бан" else "✅ разбан", _кого, _назв))
                except Exception:
                    pass
            except Exception as _e:
                # ГЛАВНОЕ ИЗ #628: не показывать владельцу сырой ответ Telegram. Разбор причины —
                # общий с кнопками под уведомлением о входе (_мод_отказ), чтобы на один и тот же
                # отказ бот отвечал одинаково, каким бы рычагом его ни дёрнули.
                # Что тут было не так, кроме английского: ветка «chat_admin_required» объявляла
                # администратором ЦЕЛЬ, хотя этой ошибкой Telegram требует прав от САМОГО БОТА —
                # владельца отправляли снимать чужую админку вместо того, чтобы включить тумблер.
                # Теперь статус цели и статус бота спрашиваются у Telegram, а не угадываются.
                try:
                    _кратко, _подробно = await _мод_отказ(
                        context.bot, _чат, _кого, _e, "забанить" if _акт == "бан" else "разбанить")
                except Exception:
                    _подробно = ("⚠️ Не удалось %s %d в «%s»: %s\n"
                                 "Проверить права: «права %s»." % (_акт, _кого, _назв, str(_e)[:200], _чат))
                await update.message.reply_text(
                    _подробно + "\n\n🔍 Проверить права бота: «права %s»." % _чат)
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
        # #153: быстрый тумблер «молчи»/«говори» в ТЕКУЩЕМ чате (резко отключить бота, если тупит)
        if _tl in ("молчи", "тихо", "замолчи"):
            _cid = str(update.effective_chat.id); a = load_access(); mt = [str(x) for x in (a.get("muted") or [])]
            if _cid not in mt: mt.append(_cid)
            save_access({"muted": mt}); await update.message.reply_text("🤫 Молчу в этом чате (отвечаю только тебе). Включить обратно: «говори».")
            return
        if _tl in ("говори", "включись", "не молчи"):
            _cid = str(update.effective_chat.id); a = load_access(); mt = [x for x in (a.get("muted") or []) if str(x) != _cid]
            save_access({"muted": mt}); await update.message.reply_text("🔊 Снова отвечаю в этом чате.")
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
        # #213 (УКАЗ — комплексная защита ОТ спама): глобальный анти-флуд ДО любой обработки.
        # Не-владелец шлёт слишком часто → тихо игнорируем (не тратим обработку/ИИ; НЕ отвечаем — иначе усилили бы спам).
        if not rate_ok('flood:' + str(user_id), limit=15, window=30):
            return
        if chat_type in ("group", "supergroup") and not rate_ok('floodchat:' + str(chat_id), limit=45, window=30):
            return
        # Режим «только свои группы»: в неразрешённой группе бот полностью молчит
        if chat_type in ("group", "supergroup"):
            acc = _access_cache or {}
            # #153: «молчи» в чате (muted) → бот не отвечает никому в нём (кроме владельца)
            if (str(chat_id) in (acc.get("muted") or [])) or (not acc.get("group_open", True) and str(chat_id) not in (acc.get("group_wl") or [])):
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

    # ============ C32: УМНЫЙ АССИСТЕНТ ЖУРНАЛА — владелец пишет в LOG_CHAT свободным текстом, ИЛИ реплаем
    # на отчёт/тревогу бота В ЛИЧКЕ («это что?») ============
    # 02.07.2026 (владелец: «обеспечь чтоб он понимал очем речь» — реплай «это что?» на тревогу-дубль в ЛИЧКЕ
    # ушёл в ОБЩИЙ исламский ассистент, который не знал контекста). В LOG_CHAT — любой текст (как раньше, там
    # всё по проекту). В личке — ТОЛЬКО если это реплай на сообщение САМОГО бота (is_reply_to_bot), иначе
    # сломали бы обычные исламские вопросы владельца боту (они и дальше идут в общий ассистент).
    # маркеры «это отчёт/тревога САМОГО бота» (worklog/backup/ошибка/заявка/дубль-детектор) — отличаем от
    # обычного ответа бота на хадис/аят/поиск, куда реплай должен ПО-ПРЕЖНЕМУ идти в общий ИИ-ассистент (ботяра).
    _REPORT_MARKERS = ("CLAUDE начал", "CLAUDE закончил", "CLAUDE остановился", "Заявка владельца",
                        "НОВАЯ ОШИБКА", "Я сам заметил и ОСТАНОВИЛ", "БЭКАП Muslimoon", "МАНИФЕСТ О ПРОГРАММЕ")
    _in_log = (chat_id == LOG_CHAT_ID)
    _replied_is_report = False
    if is_reply_to_bot and update.message.reply_to_message:
        _rtxt = getattr(update.message.reply_to_message, "text", None) or getattr(update.message.reply_to_message, "caption", None) or ""
        _replied_is_report = any(m in _rtxt for m in _REPORT_MARKERS)
    _in_dm_reply = (chat_id == OWNER_ID and chat_type == "private" and _replied_is_report)
    if (_in_log or _in_dm_reply) and user_id == OWNER_ID and text and not text.startswith('/') and not _ai_loop_guard(update, text):
        if rate_ok('jassist:' + str(user_id), limit=20, window=120):
            try:
                await _journal_assistant(update, context, text)
            except Exception as e:
                try: await update.message.reply_text("⚠️ Ассистент журнала споткнулся: " + str(e)[:140])
                except Exception: pass
        return

    # ВЫГОВОР 02.07.2026 (@jamaat_ru, Orthodox): «Мухэймине есть этот хадис?» БЕЗ «ботяра»-префикса, реплаем на
    # СВОЁ ЖЕ предыдущее сообщение с текстом — бот молчал/отвечал не по теме. Триггер работает у ВСЕХ (не только
    # владелец), независимо от «ботяра», без ИИ-домысла (честный текстовый поиск по muhaymin.json).
    if text and not _ai_loop_guard(update, text) and parse_muhaymin_check(text) and feature_allowed('bot', tg_user_dict(update)):
        if rate_ok('muhcheck:' + str(user_id), limit=6, window=120):
            hadith_src = ''
            if update.message.reply_to_message and (update.message.reply_to_message.text or update.message.reply_to_message.caption):
                hadith_src = update.message.reply_to_message.text or update.message.reply_to_message.caption
            else:
                hadith_src = re.sub(r'мух[эе]йм[иі]н[еа]?.*$', '', text, flags=re.IGNORECASE).strip()
                if not re.search(r'[ء-ي]', hadith_src): hadith_src = text  # запрос сам может содержать текст перед словом «мухэймин»
            await update.message.reply_text("🔎 Ищу в Мухэймине...")
            result = await muhaymin_check_reply_text(hadith_src)
            await send_long(update, result)
            return

    # ============ G9: «ботяра» для белого списка (не владелец) ============
    if user_id != OWNER_ID and text and not _ai_loop_guard(update, text) and not _AI_PUBLIC_OFF:  # 🔒 мастер-рубильник: ИИ не-владельцу ВЫКЛ
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
            # #450: «ботяра дай карточку X» — СТРУКТУРНЫЙ ответ (наши данные + ссылки), не общий ИИ-домысел
            _nq = parse_narr_card_query(clean)
            if _nq:
                await update.message.reply_text("🔎 Ищу в базе передатчиков...")
                result = await narr_card_reply_text(_nq[0], _nq[1])
                await send_long(update, result)
                await log_bot_ai(update, context, ai_text="structured")
                return
            # #356 (владелец: «ботяра переведи не работает» из чата): раньше «ботяра переведи текст» у ОБЫЧНОГО
            # пользователя уходило в общий ask_ai_with_memory (не гарантированный перевод) — ветка parse_translate
            # была подключена ТОЛЬКО у владельца/его канала (строка ~4148). Теперь тот же путь доступен и здесь.
            _tr = parse_translate(clean)
            if _tr is not None:
                _tr_text = _tr if _tr != "REPLY" else ((update.message.reply_to_message.text if update.message.reply_to_message else None))
                if _tr_text:
                    await update.message.reply_text("🔄 Перевожу...")
                    result = ask_ai(f"Переведи на русский:\n{_tr_text}", "Ты — переводчик.")
                    await send_long(update, result)
                    await log_bot_ai(update, context, ai_text=result)
                    return
            await update.message.reply_text("🤔 Думаю...")
            result = ask_ai_with_memory(clean)
            await send_long(update, result)
            await log_bot_ai(update, context, ai_text=result)
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

        # ============ ПРАВКА СВОИХ ПОСТОВ В КАНАЛЕ (владелец 26.07.2026) ============
        # «Обеспечь, чтобы бот умел исправлять любое своё смс, тем более в канале!!!»
        # Команда владельца: «почини анонс v1228» — бот берёт номер сообщения из журнала
        # (app_post_msgids), прогоняет ноту через чистилку и переписывает пост.
        # «почини анонсы» без версии — чинит ВСЕ посты, номера которых знает.
        try:
            _т = (text or '').strip().lower()
            if _т.startswith('почини анонс') and _claude_bridge_owner(update):
                _j = _data_get("journal.json", {}) or {}
                _мид = _j.get('app_post_msgids') or {}
                try:
                    _rq = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/update_notes_queue.json",
                                       headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}, timeout=10)
                    _оч = json.loads(base64.b64decode(_rq.json().get("content", "")).decode("utf-8") or "[]") if _rq.status_code == 200 else []
                except Exception:
                    _оч = []
                _ноты = {n.get('id'): n.get('note') for n in _оч if isinstance(n, dict) and n.get('id')}
                _цель = _т.replace('почини анонсы', '').replace('почини анонс', '').strip()
                _список = [_цель] if _цель else list(_мид)
                if not _мид:
                    await update.message.reply_text(
                        "Номеров постов пока нет: их начали запоминать только сейчас. "
                        "Старые посты правятся так — перешлите мне пост из канала, я перепишу его по номеру из пересылки.")
                    return
                _ок, _мимо = [], []
                for _в in _список:
                    _m = _мид.get(_в); _n = _ноты.get(_в)
                    if not _m or not _n:
                        _мимо.append(_в); continue
                    try:
                        _photo, _body = _format_channel_post(_clean_announce(_n))
                        await context.bot.edit_message_text(chat_id=APP_CHANNEL_ID, message_id=_m,
                                                            text=_body, parse_mode="HTML",
                                                            disable_web_page_preview=True)
                        _ок.append(_в)
                    except Exception as e:
                        _мимо.append('%s (%s)' % (_в, str(e)[:40]))
                _хвост = (' · не вышло: ' + ', '.join(_мимо)) if _мимо else ''
                await update.message.reply_text("✅ Переписано: %s%s" % (', '.join(_ок) or '—', _хвост))
                return
        except Exception:
            pass

        # ============ ID ПЕРЕСЛАННОГО ЧАТА (владелец 26.07.2026) ============
        # Крупные бэкапы владелец просил слать в чат «Архив облачный», а id этого чата взять неоткуда:
        # бот сидит на вебхуке, getUpdates пуст, в журнал заявок id не попадает. Плюс пересланные
        # сообщения бот НАРОЧНО пропускает (_ai_loop_guard: иначе он отвечал сам себе и жёг ключ).
        # Теперь: владелец пересылает боту любое сообщение из нужного чата — бот называет id.
        # Только владельцу и только по пересылке: постороннего это не касается.
        try:
            _fo = getattr(update.message, 'forward_origin', None)
            _fc = getattr(_fo, 'chat', None) or getattr(update.message, 'forward_from_chat', None)
            _fmid = getattr(_fo, 'message_id', None) or getattr(update.message, 'forward_from_message_id', None)
            if _fc is not None and _claude_bridge_owner(update):
                # ПРАВКА АНОНСА В КАНАЛЕ (владелец 26.07.2026, срочно).
                # В @muslimoonapp ушли ноты с ЛИЧНОЙ РЕЧЬЮ владельца в кавычках и внутренней кухней
                # (Railway, ключи, id чатов, бэкапы). Публичный канал — для читателей приложения.
                # Номера отправленных сообщений мы не сохраняли, а Telegram не даёт читать историю
                # канала — значит id взять неоткуда. Кроме одного пути: владелец ПЕРЕСЫЛАЕТ пост,
                # и в пересылке приходит message_id. По нему и правим.
                _ch = str(APP_CHANNEL_ID or '')
                if _fmid and _ch and str(_fc.id) == _ch:
                    исходный = (update.message.text or update.message.caption or '')
                    чистый = _clean_announce(исходный)
                    try:
                        await context.bot.edit_message_text(chat_id=_fc.id, message_id=_fmid, text=чистый)
                        await update.message.reply_text("✅ Пост в канале переписан — личные цитаты и рабочая кухня убраны.")
                    except Exception as e:
                        await update.message.reply_text("Не смог переписать: %s\n\nВот чистый текст, вставьте вручную:\n\n%s"
                                                        % (str(e)[:90], чистый))
                    return
                await update.message.reply_text(
                    "🆔 Переслано из: %s\nid: `%s`\nтип: %s"
                    % (getattr(_fc, 'title', '?'), _fc.id, getattr(_fc, 'type', '?')),
                    parse_mode="Markdown")
                return
        except Exception:
            pass

        # ============ НИШТЯЧОК (владелец 03.07.2026, С52): вытащить пользу из текста/видео/ссылки/аудио и оформить пост ============
        if await _nisht_dispatch(update, context):
            return

        if text and parse_registry_command(text) == "add_media":
            if update.message.reply_to_message:
                replied = update.message.reply_to_message
                if replied.audio or replied.voice or replied.video or replied.photo or replied.document:
                    hint = replied.caption or ""
                    _st = await update.message.reply_text("🔍 Распознаю содержимое (ИИ)…")   # #109: одно редактируемое сообщение вместо спама «Анализирую»+результат
                    desc = ai_describe_media(hint)
                    pending_edits[chat_id] = {"action": "add_registry", "description": desc}
                    try:
                        await _st.edit_text(f"📝 {desc}\n\nСохранить в реестр? (да/нет)")
                    except Exception:
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

        # #163: подтверждение голосовой ЗАЯВКИ (в аудио бывают ошибки распознавания — переспрашиваем перед записью)
        if chat_id in pending_edits and pending_edits[chat_id].get("action") == "add_request_voice":
            pend = pending_edits.pop(chat_id)
            if text.lower().strip() in ["да", "ок", "ok", "yes", "записать", "запиши", "верно", "ага"]:
                vtxt = pend.get("text", "")
                dup = req_dup(vtxt)
                if dup:
                    await update.message.reply_text(f"⚠️ Похоже, уже есть — заявка №{dup}. Не дублирую.")
                else:
                    rid = req_add(vtxt)
                    try:
                        if update.effective_chat.id != LOG_CHAT_ID:
                            await context.bot.send_message(LOG_CHAT_ID, f"📥 Заявка владельца #{rid} (голосом, {_now_msk()}):\n{vtxt[:1500]}")
                    except Exception:
                        pass
                    await update.message.reply_text(f"📥 Заявка #{rid} записана ✅ (голосом). Ищи в журнале командой «заявки».")
            else:
                await update.message.reply_text("❌ Не записал. Надиктуй заново или поправь текстом «заявка <текст>».")
            return

        # #163: голосовая ЗАЯВКА — владелец шлёт голосовое в ЛИЧКУ (без текста) → Whisper → подтверждение перед записью
        if chat_type == "private" and update.message.voice and not is_forward and not (text and text.strip()):
            _vst = await update.message.reply_text("🎤 Распознаю голосовое (Whisper)…")
            vtxt = None
            try:
                _vf = await context.bot.get_file(update.message.voice.file_id)
                _vp = os.path.join("/tmp", f"vreq_{update.message.message_id}.ogg")
                await _vf.download_to_drive(_vp)
                vtxt = await asyncio.get_event_loop().run_in_executor(None, transcribe_audio, _vp)
                try: os.remove(_vp)
                except Exception: pass
            except Exception:
                vtxt = None
            if not vtxt or not vtxt.strip():
                try: await _vst.edit_text("❌ Не удалось распознать голосовое (нужен OPENAI_API_KEY/Whisper на Railway). Можешь текстом: «заявка <текст>».")
                except Exception: pass
                return
            pending_edits[chat_id] = {"action": "add_request_voice", "text": vtxt.strip()}
            _msg = f"📝 Я распознал так:\n\n«{vtxt.strip()[:1200]}»\n\nЗаписать как заявку? (да / нет). В аудио бывают ошибки — проверь текст."
            try: await _vst.edit_text(_msg)
            except Exception: await update.message.reply_text(_msg)
            return

        if chat_type == "private" and (is_forward or has_media):
            hint = text or ""
            _st = await update.message.reply_text("🔍 Распознаю содержимое (ИИ)…")   # #109: одно редактируемое сообщение вместо «Анализирую»+результат
            desc = ai_describe_media(hint)
            pending_edits[chat_id] = {"action": "add_registry", "description": desc}
            try:
                await _st.edit_text(f"📝 {desc}\n\nСохранить в реестр? (да/нет)")
            except Exception:
                await update.message.reply_text(f"📝 {desc}\n\nСохранить в реестр? (да/нет)")
            return

        # #196 (интерфейс доносить разборы): ответь на сообщение (разбор Абу Сафии/чужой пост о достоверности) словом «в разборы» →
        # бот сохранит его как СЫРОЙ разбор (data/razbory_raw.json), Claude оформит в карточку (тема/вердикт/хадис/конспект).
        if text and update.message.reply_to_message and re.match(r'^\s*(в\s*разбор[ыа]|разбор\s*в\s*базу|сохрани\s*разбор|это\s*разбор)\s*$', text.strip().lower()):
            rep = update.message.reply_to_message
            rt = rep.text or rep.caption or ""
            doc_name = ""
            # #216/#196: если приложен ДОКУМЕНТ (.docx/.txt — работа Шабаба и т.п.) — скачиваем и извлекаем текст (без доп.библиотек)
            if (not rt or len(rt) < 40) and getattr(rep, "document", None):
                try:
                    d = rep.document; doc_name = d.file_name or ""
                    f = await context.bot.get_file(d.file_id)
                    blob = bytes(await f.download_as_bytearray())
                    low = doc_name.lower()
                    if low.endswith(".docx"):
                        import zipfile, io as _io, html as _htmlmod
                        z = zipfile.ZipFile(_io.BytesIO(blob))
                        xml = z.read("word/document.xml").decode("utf-8", "ignore")
                        xml = re.sub(r'</w:p>', "\n", xml); xml = re.sub(r'<[^>]+>', "", xml)
                        dt = _htmlmod.unescape(xml).strip()
                        if dt: rt = (rt + "\n\n" + dt) if rt else dt
                    elif low.endswith(".txt"):
                        dt = blob.decode("utf-8", "ignore").strip()
                        if dt: rt = (rt + "\n\n" + dt) if rt else dt
                except Exception as _e:
                    pass
            if not rt:
                await update.message.reply_text("❌ В том сообщении нет текста/распознаваемого документа (.docx/.txt). Ответь «в разборы» на текстовый разбор или Word-файл.")
                return
            src_url = ""
            try:
                ch = rep.sender_chat or rep.chat
                if ch and getattr(ch, "username", None):
                    src_url = f"https://t.me/{ch.username}/{rep.message_id}"
            except Exception:
                pass
            raw = _data_get("razbory_raw.json", []) or []
            new_id = max([x.get("id", 0) for x in raw], default=0) + 1
            entry = {"id": new_id, "text": rt[:9000], "url": src_url, "doc": doc_name,
                     "from": (rep.from_user.full_name if rep.from_user else ""), "ts": _now_msk()}
            raw.append(entry)
            _data_put("razbory_raw.json", raw, f"raw razbor +#{new_id} (всего {len(raw)})")
            await update.message.reply_text(
                f"📿 Сырой разбор #{new_id} сохранён (всего {len(raw)}){(' · из файла '+doc_name) if doc_name else ''}. Claude оформит его в карточку: тема, вердикт, хадис+ссылка, конспект."
                + (f"\n🔗 {src_url}" if src_url else ""))
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
        _want_transcribe = bool(re.match(r'^(расшифр\w*|транскри\w*|в\s*текст|текст\b|whisper)', _tl))
        _has_meta     = bool(re.search(r'(имя|исполнител\w*|назван\w*|описани\w*|title|artist|performer)\s*[:=]?\s*["«»“‘\']', _tl))
        # 📝 РАСШИФРОВКА речи (Whisper): ответь на голосовое/аудио/видео + «расшифровать»
        if _has_audio and _want_transcribe:
            await update.message.reply_text("📝 Расшифровываю речь… (может занять минуту)")
            _fobj = _rep.audio or _rep.voice or _rep.video or _rep.document
            try:
                _f = await _fobj.get_file()
                _ext = ".ogg"   # #163-фикс: Whisper отвергает .audio — вывести реальное расширение из источника (иначе транскрипция падала с 400)
                try:
                    _ok = (".flac",".m4a",".mp3",".mp4",".mpeg",".mpga",".oga",".ogg",".wav",".webm")
                    if _rep.voice: _ext = ".ogg"
                    elif _rep.video: _ext = ".mp4"
                    elif _rep.audio:
                        _ext = os.path.splitext(getattr(_rep.audio, "file_name", "") or "")[1] or ("." + (getattr(_rep.audio, "mime_type", "") or "").split("/")[-1])
                    elif _rep.document:
                        _ext = os.path.splitext(getattr(_rep.document, "file_name", "") or "")[1] or ".ogg"
                    if (_ext or "").lower() not in _ok: _ext = ".ogg"
                except Exception: _ext = ".ogg"
                _src = f"/tmp/{_f.file_id}{_ext}"
                await _f.download_to_drive(_src)
                _txt = await asyncio.get_event_loop().run_in_executor(None, transcribe_audio, _src)
                if _txt:
                    if len(_txt) > 3800:   # длинная речь → присылаем файлом-документом
                        from io import BytesIO
                        _bio = BytesIO(_txt.encode("utf-8")); _bio.name = "transcript.txt"
                        await update.message.reply_document(document=_bio, caption="📝 Расшифровка (длинная — файлом)")
                    else:
                        await send_long(update, "📝 Расшифровка:\n\n" + _txt)
                else:
                    await update.message.reply_text("❌ Не удалось расшифровать. Нужен OPENAI_API_KEY на Railway (Whisper).")
                try: os.remove(_src)
                except Exception: pass
            except Exception as e:
                await update.message.reply_text("❌ Ошибка расшифровки: " + str(e)[:200])
            return
        if _has_audio and (_want_mp3 or _want_enhance or _has_meta):
            await update.message.reply_text("✨ Улучшаю звук (шумодав + громкость)…" if _want_enhance else "🎧 Делаю mp3…")
            _fobj = _rep.audio or _rep.voice or _rep.video or _rep.document
            _t_meta, _a_meta, _c_meta = parse_audio_meta(text)
            # свободный заголовок после команды без кавычек: «mp3 Лекция о посте»
            if not _t_meta:
                _rest = re.sub(r'^\s*(бахни\s*)?(mp3|мп3|улучши\w*|почисти\w*|конверт\w*|студий\w*|auphonic)\b[\s:.\-—]*', '', text, flags=re.IGNORECASE).strip()
                if _rest and not re.search(r'["«»“‘\']|исполнител|описани|artist|performer|comment', _rest, re.IGNORECASE):
                    _t_meta = _rest[:150]
            _title  = _t_meta or (getattr(_rep.audio, 'title', None) if _rep.audio else None) or _now_msk()   # M302: время в заголовке mp3 — строго МСК (единая _now_msk, сервер Railway живёт в UTC)
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

    # ============ #163: ГОЛОСОВЫЕ ЗАЯВКИ ВЛАДЕЛЬЦА (voice → распознавание → ПОДТВЕРЖДЕНИЕ → регистрация) ============
    if is_owner(update) and update.message.voice and getattr(update.effective_chat, "type", "") == "private" and not update.message.reply_to_message:
        await update.message.reply_text("📝 Распознаю голос…")
        try:
            _f = await update.message.voice.get_file()
            _src = f"/tmp/{_f.file_id}.ogg"
            await _f.download_to_drive(_src)
            _txt = await asyncio.get_event_loop().run_in_executor(None, transcribe_audio, _src)
            if _txt and _txt.strip():
                _txt = _txt.strip()
                pending_edits[chat_id] = {"action": "voice_request_confirm", "transcribed_text": _txt}
                await update.message.reply_text(f"🎙️ Правильно ли я понял заявку:\n\n«{_txt}»\n\nОтветь: да / нет / или пришли исправленный текст")
            else:
                await update.message.reply_text("❌ Не удалось распознать (нужен OPENAI_API_KEY / Whisper).")
            try: os.remove(_src)
            except Exception: pass
        except Exception as e:
            await update.message.reply_text("❌ Ошибка голоса: " + str(e)[:200])
        return

    # ============ ВЛАДЕЛЕЦ: ПАМЯТЬ ============
    # M393: память/реестры — ТОЛЬКО из ЛИЧКИ владельца (в группе «запомни…» сохранял шутки в memory.json)
    if is_owner(update) and text and getattr(update.effective_chat, "type", "") == "private":
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
            if pending.get("action") == "voice_request_confirm":
                if t_lower in ["да", "ок", "ok", "yes", "верно"]:
                    txt = pending["transcribed_text"]; pending_edits.pop(chat_id)
                    dup = req_dup(txt)
                    if dup:
                        await update.message.reply_text(f"⚠️ Похоже, это уже есть — *заявка №{dup}*. Не дублирую.", parse_mode="Markdown")
                    else:
                        rid = req_add(txt)
                        try:
                            if update.effective_chat.id != LOG_CHAT_ID:
                                await context.bot.send_message(LOG_CHAT_ID, f"📥 Заявка владельца (голосом) #{rid} ({_now_msk()}):\n{txt[:1500]}")
                        except Exception: pass
                        await update.message.reply_text(f"📥 *Заявка #{rid}* записана ✅ · 🤖 бот ({_now_msk()})", parse_mode="Markdown")   # M287
                elif t_lower in ["нет", "не надо", "отмена", "no"]:
                    pending_edits.pop(chat_id)
                    await update.message.reply_text("❌ Отмена. Пришли голос снова или напиши текстом.")
                else:
                    new_text = (text or "").strip()
                    if new_text:
                        pending_edits[chat_id] = {"action": "voice_request_confirm", "transcribed_text": new_text}
                        await update.message.reply_text(f"✏️ Исправил на:\n\n«{new_text}»\n\nВерно? (да / нет)")
                    else:
                        pending_edits.pop(chat_id)
                        await update.message.reply_text("❌ Пусто. Пришли голос снова.")
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
                await log_bot_ai(update, context, ai_text=result)
                return

        # В чате/канале: отвечаем ТОЛЬКО если есть "ботяра" или ответ боту
        elif chat_type != "private" and not _ai_loop_guard(update, text):
            # #236/#284: ботяра-ИИ в группе отвечает ТОЛЬКО при ВКЛ рубильнике. Когда ВЫКЛ — НЕ выходим из обработчика:
            # обычные команды-лукапы (Бухари 7288 / Коран / передатчик) ниже ДОЛЖНЫ работать (бот = админ группы, сообщения получает).
            if (not _GROUP_AI_OFF) and ("ботяра" in text.lower() or (is_reply_to_bot and not is_reply_to_channel)):
                if not rate_ok('botchat:' + str(chat_id), limit=6, window=120):
                    return
                clean = text.replace("ботяра", "").strip()
                if update.message.reply_to_message and update.message.reply_to_message.text:
                    quoted = update.message.reply_to_message.text
                    clean = f"{clean}\n\nСообщение на которое я отвечаю:\n{quoted}" if clean else f"Прокомментируй это сообщение:\n{quoted}"
                if not clean:
                    clean = "продолжи"
                # #356: та же проверка на перевод, что и в личке — «ботяра переведи текст» в группе теперь тоже переводит
                _tr = parse_translate(clean)
                if _tr is not None:
                    _tr_text = _tr if _tr != "REPLY" else ((update.message.reply_to_message.text if update.message.reply_to_message else None))
                    if _tr_text:
                        await update.message.reply_text("🔄 Перевожу...")
                        result = ask_ai(f"Переведи на русский:\n{_tr_text}", "Ты — переводчик.")
                        await send_long(update, result)
                        await log_bot_ai(update, context, ai_text=result)
                        return
                await update.message.reply_text("🤔 Думаю...")
                result = ask_ai_with_memory(clean)
                await send_long(update, result)
                await log_bot_ai(update, context, ai_text=result)
                return

        # AI на "ботяра" в группах (#284: при выключенном групповом ИИ в группе — НЕ запускаем ботяру; в личке работает)
        if (parse_botyara(text) is not None or is_reply_to_bot) and not _ai_loop_guard(update, text) and not (_GROUP_AI_OFF and chat_type != "private"):
            if not rate_ok('botchat:' + str(chat_id), limit=6, window=120):
                return
            clean = text
            botyara_q = parse_botyara(text)
            if botyara_q is not None:
                clean = botyara_q if botyara_q else ""
            if not clean:
                clean = "продолжи"
            # #450: «ботяра дай карточку X» — СТРУКТУРНЫЙ ответ (наши данные + ссылки), не общий ИИ-домысел
            _nq = parse_narr_card_query(clean)
            if _nq:
                await update.message.reply_text("🔎 Ищу в базе передатчиков...")
                result = await narr_card_reply_text(_nq[0], _nq[1])
                await send_long(update, result)
                await log_bot_ai(update, context, ai_text="structured")
                return
            # #356: та же проверка на перевод — «ботяра переведи текст» теперь переводит и здесь
            _tr = parse_translate(clean)
            if _tr is not None:
                _tr_text = _tr if _tr != "REPLY" else ((update.message.reply_to_message.text if update.message.reply_to_message else None))
                if _tr_text:
                    await update.message.reply_text("🔄 Перевожу...")
                    result = ask_ai(f"Переведи на русский:\n{_tr_text}", "Ты — переводчик.")
                    await send_long(update, result)
                    await log_bot_ai(update, context, ai_text=result)
                    return
            await update.message.reply_text("🤔 Думаю...")
            result = ask_ai_with_memory(clean)
            await send_long(update, result)
            await log_bot_ai(update, context, ai_text=result)
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
            _qclean = re.sub(r'[*_`\[\]()]', '', query)   # #297/#465: та же чистка — сырой ввод рвал Markdown
            await update.message.reply_text(
                f"📖 *Корень:* {_qclean} → {arabic_root}\n\n"
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
        # feedback #3 (25.06.2026, «ابن لهيعة» не ищется): hawramani.com — внешний поиск, не наш индекс,
        # и он чувствителен к орфографии ة/ه (напр. в наших данных передатчик записан «لهيعه», а
        # стандартное написание — «لهيعة»). Наш собственный canon() в мини-аппе это уже фолдит,
        # здесь — та же логика ретраем: не нашли как есть → пробуем оба варианта конца слова.
        if not res and re.search(r"[ةه]$", query):
            _alt = (query[:-1] + ("ه" if query[-1] == "ة" else "ة"))
            res = search_transmitters(_alt, 8)
        if not res:
            await update.message.reply_text("❌ Не найдено в موسوعة رواة الحديث. Попробуй другое написание.")
            return
        msg = f"🧑‍🏫 <b>Передатчики «{_esc_mark(query)}»</b> (موسوعة رواة الحديث):\n\n"
        for i, t in enumerate(res, 1):
            title = _esc_mark(t["title"])
            url = (t["url"] or "").replace("&", "&amp;")
            msg += f'{i}. <a href="{url}">{title}</a>\n'
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
        msg = f"🔍 *«{re.sub(r'[*_`\[\]()]', '', sq)}»*\n\n"   # #297/#465: непарный _/* в сыром поисковом запросе рвал Markdown всего сообщения (тот же класс, что #501)
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
                # #285 (владелец: «научи подтягивать оригинал хадиса — ссылку на карточку соответствующего первоисточника»):
                # у версии есть парсуемый код+номер первоисточника (verified_from/restored_from) → даём тот же
                # deep-link формат r_{code}_{num}, что и в прямом поиске по номеру (#269, строка 4746-4747).
                _vfp = vf.split()
                if len(_vfp) >= 2 and _vfp[1].isdigit() and _vfp[0].isalpha():
                    _vfcode = {"ahmad_local": "ahmad"}.get(_vfp[0], _vfp[0])
                    body += f"\n📲 [Открыть карточку первоисточника](https://t.me/muslimoontt_bot?startapp=r_{_vfcode}_{_vfp[1]})"   # #629: голый URL с «_» Telegram-Markdown резал в курсив (юзернейм слипался → «имя не найдено») — прячем URL в markdown-ссылку
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
                # #354 (слово владельца): честная формулировка — не «пусто в источнике» огульно,
                # а «в НАШЕЙ базе не найден» + возможные причины + совет искать по тексту
                await update.message.reply_text(
                    f"❌ {NAMES.get(collection, collection)} №{number} — в нашей базе не найден.\n"
                    f"Возможные причины: номер за пределами издания ИЛИ пробел в наших данных "
                    f"(сообщи — проверим и добьём).\n"
                    f"💡 Попробуй поиск по тексту: «{NAMES.get(collection, collection)} <часть хадиса>».{hint}")
                return
            similar = search_similar_hadith(ar) if collection != "ahmad_local" else []
            msg = f"📖 {NAMES.get(collection, collection)}, №{number}\n\n"
            if ar:
                msg += f"🔤 {ar}\n\n"
            if (not tr or lang == "англ") and ar:   # БАГ (владелец «почему английский»): нет русского издания → бот показывал АНГЛИЙСКИЙ. Проект русскоязычный → ИИ-перевод на русский; английский НЕ показываем
                _ru = translate_matn(ar, "had_" + str(collection), owner=is_owner(update))   # нет готового перевода → ИИ-перевод (кэш) — у КАЖДОГО хадиса красивый пост араб+рус
                if _ru:
                    tr = _ru; lang = "рус"
                elif lang == "англ":
                    tr = ""   # ИИ не дал (не-владелец/гейт) — английский НЕ показываем (русскоязычный проект), лучше арабский без перевода
            if tr:
                msg += f"🌍 {tr}\n"
            if gr:
                msg += f"\n📊 {gr}"
            msg += f"\n\n📚 {NAMES.get(collection, collection)}, №{number}"
            if similar:
                msg += f"\n\n📖 Также:\n• " + "\n• ".join(similar[:5])
            _src_code = {"ahmad_local": "ahmad"}.get(collection, collection)
            msg += muhaymin_crossref_note(_src_code, number)
            # #269: прямая ссылка — открыть ЭТУ карточку хадиса в приложении одним тапом
            _sa269 = ('m_' + str(number)) if _src_code == 'muhaymin' else ('r_' + str(_src_code) + '_' + str(number))
            msg += f"\n\n📲 [Открыть карточку в приложении](https://t.me/muslimoontt_bot?startapp={_sa269})"   # #629: см. выше — «_» в голом URL ломали ссылку

            await send_long(update, msg)
            return

    # ============ #324: «<книга из каталога> <номер>» (вне 8 канона) → кнопка-ссылка в мини-апп ============
    # Сюда доходим ТОЛЬКО если канон/первоисточники/Коран выше не подошли. «азоми 1» → транслит-матч по
    # каталогу Мактабы → top-3 кандидата кнопками с deep-link b_<turath_id>_<номер> (мини-апп откроет книгу).
    _m324 = re.match(r"^([а-яё][а-яё'`ʼ’\s\-]{2,40}?)\s+(\d{1,5})$", text.lower().strip())
    if _m324:
        try:
            _c324 = _catalog_match(_m324.group(1))
        except Exception:
            _c324 = []
        # в группах отвечаем только при УВЕРЕННОМ матче (≥0.8) — чтобы не спамить на случайные «слово 123»
        if _c324 and (getattr(update.effective_chat, "type", "") == "private" or _c324[0][0] >= 0.8):
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup   # локальный импорт — как в «закреп» (стр. ~3231)
            _n324 = _m324.group(2)
            _kb324 = []
            for _sc, _bid, _nm, _au in _c324:
                _lbl = ("📖 " + _nm[:38] + (" — " + _au.split()[-1] if _au else ""))[:60]
                _kb324.append([InlineKeyboardButton(_lbl, url=f"https://t.me/muslimoontt_bot?startapp=b_{_bid}_{_n324}")])
            # #626 (владелец: «почему не даешь хадис? Книга и номер даны… НО ХАДИС НАДО ВЫДАТЬ!»).
            # Раньше сюда попадал ЛЮБОЙ запрос «книга + номер», и ответом были только кнопки —
            # даже когда книга оказывалась нашим каноническим сборником и текст лежал под рукой.
            # Причина: наверху хадис ищется по русским кличкам («бухари 100»), а «сахих аль-бухари 100»
            # или арабское название до той ветки не доходили и падали сюда, в каталог.
            # Теперь: если опознанная книга — одно из канонических изданий, СНАЧАЛА отдаём сам хадис.
            _c2col = {1681: "bukhari", 1727: "muslim", 1726: "abudawud", 7895: "tirmidhi",
                      829: "nasai", 1198: "ibnmajah", 1699: "malik", 25794: "ahmad_local"}
            _наш = next((_c2col[_b] for _s, _b, _nm, _au in _c324 if _b in _c2col), None)
            if _наш:
                await update.message.reply_text("⏳ Ищу хадис...")
                _ar, _tr, _lang, _gr = (get_ahmad_hadith(_n324) if _наш == "ahmad_local"
                                        else get_hadith(_наш, _n324))
                if _ar or _tr:
                    _msg = f"📖 {NAMES.get(_наш, _наш)}, №{_n324}\n\n"
                    if _ar:
                        _msg += f"🔤 {_ar}\n\n"
                    if _tr:
                        _msg += f"🌍 {_tr}\n"
                    if _gr:
                        _msg += f"\n📊 {_gr}"
                    _sc326 = {"ahmad_local": "ahmad"}.get(_наш, _наш)
                    _msg += muhaymin_crossref_note(_sc326, _n324)
                    _msg += (f"\n\n📲 [Открыть карточку в приложении]"
                             f"(https://t.me/muslimoontt_bot?startapp=r_{_sc326}_{_n324})")
                    await send_long(update, _msg)
                    return
            # #626 (владелец: «Книга и номер даны… НО ХАДИС НАДО ВЫДАТЬ!»). Книга вне наших 41
            # сборника — но это не повод отделываться ссылкой. Лист книги у Мактабы берётся по
            # номеру, номера хадисов стоят в тексте, значит нужный лист находится прицельным
            # поиском. Кнопки выбора книги при этом остаются: владелец просил и хадис выдать, и
            # возможность переключиться на другую книгу Табарани сохранить.
            _имя324 = _c324[0][2] if _c324 else ""
            _ждём = await update.message.reply_text("⏳ Ищу №%s в книге «%s»…" % (_n324, _имя324[:40]))
            _лист, _хад = await asyncio.get_event_loop().run_in_executor(
                None, мактаба_хадис, _c324[0][1], _n324)
            try:
                await _ждём.delete()
            except Exception:
                pass
            if _хад:
                # send_long кнопок не носит (у неё их нет в сигнатуре), а кнопки владелец просил
                # оставить — значит шлём одним сообщением и держим длину в рамках телеграма:
                # текст режем до 3000, шапка ~200 → влезаем в 3900.
                def _эск(s):
                    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
                await update.message.reply_text(
                    "📖 <b>%s</b>, №%s\n\n🔤 %s\n\n📄 Лист %s · книга из библиотеки Мактабы "
                    "(вне наших 41 сборника — оценки достоверности по ней у нас нет)"
                    % (_эск(_имя324), _эск(_n324), _эск(_хад[:3000]), _лист),
                    reply_markup=InlineKeyboardMarkup(_kb324), parse_mode="HTML")
                return
            # Не нашли — так и говорим. Соврать номером хуже, чем не ответить (П-43).
            await update.message.reply_text(
                f"📚 По запросу «{text}»: это «{_имя324}» из библиотеки Мактабы.\n"
                f"Хадис №{_n324} в ней найти не удалось — либо в этом издании другая нумерация, "
                f"либо номер за пределами книги. Выдумывать не буду.\n"
                f"Открыть книгу в приложении и посмотреть глазами:"
                + ("" if len(_c324) == 1 else "\n(если не та книга — выбери из кандидатов)"),
                reply_markup=InlineKeyboardMarkup(_kb324))
            return

    # ============ #124: ТЕМАТИЧЕСКИЙ РУССКИЙ ЗАПРОС (без «хадис о») — ПОСЛЕДНИЙ ФОЛБЭК по смыслу ============
    # Срабатывает ТОЛЬКО если ничего выше не подошло (Коран/книги/хадис/команды уже обработаны и вернулись).
    # Гарды: фраза ≥2 слов и ≥12 символов, не числа/двоеточия, не owner-команды → не ловит приветствия/команды.
    _tl124 = text.lower().strip()
    # #154/#153: ТОЛЬКО в ЛИЧКЕ — иначе бот спамит в группах (@jamaat_ru), реагируя на каждое сообщение.
    if (getattr(update.effective_chat, "type", "") == "private"
            and len(text.split()) >= 2 and len(text) >= 12
            and not re.match(r'^[\d\s:.,\-]+$', text)
            and not _tl124.startswith(("/", "ботяра", "запомни", "исправь", "в реестр", "реестр", "результат", "сделано", "удали", "анонс", "заявка", "замечание", "ошибк", "бан", "разбан", "память"))):
        try:
            _kw = ask_ai(
                "Из описания хадиса по смыслу выдай 4-7 КЛЮЧЕВЫХ АРАБСКИХ СЛОВ из его матна. "
                "Только слова через пробел, без огласовок, без перевода и пояснений.\nОписание: " + text,
                "Ты знаток хадисов. Отвечай ТОЛЬКО арабскими словами через пробел.",
                owner=is_owner(update))
            _kw = re.sub(r"\n*⚡ \*Модель:.*$", "", _kw or "", flags=re.S)
            _kw = re.sub(r"[^؀-ۿ\s]", " ", _kw).strip()
            if _kw:
                _cnt, _res = search_sunnah_one(_kw, limit=4)
                if _res:
                    await update.message.reply_text(f"🔎 По смыслу «{text[:45]}» → {_kw}\nالدرر السنية: найдено {_cnt}")
                    _r0 = _res[0]
                    _m = f"{hukm_emoji(_r0['hukm'])} <b>الحكم:</b> {_esc_mark(_r0['hukm'] or '—')}\n📜 <b>{_esc_mark(_r0['marked'])}</b>\n"
                    if is_owner(update):
                        try:
                            _ru = translate_matn(_r0["text"], src=_r0.get("takhreej", ""), owner=True)
                            if _ru: _m += f"🌍 {_esc_mark(_ru)}\n"
                        except Exception: pass
                    if _r0.get("takhreej"): _m += f"📋 {takhreej_html(_r0['takhreej'])}\n"
                    await send_long(update, _m, "HTML")
                    return
        except Exception:
            pass

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
            "🎧 Аудио (reply на аудио/войс): mp3 · улучшить · расшифровать (речь→текст)\n"
            "   теги: mp3 имя \"X\" исполнитель \"Y\" описание \"Z\"\n\n"
            "*Память (владелец):*\nзапомни: факт | память | удали память 2\nисправь память 2: текст | очистить память\n\n"
            "*Реестр (владелец):*\nв реестр (reply) | реестр | ожидает\nсделано 1 | удали 1 | результат 1 ссылка",
            parse_mode="Markdown",
            reply_markup=MAIN_KB
        )

# ═══ RAG-ПОИСК В ЧАТЕ (владелец 26.07.2026: «в джамаат ру включи… пока включи чё есть») ═══
# В приложении поиск идёт в браузере: там векторы книги лежат рядом. Боту их взять неоткуда,
# поэтому он тянет те же файлы с GitHub Pages ОДИН РАЗ и держит в памяти (19 МБ векторов + метаданные).
# Модель вектора вопроса — та же bge-m3: векторы разных моделей несопоставимы.
def _clean_announce(текст):
    """Чистит анонс перед публикацией: убирает личную речь владельца и рабочую кухню.

    Владелец 26.07.2026, дважды и в гневе: «ты в канал много личной кухни слил, ты что совсем
    голову потерял? Немедленно исправь и убери мои цитаты личные». Он прав: в @muslimoonapp ушли
    ноты, где ЦИТИРОВАЛАСЬ его личная речь в кавычках, и упоминались Railway, ключи, id чатов,
    бэкапы. Публичный канал — для читателей приложения: там место тому, что изменилось для НИХ,
    а не нашей переписке и не устройству серверов.

    Правило простое: строку выкидываем, если в ней есть речь владельца или внутренняя кухня.
    Заголовок версии и то, что понятно читателю, остаётся. Это ворота ДО публикации — чтобы
    впредь такое не проходило само, а не только чинилось задним числом.
    """
    ЛИЧНОЕ = ('владелец', 'заявка владельца', 'указ владельца', 'сэр', 'он прав', 'выговор')
    КУХНЯ = ('railway', 'cloudflare', 'api-ключ', 'api ключ', 'ключ ', 'токен', 'env',
             'id чата', 'бэкап', 'github', 'commit', 'коммит', 'деплой', 'quota', 'квота',
             'архив облачный', 'скрипт', 'локалк', 'ollama', 'кэш telegram')
    # ФИКС 01.08.2026 (владелец: «срочно обновление канал пишет ересь», пост #1109).
    # Чистка шла ПОСТРОЧНО, а ноты пишутся ОДНОЙ длинной строкой: правило про кавычки брало
    # кусок от ПЕРВОЙ ёлочки до ПОСЛЕДНЕЙ (в живых нотах 59-379 знаков) и выбрасывало ВСЮ ноту,
    # в канал уходила заглушка. Теперь каждая цитата судится отдельно, служебные слова судят
    # предложение, а не строку. Сырой текст не возвращается НИКОГДА — защита персданных важнее
    # полноты анонса; «почищено до пустышки» ловит вотчер и не публикует такой пост вовсе.
    def _сор(кусок):
        н = (кусок or '').lower()
        return any(с in н for с in ЛИЧНОЕ) or any(с in н for с in КУХНЯ)

    строки = []
    for стр in str(текст or '').split('\n'):
        # 🔴 05.08.2026. Было безусловное «вырезать любую цитату длиннее 26 знаков» — и под
        # нож попали слова АВТОРА КНИГИ о её названии, ради которых пост и писался. Правило
        # задумывалось против личных цитат владельца, а получилось против прямой речи вообще.
        # Теперь длинная цитата выбрасывается, только если рядом видно, что речь ЛИЧНАЯ; а
        # цитаты с арабским не трогаем никогда — это цитаты из книг, наше содержание.
        _РЕЧЬ = ('владелец', 'сказал', 'говорит', 'просил', 'написал мне', 'в гневе',
                 'он прав', 'жалоб', 'ругал', 'цитата', 'слово владельца')
        def _личная(м):
            цитата = м.group(0)
            if re.search(r'[\u0621-\u064A]', цитата):
                return цитата                     # арабская цитата — из книги, оставляем
            вокруг = стр.lower()
            return '' if any(з in вокруг for з in _РЕЧЬ) else цитата
        стр = re.sub(r'«[^«»]{26,}»', _личная, стр)
        стр = re.sub(r'[ \t]{2,}', ' ', стр)
        предл = [p for p in re.split(r'(?<=[.!?…])\s+', стр) if p.strip() and not _сор(p)]
        ост = ' '.join(предл).strip()
        if ост:
            строки.append(ост)
    из = '\n'.join(строки).strip()
    из = re.sub(r'\n{3,}', '\n\n', из)
    return из or 'Обновление приложения.'


def _cf_creds():
    """Токен и аккаунт Cloudflare из окружения — ЛЮБЫМ регистром и любым из принятых имён.

    Владелец 26.07.2026: «есть они в Railway, ты чё не проверяешь-то» — и был прав. Эндпоинт отвечал
    «no-key», хотя ключи на месте: в Railway они называются CLOUDFLARE_ACCOUNT_ID и cloudflare_api_key
    (строчными!), а код искал CLOUDFLARE_API_TOKEN. Имя переменной я предположил вместо того, чтобы
    посмотреть. Теперь берём по любому из принятых написаний и без оглядки на регистр.
    """
    # .strip() на ИМЕНИ обязателен: 26.07.2026 владелец завёл переменную, а эндпоинт всё равно молчал —
    # диагностика показала имя «CLOUDFLARE_ACCOUNT_ID » с ПРОБЕЛОМ на конце (проскочил при вводе в панель).
    # Для системы это другое имя. Чистим и имя, и значение — чтобы такая опечатка больше ничего не ломала.
    низ = {k.strip().lower(): (v or '').strip() for k, v in os.environ.items()}
    имена_ток = ('cloudflare_m_api_token', 'cloudflare_api_token', 'cloudflare_api_key',
                 'cloudflare_token', 'cf_token', 'cf_api_token')
    имена_акк = ('cloudflare_m_account_id', 'cloudflare_account_id', 'cf_account_id', 'cloudflare_account')
    tok = next((низ[n] for n in имена_ток if низ.get(n)), '')
    acc = next((низ[n] for n in имена_акк if низ.get(n)), '')
    return tok, acc


def _cf_пары():
    """ВСЕ пары «токен + аккаунт», каждая из своего источника — для запасного хода.

    Мысль владельца 26.07.2026: «надо было наверное оба аккаунта там оставить, чтобы лимитов
    хватало». Мысль верная. По расчёту одного аккаунта хватает с запасом (10 000 нейронов в сутки
    ≈ 14 000 вопросов: расчёт всей книги в 14 344 вектора выжег ровно суточную норму, значит
    вопрос стоит около 0,7 нейрона). Но норма может кончиться — тогда поиск встанет молча.

    ГЛАВНОЕ ПРАВИЛО: токен и номер аккаунта берутся ТОЛЬКО ПАРОЙ из одного источника. Именно
    смешение — токен от одного, номер от другого — и держало RAG в «401 Authentication error»
    полдня 26.07. Поэтому здесь пары, а не два независимых списка.
    """
    низ = {k.strip().lower(): (v or '').strip() for k, v in os.environ.items()}
    пары = []
    for тн, ан in (('cloudflare_api_token', 'cloudflare_account_id'),        # основной
                   ('cloudflare_m_api_token', 'cloudflare_m_account_id'),    # второй аккаунт
                   ('cf_token', 'cloudflare_account_id'),                    # запись из muslimoon_api.env
                   ('cloudflare_api_key', 'cloudflare_account_id')):
        t, a = низ.get(тн, ''), низ.get(ан, '')
        if t and a and (t, a) not in пары:
            пары.append((t, a))
    if not пары:
        t, a = _cf_creds()
        if t and a:
            пары.append((t, a))
    return пары


_RAGB = {'готово': False, 'ids': None, 'поля': None, 'body': None, 's': None,
         'dim': 0, 'n': 0, 'мета': None}

def _rag_load_sync():
    """Грузим базу книги с Pages. Синхронно и один раз — вызывается из потока, событийный цикл не держим."""
    if _RAGB['готово']:
        return True
    try:
        import base64 as _b64, array as _arr
        base = 'https://germanyalfurqan-eng.github.io/hadith-bot/rag/'
        v = requests.get(base + 'bukhari.vec.json', timeout=120).json()
        m = requests.get(base + 'bukhari.meta.json', timeout=120).json()
        сырое = _b64.b64decode(v['v'])
        # Владелец 26.07: бот сказал «ищу» и завис. Перебор 14344 векторов по 1024 измерения — это
        # 14.7 млн умножений; чистым Python на сервере это МИНУТЫ. numpy делает то же одним
        # матричным умножением за доли секунды. Без него команда в чате бесполезна.
        try:
            import numpy as _np
            M = _np.frombuffer(сырое, dtype=_np.int8).reshape(v['n'], v['dim']).astype(_np.float32)
            M *= _np.asarray(v['s'], dtype=_np.float32)[:, None]      # свой множитель на каждый вектор
            body = M
            быстро = True
        except Exception:
            body = _arr.array('b'); body.frombytes(сырое); быстро = False
        _RAGB.update({'ids': v['id'], 'поля': v.get('поле'), 'body': body, 's': v['s'],
                      'dim': v['dim'], 'n': v['n'], 'мета': m.get('м') or {},
                      'быстро': быстро, 'готово': True})
        return True
    except Exception:
        return False

RAG_CHAT_ID = -1001925828112          # @jamaat_ru — единственное место, где РАГ открыт участникам
RAG_ЛИМИТ_ЮЗЕР = 3                    # запросов в сутки на участника (владельца не касается)
_RAG_КВОТА = {}                       # uid -> {'день': 'ГГГГ-ММ-ДД', 'сколько': N}

def _rag_лимит():
    """Сколько запросов в сутки на человека. #673: «установи лимиты на одного, не знаю сколько» —
    раз число не задано, владелец должен уметь менять его на ходу («раг лимит N»), не дожидаясь
    редеплоя Railway. Значение живёт в том же файле доступа, что белый/чёрный списки."""
    try:
        n = int((_rag_access_load() or {}).get('лимит') or RAG_ЛИМИТ_ЮЗЕР)
        return n if n > 0 else RAG_ЛИМИТ_ЮЗЕР
    except Exception:
        return RAG_ЛИМИТ_ЮЗЕР


def _rag_остаток(uid):
    """Сколько запросов осталось у человека — БЕЗ списания. Отдельная функция нужна потому,
    что #673 («почему не показывает лимиты и остатки») — это ПОКАЗ, а показ не должен тратить:
    раньше единственный способ узнать остаток был потратить запрос."""
    import time as _t
    лим = _rag_лимит()
    з = _RAG_КВОТА.get(uid)
    если_сегодня = з and з.get('день') == _t.strftime('%Y-%m-%d')
    потрачено = int(з.get('сколько') or 0) if если_сегодня else 0
    return max(0, лим - потрачено), лим


def _rag_квота(uid):
    """Дневная квота участника. Каждый вопрос стоит нейронов Cloudflare из общего кошелька,
    поэтому счёт ведём по человеку и по суткам. Владелец 27.07.2026: «лимит небольшой, и не
    забудь — обращайтесь к админам, пусть пишут».

    Счётчик ОБЩИЙ для чата и приложения (#673): кошелёк нейронов один, и три запроса «раг» в
    чате плюс сколько угодно нажатий в мини-аппе — это была дыра ровно в размер приложения."""
    import time as _t
    лим = _rag_лимит()
    день = _t.strftime('%Y-%m-%d')
    з = _RAG_КВОТА.get(uid)
    if not з or з.get('день') != день:
        з = {'день': день, 'сколько': 0}
        _RAG_КВОТА[uid] = з
    if з['сколько'] >= лим:
        return False, 0
    з['сколько'] += 1
    return True, лим - з['сколько']


def _rag_нейроны_кратко(освежить=True):
    """Остаток общего кошелька Cloudflare для показа пользователю.

    Никогда не ждём сеть: _cf_neurons_sync() — блокирующий запрос к аналитике Cloudflare, и
    держать на нём ответ приложению нельзя (это ровно тот класс беды, из-за которого «🧠 Ищу
    по смыслу…» висело вечно). Отдаём последнее известное число, а обновление, если оно
    просрочено, запускаем в фоне — к следующему нажатию цифра уже свежая."""
    import time as _t
    свежо = _CF_ЛИМИТ['когда'] and (_t.time() - _CF_ЛИМИТ['когда'] < 300)
    if освежить and not свежо:
        try:
            asyncio.get_event_loop().run_in_executor(_RAG_POOL, _cf_neurons_sync)
        except Exception:
            pass
    съедено = _CF_ЛИМИТ.get('нейронов')
    return {'нейронов_съедено': съедено, 'нейронов_потолок': _CF_СУТКИ,
            'нейронов_осталось': (max(0, _CF_СУТКИ - int(съедено)) if съедено is not None else None),
            'нейроны_ошибка': _CF_ЛИМИТ.get('ошибка') or ''}

_CF_ЛИМИТ = {'нейронов': None, 'когда': 0, 'ошибка': ''}
_CF_СУТКИ = 10000        # бесплатный дневной потолок Workers AI

def _cf_neurons_sync():
    """Сколько нейронов Cloudflare съедено за сегодня. Владелец 27.07.2026: «ты не пишешь остаток
    лимита, важно знать сколько осталось». Свой счётчик запросов — это не остаток: цену запроса
    назначает Cloudflare, поэтому спрашиваем У НЕГО, через GraphQL-аналитику. Ответ держим 5 минут,
    чтобы не дёргать на каждый вопрос."""
    import time as _t
    if _CF_ЛИМИТ['когда'] and _t.time() - _CF_ЛИМИТ['когда'] < 300:
        return _CF_ЛИМИТ['нейронов']
    tok, acc = _cf_creds()
    _CF_ЛИМИТ['когда'] = _t.time()
    if not tok or not acc:
        _CF_ЛИМИТ['ошибка'] = 'нет ключей'; return None
    try:
        сег = _t.strftime('%Y-%m-%d', _t.gmtime())
        q = {"query": "query($acc:String!,$d:Date!){viewer{accounts(filter:{accountTag:$acc}){"
                      "aiInferenceAdaptiveGroups(limit:100,filter:{date_geq:$d}){sum{totalNeurons}}}}}",
             "variables": {"acc": acc, "d": сег}}
        r = requests.post('https://api.cloudflare.com/client/v4/graphql', json=q,
                          headers={'Authorization': 'Bearer ' + tok}, timeout=25).json()
        гр = (((r.get('data') or {}).get('viewer') or {}).get('accounts') or [{}])[0]
        сумма = sum(float((g.get('sum') or {}).get('totalNeurons') or 0)
                    for g in (гр.get('aiInferenceAdaptiveGroups') or []))
        _CF_ЛИМИТ['нейронов'] = сумма
        _CF_ЛИМИТ['ошибка'] = '' if гр else str(r.get('errors'))[:120]
        return сумма
    except Exception as e:
        _CF_ЛИМИТ['ошибка'] = str(e)[:120]
        return None

def _rag_query_vec_sync(q):
    _к = ' '.join((q or '').lower().split())[:300]
    if _к in _ВЕК_КЭШ:                      # уже спрашивали — лимит не тратим
        _ВЕК_СЧЁТ['из_кэша'] += 1
        return _ВЕК_КЭШ[_к]
    tok, acc = _cf_creds()
    if not tok or not acc:
        _ВЕК_СЧЁТ['сбоев'] += 1
        return None
    try:
        url = 'https://api.cloudflare.com/client/v4/accounts/%s/ai/run/@cf/baai/bge-m3' % acc
        j = requests.post(url, json={'text': [q[:600]]},
                          headers={'Authorization': 'Bearer ' + tok}, timeout=30).json()
        _в = ((j.get('result') or {}).get('data') or [None])[0]
        if _в:
            _ВЕК_СЧЁТ['новых'] += 1
            if len(_ВЕК_КЭШ) < 3000:
                _ВЕК_КЭШ[_к] = _в
        else:
            _ВЕК_СЧЁТ['сбоев'] += 1
        return _в
    except Exception:
        _ВЕК_СЧЁТ['сбоев'] += 1
        return None

def _rag_find_sync(q, top=6):
    """Поиск по книге: косинус со всеми векторами + порог отсечки мусора."""
    if not _rag_load_sync():
        return None, 'база не загрузилась'
    qv = _rag_query_vec_sync(q)
    if not qv:
        return None, 'нет ключа для вектора вопроса'
    # 26.07.2026: тут стояло math.sqrt, а модуль math в bot.py НЕ импортирован — и поиск падал
    # с NameError на первой же строке. Снаружи это выглядело как «бот сказал „Ищу…“ и замолчал»:
    # исключение в фоновом потоке до пользователя не доходит. Возведение в степень 0.5 даёт то же
    # самое и ничего не требует. Нашлось диагностическим эндпоинтом /api/rag_find за один запрос.
    nq = (sum(x * x for x in qv) ** 0.5) or 1.0
    qv = [x / nq for x in qv]
    dim, body, S, ids = _RAGB['dim'], _RAGB['body'], _RAGB['s'], _RAGB['ids']
    лучшее = {}
    if _RAGB.get('быстро'):
        # numpy: одно матричное умножение вместо 14.7 млн шагов в цикле — доли секунды вместо минут.
        # Множитель на вектор уже вшит в матрицу при загрузке, поэтому здесь только скалярное произведение.
        import numpy as _np
        оценки = body.dot(_np.asarray(qv, dtype=_np.float32))
        for i, s in enumerate(оценки):
            cid = ids[i]
            if s > лучшее.get(cid, -2.0):
                лучшее[cid] = float(s)
    else:
        for i in range(_RAGB['n']):
            off = i * dim
            k = S[i]
            s = 0.0
            for j in range(dim):
                s += qv[j] * body[off + j] * k
            cid = ids[i]
            if s > лучшее.get(cid, -2):
                лучшее[cid] = s
    ранж = sorted(лучшее.items(), key=lambda x: -x[1])
    мета = _RAGB.get('мета') or {}

    # ── ВТОРОЙ ПРИЗНАК: прямое совпадение слов ────────────────────────────────────
    # Владелец 27.07.2026: «раг бухари хариджиты» → «Не нашёл 0.470», а слово есть
    # в четырёх хадисах; «пророк слушал музыку» → пять хадисов про «سمعت النبي»
    # («я СЛЫШАЛ Пророка»), потому что вектор зацепился за корень سمع.
    # Причина одна: чистая близость векторов слаба на КОРОТКИХ запросах — слово против
    # длинного хадиса всегда «дальше», чем фраза против фразы. Об этом прямо сказано
    # в калибровке (порог.json): «области перекрылись, нужен второй признак — совпадение слов».
    # Поэтому ищем ещё и буквально: основы слов запроса в русском тексте и в арабском.
    # Русское слово меняет окончание («хариджиты/хариджитов»), поэтому сравниваем по основе.
    def _основы(текст):
        сл = re.findall(r'[а-яёa-z؀-ۿ]{4,}', (текст or '').lower())
        м = []
        for w in сл:
            if w in ('этом', 'этот', 'быть', 'если', 'чего', 'зачем', 'какой', 'какая',
                     'когда', 'нужно', 'можно', 'нельзя', 'делать', 'через'):
                continue
            м.append(w[:max(4, int(len(w) * 0.7))])
        return м

    осн = _основы(q)
    словесно = {}
    if осн:
        # 01.08.2026 (#672): основа искалась ПОДСТРОКОЙ где угодно — и ловила середину чужого
        # слова. Запрос «Пение» даёт основу «пени», а она сидит внутри «стуПЕНИ», и хадис про
        # ступени вставал ВЫШЕ двух настоящих — где погонщик подгонял верблюдов ПЕНИЕМ (№6209,
        # №6891). Требуем совпадение с НАЧАЛОМ слова: окончания русский всё так же меняет
        # («хариджиты/хариджитах» — основа «харидж» ловит оба), а середину слова больше не ловим.
        _рег = [re.compile(r'(?<![а-яёa-z])' + re.escape(о)) for о in осн]
        for cid, c in мета.items():
            текст = ((c.get('r') or '') + ' ' + (c.get('a') or '')).lower()
            если_есть = sum(1 for р in _рег if р.search(текст))
            if если_есть:
                словесно[cid] = если_есть / len(осн)

    # ── ПОРОГ: ЧЕМ КОРОЧЕ ЗАПРОС, ТЕМ СТРОЖЕ (заявка #672, 01.08.2026) ─────────────
    # БЫЛО: `0.521 if слов >= 4 else (0.47 if слов >= 2 else 0.44)` — то есть ОДНОСЛОВНОМУ
    # запросу доставался САМЫЙ МЯГКИЙ порог 0.44. Логика была перевёрнута. Рассуждали так:
    # «короткий вопрос честно даёт меньшую близость, значит и планку ему ниже». Но одно слово
    # даёт не только меньшую, а ещё и самую ШУМНУЮ близость: смысла в векторе почти нет, и
    # наверх лезет что угодно. Скрин владельца («че то очень слабо»): запрос «Пение» вернул
    # хадис про смену киблы с близостью 0.525 — он проходил порог 0.44 с большим запасом.
    #
    # ЗАМЕРЕНО, А НЕ ВЗЯТО НА ГЛАЗ. Прогон на живых запросах: 22 вопроса через рабочий
    # /api/rag_embed (та же модель bge-m3) по этой же базе с Pages. 12 вопросов на темы,
    # которые в Бухари ЕСТЬ («намаз», «закят», «хариджиты», «пить стоя», «пост рамадан»…),
    # и 10 на темы, которых там НЕТ ВОВСЕ («футбол», «космонавт», «биткоин», «интернет»,
    # «ипотека банк», «как настроить вай фай дома») — на них правильный ответ «не нашлось»:
    #     потолок мусора на однословных = 0.541 («самолёт»), 0.536 («космонавт»), 0.525 (кибла)
    #     верные попадания по вектору   = 0.617 («намаз»), 0.608 («молитва»), 0.587 («омовение»)
    #     старая настройка 0.44/0.47/0.521 → нашлось 12/12, но МУСОР вернулся на 9 из 10
    #     новая лестница 0.60/0.55/0.52    → нашлось 12/12, мусор  1 из 10
    # 0.60 выбран потому, что он лежит ВЫШЕ всего измеренного мусора и НИЖЕ настоящих попаданий.
    # Полнота не пострадала ни на одном запросе: слабые по вектору, но верные («закят» 0.460,
    # «хариджиты» 0.470) держатся вторым признаком — совпадением слов, см. ниже.
    слов_в_запросе = len(re.findall(r'\S+', q or ''))
    порог = 0.60 if слов_в_запросе <= 1 else (0.55 if слов_в_запросе <= 3 else 0.52)

    итог = {}
    for cid, s in лучшее.items():
        w = словесно.get(cid, 0.0)
        # словесное совпадение добавляет к близости; полное совпадение слов вытянет
        # хадис наверх, даже если вектор его недооценил
        итог[cid] = s + 0.12 * w
    # Спасение словами (было: `словесно >= 0.5` в обход порога) само стало источником мусора.
    # Основа режется до 4 букв, поэтому «самолёт» → «само» находится в «самому/самого»; а на
    # ОДНОСЛОВНОМ запросе одна такая основа даёт долю 1.0 — то есть полный обход порога по
    # единственному случайному совпадению. Замер показал: именно этим путём проходили
    # «интернет», «самолёт», «игра приставка», «как настроить вай фай дома».
    # Чиним классом: спасение остаётся, но теперь требует ДВУХ вещей сразу —
    #   (а) совпали ПОЧТИ ВСЕ слова запроса (0.75), а не половина;
    #   (б) вектор хотя бы не противоречит: не ниже «порог − 0.20».
    # Замер: мусорных запросов 4 → 1, и при этом НИ ОДНА верная находка не потеряна (12/12).
    ПОЛ_СЛОВ = порог - 0.20
    годные = [(cid, итог[cid], лучшее[cid], словесно.get(cid, 0.0)) for cid in итог
              if лучшее[cid] >= порог
              or (словесно.get(cid, 0.0) >= 0.75 and лучшее[cid] >= ПОЛ_СЛОВ)]
    годные.sort(key=lambda x: -x[1])

    if not годные:
        # ЧЕСТНЫЙ НОЛЬ (#672). Владелец: лучше прямо сказать «не нашлось», чем показать
        # ближайший мусор как ответ. Раньше при пустом результате вторым значением уходило
        # ЧИСЛО (лучшая близость), и в чат прилетало «🧠 Не нашёл: 0.5248» — цифра без смысла.
        # Теперь фраза, а цифры остаются внутри неё для диагностики.
        _лучший = ранж[0][1] if ранж else 0.0
        return None, ('по смыслу ничего не нашлось. Ближайшее совпадение — %d%%, а порог для '
                      'вопроса такой длины — %d%%: чем короче вопрос, тем строже отбор, иначе '
                      'в ответ попадает случайный хадис. Спроси подробнее, своими словами, '
                      'или по-арабски.' % (round(_лучший * 100), round(порог * 100)))

    out = []
    for cid, общ, век, сл in годные[:top]:
        c = мета.get(cid) or {}
        out.append({'s': век, 'w': сл, 'n': c.get('n'), 'g': c.get('g'),
                    'r': c.get('r'), 'a': c.get('a')})
    return out, (ранж[0][1] if ранж else 0)

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

# 🔴 ВЫГОВОР В-56 (06.08.2026). Ветка data ПУБЛИЧНА, а бот сохранял сообщения владельца дословно
# и коммитил их сюда без единой проверки. 28.06.2026 владелец прислал боту свои API-ключи текстом
# — бот записал их заявкой №383 и выложил на всеобщее обозрение. Ключ пролежал открытым 39 дней;
# мини-апп при открытии Кабинета тянет journal.json на устройство КАЖДОГО пользователя.
# Виноват не владелец: прислать ключ своему боту — обычное дело. Виноват код, который вынес его
# наружу. Поэтому проверка ставится не в одном месте приёма, а здесь — в ЕДИНСТВЕННОЙ двери,
# через которую вообще что-либо попадает в публичную ветку (журнал, ошибки, отклики, переписка).
_СЕКРЕТЫ = [
    re.compile(r'\bsk-[A-Za-z0-9_\-]{20,}'),          # OpenAI, OpenRouter, DeepSeek
    re.compile(r'\bgsk_[A-Za-z0-9]{20,}'),            # Groq — тот самый случай
    re.compile(r'\bcsk-[A-Za-z0-9]{20,}'),            # Cerebras
    re.compile(r'\bAIza[A-Za-z0-9_\-]{30,}'),         # Google / Gemini
    re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}'),   # GitHub
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}'),
    re.compile(r'\bhf_[A-Za-z0-9]{20,}'),             # HuggingFace
    re.compile(r'\bxox[baprs]-[A-Za-z0-9\-]{10,}'),   # Slack
    re.compile(r'\b\d{8,10}:AA[A-Za-z0-9_\-]{30,}'),  # токен телеграм-бота
]


def _замазать_секреты(строка):
    """Убрать из текста всё, что похоже на ключ, оставив первые 4 знака для опознания.

    Замазываем именно перед отправкой, а не при приёме: у владельца в его собственном журнале
    пусть остаётся как было, наружу — не уходит. Ложное срабатывание тут дёшево (в журнале
    появится «…СЕКРЕТ-УБРАН»), пропущенный ключ — дорого и необратимо.
    """
    for _об in _СЕКРЕТЫ:
        строка = _об.sub(lambda м: м.group(0)[:4] + '…СЕКРЕТ-УБРАН', строка)
    return строка


def _data_put(path, obj, message):
    """Записать JSON в ветку data."""
    if not GITHUB_TOKEN or not _ensure_data_branch():
        return False
    try:
        content = _замазать_секреты(json.dumps(obj, ensure_ascii=False, indent=1))
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

def _data_atomic_mutate(path, mutate_fn, message, retries=4):
    """ГОНКА ДВУХ RAILWAY-ИНСТАНСОВ (04.07.2026, владелец поймал v962 запощенным 3-4 раза подряд в @muslimoonapp):
    _data_put() читал sha ОДИН раз и писал без ретрая — если параллельный инстанс (redeploy держит старый+новый
    живыми одновременно) успевал закоммитить МЕЖДУ нашим GET и PUT, наш PUT падал 409 (устаревший sha) и МОЛЧА
    терялся (_data_put просто возвращал False, вызывающий код это не проверял) — отметка «уже запощено» не
    сохранялась, следующий тик видел «not posted» и постил СНОВА.
    Фикс: атомарный GET-мутировать-PUT с ретраем НА СВЕЖИХ данных при 409 — mutate_fn получает АКТУАЛЬНОЕ
    состояние (не наш возможно устаревший локальный кэш) и возвращает новое; при конфликте курс. вокруг retries раз."""
    if not GITHUB_TOKEN or not _ensure_data_branch():
        return False, None
    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    h = {"Authorization": f"token {GITHUB_TOKEN}"}
    for _ in range(retries):
        try:
            r = requests.get(api + "?ref=data", headers=h, timeout=8)
            sha = r.json().get("sha", "") if r.status_code == 200 else ""
            obj = json.loads(base64.b64decode(r.json().get("content", "")).decode("utf-8")) if r.status_code == 200 else {}
        except Exception:
            obj, sha = {}, ""
        obj = mutate_fn(obj)
        try:
            content = json.dumps(obj, ensure_ascii=False, indent=1)
            b64 = base64.b64encode(content.encode("utf-8")).decode()
            payload = {"message": message, "content": b64, "branch": "data"}
            if sha:
                payload["sha"] = sha
            rp = requests.put(api, headers=h, json=payload, timeout=12)
            if rp.status_code in (200, 201):
                return True, obj
            if rp.status_code == 409:
                continue
            return False, obj
        except Exception:
            continue
    return False, None

def _channel_claim(note, item_id=None, threshold=0.90):
    """ЕДИНЫЙ атомарный шлюз для ЛЮБОГО из 3 путей постинга в @muslimoonapp (очередь/«анонс»/рестарт-чек).
    04.07.2026: владелец поймал дубли ЧЕТЫРЕ РАЗА подряд (v962×3, v963×3, v965×2), несмотря на ДВА
    предыдущих фикса — потому что те фиксы использовали РАЗНЫЕ, НЕ координирующиеся друг с другом
    механизмы: очередь застолбливала `app_post_ids` СРАЗУ, а `app_post.note` (текст) обновляла только
    ПОСЛЕ медленного сетевого вызова _post_app_channel; «анонс»/рестарт проверяли ТОЛЬКО app_post.note.
    Между «id застолблен» и «app_post.note обновлён» было ОКНО (время самого Telegram-запроса!), в
    которое другой путь видел ещё СТАРЫЙ app_post.note → решал «не дубль» → тоже постил.
    Фикс: ОДНА атомарная GET-мутировать-PUT операция (см. _data_atomic_mutate) для ЛЮБОГО пути —
    проверяет id (если дан) И схожесть note С ОДНИМ И ТЕМ ЖЕ свежим fetch, и если пройдено — СРАЗУ,
    ДО реального поста в Telegram, обновляет И app_post_ids (если id дан), И app_post.note ВМЕСТЕ.
    Любой другой путь, вызвавший это же в ту же секунду, увидит уже обновлённое состояние — окна
    гонки больше нет ни в каком месте между вызовами. Возвращает True, только если ИМЕННО этот вызов
    получил право постить."""
    result = {"ok": False}
    def _mutate(obj):
        obj = obj or {}
        if item_id:
            ids = set(obj.get("app_post_ids") or [])
            if item_id in ids:
                result["ok"] = False
                return obj
        # ROOT-ФИКС дублей (08.07.2026, С58, владелец поймал посты-близнецы 867≡870): сверяем НЕ с ОДНИМ
        # последним постом, а с ОКНОМ последних ~50 (app_post_notes). Старый баг: между «нота A запощена»
        # и «после A запощена B» app_post.note становился B — и любой путь с нотой A (напр. рестарт-чек
        # _setup, читающий update_note.txt) видел sim(A,B)<0.90 → «не дубль» → постил A ПОВТОРНО. Окно закрывает.
        recent = list(obj.get("app_post_notes") or [])
        legacy_last = (obj.get("app_post") or {}).get("note", "")
        if legacy_last and legacy_last not in recent:
            recent.append(legacy_last)
        cand = (note or "").strip()
        for prev in recent:
            if cand and difflib.SequenceMatcher(None, cand, (prev or "").strip()).ratio() >= threshold:
                result["ok"] = False
                return obj
        result["ok"] = True
        obj["app_post"] = {"note": note, "d": datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
        _notes = obj.get("app_post_notes") or []
        _notes.append(note)
        obj["app_post_notes"] = _notes[-50:]
        if item_id:
            ids = set(obj.get("app_post_ids") or [])
            ids.add(item_id)
            obj["app_post_ids"] = list(ids)[-500:]
        return obj
    ok, newobj = _data_atomic_mutate("journal.json", _mutate, f"app_post claim ({item_id or 'note'})")
    if ok and newobj is not None:
        global _journal_cache
        if _journal_cache is not None:
            if "app_post_ids" in newobj: _journal_cache["app_post_ids"] = newobj["app_post_ids"]
            if "app_post" in newobj: _journal_cache["app_post"] = newobj["app_post"]
    return ok and result["ok"]

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
_journal_ok = False   # журнал реально прочитан из ветки data (а не подменён пустышкой при сбое сети)


def _journal_load():
    # 🔴 06.08.2026, С67. Здесь была дыра, стоившая бы всего журнала заявок. `_data_get(...) or {}`
    # превращал СБОЙ ЧТЕНИЯ в пустой словарь, неотличимый от нового журнала. Дальше первый же
    # `_journal_save` записал бы эту пустышку ПОВЕРХ 703 заявок владельца — молча, без ошибки.
    # Отсюда же росла «Заявка №1»: нумерация начиналась заново и была права, потому что ей
    # соврали на входе. Чиним вход, а не следствие.
    # Непрочитанный журнал НЕ кэшируем: следующий вызов честно повторит попытку по сети.
    global _journal_cache, _journal_ok
    if _journal_cache is None:
        _сырое = _data_get("journal.json", None)
        _прочитан = isinstance(_сырое, dict) and bool(_сырое)
        j = _сырое if _прочитан else {}
        j.setdefault("translations", {"totals": {}, "recent": []})
        j.setdefault("usage", {"totals": {"calls": 0, "fresh": 0, "cached": 0, "by_user": {}}, "recent": []})
        j.setdefault("feedback", [])
        j.setdefault("fb_seq", 0)
        j.setdefault("searches", {"total": 0, "top": {}})
        j.setdefault("app", {"opens": 0, "by_user": {}, "by_day": {}})
        j.setdefault("worklog_enabled", False)
        if not _прочитан:
            return j          # не кэшируем и не даём сохранить: лучше потерять инкремент, чем журнал
        _journal_ok = True
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
def req_add(txt, img_flag=False, imgkey="", src="🤖 бот"):
    """Заявка/замечание ВЛАДЕЛЬЦА → нумерованный журнал requests[] (отдельно от пользовательских feedback[]).
    M286: номер ПРОДОЛЖАЕТ сквозной ряд #NNN — берём max(счётчик, максимальный id в журнале), чтобы
    нумерация НИКОГДА не откатывалась к №1 (даже если req_seq потерялся при пересборке журнала).
    M287: src — место приёма заявки («🤖 бот» / «📱 апп»), пишется в запись и показывается в подтверждении."""
    j = _journal_load()
    try:
        _max_id = max((int(r.get("id", 0) or 0) for r in j.get("requests", [])), default=0)
    except Exception:
        _max_id = 0
    j["req_seq"] = max(j.get("req_seq", 0), _max_id) + 1
    rid = j["req_seq"]
    j.setdefault("requests", []).insert(0, {"id": rid, "d": _now_msk(), "src": src,
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
    # Пишем только то, что перед этим реально прочитали. Запись «журнала», которого мы не видели,
    # — это не сохранение, а стирание: один сбой сети мог унести 703 заявки владельца.
    if _journal_cache is not None and _journal_ok:
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

async def log_bot_ai(update, context, feat="ботяра", ai_text=""):
    """Расход ИИ из самого бота (ботяра/группы) → в journal.json + зеркало в LOG-канал.
    Раньше это НЕ логировалось → трата в группах была не видна (ЗАМЕЧАНИЯ #13).
    ai_text: ТРЕВОГА-фикс (владелец, 04.07.2026) — раньше ЖЁСТКО писали «DeepSeek, ключ потрачен» для
    ЛЮБОГО ответа, даже структурного (не ИИ) или отвеченного бесплатной моделью. Теперь тег модели
    берём из реального текста ответа (тот же принцип, что и в _notify_usage())."""
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
        _bmodel = _neuroModelTag(ai_text)
        if ai_text == "structured":
            tag = "🗂 структурный ответ (наши данные, не ИИ — ключ НЕ потрачен)"
        elif _bmodel and ('🆓' in _bmodel or 'бесплатно' in _bmodel.lower()):
            tag = f"🆕 свежий ({_bmodel}, ключ НЕ потрачен)"
        elif _bmodel:
            tag = f"🆕 свежий ({_bmodel})"
        else:
            tag = "🆕 свежий (модель не определена — тег не пришёл; ключ мог и НЕ тратиться)"   # #573: НЕ врать «DeepSeek потрачен» вслепую — владелец справедливо ловил на этом
        await context.bot.send_message(LOG_CHAT_ID,
            f"#ии #ботяра 🤖 {feat}: 👤 {who}{where} — {tag}\n⛔ забанить: `бан {(update.effective_user.id if update.effective_user else '')}`" + (f" · `бан {ch.id}`" if (ch and getattr(ch,'type','')!='private') else ""),
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

def maktaba_search(q, page=1, book=None):
    """ОСНОВНОЙ поиск. Стр.1: сначала адресный запрос по 40 первоисточникам+избранному (наверх),
    затем общий по всей Мактабе. Стр.>1: только общий (первоисточники уже показаны).
    M390в: book = CSV book_id — АДРЕСНЫЙ поиск только по этим книгам (фронт добирает
    недостающие печати первоисточников в номерном поиске; turath book_id принимает список)."""
    try:
        page = max(1, int(page))
    except Exception:
        page = 1
    try:
        cm = _maktaba_catmap_load()
        if book:
            fs = _turath_search(q, page, book)
            items = [_maktaba_item(x, cm) for x in (fs.get("data") or [])]
            return {"count": fs.get("count", 0), "data": items, "page": page, "first_n": len(items)}
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
        # #582/#632/#539/#576 (скрины владельца: «Не удалось загрузить книгу — попробуй позже 🔧» на
        # تهذيب الكمال, الجرح والتعديل, سنن ابن ماجه, اليعقوبي): раньше при любом не-200 возвращался пустой словарь,
        # и фронт показывал одну и ту же безликую фразу — понять, ЧТО именно случилось, было невозможно.
        # Теперь: один повтор (сеть моргнула) + осмысленная причина наружу.
        last = None
        for _try in (1, 2):
            r = requests.get('https://api.turath.io/page', params={'book_id': bid, 'pg': p},
                             headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://app.turath.io/'}, timeout=15)
            last = r
            if r.status_code == 200:
                j = r.json(); meta = j.get('meta')
                if isinstance(meta, str):
                    try: meta = json.loads(meta)
                    except Exception: meta = {}
                txt = j.get('text', '')
                if not (txt or '').strip():
                    return {'text': '', 'meta': meta or {}, 'pg': int(p),
                            'err': 'пустая страница %s в этой книге (возможно, лист вне диапазона)' % p}
                return {'text': txt, 'meta': meta or {}, 'pg': int(p)}
            if r.status_code in (404, 400):
                return {'err': 'книга %s недоступна в библиотеке-источнике (код %s)' % (bid, r.status_code)}
            time.sleep(0.6)
        return {'err': 'источник ответил кодом %s' % (getattr(last, 'status_code', '?'))}
    except Exception as e:
        return {'err': str(e)}
    return {}

# ===== #626: хадис по номеру из ЛЮБОЙ книги Мактабы (не только наших 41) =====
# Владелец: «Книга и номер даны… НО ХАДИС НАДО ВЫДАТЬ!». У turath выдаётся лист по номеру, а
# номера хадисов стоят в самом тексте — значит нужный лист можно найти, не качая книгу целиком.
_АРЦ = '٠١٢٣٤٥٦٧٨٩'
_НОМЕР_ХАДИСА = re.compile(r'(?:^|\n)\s*([٠-٩0-9]{1,6})\s*[-–—]\s')
_ПОТОЛКИ = {}          # book_id → сколько в книге листов (узнаём один раз на процесс)


def _цифры_в_число(с):
    return int(''.join(str(_АРЦ.index(ч)) if ч in _АРЦ else ч for ч in с))


def _в_араб_цифры(н):
    return ''.join(_АРЦ[int(с)] for с in str(н))


def _номера_на_листе(текст):
    """Номера хадисов, стоящие В НАЧАЛЕ строки: «٢٦٧ - حدثنا…». Цифры внутри текста (годы,
    возраст, суммы) не берём — иначе прицел уедет."""
    из = []
    for м in _НОМЕР_ХАДИСА.finditer(текст or ''):
        try:
            из.append(_цифры_в_число(м.group(1)))
        except Exception:
            pass
    return из


def _листов_в_книге(bid):
    """Потолок листов: удвоение с крупного шага, потом уточнение. Считаем один раз на книгу."""
    if bid in _ПОТОЛКИ:
        return _ПОТОЛКИ[bid]
    низ, верх = 1, 2048
    while верх < 300000:
        j = turath_page(bid, верх)
        if j.get('err') or not (j.get('text') or '').strip():
            break
        низ, верх = верх, верх * 2
    while низ + 1 < верх:
        с = (низ + верх) // 2
        j = turath_page(bid, с)
        if j.get('err') or not (j.get('text') or '').strip():
            верх = с
        else:
            низ = с
    _ПОТОЛКИ[bid] = низ
    return низ


def _замер(bid, pg, потолок, счёт, разбег=4):
    """Номера на листе; лист без номеров — заглядываем к соседям (±разбег), а не шагаем вслепую."""
    for сдвиг in [0] + [з for д in range(1, разбег + 1) for з in (д, -д)]:
        p = pg + сдвиг
        if p < 1 or p > потолок or счёт[0] >= 26:
            continue
        счёт[0] += 1
        н = _номера_на_листе((turath_page(bid, p).get('text') or ''))
        if н:
            return p, н
    return None, []


def мактаба_хадис(bid, цель, предел=16):
    """Найти хадис №цель в книге Мактабы. Возвращает (лист, текст хадиса) либо (None, '').

    Отдаём ТОЛЬКО при точном попадании номера на лист. Нет — значит нет (П-43).
    """
    try:
        цель = int(цель)
        потолок = _листов_в_книге(bid)
        if потолок < 2:
            return None, ''
        счёт = [0]
        p1, н1 = _замер(bid, max(2, потолок // 40), потолок, счёт)
        if not н1:
            return None, ''
        плотн = (н1[-1] / p1) if p1 else 1.0
        догадка = min(потолок, max(1, int(цель / (плотн or 1))))
        видел = set()
        while счёт[0] < предел:
            p, н = _замер(bid, догадка, потолок, счёт)
            if not н or p in видел:
                break
            видел.add(p)
            if цель in н:
                текст = turath_page(bid, p).get('text') or ''
                м = re.search(r'(?:^|\n)\s*' + _в_араб_цифры(цель) + r'\s*[-–—]\s', текст)
                кус = текст[м.start():] if м else текст
                сл = _НОМЕР_ХАДИСА.search(кус, 3)
                return p, (кус[:сл.start()] if сл else кус).strip()
            плотн = (н[-1] / p) if p else плотн
            нов = min(потолок, max(1, int(цель / (плотн or 1))))
            шаг = нов - p
            догадка = p + (шаг if abs(шаг) > 2 else (1 if цель > н[-1] else -1))
            if догадка < 1 or догадка > потолок:
                break
        return None, ''
    except Exception:
        return None, ''


# M366: СЕРВЕРНЫЙ БУФЕР-ПРЕДЗАГРУЗКА страниц (принцип оперативки): LRU-кэш + прогрев соседних листов.
# Листание читалки и «Текст + инструменты» отвечают из памяти; НЕ грузим 9000 книг — только то, что читают сейчас.
_PG_CACHE = {}     # (bid, pg) -> результат turath_page
_PG_ORDER = []     # LRU-порядок ключей
_PG_MAX = 900      # ~900 страниц ≈ единицы МБ текста
def _pg_cache_put(k, v):
    try:
        if k in _PG_CACHE:
            try: _PG_ORDER.remove(k)
            except ValueError: pass
        _PG_CACHE[k] = v; _PG_ORDER.append(k)
        while len(_PG_ORDER) > _PG_MAX:
            old = _PG_ORDER.pop(0); _PG_CACHE.pop(old, None)
    except Exception:
        pass
def turath_page_buf(book_id, pg):
    bid = re.sub(r'[^0-9]', '', str(book_id or ''))[:8]
    p = re.sub(r'[^0-9]', '', str(pg or '1'))[:6] or '1'
    if not bid:
        return {}
    k = (bid, int(p))
    hit = _PG_CACHE.get(k)
    res = hit if (hit and hit.get('text')) else turath_page(bid, p)
    if res and res.get('text'):
        _pg_cache_put(k, res)
    def _warm():   # прогрев pg+1, pg+2, pg-1 в фоне (читают вперёд; ошибки молча)
        for d in (1, 2, -1):
            kk = (bid, int(p) + d)
            if kk[1] < 1 or kk in _PG_CACHE:
                continue
            try:
                rr = turath_page(bid, str(kk[1]))
                if rr and rr.get('text'):
                    _pg_cache_put(kk, rr)
            except Exception:
                pass
    try:
        threading.Thread(target=_warm, daemon=True).start()
    except Exception:
        pass
    return res

# TOC: полное оглавление книги (جدول المحتويات) из files.turath.io/books-v3/<id>.json — там indexes.headings
# [{title,level,page}], где page = тот же pg, что у /page (проверено на 1727/1681). Ключи в books-v3
# обфусцированы (арабские огласовки) → ищем список заголовков СТРУКТУРНО (list[dict] с title+page).
# Файл большой (9–11 МБ) → качаем раз, отдаём только headings (десятки КБ), LRU-кэш готовых TOC в памяти.
_TOC_CACHE = {}
_TOC_ORDER = []
def turath_toc(book_id):
    bid = re.sub(r'[^0-9]', '', str(book_id or ''))[:8]
    if not bid:
        return {}
    if bid in _TOC_CACHE:
        return _TOC_CACHE[bid]
    heads = []
    try:
        r = requests.get('https://files.turath.io/books-v3/%s.json' % bid,
                         headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://app.turath.io/'}, timeout=90)
        if r.status_code == 200:
            j = r.json()
            raw = None
            for v in j.values():
                if isinstance(v, dict):
                    for v2 in v.values():
                        if isinstance(v2, list) and v2 and isinstance(v2[0], dict) and 'title' in v2[0] and 'page' in v2[0]:
                            raw = v2
                            break
                if raw:
                    break
            for h in (raw or []):
                try:
                    heads.append({'t': str(h.get('title') or '')[:300],
                                  'l': int(h.get('level') or 1),
                                  'p': int(h.get('page') or 1)})
                except Exception:
                    continue
    except Exception as e:
        return {'err': str(e), 'headings': []}
    res = {'headings': heads}
    if heads:   # пустой результат не кэшируем (мог быть сбой сети)
        _TOC_CACHE[bid] = res
        _TOC_ORDER.append(bid)
        while len(_TOC_ORDER) > 60:
            _TOC_CACHE.pop(_TOC_ORDER.pop(0), None)
    return res

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
    out = ask_neuro((text or "")[:2000], sysm) or ""
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
    async def _notify_usage(user, feat, fresh, src, num, saved, q="", frag="", model=""):
        # зеркалим ВСЮ активность ИИ в рабочий канал-журнал (LOG_CHAT_ID) — и траты, и из базы.
        # M301 (по требованию владельца): кэш-вызовы НЕ глушим — показываем с тем же ПОДРОБНЫМ описанием
        # (что/где/запрос), чтобы видеть активность функции; разница только в метке 🆕 потрачено / ♻️ из базы.
        if not application:
            return
        uid = (user or {}).get("id")
        _nm = ((user or {}).get("first_name", "") + " " + (user or {}).get("last_name", "")).strip()
        _nm = re.sub(r"[*_`\[\]()]", "", _nm)   # #312: чистим Markdown-спецсимволы в имени
        if user and user.get("username"):
            who = (f"{_nm} " if _nm else "") + "@" + user["username"]   # #312: ИМЯ + @username
        elif uid:
            who = f"[{_nm or uid}](tg://user?id={uid})"   # #312: кликабельно — имя (или id) → человек
        else:
            who = "аноним"
        # #414/#420 (повтор-жалоба владельца, скрин 01.07): раньше ЖЁСТКО писали «DeepSeek, ключ потрачен» для
        # ЛЮБОГО свежего ответа — даже когда реально ответил бесплатный Groq/Gemini. Теперь берём модель из ответа.
        if not fresh:
            tag = "♻️ из базы (ключ НЕ потрачен)"
        elif model and ('🆓' in model or 'бесплатно' in model.lower()):
            tag = f"🆕 свежий ({model}, ключ НЕ потрачен)"
        elif model:
            tag = f"🆕 свежий ({model})"
        else:
            tag = "🆕 свежий (модель не определена — тег не пришёл; ключ мог и НЕ тратиться)"   # #573: НЕ врать «DeepSeek потрачен» вслепую — владелец справедливо ловил на этом
        # #272/«ссылка вкладки»: МЕСТО = кликабельная дип-ссылка ровно на карточку хадиса в приложении (m_ для Мухаймина, r_ для остальных)
        if src and num not in (None, ''):
            _sa = ('m_' + str(num)) if src == 'muhaymin' else ('r_' + str(src) + '_' + str(num))
            loc = f" [{src} №{num}](https://t.me/muslimoontt_bot?startapp={_sa})"
            loc_plain = f" {src} №{num}"
        else:
            loc = ""; loc_plain = ""
        if saved and saved.get("new"):
            _what = (": " + saved["what"]) if saved.get("what") else ""
            extra = f" · 📦 накоплено{_what} (в базе всего {saved.get('total', '?')})"
        else:
            extra = ""
        ftag = {"перевод": "#перевод", "нейро": "#нейро", "огласовки": "#огласовки"}.get(feat, "#" + re.sub(r"\s+", "", feat))
        _qs = (" · 🔎 «" + re.sub(r"[*_`\[\]()]", "", str(q))[:70] + "»") if q else ""   # M301: ЗА ЧТО потрачено (текст запроса) · #501: непарный _/* в чужом тексте рвал Markdown-ссылку ВСЕГО сообщения (та же чистка, что уже была у _fr/_nm)
        _fr = (" · 📝 «" + re.sub(r"[*_`\[\]()]", "", str(frag))[:90] + "…»") if frag else ""   # #312: фрагмент потраченного текста
        try:
            await application.bot.send_message(LOG_CHAT_ID, f"#ии {ftag} 🤖 {feat}: {who}{loc} — {tag}{extra}{_qs}{_fr}", parse_mode="Markdown", disable_web_page_preview=True)
        except Exception:
            # B-004 «can't parse entities»: спецсимвол (_ * [ ] ` ) в имени/запросе ломал Markdown → шлём БЕЗ разметки, сообщение НЕ теряем
            try:
                who_plain = ("@" + user["username"]) if (user and user.get("username")) else (str(uid) if uid else "аноним")
                await application.bot.send_message(LOG_CHAT_ID, f"#ии {ftag} {feat}: {who_plain}{loc_plain} — {tag}{extra}{_qs}{_fr}")
            except Exception:
                pass
    async def _notify(text):
        if application:
            try:
                await application.bot.send_message(LOG_CHAT_ID, text)
            except Exception:
                pass

    async def notify_worklog(action, req_id, text, summary="", tokens=None, open_count=None, doing_count=None):
        """#62/#63/#165 (З-13): уведомление владельцу В ЛИЧКУ о работе Claude над заявкой —
        что сделал + логика/суть + сколько осталось невыполнено/в работе + потрачено токенов."""
        if not application:
            return
        j = _journal_load()
        if not j.get("worklog_enabled"):
            return
        if action == "start":
            icon, verb = "🚀", "начал заявку"
        elif action == "finish":
            icon, verb = "✅", "закончил заявку"
        else:  # stop — #62: «слать всякий раз когда остановился»
            icon, verb = "⏸️", "остановился (заявка"
        head = f"{icon} CLAUDE {verb} #{req_id}{')' if action=='stop' else ''} · {_now_msk()}"
        parts = [head]
        if text:
            parts.append((text or '')[:400])
        if summary:  # З-13: логика/суть
            parts.append(f"💡 Суть/логика: {summary[:350]}")
        cnt = []   # #62: остаток заявок
        if open_count is not None:
            cnt.append(f"🔴 невыполнено: {open_count}")
        if doing_count is not None:
            cnt.append(f"🟡 в работе: {doing_count}")
        if cnt:
            parts.append(" · ".join(cnt))
        if tokens:  # #63: потраченные токены
            parts.append(f"🧮 токенов потрачено: {tokens}")
        msg = "\n".join(parts)
        # #62: ВЛАДЕЛЬЦУ В ЛИЧКУ (OWNER_ID) + копия в рабочий журнал (LOG_CHAT_ID)
        for chat in (OWNER_ID, LOG_CHAT_ID):
            try:
                await application.bot.send_message(chat, msg, disable_web_page_preview=True)
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

    async def health(r): return _cors(web.json_response({'ok': True, 'ai': {'groq': bool(GROQ_API_KEY), 'gemini': bool(GEMINI_API_KEY), 'openrouter': bool(OPENROUTER_API_KEY), 'deepseek': bool(DEEPSEEK_API_KEY), 'nvidia_nim': bool(NVIDIA_NIM_API_KEY)}}))   # индикатор какие ИИ-ключи в env (без значений; диагностик-вызовы ИИ убраны — риск абуза)
    async def nvidia_test(r):
        """#NVIDIA-NIM-05.07: живая диагностика без раскрытия ключа — пройден/нет + модель + ЗАГОЛОВКИ ЛИМИТОВ + список доступных моделей."""
        if not NVIDIA_NIM_API_KEY:
            return _cors(web.json_response({'ok': False, 'error': 'NVIDIA_NIM_API_KEY не задан в Railway env'}))
        out = {}
        try:
            t0 = time.time()
            msgs = [{"role": "system", "content": "Ты тестовый ассистент."}, {"role": "user", "content": "ответь одним словом: тест"}]
            rr = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {NVIDIA_NIM_API_KEY}", "Content-Type": "application/json"},
                json={"model": NVIDIA_NIM_MODEL, "messages": msgs, "max_tokens": 20, "temperature": 0.3},
                timeout=60)
            dt = round(time.time() - t0, 2)
            ok = rr.status_code == 200
            reply = rr.json()["choices"][0]["message"]["content"].strip() if ok else rr.text[:300]
            # заголовки лимитов (стандарт OpenAI-совместимых API — не все провайдеры их шлют)
            rl = {k: v for k, v in rr.headers.items() if 'ratelimit' in k.lower() or 'remaining' in k.lower() or 'limit' in k.lower()}
            out.update({'ok': ok, 'model': NVIDIA_NIM_MODEL, 'seconds': dt, 'reply': str(reply)[:300], 'rate_limit_headers': rl})
        except Exception as e:
            out['ok'] = False
            out['error'] = str(e)[:300]
        try:
            mr = requests.get("https://integrate.api.nvidia.com/v1/models",
                               headers={"Authorization": f"Bearer {NVIDIA_NIM_API_KEY}"}, timeout=20)
            if mr.status_code == 200:
                ids = [m.get('id') for m in mr.json().get('data', [])]
                out['models_available_count'] = len(ids)
                out['models_sample'] = ids[:30]
            else:
                out['models_error'] = f"{mr.status_code}: {mr.text[:200]}"
        except Exception as e:
            out['models_error'] = str(e)[:200]
        # #NVIDIA-multi-05.07 (владелец: «странно если доступна только 1 модель») — реально пробуем разные модели каталога
        _sample_models = ["meta/llama-3.1-70b-instruct", "meta/llama-3.1-405b-instruct", "meta/codellama-70b",
                           "google/gemma-2-2b-it", "deepseek-ai/deepseek-coder-6.7b-instruct", "mistralai/mixtral-8x7b-instruct-v0.1",
                           "microsoft/phi-3-mini-4k-instruct", "qwen/qwen2.5-7b-instruct", "nvidia/nemotron-4-340b-instruct",
                           "ibm/granite-3.0-8b-instruct"]
        multi = []
        for m in _sample_models:
            try:
                t1 = time.time()
                rr2 = requests.post("https://integrate.api.nvidia.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {NVIDIA_NIM_API_KEY}", "Content-Type": "application/json"},
                    json={"model": m, "messages": [{"role": "user", "content": "тест"}], "max_tokens": 10}, timeout=30)
                multi.append({'model': m, 'ok': rr2.status_code == 200, 'code': rr2.status_code,
                              'seconds': round(time.time() - t1, 2), 'err': (rr2.text[:120] if rr2.status_code != 200 else '')})
            except Exception as e:
                multi.append({'model': m, 'ok': False, 'code': None, 'err': str(e)[:120]})
        out['multi_model_test'] = multi
        return _cors(web.json_response(out))
    async def gpt_test(r):
        """#GPT-05.07 (владелец: «проверь боевой OPENAI_API_KEY в Railway Muslimoon, деньги были»): живая диагностика без раскрытия ключа."""
        if not OPENAI_API_KEY:
            return _cors(web.json_response({'ok': False, 'error': 'OPENAI_API_KEY не задан в Railway env'}))
        try:
            t0 = time.time()
            resp = ask_gpt("ответь одним словом: тест", "Ты тестовый ассистент.", max_tokens=20)
            dt = round(time.time() - t0, 2)
            ok = bool(resp) and not str(resp).startswith("⚠️")
            return _cors(web.json_response({'ok': ok, 'model': OPENAI_MODEL, 'seconds': dt, 'reply': str(resp)[:300]}))
        except Exception as e:
            return _cors(web.json_response({'ok': False, 'error': str(e)[:300]}))
    async def ochered(r):
        """Очередь «владелец зовёт технадзора» — забрать и пометить разобранным.

        Владелец 05.08.2026: «можешь построить оперативный канал, чтобы я через DSOC обращался
        и ты мог оперативно реагировать? Вот я например жду сейчас тут». Раньше он писал в
        чат, а я узнавал об этом случайно и с опозданием — то есть канала не было вовсе, была
        удача."""
        if not application or not BACKUP_SECRET:
            return _cors(web.json_response({'error': 'disabled'}, status=503))
        try:
            body = await r.json()
        except Exception:
            body = {}
        if str(body.get('secret', '')).strip() != (BACKUP_SECRET or '').strip():
            return _cors(web.json_response({'error': 'auth'}, status=403))
        сп = _data_get(DSOC_ОЧЕРЕДЬ_ФАЙЛ, []) or []
        готово = body.get('готово')
        if готово is not None:
            for з in сп:
                if int(з.get('n') or 0) == int(готово):
                    з['взято'] = True
            _data_put(DSOC_ОЧЕРЕДЬ_ФАЙЛ, сп[-60:], 'очередь технадзора: #%s разобрано' % готово)
            return _cors(web.json_response({'ok': True}))
        return _cors(web.json_response({'ok': True,
                                        'новые': [з for з in сп if not з.get('взято')]}))

    async def fayl(r):
        """Отдать текст файлом в чат — тем же ходом, что и помощник."""
        if not application or not BACKUP_SECRET:
            return _cors(web.json_response({'error': 'disabled'}, status=503))
        try:
            body = await r.json()
        except Exception:
            return _cors(web.json_response({'error': 'bad_json'}, status=400))
        if str(body.get('secret', '')).strip() != (BACKUP_SECRET or '').strip():
            return _cors(web.json_response({'error': 'auth'}, status=403))
        текст = str(body.get('текст', ''))
        имя = str(body.get('имя') or 'file.md')
        if not текст.strip():
            return _cors(web.json_response({'error': 'нужен текст'}, status=400))
        _ч = body.get('чат')
        чат = _ч if isinstance(_ч, str) and _ч.startswith('@') else int(_ч or LOG_CHAT_ID)
        ок, беда = await отправить_файлом(application.bot, чат, имя, текст,
                                          str(body.get('подпись') or ''),
                                          int(body['ответ_на']) if body.get('ответ_на') else None)
        return _cors(web.json_response({'ok': ок, 'error': беда}))

    async def oc_balans(r):
        """Остаток на счёте OpenCode — по данным самого OpenCode, а не нашего журнала.

        Владелец 05.08.2026: «ты должен иметь доступ к остаткам баланса OpenCode». Он прав:
        наш журнал знает лишь то, что потратили МЫ; о деньгах на счёте он не знает ничего —
        владелец мог пополнить, могла списаться подписка. Спрашивать надо у источника."""
        if not BACKUP_SECRET:
            return _cors(web.json_response({'error': 'disabled'}, status=503))
        try:
            body = await r.json()
        except Exception:
            body = {}
        if str(body.get('secret', '')).strip() != (BACKUP_SECRET or '').strip():
            return _cors(web.json_response({'error': 'auth'}, status=403))
        итог = {'ok': True, 'по_нашему_журналу': None, 'у_провайдера': None}
        try:
            сп = _data_get(DSOC_ФАЙЛ_ТРАТ, []) or []
            итог['по_нашему_журналу'] = {
                'вызовов': len(сп), 'потрачено': round(sum(float(x[1]) for x in сп), 6)}
        except Exception:
            pass
        # У OpenCode нет описанного эндпоинта баланса; пробуем известные и честно говорим, что
        # ответил каждый — гадать о деньгах нельзя.
        попытки = {}
        for адрес in ('https://opencode.ai/zen/go/v1/balance',
                      'https://opencode.ai/zen/v1/balance',
                      'https://opencode.ai/api/billing/balance'):
            try:
                о = requests.get(адрес, timeout=25,
                                 headers={'Authorization': 'Bearer ' + (OPENCODE_KEY or '')})
                попытки[адрес] = {'код': о.status_code, 'ответ': о.text[:200]}
                if о.status_code == 200:
                    итог['у_провайдера'] = о.text[:400]
                    break
            except Exception as e:
                попытки[адрес] = {'ошибка': str(e)[:120]}
        итог['попытки'] = попытки
        return _cors(web.json_response(итог))

    async def golos(r):
        """Озвучить текст и отправить в чат. Нужен мне, чтобы ПРОВЕРЯТЬ озвучку живьём, а не
        докладывать «починил» вслепую — сегодня я на этом обжёгся трижды."""
        if not application or not BACKUP_SECRET:
            return _cors(web.json_response({'error': 'disabled'}, status=503))
        try:
            body = await r.json()
        except Exception:
            return _cors(web.json_response({'error': 'bad_json'}, status=400))
        if str(body.get('secret', '')).strip() != (BACKUP_SECRET or '').strip():
            return _cors(web.json_response({'error': 'auth'}, status=403))
        текст = str(body.get('текст', '')).strip()
        чат = int(body.get('чат') or LOG_CHAT_ID)
        ответ_на = body.get('ответ_на')
        # 🔴 Проверка «нужен текст» стояла ВЫШЕ ветки с аятом — и просьба прочитать аят
        # отвергалась, хотя текста там и не должно быть. Порядок проверок оказался важнее их
        # содержания: сначала разбираем, ЧТО просят, потом требуем нужное для этого.
        _аят = str(body.get('аят') or '').strip()
        if not текст and not _аят:
            return _cors(web.json_response({'error': 'нужен текст или аят'}, status=400))
        # Просят аят — отдаём запись настоящего чтеца, а не синтез.
        if _аят and ':' in _аят:
            try:
                _с, _а = _аят.split(':')[:2]
                ок, что = await отправить_аят(application.bot, чат, int(_с), int(_а),
                                              str(body.get('чтец') or 'alafasy'),
                                              int(ответ_на) if ответ_на else None)
                return _cors(web.json_response({'ok': ок, 'чтец': что}))
            except Exception as e:
                return _cors(web.json_response({'ok': False, 'error': str(e)[:250]}))
        путь = os.path.join("/tmp", "golos_api_%d.mp3" % int(time.time()))
        try:
            if not await озвучить(текст, путь, str(body.get("голос") or "") or None):
                return _cors(web.json_response(
                    {'ok': False, 'error': 'озвучка не собралась: ни edge-tts, ни gTTS'}))
            _г = str(body.get('голос') or '') or ГОЛОСА.get(_язык_текста(текст), ГОЛОСА['ru'])
            ок, замечание = await отправить_звук(
                application.bot, чат, путь, int(ответ_на) if ответ_на else None,
                подпись=str(body.get('подпись') or
                            ('🔊 озвучено синтезом · голос <b>%s</b>' % _г)))
            # Возвращаем, КАКИМ голосом озвучено: 05.08.2026 владелец сказал «это одинаковые
            # голоса», и он был прав — образцы ушли раньше выкатки. Доказывать различие надо
            # фактом, а не уверением.
            return _cors(web.json_response({'ok': ок, 'замечание': замечание,
                                            'голос': (str(body.get('голос') or '')
                                                      or 'по умолчанию')}))
        except Exception as e:
            return _cors(web.json_response({'ok': False, 'error': str(e)[:300]}))
        finally:
            try:
                os.remove(путь)
            except Exception:
                pass

    async def skazat(r):
        """Сказать в конкретный чат, при желании — ответом на конкретное сообщение.
        Понадобилось четвёртый раз за день; каждый раз приспосабливать чужой эндпоинт —
        плодить сущности там, где нужна одна честная (З-33)."""
        if not application or not BACKUP_SECRET:
            return _cors(web.json_response({'error': 'disabled'}, status=503))
        try:
            body = await r.json()
        except Exception:
            return _cors(web.json_response({'error': 'bad_json'}, status=400))
        if str(body.get('secret', '')).strip() != (BACKUP_SECRET or '').strip():
            return _cors(web.json_response({'error': 'auth'}, status=403))
        текст = str(body.get('текст', '')).strip()
        # Чат может быть и числом, и @именем канала: Telegram принимает оба, а раньше мы
        # насильно приводили к числу — и написать в канал по имени было нельзя вовсе.
        _ч = body.get('чат')
        чат = _ч if isinstance(_ч, str) and _ч.strip().startswith('@') else int(_ч or LOG_CHAT_ID)
        ответ_на = body.get('ответ_на')
        if not текст:
            return _cors(web.json_response({'error': 'нужен текст'}, status=400))
        try:
            м = await application.bot.send_message(
                чат, текст[:4000], parse_mode='HTML', disable_web_page_preview=True,
                reply_to_message_id=int(ответ_на) if ответ_на else None)
            return _cors(web.json_response({'ok': True, 'пост': getattr(м, 'message_id', None)}))
        except Exception as e:
            # 🔴 05.08.2026: повторяли при ЛЮБОЙ ошибке — и один ответ ушёл владельцу дважды
            # (посты 725412 и 725413). Повтор уместен, только если Telegram отверг именно
            # разметку; всё прочее могло случиться уже ПОСЛЕ отправки, и тогда повтор — дубль.
            if 'parse' not in str(e).lower() and 'entities' not in str(e).lower():
                return _cors(web.json_response({'ok': False, 'error': str(e)[:250]}, status=500))
            try:
                м = await application.bot.send_message(
                    чат, re.sub(r'<[^>]+>', '', текст)[:4000],
                    reply_to_message_id=int(ответ_на) if ответ_на else None)
                return _cors(web.json_response({'ok': True, 'пост': getattr(м, 'message_id', None),
                                                'разметка': 'снята: ' + str(e)[:120]}))
            except Exception as e2:
                return _cors(web.json_response({'ok': False, 'error': str(e2)[:250]}, status=500))

    async def upd_post(r):
        """ЗАКОН ОБ ИСПРАВЛЕНИИ (владелец 05.08.2026). Ошиблись в опубликованном посте — не
        правим тихо: дописываем UPD, ЗАЧЁРКИВАЕМ неверную фразу и отдельным сообщением-ответом
        объявляем неточность. Тихая правка выглядит так, будто ошибки не было, — а её видели
        люди, и это обман задним числом."""
        if not application or not BACKUP_SECRET:
            return _cors(web.json_response({'error': 'disabled'}, status=503))
        try:
            body = await r.json()
        except Exception:
            return _cors(web.json_response({'error': 'bad_json'}, status=400))
        if str(body.get('secret', '')).strip() != (BACKUP_SECRET or '').strip():
            return _cors(web.json_response({'error': 'auth'}, status=403))
        мид = int(body.get('пост') or 0)
        неверно = str(body.get('неверно', '')).strip()
        upd = str(body.get('upd', '')).strip()
        куда = int(body.get('чат') or APP_CHANNEL_ID)
        если_текст = str(body.get('текст', '')).strip()      # полный текст поста, если знаем
        if not мид or not upd:
            return _cors(web.json_response({'error': 'нужны пост и upd'}, status=400))
        итог = {'ok': True, 'пост': мид}
        if если_текст:
            новый = если_текст
            if неверно and неверно in новый:
                новый = новый.replace(неверно, '<s>' + неверно + '</s>', 1)
            новый += ('\n\n<b>UPD ' + _now_msk() + '</b>\n' + upd)
            try:
                await application.bot.edit_message_text(chat_id=куда, message_id=мид,
                                                        text=новый[:4000], parse_mode='HTML',
                                                        disable_web_page_preview=True)
                итог['правка'] = 'да'
            except Exception as e:
                итог['правка'] = str(e)[:200]
        try:
            м = await application.bot.send_message(
                куда, '✏️ <b>УТОЧНЕНИЕ к посту выше</b>\n\n' + upd,
                parse_mode='HTML', reply_to_message_id=мид, disable_web_page_preview=True)
            итог['уточнение'] = getattr(м, 'message_id', None)
        except Exception as e:
            итог['уточнение_ошибка'] = str(e)[:200]
        return _cors(web.json_response(итог))

    async def vygovor_put(r):
        """Выговор помощнику — в ЕГО журнал. Он держит их в системном промте всегда:
        выговор, который не перечитываешь, повторяется."""
        if not application or not BACKUP_SECRET:
            return _cors(web.json_response({'error': 'disabled'}, status=503))
        try:
            body = await r.json()
        except Exception:
            return _cors(web.json_response({'error': 'bad_json'}, status=400))
        if str(body.get('secret', '')).strip() != (BACKUP_SECRET or '').strip():
            return _cors(web.json_response({'error': 'auth'}, status=403))
        текст = str(body.get('текст', '')).strip()
        if not текст:
            return _cors(web.json_response({'error': 'нужен текст'}, status=400))
        сп = _data_get(DSOC_ВЫГОВОРЫ_ФАЙЛ, []) or []
        ид = len(сп) + 1
        сп.append({'n': ид, 'd': _now_msk(), 't': текст[:600]})
        _data_put(DSOC_ВЫГОВОРЫ_ФАЙЛ, сп[-40:], 'выговор помощнику #%d' % ид)
        try:
            await application.bot.send_message(
                LOG_CHAT_ID, '⚠️ <b>ВЫГОВОР ПОМОЩНИКУ №%d</b>\n%s' % (ид, текст[:900]),
                parse_mode='HTML')
        except Exception:
            pass
        return _cors(web.json_response({'ok': True, 'номер': ид, 'всего': len(сп)}))

    async def polka_put(r):
        """Положить запись на полку: и постом в рабочий журнал (для глаз владельца), и в
        ветку data (для рук помощника). Авторизация тем же BACKUP_SECRET — токен бота
        наружу не выдаётся."""
        if not application:
            return _cors(web.json_response({'error': 'no_app'}, status=503))
        if not BACKUP_SECRET:
            return _cors(web.json_response({'error': 'disabled'}, status=503))
        try:
            body = await r.json()
        except Exception:
            return _cors(web.json_response({'error': 'bad_json'}, status=400))
        if str(body.get('secret', '')).strip() != (BACKUP_SECRET or '').strip():
            return _cors(web.json_response({'error': 'auth'}, status=403))
        метка = str(body.get('метка', '')).strip().upper()
        заголовок = str(body.get('заголовок', '')).strip()
        текст = str(body.get('текст', '')).strip()
        if not метка or not текст:
            return _cors(web.json_response({'error': 'нужны метка и текст'}, status=400))
        try:
            п = _data_get(DSOC_ПОЛКА_ФАЙЛ, {}) or {}
            п[метка] = {'заголовок': заголовок, 'текст': текст[:20000], 'когда': _now_msk()}
            _data_put(DSOC_ПОЛКА_ФАЙЛ, п, 'полка: ' + метка)
        except Exception as e:
            return _cors(web.json_response({'ok': False, 'error': str(e)[:300]}, status=500))
        мид = None
        try:
            пост = ('📚 <b>%s</b> — %s\n\n%s' % (метка, заголовок, текст[:3300]))
            м = await application.bot.send_message(LOG_CHAT_ID, пост, parse_mode='HTML',
                                                  disable_web_page_preview=True)
            мид = getattr(м, 'message_id', None)
        except Exception:
            try:
                м = await application.bot.send_message(
                    LOG_CHAT_ID, '📚 %s — %s\n\n%s' % (метка, заголовок, текст[:3300]))
                мид = getattr(м, 'message_id', None)
            except Exception:
                pass
        return _cors(web.json_response({'ok': True, 'метка': метка, 'пост': мид,
                                        'на_полке': len(_data_get(DSOC_ПОЛКА_ФАЙЛ, {}) or {})}))

    async def claude_notify(r):
        """#claude-notify-05.07 (владелец: «мне не важно как, просто скинь мне в личку то, что я попросил»):
        Клод шлёт себе сообщение в личку владельца через бота — токен НЕ передаётся Клоду, он остаётся
        внутри Railway; авторизация тем же BACKUP_SECRET, что и /api/backup_push."""
        if not application:
            return _cors(web.json_response({'error': 'no_app'}, status=503))
        if not BACKUP_SECRET:
            return _cors(web.json_response({'error': 'disabled', 'message': 'BACKUP_SECRET не задан в env Railway'}, status=503))
        try:
            body = await r.json()
        except Exception:
            return _cors(web.json_response({'error': 'bad_json'}, status=400))
        secret = str(body.get('secret', '')).strip()
        text = str(body.get('text', '')).strip()
        if not secret or secret != (BACKUP_SECRET or '').strip():
            return _cors(web.json_response({'error': 'auth'}, status=403))
        # режим «в_чат»: ответить реплаем на последний «раг» владельца — там, где он спрашивал
        if body.get('в_чат'):
            # «на_вопрос»: кусок текста вопроса — ответим именно на него, а не на последний
            _цель = dict(_ПОСЛ_РАГ)
            _иск = str(body.get('на_вопрос', '') or '').strip().lower()
            if _иск:
                for _з in reversed(_ЛЕНТА_РАГ):
                    if _иск in (_з.get('вопрос') or '').lower():
                        _цель = _з
                        break
            if not _цель.get('chat'):
                return _cors(web.json_response({'ok': False, 'error': 'бот ещё не видел ни одного «раг» после перезапуска'}))
            try:
                await application.bot.send_message(
                    _цель['chat'], text[:3900],
                    reply_to_message_id=_цель['msg'], disable_web_page_preview=True)
                return _cors(web.json_response({'ok': True, 'sent': 'в_чат', 'chat': _цель['chat'],
                                                'на_вопрос': _цель['вопрос']}))
            except Exception as e:
                return _cors(web.json_response({'ok': False, 'error': str(e)[:300]}), status=500)
        b64 = str(body.get('file_b64', '') or '')
        fname = str(body.get('filename', 'файл.md') or 'файл.md')
        caption = str(body.get('caption', '') or '')
        if b64:
            try:
                import io as _io
                data = base64.b64decode(b64)
                bio = _io.BytesIO(data); bio.name = fname
                await application.bot.send_document(OWNER_ID, document=bio, filename=fname, caption=("🤖 #клод_сказал\n" + caption)[:1024] if caption else None)
                return _cors(web.json_response({'ok': True, 'sent': 'file', 'size': len(data)}))
            except Exception as e:
                return _cors(web.json_response({'ok': False, 'error': str(e)[:300]}), status=500)
        if not text:
            return _cors(web.json_response({'error': 'no_text'}, status=400))
        # ── #634/#638/#639/#640/#642: «СМЕНА ДОСТУПНОСТИ API» БОЛЬШЕ НЕ ХОДИТ В ЛИЧКУ ──────────
        # Что было: сторож (scratch_marathon/api_availability_notify.py, Планировщик каждые 15 мин)
        # слал владельцу отчёт при КАЖДОМ переходе провайдера доступен↔нет. За сутки 24.07 он
        # прислал их столько, что владелец завёл пять заявок подряд: «я же просил — это смена
        # доступности [бесполезна]», «срочно отключи проверку, она исчерпывает лимиты».
        # Почему гейт стоит ЗДЕСЬ, в боте: сторожей, которые могут постучаться в /api/claude_notify,
        # много (и они переживают редеплой), а дверь в личку владельца одна — закрываем класс,
        # а не отдельный скрипт (З-40). Сам сторож всё равно надо снять с Планировщика: этот
        # гейт гасит ШУМ, но не прекращает опрос провайдеров.
        _низ_ув = text.lower()
        if ('смена доступности' in _низ_ув) or ('#сменадоступности' in _низ_ув):
            _ПОДАВЛЕНО['доступность'] = _ПОДАВЛЕНО.get('доступность', 0) + 1
            return _cors(web.json_response({
                'ok': False, 'подавлено': 'сводки «смена доступности API» владелец отключил '
                                          '(заявки #639/#640/#642) — сними сторож с Планировщика',
                'подавлено_с_перезапуска': _ПОДАВЛЕНО['доступность']}))
        try:
            await application.bot.send_message(OWNER_ID, ("🤖 #клод_сказал\n" + text)[:4000])
            return _cors(web.json_response({'ok': True}))
        except Exception as e:
            return _cors(web.json_response({'ok': False, 'error': str(e)[:300]}), status=500)

    async def send_poll_api(r):
        """#опросы-13.07 (владелец: пакеты решений опросами в личку, «свой вариант» кнопкой; результаты в data)."""
        if not application: return _cors(web.json_response({'error': 'no_app'}, status=503))
        try: body = await r.json()
        except Exception: return _cors(web.json_response({'error': 'bad_json'}, status=400))
        if str(body.get('secret','')).strip() != (BACKUP_SECRET or '').strip():
            return _cors(web.json_response({'error': 'auth'}, status=403))
        q = str(body.get('question',''))[:290]
        opts = [str(o)[:95] for o in (body.get('options') or [])][:9]
        ref = str(body.get('ref',''))[:60]
        if not q or len(opts) < 2: return _cors(web.json_response({'error': 'need question+2options'}, status=400))
        opts = opts + ['✍️ Свой вариант (отвечу сообщением)']
        try:
            msg = await application.bot.send_poll(OWNER_ID, q, opts, is_anonymous=False, allows_multiple_answers=False)
            pid = msg.poll.id
            pm = _data_get('poll_map.json', {}) or {}
            pm[pid] = {'ref': ref, 'q': q[:120], 'opts': opts, 'ts': _now_msk(), 'msg_id': msg.message_id}
            _data_put('poll_map.json', pm, 'опрос ' + (ref or pid))
            return _cors(web.json_response({'ok': True, 'poll_id': pid}))
        except Exception as e:
            return _cors(web.json_response({'ok': False, 'error': str(e)[:300]}), status=500)
    async def opt(r): return _cors(web.Response(text=''))
    async def worklog(r):
        # #62/#63/#165: триггер уведомления владельцу о работе Claude над заявкой (Claude дёргает curl).
        d = await _body(r)
        action = (d.get('action') or '').lower()
        if action not in ('start', 'finish', 'stop'):
            return _cors(web.json_response({'error': 'invalid_action'}, status=400))
        try: req_id = int(d.get('req_id'))
        except Exception: return _cors(web.json_response({'error': 'invalid_req_id'}, status=400))
        if not rate_ok('worklog:global', limit=30, window=3600):   # #165-фикс: глобальный бакет — раньше ключ включал req_id, спам обходился перебором req_id
            return _ratelimited()
        text = (d.get('text') or '').strip()[:500]
        summary = (d.get('summary') or '').strip()[:400]
        tokens = d.get('tokens')
        oc = d.get('open_count'); dc = d.get('doing_count')
        try: oc = int(oc) if oc is not None else None
        except Exception: oc = None
        try: dc = int(dc) if dc is not None else None
        except Exception: dc = None
        try: await notify_worklog(action, req_id, text, summary, tokens, oc, dc)
        except Exception as e: return _cors(web.json_response({'error': str(e)[:120]}, status=500))
        return _cors(web.json_response({'ok': True}))

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

    async def assistant(r):
        # #214 (ПРАВИЛО владельца): помощник по проекту — ИИ-ответ по Корану/Сунне с незыблемыми правилами + самообучение (кэш ответов)
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('assistant')
        if not rate_ok('assistant:' + _uid(user, r), 8, 120):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q:
            return _q
        try:
            q = (d.get('q') or '').strip()[:600]
            if len(q) < 2:
                return _cors(web.json_response({'answer': '', 'cached': False}))
            # ВЫГОВОР 02.07.2026 (владелец сам проверил встроенного «Помощника»): «найди в мухэймине хадис «...»»
            # → ИИ БЕЗ проверки реальных данных сочинил номера «Муслим 2199»/«Абу Дауд 5122» (галлюцинация,
            # тот же класс, что уже чинил в чате @jamaat_ru). ЗДЕСЬ ТОЖЕ — честный текстовый поиск по muhaymin.json
            # ВМЕСТО ask_ai для вопросов конкретно про Мухэймин (остальные вопросы — по-прежнему через ИИ, полный
            # RAG на ВСЮ базу — отдельный больший проект, Ассистент_Муслимун/rag/, ещё не подключён к продакшну).
            if parse_muhaymin_check(q):
                qm = re.search(r'[«"]([^«»"]{10,})[»"]', q)
                hadith_src = qm.group(1) if qm else q
                m_ans = await muhaymin_check_reply_text(hadith_src)
                await loop.run_in_executor(None, usage_log, user, "помощник (мухэймин, без ИИ)", True, len(q), "", "")
                return _cors(web.json_response({'answer': m_ans, 'cached': False}))
            akey = 'assist|' + q.lower()
            cached = await loop.run_in_executor(None, neuro_get, akey)
            if cached and isinstance(cached, dict) and cached.get('answer'):
                await _notify_usage(user, "помощник", False, "", "", None, q=q)
                out = dict(cached)
                out['cached'] = True
                return _cors(web.json_response(out))
            sysp = (
                "Ты — помощник исламского приложения Muslimoon (Коран и достоверная Сунна по первоисточникам). "
                "Отвечай ТОЛЬКО на русском, ясно и по делу.\n"
                "НЕЗЫБЛЕМЫЕ ПРАВИЛА:\n"
                "1) Опирайся на Коран и Сунну (Бухари, Муслим, Абу Дауд, Тирмизи, Насаи, Ибн Маджа, Малик, Ахмад и др.).\n"
                "2) Приводя хадис/аят — указывай источник (сборник+номер или сура:аят). Номер давай ТОЛЬКО при уверенности, не выдумывай.\n"
                "3) Не выдумывай хадисы и факты. Не знаешь — честно скажи и предложи уточнить у учёных.\n"
                "4) Не выноси собственных фетв и оценок достоверности — это дело учёных; мнения учёных передавай как мнения.\n"
                "5) Тон уважительный; без политики, оскорблений и разжигания.\n"
                "Если уместно, в конце подскажи, что искать в приложении (слово/номер/тему)."
            )
            ans = await loop.run_in_executor(None, ask_ai, q, sysp, False, 900)
            _asModel = _neuroModelTag(ans or '')
            ans = re.sub(r'\s*[⚡💎].*$', '', (ans or ''), flags=re.S).strip()
            out = {'answer': ans, 'cached': False}
            if ans and ans[0] not in '⚠❌⏸':
                await loop.run_in_executor(None, neuro_put, akey, out)
            await loop.run_in_executor(None, usage_log, user, "помощник", True, len(q), "", "")
            await _notify_usage(user, "помощник", True, "", "", None, q=q, model=_asModel)   # #421-класс: раньше ВСЕГДА логировался как fresh=False — трата ИИ была невидима в учёте
            return _cors(web.json_response(out))
        except Exception as e:
            return _cors(web.json_response({'answer': '', 'error': str(e)[:120]}))

    async def groupai(r):
        # #236: app-рубильник ИИ-«ботяра» в группах (ТОЛЬКО владелец). POST {set:bool} вкл/выкл; без set — текущее состояние.
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not (user and str(user.get('id')) == str(OWNER_ID)):
            return _deny('groupai')
        global _GROUP_AI_OFF
        if isinstance(d.get('set'), bool):
            _GROUP_AI_OFF = (not d['set']); _save_ai_gate()   # ФИКС: персист — переживёт рестарт/деплой
        return _cors(web.json_response({'on': (not _GROUP_AI_OFF)}))

    def _neuroResultFrag(res):
        # #502 (владелец: «в логе нейро не указан результат»): короткая сводка, ЧТО реально подобрал ИИ — раньше
        # в журнал шёл только запрос (q), сам ответ был не виден.
        if not res: return ""
        parts = list((res.get('hadiths') or [])[:2]) + list((res.get('phrases') or [])[:2]) + list((res.get('quran') or [])[:1])
        return ' · '.join(str(p) for p in parts if p)[:150]

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
                await _notify_usage(user, "нейро", False, "", "", None, q=meaning, frag=_neuroResultFrag(cached))   # #502: в журнале теперь виден и РЕЗУЛЬТАТ, не только запрос
                out = dict(cached); out['cached'] = True
                return _cors(web.json_response(out))
            # 2) УМНЫЙ ИИ-поиск: понять смысл (исправить опечатки), дать НОМЕР аята и/или характерную арабскую фразу
            sysm = ("Ты — умный поиск по Корану и хадисам. Запрос на русском (ВОЗМОЖНЫ ОПЕЧАТКИ) описывает аят/хадис "
                    "ПО СМЫСЛУ, либо это транскрипция арабского слова. Пойми, ЧТО хочет человек (мысленно исправь "
                    "опечатки), и ответь СТРОГО 5 строками (метки именно так):\n"
                    "АЯТЫ: <номера сура:аят через запятую, если запрос про конкретный аят/историю Корана; иначе ->\n"
                    "ХАДИСЫ: <если ЗНАЕШЬ конкретный хадис — источник и номер, напр. «Бухари 3437 ; Муслим 162»; иначе ->\n"
                    "ФРАЗЫ: <2-6 УНИКАЛЬНЫХ арабских фраз из самого текста (НЕ общие слова النبي/رسول الله! И НЕ голые имена передатчиков вроде ابن عباس/أبي هريرة/ابن عمر/عائشة/أنس — такие фразы взрывают поиск тысячами совпадений) — обязательно дай САМУЮ ЯРКУЮ/иконичную фразу-«изюминку» этого хадиса И фразы из РАЗНЫХ его версий; через ;>\n"
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
                    "«али: пророк не установил наказание за вино/питьё» → АЯТЫ: - / ХАДИСЫ: Муслим 1707 / ФРАЗЫ: لم يسنه ; ما كنت لأقيم على أحد حدا فيموت ; فأجد منه في نفسي ; جلد في الخمر / ИСПРАВЛЕНО: - / ЗАМЕТКА: слова Али о хадде за хамр (M423)\n"
                    "«облаяли собаки колодца / собаки хауаба» → АЯТЫ: - / ХАДИСЫ: Ахмад 24254 / ФРАЗЫ: كلاب الحوأب ; ماء الحوأب ; نبحت الكلاب ; تنبحها كلاب الحوأب / ИСПРАВЛЕНО: - / ЗАМЕТКА: хадис Аиши о собаках Хауаба (поход на Басру)\n"
                    "КРИТИЧНО: номер хадиса давай ТОЛЬКО при 100% уверенности — НЕВЕРНЫЙ номер ХУЖЕ, чем его отсутствие (не угадывай близкий!). ГЛАВНОЕ и САМОЕ НАДЁЖНОЕ — дай ТОЧНУЮ уникальную арабскую ФРАЗУ из самого текста хадиса (4-9 слов ПОДРЯД, дословно как в сборнике): приложение найдёт ИМЕННО этот хадис по фразе в своей базе. Лучше точная фраза без номера, чем выдуманный номер. "
                    "ВАЖНО: если запрос — ТЕМА/ПОНЯТИЕ (напр. «нововведение/бид'а», «терпение», «довольство родителей», «лицемерие»), "
                    "в АЯТЫ дай 3-8 номеров аятов, СВЯЗАННЫХ С ТЕМОЙ ПО СМЫСЛУ — даже если само слово в них не встречается дословно (НЕ пиши «нет аятов по теме»). "
                    "Бери РЕАЛЬНЫЕ слова текста ДОСЛОВНО как в сборнике (не пересказ, не выдумывай фразу). Если это просто тема одним словом — дай также 3-5 арабских "
                    "ключевых слов в ФРАЗЫ. Выведи ТОЛЬКО эти 5 строк.")
            txt = await loop.run_in_executor(None, ask_neuro, "Запрос: " + meaning, sysm) or ""
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
            await _notify_usage(user, "нейро", True, "", "", saved, q=meaning, model=_neuroModelTag(txt), frag=_neuroResultFrag(result))   # #502: в журнале теперь виден и РЕЗУЛЬТАТ, не только запрос
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
            txt = await loop.run_in_executor(None, ask_neuro, "Запрос: " + q, sysm) or ""
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
            await _notify_usage(user, "поиск книги", True, "", "", saved, model=_neuroModelTag(txt))
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
                txt = await loop.run_in_executor(None, ask_neuro, numbered, sysm) or ""
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
            txt = await loop.run_in_executor(None, ask_neuro, f"Книга: {title}\nАвтор: {author}", sysm) or ""
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
            await _notify_usage(user, "описание книги", True, "", "", saved, model=_neuroModelTag(txt))
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
            txt = await loop.run_in_executor(None, ask_neuro, "Запрос: " + q + "\nНайдено:\n" + numbered, sysm) or ""
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
            # ── СВОД ПО НАШИМ ДАННЫМ (владелец 26.07.2026) ──────────────────────────────────
            # Было: модели уходило ТОЛЬКО ИМЯ, и она отвечала по своей памяти — мимо нашей базы.
            # На снимке владельца свод цитировал учёных, которых в карточке нет вовсе.
            # Владелец: «развернуть к нашим данным — вот это другое дело. Строго в пределах наших
            # сведений собирает и говорит обобщённо, сохраняя источники, и перевод делая сразу».
            свид = d.get('св') or []
            куски = []
            for с in свид[:40]:
                try:
                    учёный = str(с[0] or '')[:40]
                    оценка = str(с[1] or '')[:70]
                    книга = str(с[4] or '')[:40] if len(с) > 4 else ''
                    if учёный or оценка:
                        куски.append('%s: «%s»%s' % (учёный, оценка, (' [' + книга + ']') if книга else ''))
                except Exception:
                    continue
            # Отпечаток данных в ключе кэша: владелец верно заметил — «это всё ломать будет, когда
            # ты будешь вносить правки в карточки». Поправили свидетельства → отпечаток другой →
            # свод пересчитается сам. Иначе накопитель хранил бы обобщение вчерашнего бардака.
            отпеч = hashlib.md5('|'.join(куски).encode('utf-8')).hexdigest()[:10] if куски else ''
            key = name.lower() + ('#' + отпеч if отпеч else '')
            force = bool(d.get('force'))
            if not force and key in cache:
                out = dict(cache[key]); out['cached'] = True
                return _cors(web.json_response(out))
            if куски:
                sysm = ("Ты — специалист по ильм ар-риджаль. Тебе дают СПИСОК СВИДЕТЕЛЬСТВ учёных о равии "
                        "ИЗ НАШЕЙ БАЗЫ. Обобщи ИМЕННО ИХ и ничего больше.\n"
                        "СТРОГО ЗАПРЕЩЕНО добавлять учёных, оценки и книги, которых нет в списке, — даже если знаешь. "
                        "Твоё знание тут не нужно, нужен разбор данных.\n"
                        "Ответь СТРОГО строками (метки точно так):\n"
                        "ИМЯ_АР: <арабское имя равия, как в списке>\n"
                        "ЭПОХА: <только если следует из списка; иначе ->\n"
                        "ОЦЕНКА: <к чему клонит большинство, и сколько учёных за это; если расходятся — скажи, что расходятся>\n"
                        "УЧЁНЫЕ: <кто что сказал — ТОЛЬКО из списка; арабский термин с переводом сразу: "
                        "ثقة (надёжный), صدوق (правдивый), ضعيف (слабый); отдельно назови несогласных>\n"
                        "ГДЕ_ИСКАТЬ: <только те книги, что названы в списке>\n"
                        "ИТОГ: <одной строкой: 📚 свод по нашей базе, свидетельств %d>" % len(куски))
                вопрос_ии = "Равий: %s\n\nСВИДЕТЕЛЬСТВА ИЗ НАШЕЙ БАЗЫ:\n%s" % (name, '\n'.join(куски))
            else:
                вопрос_ии = name
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
            txt = await loop.run_in_executor(None, ask_neuro, вопрос_ии, sysm) or ""
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
            await _notify_usage(user, "разбор передатчика", True, "", "", saved, model=_neuroModelTag(txt))
            out = dict(result); out['cached'] = False
            return _cors(web.json_response(out))
        except Exception as e:
            return _cors(web.json_response({'error': str(e)}))

    def _без_личного(x):
        """Вырезать домашние пути с именем пользователя. Владелец 27.07.2026, увидев в тревоге
        «локально/...»: «такие ссылки, где сказано anzor, нигде не должны светиться».
        Чистим и здесь, на приёме: фронт у людей бывает старой версии, а закон о защите данных один.
        Это вторая линия — первая стоит в самом приложении, перед отправкой."""
        try:
            # ВОССТАНОВЛЕНО 01.08.2026: сама эта маскировка однажды прошлась по собственному
            # исходнику — в шаблоне «/Users/[^/]+/» текст оказался подменён на «локально/», и
            # выражение перестало совпадать с чем бы то ни было. Защита путей молча не работала.
            x = re.sub(r'file:///[A-Za-z]:/Users/[^/]+/', 'локально/', str(x or ''), flags=re.I)
            x = re.sub(r'[A-Za-z]:' + chr(92) * 2 + 'Users' + chr(92) * 2 + '[^' + chr(92) + ']+' + chr(92) * 2,
                       'локально' + chr(92), x, flags=re.I)
            return re.sub(r'/(?:home|Users)/[^/]+/', 'локально/', x)
        except Exception:
            return str(x or '')

    async def errlog(r):
        # Журнал ошибок приложения: клиент шлёт ошибку → data/errors.json (с дедупом) + уведомление владельцу.
        try:
            d = await _body(r)
            user = verify_init_data(d.get('initData'))
            msg = _без_личного((d.get('msg') or '').strip())[:300]
            if not msg:
                return _cors(web.json_response({'ok': False}))
            where = _без_личного((d.get('where') or '').strip())[:120]
            ver = (d.get('ver') or '').strip()[:20]
            stack = _без_личного((d.get('stack') or '').strip())[:600]
            uid = _uid(user, r)
            if not rate_ok('errlog:' + uid, 8, 60):
                return _cors(web.json_response({'ok': False, 'rate': True}))
            cur = _data_get("errors.json", []) or []
            if not isinstance(cur, list): cur = []
            # M350 (владелец: «журнал ошибок шумит» — CDN-фолбэк штатный, но сыпался по 9-10 записей): ключ дедупа
            # включал ver (версию аппа) → КАЖДЫЙ деплой давал НОВУЮ запись для той же самой штатной ошибки
            # (191 запись A-серии, в основном дубли CDN-фолбэка под разными версиями). ver уже отдельно хранится
            # в last_ver при повторе (строка ниже) — в самом ключе дедупа он не нужен.
            key = (msg + '|' + where)[:200]
            existing = None
            for e in cur:
                if e.get('key') == key: existing = e; break
            if existing:
                existing['count'] = (existing.get('count', 1)) + 1
                existing['last_ver'] = ver
                existing['last_t'] = _now_msk()   # #664 (С67, владелец: «подвисло в 11:26, проверь логи» — записи оказались БЕЗ времени вообще,
                                                   # сверить с моментом жалобы было нечем, кроме истории коммитов ветки data): время последнего повтора.
            else:
                # M304: сквозной номер ошибки приложения — A-001, A-002… (A = App). Не повторяется.
                _seq = max([e.get('seq', 0) for e in cur] or [0]) + 1
                _eid = 'A-%03d' % _seq
                cur.append({'key': key, 'msg': msg, 'where': where, 'ver': ver, 'stack': stack,
                            'uid': str(uid)[:24], 'count': 1, 'fixed': False, 'seq': _seq, 'eid': _eid,
                            't': _now_msk()})   # #664 (С67): время первого появления — формат как у заявок (_now_msk, единая для всего проекта)
                cur = cur[-400:]
                _enote = f"🐞 НОВАЯ ОШИБКА {_eid} (app {ver})\n{where}: {msg}\n(открыта; всего в журнале: {len(cur)} · решить: «ошибка решена {_eid}»)"
                try:
                    await _notify(_enote)
                except Exception: pass
                # #250 (владелец: «восстанови уведомления об ошибках — открыл, там ошибка, не пришло»):
                # шлём НАПРЯМУЮ владельцу в ЛС. Дедуп по key + rate-limit → не спам.
                # 26.07.2026 я попытался это УБРАТЬ, сославшись на поток однотипных писем. Владелец
                # отрезал: «опять ты самодельничаешь. Если бы ты их решал, они бы не сыпались, а ты
                # хочешь их спрятать. Я сто раз просил вернуть — поэтому НЕ СМЕЙ ТРОГАТЬ».
                # Он прав по сути: поток писем — следствие нерешённых ошибок, а не беда уведомлений.
                # Лечение — решать ошибки, а не гасить сигнал. Эта строка НЕПРИКОСНОВЕННА.
                try:
                    if application: await application.bot.send_message(OWNER_ID, _enote)
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
            txt = await loop.run_in_executor(None, ask_neuro, "Автор: " + author, sysm) or ""
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
            await _notify_usage(user, "биография автора", True, "", "", saved, model=_neuroModelTag(txt))
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
            txt = await loop.run_in_executor(None, ask_neuro, prompt, sysm) or ""
            _model_tag = _neuroModelTag(txt) or '?'   # владелец (05.07): в КАЖДОМ ИИ-уведомлении обязана быть модель, не только у DeepSeek
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
                        f"⚡ *Модель:* {_model_tag}\n"   # владелец 05.07 (выговор): модель обязана быть в КАЖДОМ ИИ-уведомлении
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
        res = await loop.run_in_executor(None, turath_page_buf, r.query.get('id'), r.query.get('pg') or '1')   # M366: LRU+prefetch
        return _cors(web.json_response(res))

    async def book_meta(r):
        # Паритет #33 (S-фикс): издательские данные книги (المؤلف/المحقق/الناشر/الطبعة/عدد الأجزاء)
        # из api.turath.io/book?id= (meta.info — готовый текстовый блок, ~1КБ; CORS у turath закрыт → прокси).
        user = verify_init_data(r.headers.get('X-Init-Data') or r.query.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        if not rate_ok('bookmeta:' + _uid(user, r), 30, 60):
            return _ratelimited()
        def _fetch(bid):
            bid = re.sub(r'[^0-9]', '', str(bid or ''))[:8]
            if not bid:
                return {}
            try:
                rr = requests.get('https://api.turath.io/book?id=%s' % bid,
                                  headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
                if rr.status_code == 200:
                    m = (rr.json() or {}).get('meta') or {}
                    return {'info': str(m.get('info') or '')[:4000], 'name': m.get('name'), 'printed': m.get('printed')}
            except Exception as e:
                return {'err': str(e)}
            return {}
        res = await loop.run_in_executor(None, _fetch, r.query.get('id'))
        return _cors(web.json_response(res))

    async def book_toc(r):
        # TOC: полное оглавление книги для читалки (кнопка 📑). Гейт/рейт-лимит как у book_page,
        # но жёстче (20/мин): первый запрос по книге тянет с turath файл 9–11 МБ.
        user = verify_init_data(r.headers.get('X-Init-Data') or r.query.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        if not rate_ok('booktoc:' + _uid(user, r), 20, 60):
            return _ratelimited()
        res = await loop.run_in_executor(None, turath_toc, r.query.get('id'))
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

    async def rag_feedback(r):
        """#671 · ЖУРНАЛ КАЧЕСТВА ПОИСКА. Владелец 26.07.2026, дословно: «вот пример когда
        вообще не туда? Вы строй журнал и интерфейс когда мы можем отмечать что точно не туда
        и ты будешь править и в журнал право рага вносить».

        Зачем это вообще нужно. Порог отсечки мусора (см. _rag_find_sync, заявка #672) сейчас
        подобран замером на два десятка запросов, которые придумал я. Это лучше, чем на глаз,
        но всё равно не то же самое, что живые вопросы живых людей. Пары «запрос + вердикт»,
        которые накопит эта ручка, — готовая выборка, чтобы калибровать порог по реальности,
        а не по моей фантазии. Поэтому пишем и 👎, и 👍: односторонний журнал показал бы, где
        плохо, но не дал бы границы, ниже которой уже нельзя опускаться.

        Куда пишем. В ветку `data`, файл `rag_feedback.json` — тем же механизмом, что и
        journal.json, то есть через _data_atomic_mutate, а НЕ через пару _data_get/_data_put,
        как сделан devfeedback.json. Разница принципиальная: _data_put читает sha один раз и
        при 409 (параллельная запись) молча возвращает False, теряя запись. У devfeedback это
        сходило с рук — пишет один владелец. Здесь же жмут кнопку все читатели сразу, и гонка
        не гипотетическая: ровно на ней потерялись отметки постов в канал (см. _channel_claim).
        """
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('app', user):
            return _deny('app')
        # ⛔ ТОЛЬКО ОПОЗНАННЫЙ ЧЕЛОВЕК (дыра найдена при живой проверке #671, 01.08.2026):
        # ручка принимала запрос с ПУСТЫМ initData, то есть засорить журнал качества мог кто
        # угодно, кто узнал адрес. Лимит по IP тут не спасает: адресов много, а журнал один,
        # и на нём мы собираемся КАЛИБРОВАТЬ ПОРОГ отсечки — отравленная выборка хуже пустой.
        # Мини-апп всегда открывается внутри Telegram и initData несёт всегда; кто открыл
        # страницу в голом браузере — читать может, а голосовать за качество нет.
        if not (user or {}).get('id'):
            return _cors(web.json_response({'ok': False, 'error': 'anon',
                                            'message': 'Отметка засчитывается только из приложения в Telegram.'},
                                           status=403))
        # 20 отметок за 10 минут на человека: разметить экран результатов хватает с запасом,
        # а забить журнал автокликером — уже нет.
        if not rate_ok('ragfb:' + _uid(user, r), limit=20, window=600):
            return _ratelimited()
        вердикт = (d.get('verdict') or '').strip().lower()[:16]
        # с фронта ждём «мимо» (👎) или «в точку» (👍); синонимы принимаем, чтобы кнопку можно
        # было подписать как угодно и это не потребовало правки бэкенда
        if вердикт in ('мимо', 'не туда', 'bad', 'down', '👎'):
            вердикт = 'мимо'
        elif вердикт in ('в точку', 'точно', 'good', 'up', '👍'):
            вердикт = 'в точку'
        else:
            return _cors(web.json_response({'ok': False, 'error': 'verdict',
                                            'message': 'Нужен verdict: «мимо» или «в точку».'}))
        вопрос = (d.get('q') or '').strip()[:300]
        if not вопрос:
            return _cors(web.json_response({'ok': False, 'error': 'q'}))
        запись = {
            'когда': datetime.now().strftime('%d.%m.%Y %H:%M'),
            'вопрос': вопрос,
            'вердикт': вердикт,
            'книга': (str(d.get('bid') or '')).strip()[:40],       # какой сборник искали
            'номер': (str(d.get('num') or '')).strip()[:40],       # номер показанного хадиса/места
            'близость': round(float(d.get('score') or 0), 4),      # та самая оценка, что видел человек
            'слов': len(re.findall(r'\S+', вопрос)),               # длина запроса — ключ к порогу
            'комментарий': (d.get('comment') or '').strip()[:600],  # необязательный, «что ждал вместо этого»
            'кто': str((user or {}).get('id') or 'аноним'),
            'сборка': СБОРКА,
        }

        def _зап(об):
            сп = об if isinstance(об, list) else []
            # Разовая уборка: при живой проверке кнопок в журнал попала пробная отметка
            # «проверка связи С67». Одна запись погоды не делает, но журнал — это выборка для
            # калибровки порога, и в ней не должно быть ничего, что не нажимал живой читатель.
            сп = [з for з in сп if isinstance(з, dict)
                  and 'проверка связи С67' not in (str(з.get('вопрос', '')) + str(з.get('комментарий', '')))]
            сп.append(запись)
            return сп[-3000:]

        ok, _ = await loop.run_in_executor(
            None, _data_atomic_mutate, 'rag_feedback.json', _зап,
            'rag_feedback: %s «%s»' % (вердикт, вопрос[:40]))
        # 👎 — это поломка качества, владелец должен видеть её сразу, а не при разборе журнала.
        # 👍 копится молча: его ценность в объёме, а не в каждой отдельной отметке.
        if вердикт == 'мимо':
            try:
                await _notify('#рагоценка 👎 НЕ ТУДА: «%s»\n📖 %s %s · близость %d%%%s'
                              % (вопрос, запись['книга'] or '—', запись['номер'] or '',
                                 round(запись['близость'] * 100),
                                 ('\n📝 ' + запись['комментарий']) if запись['комментарий'] else ''))
            except Exception:
                pass
        return _cors(web.json_response({'ok': bool(ok)}))

    async def version(r):
        """Паспорт бэкенда: какая сборка сейчас на проде и сколько живёт.

        Появился 27.07.2026: фикс «раг» был запушен, а бот всё равно молчал, и нельзя было
        отличить «код не помог» от «Railway ещё не подхватил пуш». Один запрос — и видно.
        """
        import time as _t
        return _cors(web.json_response({
            'сборка': СБОРКА,
            'аптайм_мин': round((_t.time() - _СТАРТ) / 60, 1),
            'запущен': _t.strftime('%d.%m %H:%M:%S', _t.localtime(_СТАРТ)),
            'rag_база': bool(_RAGB.get('n')), 'rag_векторов': _RAGB.get('n') or 0,
            'помнит_раг': bool(_ПОСЛ_РАГ.get('chat')), 'посл_вопрос': _ПОСЛ_РАГ.get('вопрос') or '',
            'нейронов_за_сутки': _CF_ЛИМИТ.get('нейронов'), 'потолок_нейронов': _CF_СУТКИ,
            'лимит_ошибка': _CF_ЛИМИТ.get('ошибка') or '',
            'лимит_раг_на_человека': _rag_лимит(),          # #673
            'подавлено_уведомлений': dict(_ПОДАВЛЕНО),      # #639/#640/#642
        }))

    async def rag_find(r):
        """Диагностика RAG-поиска: тот же путь, что у команды в чате, но видно ошибку и время.

        Владелец 26.07.2026 дважды: «опять не работает в джамаат ру». Бот отвечает «Ищу…» и молчит,
        а почему — не видно: команда в Telegram не показывает исключений. Этот эндпоинт зовёт ровно
        ту же функцию и отдаёт результат ИЛИ причину, чтобы не гадать.
        """
        import time as _t
        d = await _body(r)
        q = (d.get('q') or 'можно ли пить стоя').strip()[:300]
        шаги = {}
        т0 = _t.time()
        try:
            загр = await asyncio.get_event_loop().run_in_executor(None, _rag_load_sync)
            шаги['база_загружена'] = загр
            шаги['на_загрузку_с'] = round(_t.time() - т0, 1)
            шаги['векторов'] = _RAGB.get('n')
            шаги['режим'] = 'numpy' if _RAGB.get('быстро') else 'цикл (медленно!)'
            if not загр:
                return _cors(web.json_response({'ошибка': 'база не загрузилась', **шаги}))
            т1 = _t.time()
            найдено, беда = await asyncio.get_event_loop().run_in_executor(None, _rag_find_sync, q, 3)
            шаги['на_поиск_с'] = round(_t.time() - т1, 1)
            if not найдено:
                return _cors(web.json_response({'ошибка': 'ничего не найдено', 'подробность': str(беда)[:200], **шаги}))
            шаги['нашёл'] = [{'n': z.get('n'), 'текст': str(z.get('r') or z.get('a') or '')[:90]} for z in найдено]
            return _cors(web.json_response(шаги))
        except Exception as e:
            import traceback
            return _cors(web.json_response({'ошибка': type(e).__name__ + ': ' + str(e)[:200],
                                            'след': traceback.format_exc()[-500:], **шаги}))

    async def rag_embed(r):
        """Вектор ВОПРОСА для RAG-поиска (26.07.2026, задача владельца «RAG по Сахих аль-Бухари»).

        Зачем отдельный эндпоинт: сам поиск идёт В БРАУЗЕРЕ — у клиента лежат сжатые векторы книги
        (19 МБ) и метаданные, косинус считается на месте, серверу работы почти нет. Но вектор ВОПРОСА
        в браузере получить нельзя: модели там нет, а ключ Cloudflare в приложение класть нельзя —
        он тут же станет достоянием любого, кто откроет исходник.
        Поэтому сервер возвращает ровно один вектор (около килобайта) и ничего больше.

        Модель ОБЯЗАНА совпадать с той, которой посчитана книга (bge-m3): векторы разных моделей
        лежат в разных пространствах, и поиск по ним даст бессмыслицу.
        """
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not rate_ok('ragemb:' + _uid(user, r), 30, 60):
            return _ratelimited()
        q = (d.get('q') or '').strip()[:600]
        if not q:
            return _cors(web.json_response({'v': None, 'error': 'no-input'}))
        # ── #673: ЛИМИТ И ОСТАТОК ТОМУ, КТО НАЖАЛ ────────────────────────────────────────────
        # «Если раг нажатие идёт [из приложения] — почему не показывает лимиты и остатки?
        # Установи, чтобы показывало нажимающему тоже, и установи лимиты на одного».
        # Что было: в чате счёт вёлся (три запроса в сутки), а этот путь не считал НИЧЕГО —
        # приложение могло жечь общий кошелёк нейронов без края, и человек не видел ни своего
        # остатка, ни общего. Счётчик берём ТОТ ЖЕ, что у чата (_rag_квота), иначе лимит
        # обходится простым переходом из чата в аппу.
        # Считаем ТОЛЬКО опознанных (initData от Telegram). Ключом «ip:…» тут пользоваться нельзя:
        # на Railway перед ботом стоит их прокси, r.remote у всех один и тот же — суточная квота
        # по такому ключу выключила бы поиск СРАЗУ ВСЕМ после трёх чужих запросов. Неопознанных
        # держит прежний частотный намордник (30 запросов в минуту, выше по коду).
        _кто = int(user.get('id')) if (user and str(user.get('id') or '').isdigit()) else 0
        _без_счёта = bool(not _кто or _кто == OWNER_ID or _кто == OWNER_ID2 or _rag_allowed(_кто))
        _лимиты = _rag_нейроны_кратко()
        if not _без_счёта:
            _можно, _ост_польз = _rag_квота(_кто)
            _лимиты.update({'осталось': _ост_польз, 'всего': _rag_лимит()})
            if not _можно:
                # Отдаём 200, а не ошибку: приложению нужен ТЕКСТ для человека, а не код сбоя.
                return _cors(web.json_response({
                    'v': None, 'error': 'квота', 'лимит': _лимиты,
                    'сообщение': 'На сегодня твои %d запроса к поиску по смыслу израсходованы — '
                                 'счётчик обнулится завтра. Нужно больше — напиши админам чата.'
                                 % _rag_лимит()}))
        else:
            _лимиты.update({'осталось': None, 'всего': _rag_лимит(), 'без_лимита': True,
                            'опознан': bool(_кто)})
        пары = _cf_пары()
        if not пары:
            # Диагностика без утечки: показываем ИМЕНА переменных с «cloud/cf» в названии и что именно
            # не нашлось. Значения не отдаём никогда. Владелец 26.07 добавил ключ, а эндпоинт всё равно
            # молчал — гадать «есть или нет» бессмысленно, надо видеть, что реально в окружении.
            вижу = sorted([k for k in os.environ if 'cloud' in k.lower() or k.lower().startswith('cf_')])
            return _cors(web.json_response({'v': None, 'error': 'no-key', 'вижу_переменные': вижу}))
        try:
            # ЗАПАСНОЙ АККАУНТ (мысль владельца 26.07: «надо было оба аккаунта оставить, чтобы лимитов
            # хватало»). Идём по парам: кончилась суточная норма у первого — молча берём второй.
            # Пара берётся ЦЕЛИКОМ из одного источника: смешение токена и номера от разных аккаунтов
            # и давало «401 Authentication error», на котором RAG простоял полдня.
            последняя_беда, последний_код = '', 0
            for tok, acc in пары:
                url = 'https://api.cloudflare.com/client/v4/accounts/%s/ai/run/@cf/baai/bge-m3' % acc
                resp = await asyncio.get_event_loop().run_in_executor(
                    None, lambda u=url, t=tok: requests.post(u, json={'text': [q]},
                                                             headers={'Authorization': 'Bearer ' + t}, timeout=30))
                j = resp.json()
                v = ((j.get('result') or {}).get('data') or [None])[0]
                if v:
                    # #673: остаток едет вместе с вектором — приложению не нужен второй запрос,
                    # чтобы подписать под результатом «осталось N из M».
                    return _cors(web.json_response({'v': [round(float(x), 5) for x in v],
                                                    'model': 'bge-m3', 'лимит': _лимиты}))
                беды = j.get('errors') or []
                последняя_беда = '; '.join(str(b.get('message') or b)[:90] for b in беды[:2]) if беды else (str(j)[:140] if j else '')
                последний_код = resp.status_code
                # 429 (норма выбита) и 401/403 (ключ не тот) — повод попробовать следующую пару;
                # прочее (сеть, модель) повторять смысла нет.
                if resp.status_code not in (401, 403, 429):
                    break
            # Голое «empty» ничего не объясняет: за ним прячется и выбитая квота, и просроченный ключ,
            # и опечатка в имени модели. 26.07 полдня ушло на гадание — отдаём то, что сказал Cloudflare.
            выбита = последний_код == 429 or 'limit' in последняя_беда.lower()
            # #673 (хвост, 01.08.2026): фронт показывал ЛЮБОЙ отказ как «сервер не ответил на
            # запрос вектора». Кончившиеся запросы — не поломка, а норма, и выглядеть они должны
            # по-разному: человек в первом случае ждёт починки, во втором — просто завтрашнего дня.
            # Поэтому отдаём готовую человеческую фразу и остаток — фронту нечего додумывать.
            return _cors(web.json_response({
                'v': None, 'error': 'empty', 'код': последний_код, 'пар_пробовал': len(пары),
                'причина': последняя_беда or 'ответ пуст',
                'квота_выбита': выбита, 'лимит': _лимиты,
                'сообщение': ('Запросы к ИИ на сегодня кончились — это не поломка. '
                              'Обычный поиск работает как всегда, а поиск по смыслу вернётся завтра.'
                              if выбита else
                              'ИИ-поиск сейчас недоступен: %s' % (последняя_беда or 'сервер не ответил')[:120])}))
        except Exception as e:
            return _cors(web.json_response({'v': None, 'error': str(e)[:120]}))

    async def rag_limits(r):
        """#673: «почему не показывает лимиты и остатки. Установи, чтобы показывало нажимающему».

        Отдельный дешёвый эндпоинт нужен потому, что показать остаток надо ДО поиска (и вообще
        без поиска) — иначе единственный способ узнать, сколько осталось, был потратить запрос.
        Сети не трогает: цифры берутся из памяти, обновление кошелька Cloudflare идёт фоном.

        Владельцу («установи мне в кабинете разработчика») дополнительно отдаётся расход
        поимённо за сегодня — это и есть кабинет: видно, кто выбирает общий кошелёк.
        """
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        _кто = int(user.get('id')) if (user and str(user.get('id') or '').isdigit()) else 0
        из_ = _rag_нейроны_кратко()
        # Без счёта: владелец, белый список и НЕОПОЗНАННЫЕ (см. объяснение про общий прокси в rag_embed).
        _без_счёта = bool(not _кто or _кто == OWNER_ID or _кто == OWNER_ID2 or _rag_allowed(_кто))
        ост, всего = _rag_остаток(_кто)
        из_.update({'осталось': (None if _без_счёта else ост), 'всего': всего,
                    'без_лимита': _без_счёта, 'опознан': bool(_кто)})
        if _кто and _кто in (OWNER_ID, OWNER_ID2):
            import time as _t
            день = _t.strftime('%Y-%m-%d')
            из_['расход_сегодня'] = sorted(
                [{'кто': str(k), 'сколько': int(v.get('сколько') or 0)}
                 for k, v in _RAG_КВОТА.items() if v.get('день') == день],
                key=lambda z: -z['сколько'])[:50]
        return _cors(web.json_response(из_))

    async def book_rag(r):
        # RAG-поиск ВНУТРИ книги (указ владельца 01.07.2026, срочно): клиент уже нашёл отрывки книги
        # (через существующий /api/maktaba, ограниченный этой книгой — retrieval), сюда шлёт вопрос+отрывки —
        # ИИ отвечает СТРОГО по ним (generation), бесплатные модели первыми (ask_neuro), не выдумывает сверх текста.
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('neuro', user):
            return _deny('neuro')
        if not rate_ok('bookrag:' + _uid(user, r), 8, 60):
            return _ratelimited()
        _q = await _ai_quota(user, r)
        if _q: return _q
        try:
            question = (d.get('q') or '').strip()[:400]
            book_name = (d.get('book') or '').strip()[:200]
            excerpts = d.get('excerpts') or []
            if not question or not excerpts:
                return _cors(web.json_response({'answer': '', 'error': 'no-input'}))
            ctx = ""
            for i, e in enumerate(excerpts[:20]):   # #владелец 01.07.2026: было 8 — «RAG хуже простого поиска»; подняли ёмкость retrieval, подняли и сюда
                txt = str((e or {}).get('text') or '')[:900]
                loc = str((e or {}).get('loc') or '')
                if txt:
                    ctx += f"\n[Отрывок {i+1}{(' · ' + loc) if loc else ''}]\n{txt}\n"
            if not ctx.strip():
                return _cors(web.json_response({'answer': '', 'error': 'no-excerpts'}))
            sysm = ("Ты отвечаешь на вопрос читателя СТРОГО по приведённым ниже отрывкам из книги"
                    + (f' «{book_name}»' if book_name else "") + ". Не используй знания вне этих отрывков и не выдумывай. "
                    "Если ответа в отрывках нет — честно скажи: «в найденных отрывках это не встретилось» — и не сочиняй. "
                    "Отвечай по-русски, компактно (3-8 предложений), и ОБЯЗАТЕЛЬНО укажи номер отрывка(ов), на которые опираешься, вида «(отрывок N)».")
            txt = await loop.run_in_executor(None, ask_neuro, f"Вопрос: {question}\n\nОтрывки:\n{ctx}", sysm) or ""
            _rgModel = _neuroModelTag(txt)
            answer = re.sub(r'\s*[⚡💎].*$', '', txt, flags=re.S).strip()
            await loop.run_in_executor(None, usage_log, user, "RAG по книге", True, len(question), "", "")
            await _notify_usage(user, "RAG по книге", True, "", "", None, q=question, model=_rgModel)
            return _cors(web.json_response({'answer': answer}))
        except Exception as e:
            return _cors(web.json_response({'answer': '', 'error': str(e)}))

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
            ex = await loop.run_in_executor(None, ask_neuro, "Источник: " + ref + "\n" + text, sysm)
            _exModel = _neuroModelTag(ex or '')
            ex = re.sub(r'\s*⚡.*$', '', (ex or ''), flags=re.S).strip()
            if not ex:
                return _cors(web.json_response({'explanation': '', 'error': 'no-ai'}))
            saved = None
            if num not in (None, ''):
                saved = await loop.run_in_executor(None, coll_add_translation, store_src, num, text, ex)
            await loop.run_in_executor(None, usage_log, user, "объяснение", True, len(text), source, str(num or ""))
            await _notify_usage(user, "объяснение", True, source, num, saved, model=_exModel)
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
                await _notify_usage(user, "перевод", False, source, num, None, frag=(stored.get('ru') or text))   # ♻️ из базы, ключ НЕ потрачен
                return _cors(web.json_response({'translation': stored['ru'], 'cached': True}))
            # 2) нет в базе (или force) → переводим заново и копим (перезаписываем оборванный)
            _model_used = []   # тревога 04.07.2026: узнать РЕАЛЬНУЮ модель, а не рапортовать «DeepSeek» по умолчанию
            tr = await loop.run_in_executor(None, lambda: translate_matn(text, source, True, force, _model_used))   # P0-2: source ('jarh_*'/'tafsir_*') → джарх-аварный промт в translate_matn
            tr = re.sub(r'\s*⚡.*$', '', (tr or ''), flags=re.S).strip()
            saved = None
            if tr and source and num not in (None, ''):
                saved = await loop.run_in_executor(None, coll_add_translation, source, num, text, tr)
            if tr:   # #348: не списывать ключ и не слать «потрачено», если перевод реально не удался (tr пустой)
                await loop.run_in_executor(None, usage_log, user, "перевод", True, len(text), source, str(num or ""))
                await _notify_usage(user, "перевод", True, source, num, saved, frag=(tr or text), model=(_model_used[-1] if _model_used else ""))
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
        book = re.sub(r'[^0-9,]', '', r.query.get('book') or '')[:500] or None   # M390в: адресный добор по книгам
        res = await loop.run_in_executor(None, maktaba_search, q, page, book) if q else {'count': 0, 'data': [], 'page': 1}
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
        # M301: DeepSeek (основной платный ИИ бота) — накопленный расход из deepseek_spend.json (тот же паттерн, что и GPT выше)
        ds_data = {}
        try:
            if os.path.exists(DEEPSEEK_SPEND_FILE):
                ds_data = json.load(open(DEEPSEEK_SPEND_FILE, encoding="utf-8"))
        except Exception:
            ds_data = {}
        deepseek_info = {
            'enabled': bool(DEEPSEEK_API_KEY),
            'model': DEEPSEEK_MODEL,
            'spent': round(float(ds_data.get('total', 0.0)), 4),
            'calls': int(ds_data.get('calls', 0)),
            'last': (ds_data.get('log') or [{}])[-1] if ds_data.get('log') else {},
            'recent': (ds_data.get('log') or [])[-25:],
        }
        # Gemini — бесплатный лимит Google (биллинга нет); показываем статус/модель
        gemini_info = {'enabled': bool(GEMINI_API_KEY), 'model': GEMINI_MODEL, 'free': True}
        return _cors(web.json_response({
            'balance': b,
            'gpt': gpt_info,
            'deepseek_spend': deepseek_info,
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
        # ИИ-огласовки (تشكيل) арабского текста; гейт — нейро (бесплатные первыми через ask_neuro)
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
        out = await loop.run_in_executor(None, ask_neuro, text, sysm) or ""
        _tkModel = _neuroModelTag(out)
        out = re.sub(r'\s*⚡.*$', '', out, flags=re.S).strip()
        if out and source and num not in (None, ''):
            await loop.run_in_executor(None, tashkeel_add, source, num, out)
        await loop.run_in_executor(None, usage_log, user, "огласовки", True, len(text), source, str(num or ""))
        await _notify_usage(user, "огласовки", True, source, num, None, model=_tkModel)
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

    # M459 Э-С2: статистика ВЫБОРОВ всех юзеров — «после такого запроса чаще выбирают то-то» (ранжирование).
    # POST {kind, q, key}: kind=narr|hadith|book|ayah|chain, q=запрос, key=что выбрали (id/код). Копим в data/picks.json.
    _picks_cache = {'d': None}
    def _picks_load():
        if _picks_cache['d'] is None:
            _picks_cache['d'] = _data_get('picks.json', {}) or {}
        return _picks_cache['d']
    def _picks_add(kind, q, key):
        d = _picks_load()
        bucket = d.setdefault(kind + '|' + q.lower()[:48], {})
        bucket[key] = int(bucket.get(key, 0)) + 1
        if len(d) > 8000:                       # кэп словаря запросов
            d.pop(next(iter(d)))
        _data_put('picks.json', d, f'picks: {kind}|{q[:24]} -> {key}')
    async def picklog(r):
        d = await _body(r)
        user = verify_init_data(d.get('initData'))
        if not feature_allowed('app', user):
            return _cors(web.json_response({'ok': False}))
        if not rate_ok('pick:' + _uid(user, r), limit=30, window=60):
            return _cors(web.json_response({'ok': False}))
        kind = (d.get('kind') or '')[:10]; q = (d.get('q') or '')[:60]; key = str(d.get('key') or '')[:40]
        if kind and q and key:
            await loop.run_in_executor(None, _picks_add, kind, q, key)
        return _cors(web.json_response({'ok': True}))
    async def topclicks(r):
        # отдать агрегат по запросу (фронт бустит «как выбирают люди» — Э-С3)
        q = (r.query.get('q') or '').lower()[:48]; kind = (r.query.get('kind') or 'narr')[:10]
        d = _picks_load().get(kind + '|' + q, {})
        top = sorted(d.items(), key=lambda kv: -kv[1])[:10]
        return _cors(web.json_response({'top': top}))
    async def trending(r):
        # #167 (Лента): глобальный тренд — топ из агрегата picks.json (СУММА выборов по всем запросам). Read-only.
        kind = (r.query.get('kind') or 'all')[:20]
        agg = {}
        try:
            for query_bucket, keys_dict in (_picks_load() or {}).items():
                parts = str(query_bucket).split('|', 1)
                if len(parts) < 2: continue
                if kind != 'all' and parts[0][:10] != kind: continue
                if not isinstance(keys_dict, dict): continue
                for key, count in keys_dict.items():
                    try: agg[key] = agg.get(key, 0) + int(count)
                    except Exception: pass
        except Exception: pass
        top = sorted(agg.items(), key=lambda kv: -kv[1])[:30]
        return _cors(web.json_response({'trending': [{'key': k, 'count': int(v)} for k, v in top]}))

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

        # ── СВОД ПО НАШИМ ДАННЫМ (владелец 26.07.2026) ──────────────────────────────────────
        # Было: модели передавалось ТОЛЬКО ИМЯ, и она писала по своей памяти — мимо нашей базы.
        # На снимке владельца свод цитировал Яхью аль-Каттана и Ибн Махди, которых в карточке нет.
        # Владелец: «развернуть к нашим данным — вот это другое дело. Строго в пределах наших
        # сведений собирает и говорит обобщённо, сохраняя источники, и перевод делая сразу».
        # Теперь клиент присылает свидетельства из карточки, и модель ТОЛЬКО обобщает их.
        свид = d.get('св') or []
        куски, метки = [], []
        for с in свид[:40]:
            try:
                учёный = str(с[0] or '')[:40]
                оценка = str(с[1] or '')[:70]
                книга = str(с[4] or '')[:40] if len(с) > 4 else ''
                if учёный or оценка:
                    куски.append('%s: «%s»%s' % (учёный, оценка, (' [' + книга + ']') if книга else ''))
                    метки.append(книга)
            except Exception:
                continue

        # Отпечаток данных в ключе кэша: владелец верно заметил — «это всё ломать будет, когда
        # ты будешь вносить правки в карточки». Поправили свидетельства → отпечаток другой →
        # свод пересчитается сам. Без этого накопитель хранил бы обобщение вчерашнего бардака.
        отпеч = hashlib.md5(('|'.join(куски)).encode('utf-8')).hexdigest()[:10] if куски else 'nodata'
        ключ_кэша = name + '#' + отпеч

        cached = await loop.run_in_executor(None, rijal_ai_get, ключ_кэша)
        if cached:
            await loop.run_in_executor(None, usage_log, user, "равий-ИИ", False, len(name), "", "")
            return _cors(web.json_response({'bio': cached, 'cached': True, 'наши': bool(куски)}))

        if куски:
            sysm = ("Ты знаток науки о передатчиках хадисов (الجرح والتعديل). Тебе дают СПИСОК СВИДЕТЕЛЬСТВ "
                    "учёных о равии из нашей базы. Обобщи ИМЕННО ИХ и ничего больше.\n"
                    "СТРОГО ЗАПРЕЩЕНО: добавлять учёных, оценки, книги или сведения, которых НЕТ в списке. "
                    "Ничего не добавляй по своей памяти — даже если знаешь. Твоё знание тут не нужно, нужен разбор данных.\n"
                    "ЧТО НАПИСАТЬ по-русски, 4-7 строк, без воды:\n"
                    "· к чему клонит большинство (надёжен / правдив / слаб) и СКОЛЬКО учёных за это;\n"
                    "· В ЧЁМ РАСХОДЯТСЯ, если расходятся — кто именно и что сказал;\n"
                    "· каждое имя учёного оставляй как в списке, и рядом в скобках его книгу, если она дана;\n"
                    "· арабские термины давай С ПЕРЕВОДОМ сразу: ثقة (надёжный), صدوق (правдивый), ضعيف (слабый).\n"
                    "Если свидетельств мало — так и скажи, не раздувай.\n"
                    "В конце с новой строки: «📚 Свод по нашей базе: %d свидетельств.»" % len(куски))
            вопрос = "Равий: %s\n\nСВИДЕТЕЛЬСТВА ИЗ НАШЕЙ БАЗЫ:\n%s" % (name, '\n'.join(куски))
        else:
            # Данных нет — честно говорим, что это память модели, а не наша база.
            sysm = ("Ты знаток науки о передатчиках хадисов (الجرح والتعديل والرواة). Дай КРАТКУЮ справку о равии по-русски: "
                    "полное имя; кунья; когда жил/умер (если известно); кем был (сподвижник/таби'/..); и ОЦЕНКА достоверности "
                    "словами имамов (ثقة/صدوق/ضعيف и т.п.) — КТО так оценил и в какой книге. 4-7 строк, без воды. "
                    "В конце с новой строки: «⚠️ В нашей базе свидетельств об этом равии нет — справка собрана ИИ по памяти, "
                    "сверяйте с первоисточниками (الجرح والتعديل، تقريب التهذيب).»")
            вопрос = "Передатчик хадисов: " + name

        bio = await loop.run_in_executor(None, ask_neuro, вопрос, sysm) or ""
        bio = bio.strip()
        if bio and len(bio) > 15:
            await loop.run_in_executor(None, rijal_ai_put, ключ_кэша, bio)
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

    async def backup_push(r):
        # #259/#261: локальный backup_muslimoon.ps1 заливает сюда свежий Muslimoon_RECOVERY.zip,
        # бот пересылает САМ ФАЙЛ в ЖУРНАЛ УВЕДОМЛЕНИЙ (LOG_CHAT) + владельцу в ЛС (приватно — внутри журналы, R42).
        # Аутентификация — общий секрет BACKUP_SECRET (env Railway == локальный .backup_secret).
        if not application:
            return _cors(web.json_response({'error': 'no_app'}, status=503))
        if not BACKUP_SECRET:
            return _cors(web.json_response({'error': 'disabled', 'message': 'BACKUP_SECRET не задан в env Railway'}, status=503))
        try:
            secret = ''; caption = ''; filename = 'Muslimoon_RECOVERY.zip'; data = None
            reader = await r.multipart()
            async for part in reader:
                if part.name == 'secret':
                    secret = (await part.text()).strip()
                elif part.name == 'caption':
                    caption = (await part.text()).strip()
                elif part.name == 'file':
                    filename = part.filename or filename
                    data = await part.read(decode=False)
            if not secret or secret.strip() != (BACKUP_SECRET or '').strip():   # #259: strip обеих сторон — невидимый пробел/перенос в env Railway давал ложный 403
                return _cors(web.json_response({'error': 'auth'}, status=403))
            if not data:
                return _cors(web.json_response({'error': 'no_file'}, status=400))
            if len(data) > 49 * 1024 * 1024:
                return _cors(web.json_response({'error': 'too_big', 'size': len(data)}, status=413))
            kb = round(len(data) / 1024)
            cap = ("📦 БЭКАП Muslimoon · " + (caption or ("свежий " + filename)) + (" (%d КБ)" % kb)) + "\n🗄 Резервная копия (журналы+bot.py+index.html). Приватно (R42) — не пересылать."
            sent = []
            for chat in (LOG_CHAT_ID, OWNER_ID):
                try:
                    await application.bot.send_document(chat, document=bytes(data), filename=filename, caption=cap[:1000])
                    sent.append(chat)
                except Exception:
                    pass
            return _cors(web.json_response({'ok': bool(sent), 'sent': sent, 'size': len(data), 'filename': filename}))
        except Exception as e:
            return _cors(web.json_response({'error': str(e)[:160]}, status=500))

    async def hermes_hb(r):
        # 🌩 пульс ПК для Гермес-релея: klod_responder шлёт каждые ~2 мин; секрет = BACKUP_SECRET
        try:
            d = await r.json()
        except Exception:
            d = {}
        if not BACKUP_SECRET or (d.get('secret') or '').strip() != BACKUP_SECRET.strip():
            return _cors(web.json_response({'error': 'auth'}, status=403))
        _hermes_hb['ts'] = time.time()
        return _cors(web.json_response({'ok': True}))

    a = web.Application(client_max_size=50 * 1024 * 1024)   # #259: дефолт aiohttp=1МБ рубил бэкап-zip (~1.2МБ) как «Request Entity Too Large» ещё до обработчика
    a.add_routes([web.get('/api/health', health), web.get('/api/nvidia_test', nvidia_test), web.get('/api/gpt_test', gpt_test), web.post('/api/claude_notify', claude_notify), web.post('/api/polka', polka_put), web.post('/api/upd', upd_post), web.post('/api/skazat', skazat), web.post('/api/golos', golos), web.post('/api/oc_balans', oc_balans), web.post('/api/fayl', fayl), web.post('/api/ochered', ochered), web.post('/api/vygovor', vygovor_put), web.post('/api/send_poll', send_poll_api), web.post('/api/neuro', neuro), web.post('/api/assistant', assistant), web.post('/api/groupai', groupai),
                  web.post('/api/translate', translate), web.get('/api/search', search), web.get('/api/wide', wide),
                  web.get('/api/maktaba', maktaba), web.get('/api/rijal', rijal),
                  web.post('/api/access', access), web.post('/api/balance', balance),
                  web.post('/api/feedback', feedback), web.post('/api/searchlog', searchlog),
                  web.post('/api/pick', picklog), web.get('/api/topclicks', topclicks), web.get('/api/trending', trending),
                  web.post('/api/tashkeel', tashkeel),
                  web.get('/api/takhrij', takhrij_read), web.post('/api/takhrij', takhrij_save),
                  web.get('/api/narrator', narrator), web.post('/api/narrator_ai', narrator_ai), web.post('/api/hit', hit),
                  web.get('/api/popular', popular), web.get('/api/arabus', arabus),
                  web.post('/api/wordai', wordai), web.post('/api/explain', explain), web.post('/api/book_rag', book_rag),
                  web.get('/api/version', version), web.post('/api/rag_embed', rag_embed), web.post('/api/rag_find', rag_find),   # 26.07.2026: вектор вопроса для RAG-поиска по Бухари (сам поиск — в браузере)
                  web.post('/api/rag_limits', rag_limits), web.get('/api/rag_limits', rag_limits),   # #673: остаток запросов нажимающему (и расход поимённо — владельцу)
                  web.post('/api/booksearch', booksearch),
                  web.post('/api/booktrans', booktrans), web.post('/api/bookinfo', bookinfo),
                  web.post('/api/authorinfo', authorinfo), web.get('/api/qaudio', qaudio),
                  web.post('/api/errlog', errlog), web.post('/api/narrator_rijal', narrator_rijal),
                  web.post('/api/structure', structure_results),
                  web.get('/api/book_page', book_page), web.get('/api/book_toc', book_toc), web.get('/api/book_meta', book_meta), web.post('/api/isnad_ai', isnad_ai_h),
                  web.post('/api/devfeedback', devfeedback), web.post('/api/worklog', worklog),
                  web.post('/api/rag_feedback', rag_feedback),   # #671: отметка «не туда»/«в точку» у RAG-результата
                  web.post('/api/backup_push', backup_push),
                  web.post('/api/hermes_hb', hermes_hb),
                  web.options('/api/{t:.*}', opt)])
    runner = web.AppRunner(a); await runner.setup()
    port = int(os.environ.get('PORT', '8080'))
    site = web.TCPSite(runner, '0.0.0.0', port); await site.start()
    try:
        await loop.run_in_executor(None, load_access)   # прогреть правила доступа на старте
    except Exception:
        pass
    print("API server on port", port)

async def _req_imgs_export(application):
    """TB-4/M437: скрины заявок владельца — ВЫГРУЗИТЬ В data/req_img/<id>.json (b64), чтобы Claude видел их сам.
    One-shot на старте: проходит по requests[] с imgkey, докачивает отсутствующие (старые file_id живы)."""
    try:
        j = _journal_load()
        todo = [r for r in j.get("requests", []) if r.get("imgkey") and not r.get("img_saved")]
        n = 0
        for r in todo[:30]:
            try:
                f = await application.bot.get_file(r["imgkey"])
                import base64
                from io import BytesIO
                bio = BytesIO()
                await f.download_to_memory(out=bio)
                b64 = "data:image/jpeg;base64," + base64.b64encode(bio.getvalue()).decode()
                _data_put("req_img/%d.json" % int(r["id"]), {"b64": b64, "d": r.get("d", "")}, "req img %s" % r["id"])
                r["img_saved"] = True
                n += 1
            except Exception:
                pass
        if n:
            _journal_save("выгружено скринов заявок: %d" % n)
            try:
                await application.bot.send_message(OWNER_ID, "📤 Скрины твоих заявок выгружены в журнал (%d шт) — Claude теперь видит их сам." % n)
            except Exception:
                pass
    except Exception as e:
        print("req imgs export failed:", e)

async def _setup(application):
    # 📢 05.08.2026, заявка владельца: «можешь в рабочий журнал слать, когда деплоится на
    # Railway и когда закончено? а то чтобы посмотреть, деплоится ли, надо постоянно
    # открывать Railway и смотреть».
    # Накладно ли — нет. «Деплой начался» из облака узнать нечем и незачем, а вот «деплой
    # ЗАКОНЧЕН» бот знает точнее всех: он в этот самый миг и просыпается. Одно сообщение
    # при старте — и открывать Railway больше не нужно. Стоит это ноль.
    try:
        _вер = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")[:7] or "—"
        _сообщ = os.environ.get("RAILWAY_GIT_COMMIT_MESSAGE", "").split(chr(10))[0][:120]
        _строки = ["🚀 БОТ ПОДНЯЛСЯ ПОСЛЕ ДЕПЛОЯ",
                   "🕐 " + _now_msk(),
                   "🔖 сборка " + _вер]
        if _сообщ:
            _строки.append("📝 " + _сообщ)
        _строки.append("Открывать Railway не нужно: пришло это сообщение — значит деплой "
                       "закончен и бот жив.")
        await application.bot.send_message(LOG_CHAT_ID, chr(10).join(_строки))
    except Exception:
        pass
    try:
        await _req_imgs_export(application)
    except Exception:
        pass
    try:
        if application.job_queue:
            application.job_queue.run_repeating(_claude_timer_poll, interval=40, first=15)   # owner: «оперативно» — не ждать активности в чате
    except Exception as e:
        print("claude job_queue setup failed:", e)
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
        # Claude → ЖУРНАЛ (только LOG_CHAT, НЕ в публичный канал): отчёты по ошибкам/работе.
        # Закон владельца: ошибку решил → отчитайся в журнал в тот же день. Я пишу journal_note.txt, бот постит при рестарте (дедуп).
        try:
            jn = ""
            rj = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/journal_note.txt",
                              headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}, timeout=8)
            if rj.status_code == 200:
                jn = base64.b64decode(rj.json().get("content", "")).decode("utf-8").strip()
            if jn and jn != (j.get("journal_note") or {}).get("note", ""):
                await application.bot.send_message(LOG_CHAT_ID, jn, disable_web_page_preview=True)
                j["journal_note"] = {"note": jn, "d": datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
                _journal_save("journal_note → LOG")
        except Exception:
            pass
        # 08.07.2026 (С58): РЕСТАРТ-ЧЕК В КАНАЛ УДАЛЁН (владелец поймал посты-близнецы 867≡870).
        # Он постил update_note.txt в @muslimoonapp при КАЖДОМ рестарте Railway (редеплой = любой пуш) и был
        # ВТОРЫМ, НЕзависимым от очереди писателем в канал: если после его ноты очередь успевала запостить
        # ДРУГУЮ, сверка-с-одним-последним промахивалась и нота уходила ПОВТОРНО (через пару позиций — 867/870).
        # Теперь канал наполняет ТОЛЬКО очередь (_app_channel_watcher ниже) + ручной «анонс», оба через единый
        # _channel_claim с ОКНОМ дедупа. update_note.txt остаётся лишь для модалки «что нового» во фронте (fetch),
        # напрямую в канал он больше НЕ постится — единственный путь в @muslimoonapp это update_notes_queue.json.
    except Exception as e:
        print("deploy notify block failed:", e)
    # Авто-вотчер канала @muslimoonapp: фронт-деплои (GitHub Pages) НЕ рестартят Railway,
    # поэтому стартовый пост выше срабатывает ТОЛЬКО при редеплое бэкенда. Эта фоновая
    # задача каждые 5 мин сама читает КОРНЕВОЙ update_note.txt из репозитория и постит в
    # канал, если нота новее последней опубликованной (дедуп — через journal app_post,
    # тот же, что у стартового блока → двойных постов нет). Канал больше НЕ отстаёт.
    try:
        asyncio.create_task(_app_channel_watcher(application))
        threading.Thread(target=_hermes_cloud_relay, daemon=True).start()   # 🌩 Гермес-облако (ПК выключен → отвечает Railway)
    except Exception as e:
        print("app channel watcher start failed:", e)
    # #147: разовая авто-обработка разборов достоверности /11..173 из @hadis_isnad (бот — участник)
    try:
        asyncio.create_task(_razbory_fetch_bg(application))
    except Exception as e:
        print("razbory fetch start failed:", e)
    # 🧩 RAG keep-alive: пинг HF Space каждые 5 мин, чтобы оперативная база НИКОГДА не засыпала
    try:
        asyncio.create_task(_hf_keepalive(application))
    except Exception as e:
        print("hf keepalive start failed:", e)

async def _razbory_fetch_bg(application):
    """#147: разово тянет разборы /11..173 из @hadis_isnad (бот — участник): текст/аудио→Whisper→data/razbory.json.
    Идемпотентно (пропускает готовые), по одному с паузой (щадим Whisper/баланс), сохраняет инкрементально."""
    CH = "@hadis_isnad"; LO, HI = 11, 173
    await asyncio.sleep(40)   # дать боту прогрузиться
    try:
        store = _data_get("razbory.json", {}) or {}
    except Exception:
        store = {}
    if store.get('_done'):   # #205-фикс: уже прошли весь диапазон → НЕ перезапускать/НЕ слать DM на каждом рестарте (38 несуществующих id всегда «missing» — спамило владельца)
        return
    missing = [n for n in range(LO, HI + 1) if str(n) not in store]
    if not missing:
        store['_done'] = True
        try: _data_put("razbory.json", store, "razbory _done")
        except Exception: pass
        return
    try:
        await application.bot.send_message(OWNER_ID, f"📥 Авто-обработка разборов {CH}: тяну {len(missing)} постов (из {HI-LO+1}). Аудио → Whisper → сохраняю по мере готовности.")
    except Exception:
        pass
    done = 0
    for mid in missing:
        try:
            m = await application.bot.forward_message(LOG_CHAT_ID, CH, mid)
            txt = (m.text or m.caption or "").strip()
            kind = "text"
            if (m.voice or m.audio) and len(txt) < 60:
                kind = "audio"
                media = m.voice or m.audio
                f = await media.get_file()
                ext = ".ogg" if m.voice else ".mp3"
                p = f"/tmp/raz_{mid}{ext}"
                await f.download_to_drive(p)
                tr = transcribe_audio(p)
                if tr:
                    txt = (txt + "\n" + tr).strip()
                try: os.remove(p)
                except Exception: pass
            try: await application.bot.delete_message(LOG_CHAT_ID, m.message_id)
            except Exception: pass
            if txt:
                store[str(mid)] = {"text": txt[:9000], "kind": kind, "url": f"https://t.me/hadis_isnad/{mid}", "n": mid}
                done += 1
                if done % 5 == 0:
                    try: _data_put("razbory.json", store, f"razbory bg → {mid} (#147)")
                    except Exception: pass
        except Exception:
            pass
        await asyncio.sleep(4)   # щадим лимиты/баланс
    store['_done'] = True   # #205-фикс: весь диапазон пройден — больше НЕ перезапускать/НЕ слать DM (38 несуществующих id всегда «missing»)
    try: _data_put("razbory.json", store, f"razbory bg done: {len(store)} (#147)")
    except Exception: pass
    try:
        await application.bot.send_message(OWNER_ID, f"✅ Разборы: в базе {len(store)} (data/razbory.json). Больше авто-обработка не перезапускается. Claude оформит карточки.")
    except Exception:
        pass

def _format_channel_post(note):
    """ЗАКОН (С31, владелец): пост обновления в @muslimoonapp = [скрин из приложения] + анонс + СВОРАЧИВАЕМАЯ инструкция (Telegram expandable-цитата).
    Формат update_note.txt:
        SHOT: shots/v605.png        ← опц. ПЕРВАЯ строка: относит. путь (Pages) или http-URL скрина
        <анонс: заголовок + пункты>
        ИНСТРУКЦИЯ:                 ← опц. маркер; всё ниже уходит в сворачиваемую цитату
        <шаги инструкции>
    Возвращает (photo_url|None, html_body). Тело — под parse_mode="HTML".
    Обратная совместимость: нет маркеров → весь note идёт анонсом (как раньше), просто HTML-эскейп."""
    def esc(s):
        """Экранировать всё, затем вернуть НАШИ теги разметки.

        05.08.2026: ноты пишутся с разметкой, а экранирование не отличало наш тег от угловой
        скобки в чужом тексте — и читатель канала увидел «<b>» буквами. Белый список решает
        обе задачи разом: чужое остаётся безопасным, своё работает."""
        s = (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for тег in ("b", "i", "u", "s", "code", "blockquote"):
            s = s.replace("&lt;%s&gt;" % тег, "<%s>" % тег).replace("&lt;/%s&gt;" % тег,
                                                                   "</%s>" % тег)
        s = s.replace("&lt;blockquote expandable&gt;", "<blockquote expandable>")
        s = re.sub(r'&lt;a href=&quot;([^&]+)&quot;&gt;', r'<a href="\1">', s)
        s = re.sub(r'&lt;a href="([^"]+)"&gt;', r'<a href="\1">', s)
        s = s.replace("&lt;/a&gt;", "</a>")
        return s
    lines = (note or "").split("\n")
    photo = None
    deeplink = None     # #246: глубокая ссылка «открыть в приложении ровно то, что на скрине» (startapp-токен r_muslim_987 / q_2_255 / b_16_78)
    rest = []
    for ln in lines:
        m = re.match(r'^\s*SHOT:\s*(.+?)\s*$', ln)
        if m and photo is None and not rest:            # только если ещё не было текста (SHOT — в шапке)
            p = m.group(1).strip()
            photo = p if p.startswith("http") else ("https://germanyalfurqan-eng.github.io/hadith-bot/" + p.lstrip("/"))
            continue
        ml = re.match(r'^\s*LINK:\s*(.+?)\s*$', ln)
        if ml and deeplink is None and not rest:
            tok = ml.group(1).strip()
            deeplink = tok if tok.startswith("http") else ("https://t.me/muslimoontt_bot?startapp=" + tok)
            continue
        rest.append(ln)
    main, instr, in_instr = [], [], False
    for ln in rest:
        if not in_instr and re.match(r'^\s*(?:📋\s*)?ИНСТРУКЦИЯ\s*:?\s*$', ln.strip(), re.I):
            in_instr = True
            continue
        (instr if in_instr else main).append(ln)
    main_txt = "\n".join(main).strip()
    instr_txt = "\n".join(instr).strip()
    body = esc(main_txt)
    if instr_txt:
        body += "\n\n<blockquote expandable>📋 <b>Как пользоваться</b>\n" + esc(instr_txt) + "</blockquote>"
    if deeplink:
        body += '\n\n👉 <a href="' + esc(deeplink) + '">Открыть в приложении то, что на скрине</a>'
    body += "\n\n———\n📲 Приложение: https://t.me/muslimoontt_bot?startapp\n🤖 Бот: https://t.me/muslimoontt_bot"
    return photo, body

async def _post_app_channel(bot, note, note_id=None):
    """Единый постер в @muslimoonapp: скрин (если есть) + анонс + сворачиваемая инструкция. Фолбэк — текстом, чтобы пост не потерялся.

    ЗАЯВКА ВЛАДЕЛЬЦА #687 (01.08.2026, ссылка на пост t.me/muslimoonapp/1106: «почему обновления
    текст не пишется»). В канал уходили посты БЕЗ текста обновления. Дыр оказалось три, и все три
    закрыты ЗДЕСЬ, в единых воротах, а не в одном из путей (З-40 — чиним КЛАСС, а не случай:
    через эту функцию идут и очередь, и ручной «анонс»):
      ① ГОЛАЯ КАРТИНКА. Подпись к фото у Telegram ограничена 1024 знаками. Когда тело было
         длиннее, код слал send_photo ВООБЩЕ БЕЗ caption, а текст — отдельным вторым сообщением.
         Первым в канале появлялся пост из одной картинки — это и есть «текст не пишется».
         Теперь подпись есть ВСЕГДА: тело режется по безопасной границе (перед сворачиваемой
         цитатой, иначе по концу строки — чтобы не разорвать разметку), начало идёт подписью,
         остаток — вторым сообщением.
      ② ПУСТЫШКА. Чистилка _clean_announce, срезав ноту целиком, возвращает заглушку
         «Обновление приложения.» — и в канал уходил пост из этой заглушки и футера со ссылками
         (так вышел пост #1112). Сторож стоял только в очереди и только для нот длиннее 120
         знаков, а ручной «анонс» шёл мимо него вовсе. Теперь пустой анонс не публикуется
         НИКОГДА: бросаем исключение, вызывающий откатит заявку и скажет владельцу.
      ③ ЗАПАСНОЙ ПУТЬ ПАДАЛ ТАК ЖЕ. Ветка except слала то же тело с тем же parse_mode="HTML" —
         если отправку завалила именно разметка, второй заход валился по той же причине.
         Теперь каскад: с разметкой → тот же текст без разметки → и только потом ошибка наверх.
    """
    # ВОРОТА ЧИСТОТЫ (владелец 26.07.2026): через эту функцию идёт ВСЁ, что попадает в канал —
    # и очередь, и ручной «анонс». Значит одна проверка здесь закрывает все пути разом.
    # Личная речь владельца и рабочая кухня (ключи, Railway, бэкапы) наружу не выходят.
    note = _clean_announce(note)
    # СТРАЖ ПУСТОГО АНОНСА (дыра ② выше). Считаем ТОЛЬКО собственный текст обновления: без
    # служебных строк SHOT:/LINK: и без постоянного футера со ссылками, который добавляется ниже
    # и создаёт видимость «пост не пустой». Лучше не опубликовать ничего и разбудить владельца,
    # чем занять канал постом, из которого он ничего о работе не узнает.
    _полезное = "\n".join(стр for стр in str(note or '').split("\n")
                          if not re.match(r'^\s*(?:SHOT|LINK)\s*:', стр)).strip()
    if len(_полезное) < 15 or _полезное == 'Обновление приложения.':
        raise RuntimeError("пустой анонс: после чистки осталось %d знаков — пост без текста обновления в канал не выпускаю"
                           % len(_полезное))
    photo, body = _format_channel_post(note)
    # ЗАПОМИНАЕМ НОМЕР ПОСТА (владелец 26.07.2026: «обеспечь, чтобы бот умел исправлять любое своё
    # смс, тем более в канале!!!»). Раньше номера не сохранялись — и когда в канал ушли ноты с личной
    # речью владельца, править было НЕЧЕГО: Telegram не даёт боту читать историю канала, а без
    # message_id ни отредактировать, ни удалить нельзя. Теперь каждый пост записывается в журнал,
    # и бот правит свои сообщения сам, без пересылок и без ручной работы владельца.
    ПОДПИСЬ_МАКС = 1024          # предел подписи к фото у Telegram — из-за него и родилась дыра N1

    def _плоско(тело):
        """Тот же текст без разметки — на случай, если Telegram не принял HTML."""
        чист = re.sub(r'<[^>]+>', '', тело or '')
        return чист.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').strip()

    async def _текстом(тело):
        """Тело сообщением: сперва с разметкой, при отказе — тем же текстом без неё (дыра N3)."""
        try:
            return await bot.send_message(APP_CHANNEL_ID, тело, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            return await bot.send_message(APP_CHANNEL_ID, _плоско(тело), disable_web_page_preview=True)

    def _разрезать(тело):
        """Делит тело на подпись к картинке и остаток. Режем ТОЛЬКО по границе строки и НИКОГДА
        внутри сворачиваемой цитаты: разорванный тег Telegram отвергнет, и пост опять уйдёт без
        текста. Если цитата начинается в пределах подписи — режем ровно перед ней; иначе граница
        заведомо попадает в обычный текст анонса, где тегов нет."""
        if len(тело) <= ПОДПИСЬ_МАКС:
            return тело, ''
        поз = тело.find('\n\n<blockquote')
        if 0 < поз <= ПОДПИСЬ_МАКС:
            return тело[:поз].strip(), тело[поз:].strip()
        край = тело.rfind('\n', 0, ПОДПИСЬ_МАКС - 1)
        if край < 200:                     # переносов нет вовсе — режем по длине, разметки тут нет
            край = ПОДПИСЬ_МАКС - 1
        return тело[:край].strip(), тело[край:].strip()

    _отпр = None      # сообщение, по которому потом правится пост (по возможности ТЕКСТОВОЕ)
    if photo:
        подпись, хвост = _разрезать(body)
        try:
            _отпр = await bot.send_photo(APP_CHANNEL_ID, photo=photo, caption=подпись, parse_mode="HTML")
        except Exception:
            # картинка не открылась (404) или подпись не прошла разметкой — публикуем ВЕСЬ текст
            _отпр = await _текстом(body)
            хвост = ''
        if хвост:
            try:
                _отпр = await _текстом(хвост)
            except Exception:
                # начало обновления уже опубликовано подписью к картинке — пост НЕ пустой,
                # поэтому заявку не роняем: иначе следующий тик перепостит и картинку заодно.
                pass
    else:
        # если не вышло ни с разметкой, ни без неё — исключение уходит НАВЕРХ: вызывающий откатит
        # заявку (В-42) и скажет владельцу, вместо тихого «числится запощенным, а в канале нет».
        _отпр = await _текстом(body)
    try:
        if _отпр is not None:
            # ДОКАЗАТЕЛЬСТВО ДОСТАВКИ (закон З-47, класс выговора В-42). Номер поста присваивает
            # сам Telegram — и только он доказывает, что обновление реально вышло в канал.
            # ЧТО БЫЛО: ключом служило ПЕРВОЕ СЛОВО ноты. Ноты начинаются с эмодзи-новинки, за
            # которым идёт номер версии, поэтому в живом журнале вместо версий лежали ключи
            # «(эмодзи)» и «Обновление», и каждый следующий пост ЗАТИРАЛ предыдущий: проверить
            # доставку по закону стало НЕВОЗМОЖНО — v1253-v1256 и v1258 числились незапощенными,
            # хотя посты вышли. Прежняя заплатка «поискать номер в тексте» не работала вовсе: в
            # её шаблон вместо границ слова попали НЕВИДИМЫЕ управляющие символы (код 8), и
            # совпадения не находилось НИКОГДА — ключ всё равно оставался эмодзи.
            # ЧИНИМ ПРИЧИНУ, А НЕ СИМПТОМ: id версии приходит АРГУМЕНТОМ от того, кто знает его
            # точно (очередь). Поиск номера в тексте — запасной путь для ручного «анонса», где id
            # взять неоткуда; первое слово ноты — последний резерв, чтобы ключ не был пустым.
            вер = str(note_id or '').strip()[:12]
            if not вер:
                _mv = re.search(r'v(\d{3,5})', str(note or ''))
                вер = ('v' + _mv.group(1)) if _mv else ((str(note or '').strip().split() or ['?'])[0])[:12]
            _мид = _отпр.message_id
            def _зап(o):
                o.setdefault('app_post_msgids', {})[вер] = _мид
                return o
            _data_atomic_mutate("journal.json", _зап, "app_post_msgids: запомнили номер поста " + вер)
    except Exception:
        pass

async def _app_channel_watcher(application):
    """Фон: раз в 5 мин публикует новую update_note.txt в @muslimoonapp (см. _setup)."""
    while True:
        try:
            await asyncio.sleep(300)
            # ЧИСТКА ПОСТОВ КАНАЛА ОТ ЛИЧНОГО (заявка владельца #666, 26.07.2026:
            # «я сто раз сказал убери личные переписки»). Номера постов берём из файла
            # clean_posts.txt (по номеру в строке) — их видно прямо в ссылке t.me/muslimoonapp/NNNN.
            # Каждый пост перечитываем, прогоняем через _clean_announce и переписываем.
            try:
                rc = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/clean_posts.txt",
                                  headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}, timeout=8)
                if rc.status_code == 200:
                    _спис = base64.b64decode(rc.json().get("content", "")).decode("utf-8").strip()
                    _jc = _journal_load()
                    # ⛔ ПРИЗНАК ИЗМЕНЕНИЯ — ХЕШ ВСЕГО ФАЙЛА, А НЕ ЕГО НАЧАЛО (02.08.2026).
                    # Было `_спис[:60]` — первые шестьдесят знаков. А там лежит НЕИЗМЕННЫЙ
                    # комментарий-заголовок «# Посты канала @muslimoonapp, которые надо…».
                    # Значит сколько постов в список ни добавляй, признак не менялся и чистка
                    # НЕ ЗАПУСКАЛАСЬ НИКОГДА после первого раза (26.07.2026 11:46). Владелец
                    # просил трижды — «я сто раз сказал убери личные переписки» (#666) — пост
                    # 1081 стоял в списке и всё это время оставался с его прямой речью.
                    _хеш = hashlib.md5(_спис.encode("utf-8")).hexdigest()
                    if _спис and _хеш != (_jc.get("clean_posts") or {}).get("flag", ""):
                        _почищено, _мимо = [], []
                        for _стр in _спис.splitlines():
                            _стр = _стр.strip()
                            if not _стр or _стр.startswith("#"):
                                continue
                            _мид = "".join(c for c in _стр if c.isdigit())
                            if not _мид:
                                continue
                            # текст поста берём из очереди нот по версии, если она указана в строке
                            _вер = ""
                            for _w in _стр.split():
                                if _w.startswith("v") and _w[1:].isdigit():
                                    _вер = _w
                            _нота = ""
                            if _вер:
                                try:
                                    _rq2 = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/update_notes_queue.json",
                                                        headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}, timeout=8)
                                    _оч2 = json.loads(base64.b64decode(_rq2.json().get("content", "")).decode("utf-8") or "[]") if _rq2.status_code == 200 else []
                                    _нота = next((x.get("note", "") for x in _оч2 if x.get("id") == _вер), "")
                                except Exception:
                                    _нота = ""
                            if not _нота:
                                _мимо.append(_мид + " (нет текста)"); continue
                            try:
                                _p, _b = _format_channel_post(_clean_announce(_нота))
                                await application.bot.edit_message_text(chat_id=APP_CHANNEL_ID, message_id=int(_мид),
                                                                        text=_b, parse_mode="HTML",
                                                                        disable_web_page_preview=True)
                                _почищено.append(_мид)
                            except Exception as _e:
                                # ⛔ ПОЧЕМУ НЕ ВЫШЛО — НАДО СКАЗАТЬ СЛОВАМИ (02.08.2026, заявка #666).
                                # Telegram не даёт боту править СВОИ ЖЕ посты старше 48 часов. Пост 1081 —
                                # недельной давности, и переписать его мы не сможем НИКОГДА, сколько ни чини
                                # механизм. Раньше это уходило владельцу обрывком английской ошибки, он читал
                                # его как очередную поломку и просил снова. Теперь говорим прямо: править
                                # нечем, вот ссылка, сделай сам одним нажатием.
                                _txt_e = str(_e)
                                if "can't be edited" in _txt_e or "message to edit not found" in _txt_e:
                                    _мимо.append("%s — СТАРШЕ 48 ЧАСОВ, бот править не может: открой "
                                                 "https://t.me/muslimoonapp/%s и поправь или удали сам" % (_мид, _мид))
                                else:
                                    _мимо.append("%s (%s)" % (_мид, _txt_e[:60]))
                        _jc["clean_posts"] = {"flag": _хеш, "d": datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
                        _journal_save("чистка постов канала от личного")
                        try:
                            await application.bot.send_message(OWNER_ID,
                                "🧹 Чистка постов канала: переписано %s%s"
                                % (", ".join(_почищено) or "—",
                                   (chr(10)+"не вышло: " + ", ".join(_мимо)) if _мимо else ""))
                        except Exception:
                            pass
            except Exception:
                pass

            # РАЗОВОЕ ОБЪЯВЛЕНИЕ В @jamaat_ru (владелец 26.07.2026: «если работает сейчас,
            # объявление вышли, обрадуй»). Тот же приём, что с манифестом: маркер-файл в репо,
            # бот шлёт один раз и запоминает метку — повторов не будет.
            try:
                rj = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/jamaat_note.txt",
                                  headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}, timeout=8)
                if rj.status_code == 200:
                    _текст = base64.b64decode(rj.json().get("content", "")).decode("utf-8").strip()
                    _jj = _journal_load()
                    _метка = _текст[:40]
                    if _текст and _метка != (_jj.get("jamaat_note") or {}).get("flag", ""):
                        await application.bot.send_message(JAMAAT_RU_CHAT_ID, _текст,
                                                           parse_mode="HTML", disable_web_page_preview=True)
                        _jj["jamaat_note"] = {"flag": _метка, "d": datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
                        _journal_save("объявление о RAG → @jamaat_ru")
            except Exception:
                pass

            # M373: разовая отправка МАНИФЕСТА (PDF) в канал — по маркеру manifest_flag.txt в корне репо
            try:
                rf = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/manifest_flag.txt",
                                  headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}, timeout=8)
                if rf.status_code == 200:
                    flag = base64.b64decode(rf.json().get("content", "")).decode("utf-8").strip()
                    jm = _journal_load()
                    if flag and flag != (jm.get("manifest_post") or {}).get("flag", ""):
                        await application.bot.send_document(APP_CHANNEL_ID,
                            document="https://germanyalfurqan-eng.github.io/hadith-bot/manifest.pdf",
                            caption="⚖️ МАНИФЕСТ О ПРОГРАММЕ «MUSLIMOON APP» — фундамент проекта (Конституция проекта). 11.06.2026")
                        jm["manifest_post"] = {"flag": flag, "d": datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
                        _journal_save("манифест (PDF) → канал приложения")
            except Exception as e:
                print("manifest post error:", e)
            # ЗАКОН 17.06 (владелец, «сто раз»): бэкап → в рабочий журнал (LOG_CHAT) + владельцу в ЛС, куда идут ошибки.
            try:
                rb = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/backup_note.txt",
                                  headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}, timeout=8)
                if rb.status_code == 200:
                    bnote = base64.b64decode(rb.json().get("content", "")).decode("utf-8").strip()
                    jb = _journal_load()
                    if bnote and bnote != (jb.get("backup_post") or {}).get("note", ""):
                        _btxt = "💾 " + bnote
                        try: await application.bot.send_message(LOG_CHAT_ID, _btxt)
                        except Exception: pass
                        try: await application.bot.send_message(OWNER_ID, _btxt)
                        except Exception: pass
                        jb["backup_post"] = {"note": bnote, "d": datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
                        _journal_save("backup_post → рабочий журнал + ЛС владельца")
            except Exception as e:
                print("backup note post error:", e)
            # ПРЕЦЕДЕНТ 01.07.2026 (владелец, ТРЕВОГА): при частых деплоях (несколько версий за <5 мин) старый механизм
            # «сравни update_note.txt с последним запощенным» ТЕРЯЛ анонсы — если файл перезаписывался чаще, чем раз
            # в 5 мин, промежуточные версии никогда не проверялись (видели только САМУЮ ПОСЛЕДНЮЮ на момент тика).
            # Фикс: очередь update_notes_queue.json (список {id, note}, я ДОПИСЫВАЮ, не перезаписываю) + журнал
            # посчитанных id (app_post_ids) — постим ВСЕ ещё не запощенные по очереди, ничего не теряется
            # независимо от скорости деплоя.
            # 02.07.2026 (владелец поймал v905 И v906 ДВАЖДЫ в канале — «разберись нормально», не заплатками):
            # СТАРЫЙ одиночный путь (сравнение корневого update_note.txt с app_post.note) УДАЛЁН целиком, а не
            # заглушен доп.условием — он был АРХИТЕКТУРНО ИЗБЫТОЧЕН: 1) «анонс»-команда постит СИНХРОННО сама
            # (owner_cmd, строка ~2586), watcher ей не нужен; 2) окно «Что нового» в аппе читает update_note.txt
            # НАПРЯМУЮ с фронта (fetch), тоже не через watcher/journal. Единственный писатель app_post-очереди для
            # @muslimoonapp — ОЧЕРЕДЬ выше. Два независимых пути к одному каналу = гарантированная гонка/дубль
            # при любой задержке одного из GET-запросов к GitHub API — убрано насовсем, не патчем поверх.
            try:
                rq = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/update_notes_queue.json",
                                  headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}, timeout=8)
                queue = []
                if rq.status_code == 200:
                    queue = json.loads(base64.b64decode(rq.json().get("content", "")).decode("utf-8") or "[]")
                if isinstance(queue, list) and queue:
                    j = _journal_load()
                    posted_ids = set(j.get("app_post_ids") or [])
                    _stuck = set(j.get("app_post_stuck") or [])   # отложены после 3 неудач — не дёргаем каждые 5 мин
                    pending = [x for x in queue if isinstance(x, dict) and x.get("id") and x.get("note")
                               and x["id"] not in posted_ids and x["id"] not in _stuck]
                    posted_now = 0
                    for item in pending[:8]:   # предохранитель: не больше 8 постов за один тик (не заспамить канал разом)
                        # 04.07.2026 (владелец поймал дубли ЧЕТЫРЕ РАЗА, несмотря на 2 предыдущих фикса —
                        # см. docstring _channel_claim): ОДИН атомарный вызов делает id-claim И note-claim
                        # ВМЕСТЕ, ДО поста — закрывает окно гонки с «анонс»/рестарт-чеком полностью.
                        if not _channel_claim(item["note"], item_id=item["id"]):
                            # False значит ЛИБО id уже был занят (другой инстанс очереди), ЛИБО текст похож
                            # на уже запощенный (кто-то другой путь — анонс/рестарт — успел раньше). В обоих
                            # случаях — тихо пропускаем сам пост, но если это была РЕАЛЬНАЯ похожая заметка
                            # (не просто гонка id), даём знать владельцу по-человечески, не жаргоном.
                            last_posted_note = (_journal_cache or {}).get("app_post", {}).get("note", "") if _journal_cache else ""
                            sim = difflib.SequenceMatcher(None, (item["note"] or "").strip(), (last_posted_note or "").strip()).ratio() if last_posted_note else 0.0
                            if sim >= 0.90 and item["id"] not in (set(_journal_cache.get("app_post_ids") or []) if _journal_cache else set()):
                                def _mk_alert(obj, _item=item, _sim=sim):
                                    obj = obj or {}
                                    alerts = obj.get("dup_alerts") or []
                                    alerts.append({"id": _item["id"], "sim": round(_sim, 3), "d": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                                                   "note": (_item["note"] or "")[:200]})
                                    obj["dup_alerts"] = alerts[-100:]
                                    return obj
                                # П-С56-2 (скрин владельца 02:25: алерт каждые 5 мин ВЕЧНО): пропущенный как дубль id
                                # ОБЯЗАН помечаться обработанным — иначе на следующем тике он снова pending и снова алерт.
                                def _mk_alert2(obj, _item=item, _sim=sim, _base=_mk_alert):
                                    obj = _base(obj)
                                    ids = obj.get("app_post_ids") or []
                                    if _item["id"] not in ids:
                                        ids.append(_item["id"])
                                    obj["app_post_ids"] = ids
                                    return obj
                                _ok_a, _newj_a = _data_atomic_mutate("journal.json", _mk_alert2, f"app_post → пропущен как дубль, id {item['id']} помечен")
                                if _ok_a and _newj_a is not None and _journal_cache is not None:
                                    _journal_cache["app_post_ids"] = _newj_a.get("app_post_ids", [])
                                if _ok_a and _newj_a is not None and _journal_cache is not None:
                                    _journal_cache["dup_alerts"] = _newj_a.get("dup_alerts", [])
                                _atxt = ("✅ Я сам заметил и ОСТАНОВИЛ повторную публикацию в канал @muslimoonapp — "
                                         "чуть не вышло ДВА одинаковых поста подряд про одно и то же обновление. "
                                         "Это моя защита сработала как надо, действий от тебя не требуется.\n\n"
                                         f"📋 Про какое обновление речь:\n{(item['note'] or '')[:250]}")
                                try: await application.bot.send_message(LOG_CHAT_ID, _atxt)
                                except Exception: pass
                                try: await application.bot.send_message(OWNER_ID, _atxt)
                                except Exception: pass
                            continue
                        # 🔴 ВЫГОВОР В-41 (владелец 01.08.2026: «ты всё это время не описывал обновления
                        # в канал… 1252 последнее обновление, мне негде иначе узнать что ты сделал»).
                        # ЧТО БЫЛО. Заявка (_channel_claim) ставилась ДО поста и НЕ ОТКАТЫВАЛАСЬ при провале,
                        # а сам вызов Telegram шёл БЕЗ try/except. Любая ошибка отправки → исключение улетало
                        # в общий except ниже, который только печатает в лог Railway (его никто не читает),
                        # ОБРЫВАЛ весь цикл (остальные ожидающие версии тоже пропускались) и оставлял заявку.
                        # Итог: v1253, v1254, v1255, v1256 числятся запощенными, а в канале их НЕТ —
                        # доказано по app_post_msgids: последний реальный пост v1252 (#1104).
                        # ЧИНИМ КЛАСС, А НЕ СЛУЧАЙ: заявка — это ЗАМОК. Работа провалилась → замок отпустить,
                        # владельцу сказать, соседние версии не терять.
                        # СТРАЖ ПУСТЫШКИ (01.08.2026, «канал пишет ересь»): если чистка съела ноту
                        # почти целиком — публиковать нечего. Пост НЕ выходит, заявка откатывается,
                        # владельцу уходит исходный текст, чтобы он переписал его сам.
                        _сыро = re.sub(r"\s+", " ", str(item["note"] or "")).strip()
                        _чист = _clean_announce(item["note"])
                        if len(_сыро) >= 120 and len(_чист) < max(60, len(_сыро) * 0.25):
                            def _откат0(obj, _id=item["id"], _note=item["note"]):
                                obj = obj or {}
                                obj["app_post_ids"] = [x for x in (obj.get("app_post_ids") or []) if x != _id]
                                obj["app_post_notes"] = [x for x in (obj.get("app_post_notes") or [])
                                                         if (x or "").strip() != (_note or "").strip()]
                                return obj
                            try:
                                _data_atomic_mutate("journal.json", _откат0, "почищено до пустышки: " + item["id"])
                            except Exception:
                                pass
                            # БЕЗ СПАМА (владелец: «это че за спам?»): состояние повторяется каждые
                            # 5 минут, поэтому сообщаем ОДИН раз на версию, а не на каждой проверке.
                            _уже = ((_journal_cache or {}).get("app_post_fail_n") or {}).get(item["id"], 0)
                            def _счёт(obj, _id=item["id"]):
                                obj = obj or {}
                                c = obj.get("app_post_fail_n") or {}
                                c[_id] = int(c.get(_id, 0)) + 1
                                obj["app_post_fail_n"] = c
                                return obj
                            try:
                                _ok_c, _nj = _data_atomic_mutate("journal.json", _счёт, "счётчик пустышки " + item["id"])
                                if _ok_c and _nj is not None and _journal_cache is not None:
                                    _journal_cache["app_post_fail_n"] = _nj.get("app_post_fail_n", {})
                            except Exception:
                                pass
                            if _уже == 0:
                                _t = ("НЕ публикую %s в @muslimoonapp: после чистки осталось %d знаков из %d, "
                                      "в канал ушла бы пустышка вместо обновления.\n\nИсходный текст:\n%s\n\n"
                                      "Перепиши без длинных цитат в ёлочках и без служебных слов — опубликую. "
                                      "Об этом сообщаю ОДИН раз, повторов не будет."
                                      % (item["id"], len(_чист), len(_сыро), _сыро[:1500]))
                                for _ч in (OWNER_ID, LOG_CHAT_ID):
                                    try:
                                        await application.bot.send_message(_ч, _t)
                                    except Exception:
                                        pass
                            continue
                        try:
                            # note_id — НАСТОЯЩИЙ id версии из очереди. Именно под ним постер
                            # запишет номер поста в app_post_msgids, и доставку станет видно по
                            # закону З-47 (раньше ключ выводился из текста ноты и был мусорным).
                            await _post_app_channel(application.bot, item["note"], note_id=item["id"])
                            posted_now += 1
                            def _сброс(obj, _id=item["id"]):     # вышло — счётчик неудач обнуляем
                                obj = obj or {}
                                c = obj.get("app_post_fail_n") or {}
                                c.pop(_id, None)
                                obj["app_post_fail_n"] = c
                                obj["app_post_stuck"] = [x for x in (obj.get("app_post_stuck") or []) if x != _id]
                                return obj
                            try: _data_atomic_mutate("journal.json", _сброс, "успех, счётчик сброшен " + item["id"])
                            except Exception: pass
                        except Exception as _e_post:
                            def _откат(obj, _id=item["id"], _note=item["note"]):
                                obj = obj or {}
                                obj["app_post_ids"] = [x for x in (obj.get("app_post_ids") or []) if x != _id]
                                obj["app_post_notes"] = [x for x in (obj.get("app_post_notes") or [])
                                                         if (x or "").strip() != (_note or "").strip()]
                                sb = obj.get("app_post_fails") or []
                                sb.append({"id": _id, "err": str(_e_post)[:200],
                                           "d": datetime.now().strftime("%d.%m.%Y %H:%M:%S")})
                                obj["app_post_fails"] = sb[-50:]
                                return obj
                            try:
                                _data_atomic_mutate("journal.json", _откат,
                                                    "ОТКАТ заявки: пост %s не вышел" % item["id"])
                                if _journal_cache is not None:
                                    _journal_cache["app_post_ids"] = [x for x in (_journal_cache.get("app_post_ids") or []) if x != item["id"]]
                            except Exception:
                                pass
                            # БЕЗ СПАМА (владелец 01.08: «это че за спам? обеспечь чтобы каждое смс
                            # тут было продуктивным»). Провал отправки — это СОСТОЯНИЕ, повторяющееся
                            # каждые 5 минут, а не событие. Сообщаем ОДИН раз при входе в него; после
                            # трёх неудач перестаём и пытаться, чтобы не дёргать Telegram вхолостую.
                            _n_бывш = ((_journal_cache or {}).get("app_post_fail_n") or {}).get(item["id"], 0)
                            def _счёт2(obj, _id=item["id"]):
                                obj = obj or {}
                                c = obj.get("app_post_fail_n") or {}
                                c[_id] = int(c.get(_id, 0)) + 1
                                obj["app_post_fail_n"] = c
                                if c[_id] >= 3:
                                    st = obj.get("app_post_stuck") or []
                                    if _id not in st:
                                        st.append(_id)
                                    obj["app_post_stuck"] = st
                                return obj
                            try:
                                _ok_c2, _nj2 = _data_atomic_mutate("journal.json", _счёт2, "счётчик провалов " + item["id"])
                                if _ok_c2 and _nj2 is not None and _journal_cache is not None:
                                    _journal_cache["app_post_fail_n"] = _nj2.get("app_post_fail_n", {})
                                    _journal_cache["app_post_stuck"] = _nj2.get("app_post_stuck", [])
                            except Exception:
                                pass
                            if _n_бывш == 0:
                                _txt_fail = ("НЕ смог опубликовать обновление %s в @muslimoonapp.\n\n"
                                             "Причина: %s\n\n"
                                             "Заявку откатил, попробую ещё дважды. Сообщаю об этом ОДИН раз — "
                                             "повторов каждые 5 минут не будет. Если не выйдет и с третьей "
                                             "попытки, версия отложится и я скажу отдельно."
                                             % (item["id"], str(_e_post)[:300]))
                                for _чат in (OWNER_ID, LOG_CHAT_ID):
                                    try: await application.bot.send_message(_чат, _txt_fail)
                                    except Exception: pass
                            elif _n_бывш == 2:
                                _txt_fail = ("Обновление %s отложено: три неудачных попытки публикации подряд. "
                                             "Больше не пробую, чтобы не занимать канал вхолостую. "
                                             "Последняя причина: %s\n\nПроверь, остаётся ли бот администратором "
                                             "@muslimoonapp с правом публикации." % (item["id"], str(_e_post)[:300]))
                                for _чат in (OWNER_ID, LOG_CHAT_ID):
                                    try: await application.bot.send_message(_чат, _txt_fail)
                                    except Exception: pass
                            continue   # соседние версии не теряем — идём дальше по очереди
                        await asyncio.sleep(2)   # пауза между постами — не флудить Telegram API
            except Exception as e:
                print("app channel queue watcher error:", e)
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
            # M202 (владелец: «нативная Mini App кнопка в группах, short_name app уже задан»): web_app-инлайн в группах
            # нельзя, но t.me/<bot>/<short_name> открывает мини-апп ВНУТРИ Telegram. Голый WEBAPP_URL (GitHub Pages)
            # выкидывал человека из Telegram — там нет initData, и он упирался в гейт «доступ только для владельца».
            btn = InlineKeyboardButton("📗 Открыть Muslimoon", url="https://t.me/muslimoontt_bot/app")
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
# B-004 ГЛОБАЛЬНЫЙ ФИКС «can't parse entities» (×32 в журнале): спецсимвол (_*[]`) в тексте/имени/запросе ломал Markdown.
# Патчим метод класса Bot.send_message → при ошибке разметки автоматически шлём БЕЗ parse_mode (сообщение НЕ теряется, ошибка не плодится). Покрывает и reply_text (он зовёт send_message).
try:
    from telegram.error import BadRequest as _BadReq
    _BotCls = type(app.bot); _orig_send = _BotCls.send_message
    async def _send_md_safe(self, *a, **kw):
        try:
            return await _orig_send(self, *a, **kw)
        except _BadReq as e:
            if kw.get("parse_mode") and "parse entities" in str(e).lower():
                kw2 = dict(kw); kw2.pop("parse_mode", None)
                return await _orig_send(self, *a, **kw2)
            raise
    _BotCls.send_message = _send_md_safe
    print("B-004 fix: send_message обёрнут (fallback без разметки)")
except Exception as _e:
    print("B-004 fix НЕ применён:", _e)

async def on_poll_answer(update, context):
    """#опросы-13.07: фиксируем голос владельца/джамаата в data/poll_results.json."""
    try:
        pa = update.poll_answer
        if not pa: return
        res = _data_get('poll_results.json', {}) or {}
        rec = res.setdefault(pa.poll_id, {'votes': {}})
        rec['votes'][str(pa.user.id)] = list(pa.option_ids)
        _data_put('poll_results.json', res, 'голос ' + pa.poll_id)
        # «✍️ Свой вариант» = последний вариант → ждём текст ответа следующим сообщением
        try:
            pm = _data_get('poll_map.json', {}) or {}
            info = pm.get(pa.poll_id)
            if info and pa.user.id == OWNER_ID and pa.option_ids and pa.option_ids[0] == len(info.get('opts', [])) - 1:
                _data_put('poll_pending.json', {'poll_id': pa.poll_id, 'ref': info.get('ref', ''), 'q': info.get('q', '')}, 'ждём свой вариант ' + pa.poll_id)
        except Exception:
            pass
    except Exception:
        pass

async def on_reaction(update, context):
    """#лайки-13.07: владелец ставит ❤️/👍 на опрос — фиксируем «понравившийся» в data/poll_likes.json."""
    try:
        mr = update.message_reaction
        if not mr or (mr.user and mr.user.id != OWNER_ID): return
        emojis = []
        for rx in (mr.new_reaction or []):
            e = getattr(rx, 'emoji', None) or getattr(rx, 'custom_emoji_id', None)
            if e: emojis.append(str(e))
        likes = _data_get('poll_likes.json', {}) or {}
        key = str(mr.chat.id) + ':' + str(mr.message_id)
        if emojis: likes[key] = {'emojis': emojis, 'ts': _now_msk()}
        else: likes.pop(key, None)   # реакцию сняли
        _data_put('poll_likes.json', likes, 'лайк ' + key)
    except Exception:
        pass
app.add_handler(MessageReactionHandler(on_reaction))
app.add_handler(PollAnswerHandler(on_poll_answer))
async def on_rag_help(update, context):
    """Кнопка «Как пользоваться РАГ» под каждым ответом (владелец 27.07.2026: «сделай кнопку,
    которая показывает, как пользоваться рагом, что есть только бухари пока, что это жрёт лимиты»)."""
    q = update.callback_query
    try:
        await q.answer()
        await q.message.reply_text(СПРАВКА_РАГ, parse_mode='HTML', disable_web_page_preview=True)
    except Exception:
        try:
            await q.answer('Справка недоступна', show_alert=True)
        except Exception:
            pass

app.add_handler(CallbackQueryHandler(on_rag_help, pattern='^rag_help$'))
# #614/#660: кнопки бана/ограничения под уведомлением о входе. Шаблон строгий — чужие
# callback_data сюда не попадут, а свои разбираются по формату mod:<действие>:<чат>:<кого>.
# 🔴 05.08.2026: шаблон был r'^mod:(ban|mute):-?\d+:\d+$' — и новые кнопки меню ограничений
# (mod:m_media, mod:m_voice, mod:m_all1h…) до обработчика бы НЕ ДОШЛИ: Telegram молча
# проглотил бы нажатие. Кнопку сделал, а дверь ей не открыл. Расширяю до всего семейства mod:.
app.add_handler(CallbackQueryHandler(on_moderate, pattern=r'^mod:'))
app.add_handler(CallbackQueryHandler(on_dsoc_back, pattern=r'^dsocback:'))
app.add_handler(CallbackQueryHandler(on_neudacha, pattern=r'^neud:'))
app.add_handler(CallbackQueryHandler(on_ctx, pattern=r'^ctx:'))
app.add_handler(CommandHandler("start", start_cmd))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.VIDEO | filters.PHOTO | filters.Document.ALL, handle))
# ===== TB-9: уведомление владельцу о ЗАКРЕПЕ в группе/канале, где сидит бот =====
# Сервисное сообщение о закрепе НЕ ловится TEXT/media-фильтрами выше — отдельный хендлер на StatusUpdate.PINNED_MESSAGE.
async def handle_pinned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.effective_message
        pm = getattr(msg, "pinned_message", None) if msg else None
        if not pm:
            return
        ch = update.effective_chat
        if getattr(ch, "type", "") == "private":
            return   # закреп в личке с ботом владельцу не интересен
        title = getattr(ch, "title", None) or (("@" + ch.username) if getattr(ch, "username", None) else str(ch.id))
        body = (pm.text or pm.caption or "").strip() or "(медиа/без текста)"
        if getattr(ch, "username", None):
            link = f"https://t.me/{ch.username}/{pm.message_id}"
        else:   # приватная группа/канал: t.me/c/<внутренний id без -100>/<msg_id>
            _cid = str(ch.id)
            _cid = _cid[4:] if _cid.startswith("-100") else _cid.lstrip("-")
            link = f"https://t.me/c/{_cid}/{pm.message_id}"
        await context.bot.send_message(
            OWNER_ID,
            f"📌 Закреп в «{title}»: {body[:100]}{'…' if len(body) > 100 else ''}\nСсылка: {link}",
            disable_web_page_preview=True)
    except Exception:
        pass
app.add_handler(MessageHandler(filters.StatusUpdate.PINNED_MESSAGE, handle_pinned))
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
    # M338: ошибки БОТА регистрируются в общий журнал с номером B-NNN (B=Bot), с дедупом и существом
    eid = ''
    try:
        cur = _data_get("errors.json", []) or []
        if not isinstance(cur, list): cur = []
        key = ('bot|' + err[:160])
        existing = None
        for e in cur:
            if e.get('key') == key: existing = e; break
        if existing:
            existing['count'] = existing.get('count', 1) + 1
            existing['last_t'] = _now_msk()   # #664 (С67): тот же приём, что в errlog() — время последнего повтора
            eid = existing.get('eid', '')
        else:
            _seq = max([e.get('bseq', 0) for e in cur] or [0]) + 1
            eid = 'B-%03d' % _seq
            try: _where = (update and getattr(update, 'effective_chat', None) and str(update.effective_chat.id)) or 'bot'
            except Exception: _where = 'bot'
            cur.append({'key': key, 'msg': err[:500], 'where': _where, 'ver': 'bot', 'stack': '',
                        'uid': '', 'count': 1, 'fixed': False, 'bseq': _seq, 'eid': eid,
                        't': _now_msk()})   # #664 (С67): время первого появления — как в errlog()
            cur = cur[-400:]
        _data_put("errors.json", cur, f"boterr: {err[:40]}")
    except Exception:
        pass
    try:
        await context.bot.send_message(LOG_CHAT_ID, ("🐞 ОШИБКА БОТА %s\n%s\n(в журнале; решить: «ошибка решена %s»)" % (eid or '—', err[:600], eid)) if eid else ("⚠️ Ошибка бота:\n" + err[:700]))
    except Exception:
        pass
app.add_error_handler(_on_error)
_load_ai_gate()   # 🔒 восстановить состояние рубильника публичного ИИ (дефолт — ВЫКЛ для публики)
from telegram import Update as _Upd
app.run_polling(drop_pending_updates=True, allowed_updates=_Upd.ALL_TYPES)
