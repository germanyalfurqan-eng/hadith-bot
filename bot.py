import os
import re
import random
import json
import base64
import requests
from datetime import datetime
from html import unescape
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, ChatMemberHandler

TOKEN = os.environ.get("TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER_ID = 131827895
OWNER_CHANNEL_ID = -1001660979432
LOG_CHAT_ID = -1003480426073
GITHUB_REPO = "germanyalfurqan-eng/hadith-bot"
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
AI_MODEL = "google/gemini-flash-latest"

pending_edits = {}

def today():
    return datetime.now().strftime("%d.%m.%Y")

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
def enhance_audio(input_path, output_path):
    try:
        from pydub import AudioSegment
        import noisereduce as nr
        import numpy as np
        import soundfile as sf
        import os

        sound = AudioSegment.from_file(input_path)
        sound = sound.set_frame_rate(16000).set_channels(1)
        temp_wav = input_path + ".temp.wav"
        sound.export(temp_wav, format="wav")

        data, rate = sf.read(temp_wav)

        reduced = nr.reduce_noise(y=data, sr=rate)

        out_wav = output_path + ".wav"
        sf.write(out_wav, reduced, rate)

        result = AudioSegment.from_wav(out_wav)
        result.export(output_path, format="mp3", bitrate="64k")

        os.remove(temp_wav)
        os.remove(out_wav)

        return True
    except Exception as e:
        print(f"Audio error: {e}")
        return False
def is_owner(update: Update) -> bool:
    user_id = update.effective_user.id if update.effective_user else 0
    sender_chat_id = 0
    if update.message and update.message.sender_chat:
        sender_chat_id = update.message.sender_chat.id
    return user_id == OWNER_ID or sender_chat_id == OWNER_CHANNEL_ID

def parse_hadith_query(text):
    text = text.lower().strip()
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
        if ":" in ref: parts = ref.split(":")
        elif " " in ref: parts = ref.split()
        else: return None, None
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

def get_hadith(collection, number):
    try:
        ua = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/ara-{collection}/{number}.min.json"
        ur = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/rus-{collection}/{number}.min.json"
        ue = f"https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/eng-{collection}/{number}.min.json"
        arabic = russian = english = grade = ""
        try:
            r = requests.get(ua, timeout=10)
            if r.status_code == 200:
                h = r.json().get("hadiths", [])
                if h: arabic = h[0].get("text", "").replace("\n", " ")
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
        else:
            url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/ahmad_2.json"
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

def ask_ai(prompt, system=None):
    if not OPENROUTER_API_KEY: return "❌ API-ключ не настроен."
    if system is None: system = "Ты — полезный ассистент в исламском Телеграм-боте. Отвечай на русском."
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": AI_MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
            timeout=30
        )
        if r.status_code == 200: return r.json()["choices"][0]["message"]["content"]
        else: return f"❌ Ошибка AI: {r.status_code}"
    except Exception as e: return f"❌ Ошибка: {e}"

def ask_ai_with_memory(prompt):
    memory = load_memory()
    system = "Ты — полезный ассистент в исламском Телеграм-боте. Отвечай на русском."
    if memory:
        memory_text = "\n".join([f"- [{m.get('date','—')}] {m.get('text','')}" for m in memory])
        system += f"\n\nЧто ты знаешь о владельце и контексте:\n{memory_text}"
    return ask_ai(prompt, system)

async def send_long(update, text, parse_mode=None):
    for i in range(0, len(text), 4000):
        chunk = text[i:i+4000]
        if parse_mode:
            await update.message.reply_text(chunk, parse_mode=parse_mode)
        else:
            await update.message.reply_text(chunk)

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

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    chat_type = update.effective_chat.type
    text = update.message.text or update.message.caption or ""
    text = text.strip()
    chat_id = update.effective_chat.id
    if chat_type == "private" and not is_owner(update): return

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

    # Улучшение аудио
    if is_owner(update) and text and text.lower() == "улучшить":
        if update.message.reply_to_message and (update.message.reply_to_message.audio or update.message.reply_to_message.voice):
            await update.message.reply_text("🎧 Обрабатываю аудио...")
            replied = update.message.reply_to_message
            file_obj = replied.audio or replied.voice
            file = await file_obj.get_file()
            input_path = f"/tmp/{file.file_id}.ogg"
            output_path = f"/tmp/{file.file_id}_clean.mp3"
            await file.download_to_drive(input_path)
            
            if enhance_audio(input_path, output_path):
                await update.message.reply_audio(audio=open(output_path, "rb"), title="Чистое аудио")
            else:
                await update.message.reply_text("❌ Не удалось обработать аудио.")
        else:
            await update.message.reply_text("❌ Ответь на аудио или войс командой 'улучшить'.")
        return

    if not text: return

    if is_owner(update):
        t_lower = text.lower().strip()
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

        botyara_q = parse_botyara(text)
        if botyara_q is not None:
            if botyara_q in ["очисти свою память", "очисти память", "забудь всё", "сотри память", "стереть память"]:
                pending_edits[chat_id] = {"action": "clear_memory"}
                await update.message.reply_text("⚠️ Ты хочешь удалить ВСЮ память!\nЭто нельзя отменить.\n\nЕсли уверен — напиши: **точно ботяра**")
                return

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

        if t_lower == "очистить память":
            save_memory([])
            await update.message.reply_text("🧠 Память очищена.")
            return

    # Авто-AI в личке для владельца (без "ботяра")
    if is_owner(update) and chat_type == "private":
        # Проверяем не команда ли это (хадис, коран, реестр...)
        is_command = False
        if parse_hadith_query(text)[0]: is_command = True
        if parse_quran_query(text)[0]: is_command = True
        if parse_search_query(text): is_command = True
        if parse_translate(text): is_command = True
        if parse_tafsir_query(text)[0]: is_command = True
        if parse_registry_command(text): is_command = True
        if text.lower() in ["память", "помощь", "справка", "команды"]: is_command = True
        if text.lower().startswith(("запомни", "удали память", "исправь память", "очистить память")): is_command = True
        if parse_botyara(text) is not None: is_command = True
        
        if not is_command:
            if update.message.reply_to_message and update.message.reply_to_message.from_user and update.message.reply_to_message.from_user.is_bot:
                await update.message.reply_text("🤔 Думаю...")
                result = ask_ai_with_memory(text)
                await send_long(update, result)
                return
            await update.message.reply_text("🤔 Думаю...")
            result = ask_ai_with_memory(text)
            await send_long(update, result)
            return

    if is_owner(update) and update.message.reply_to_message:
        if update.message.reply_to_message.from_user and update.message.reply_to_message.from_user.is_bot:
            await update.message.reply_text("🤔 Думаю...")
            result = ask_ai_with_memory(text)
            await send_long(update, result)
            return

    if is_owner(update):
        botyara_q = parse_botyara(text)
        if botyara_q is not None and botyara_q not in ["очисти свою память", "очисти память", "забудь всё", "сотри память", "стереть память"]:
            if update.message.reply_to_message and update.message.reply_to_message.text:
                original_text = update.message.reply_to_message.text
                if botyara_q == "":
                    prompt = f"Объясни это сообщение:\n\n{original_text}"
                elif "переведи" in botyara_q:
                    prompt = f"Переведи на русский:\n{original_text}"
                elif "источник" in botyara_q or "откуда" in botyara_q:
                    prompt = f"Найди источник:\n\n{original_text}"
                elif "достоверн" in botyara_q or "сахих" in botyara_q:
                    prompt = f"Проверь достоверность:\n\n{original_text}"
                else:
                    prompt = f"{botyara_q}\n\nСообщение: {original_text}"
            else:
                prompt = botyara_q if botyara_q else None
            if prompt:
                await update.message.reply_text("🤔 Думаю...")
                result = ask_ai_with_memory(prompt)
                await send_long(update, result)
            else:
                await update.message.reply_text("❌ Напиши что-то после 'ботяра'.")
            return

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

        surah, ayah = parse_tafsir_query(text)
        if surah and ayah:
            await update.message.reply_text(f"📖 Ищу тафсир {surah}:{ayah}...")
            arabic_ayah, _ = get_quran_ayah(surah, ayah)
            prompt = f"Дай тафсир Ибн Касира на аят {surah}:{ayah}."
            if arabic_ayah: prompt += f"\n\nАят: {arabic_ayah}"
            result = ask_ai(prompt, "Ты — знаток тафсира Ибн Касира.")
            await send_long(update, result)
            return

    sq = parse_search_query(text)
    if sq:
        await update.message.reply_text(f"🔍 Ищу: {sq}...")
        results = search_hadith(sq)
        if not results: await update.message.reply_text("❌ Ничего не найдено."); return
        msg = f"🔍 *«{sq}»*\n\n"
        for i, r in enumerate(results, 1):
            msg += f"*{i}.* {r['text'][:300]}\n"
            if r['rawi']: msg += f"👤 {r['rawi']}\n"
            if r['source']: msg += f"📚 {r['source']}\n"
            if r['grade']: msg += f"📊 {r['grade']}\n"
            msg += "\n"
        await send_long(update, msg, "Markdown")
        return

    surah, ayah = parse_quran_query(text)
    if surah and ayah:
        await update.message.reply_text("⏳ Ищу аят...")
        a, r = get_quran_ayah(surah, ayah)
        if not a and not r: await update.message.reply_text(f"❌ Аят {surah}:{ayah} не найден."); return
        msg = f"📖 Коран, {surah}:{ayah}\n\n"
        if a: msg += f"🔤 {a}\n\n"
        if r: msg += f"🌍 {r}\n"
        msg += f"\n📚 Коран, {surah}:{ayah}"
        await send_long(update, msg)
        return

    collection, number = parse_hadith_query(text)
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
                else: await update.message.reply_text("❌ Не удалось.")
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
                else: await update.message.reply_text("❌ Не удалось.")
                return
        if number:
            await update.message.reply_text("⏳ Ищу хадис...")
            if collection == "ahmad_local":
                ar, tr, lang, gr = get_ahmad_hadith(number)
            else:
                ar, tr, lang, gr = get_hadith(collection, number)
            if not ar and not tr: await update.message.reply_text(f"❌ {NAMES.get(collection, collection)} №{number} не найден."); return
            similar = search_similar_hadith(ar) if collection != "ahmad_local" else []
            msg = f"📖 {NAMES.get(collection, collection)}, №{number}\n\n"
            if ar: msg += f"🔤 {ar}\n\n"
            if tr: msg += f"🌍 ({lang}): {tr}\n"
            if gr: msg += f"\n📊 {gr}"
            msg += f"\n\n📚 {NAMES.get(collection, collection)}, №{number}"
            if similar: msg += f"\n\n📖 Также:\n• " + "\n• ".join(similar[:5])
            await send_long(update, msg)
            return

    if text.lower() in ["помощь", "справка", "команды", "хелп", "help", "/start"]:
        await update.message.reply_text(
            "📚 *Команды бота:*\n\n"
            "*Хадисы (8 сборников):*\nбухари 1 | муслим 1 | абу дауд 1\nтирмизи 1 | ибн маджа 1 | насаи 1 | муватта 1\nахмад 1\n\n"
            "*Случайные:*\nслучайный | случайный бухари | случайный муслим | случайный коран\n\n"
            "*Коран:*\nкоран 2:255\n\n"
            "*Поиск:*\nискать بدعة\n\n"
            "*Ботяра (владелец):*\nботяра вопрос | ботяра очисти свою память\n\n"
            "*В личке:* просто вопрос → AI ответит\n\n"
            "*Память (владелец):*\nзапомни: факт | память | удали память 2\nисправь память 2: текст | очистить память\n\n"
            "*Реестр (владелец):*\nв реестр (reply) | реестр | ожидает\nсделано 1 | удали 1 | результат 1 ссылка",
            parse_mode="Markdown"
        )

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.VIDEO | filters.PHOTO | filters.Document.ALL, handle))
app.add_handler(ChatMemberHandler(track_member, ChatMemberHandler.CHAT_MEMBER))
app.run_polling()
