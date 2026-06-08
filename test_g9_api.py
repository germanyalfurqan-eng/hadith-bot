# -*- coding: utf-8 -*-
"""Интеграционный тест HTTP-бэкенда G9: поднимает реальный _api_serve и стучится в /api."""
import sys, os, types, json, hmac, hashlib, time, asyncio
from urllib.parse import urlencode, quote
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TEST_TOKEN = "123456:TEST-abcDEF_ghi"
os.environ["TOKEN"] = TEST_TOKEN
os.environ["GITHUB_TOKEN"] = ""
os.environ["PORT"] = "8731"
BASE = "http://127.0.0.1:8731/api"

def _mk(name):
    m = types.ModuleType(name); sys.modules[name] = m; return m
class _Resp:
    status_code = 404; text = ""
    def json(self): return {}
req = _mk("requests"); req.get = req.post = req.put = lambda *a, **k: _Resp()
tg = _mk("telegram"); tg.Update = object; tg.ReplyKeyboardMarkup = lambda *a, **k: None
class _App:
    def add_handler(self, *a, **k): pass
    def add_error_handler(self, *a, **k): pass
    def run_polling(self, *a, **k): pass
class _Builder:
    def token(self, *a, **k): return self
    def post_init(self, *a, **k): return self
    def build(self, *a, **k): return _App()
class _CMH:
    CHAT_MEMBER = 0; MY_CHAT_MEMBER = 0
    def __init__(self, *a, **k): pass
ext = _mk("telegram.ext")
ext.ApplicationBuilder = lambda *a, **k: _Builder()
ext.MessageHandler = lambda *a, **k: None
ext.CommandHandler = lambda *a, **k: None
ext.ChatMemberHandler = _CMH
ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
ext.filters = types.SimpleNamespace(TEXT=0, COMMAND=0, AUDIO=0, VOICE=0, VIDEO=0, PHOTO=0,
    Document=types.SimpleNamespace(ALL=0), ChatType=types.SimpleNamespace(CHANNEL=0))

import bot
import aiohttp

# мок ИИ/поиска — без сети
bot.ask_deepseek = lambda prompt, system: "الصبر\nالصلاة\n1. النية"
bot.search_hadith = lambda q: [{"matn": "نتيджа", "grade": "صحيح"}]
# фикс. правила доступа
bot._access_cache = bot._merge_access({
    "all": {"whitelist": []},
    "app": {"public": False, "whitelist": ["@alice"]},
    "translate": {"public": True, "whitelist": []},
    "neuro": {"public": False, "whitelist": []},
    "bot": {"public": False, "whitelist": []},
})

OK = 0; FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  [OK] {name}")
    else:    FAIL += 1; print(f"  [FAIL] {name} {extra}")

def idata(user):
    d = {"user": json.dumps(user, separators=(",", ":")), "auth_date": str(int(time.time())), "query_id": "Q"}
    cs = "\n".join(f"{k}={d[k]}" for k in sorted(d))
    sec = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    d["hash"] = hmac.new(sec, cs.encode(), hashlib.sha256).hexdigest()
    return urlencode(d)

OWNER = {"id": bot.OWNER_ID, "username": "owner"}
ALICE = {"id": 555, "username": "Alice"}

async def main():
    await bot._api_serve()
    async with aiohttp.ClientSession() as s:
        async def post(path, body):
            async with s.post(BASE + path, json=body) as r:
                return r.status, await r.json()
        async def get(path):
            async with s.get(BASE + path) as r:
                return r.status, await r.json()

        print("== health / CORS ==")
        st, j = await get("/health"); check("GET /health → 200 ok", st == 200 and j.get("ok"))

        print("== /api/access (get) ==")
        st, j = await post("/access", {"initData": idata(OWNER), "action": "get"})
        check("owner: 200, owner=True", st == 200 and j["me"]["owner"], j)
        check("owner: allow всё True", all(j["allow"].values()), j["allow"])
        check("owner: получает config", "config" in j)
        st, j = await post("/access", {"action": "get"})
        check("аноним: app=False, translate=True", st == 200 and j["allow"]["app"] is False and j["allow"]["translate"] is True, j.get("allow"))
        check("аноним: config НЕ отдаём", "config" not in j)
        st, j = await post("/access", {"initData": idata(ALICE), "action": "get"})
        check("alice: app=True (в списке), neuro=False", j["allow"]["app"] is True and j["allow"]["neuro"] is False, j.get("allow"))

        print("== /api/access (set) — только owner ==")
        st, j = await post("/access", {"initData": idata(ALICE), "action": "set", "config": {"app": {"public": True}}})
        check("alice set → 403", st == 403, st)
        st, j = await post("/access", {"initData": idata(OWNER), "action": "set",
                                       "config": {"neuro": {"public": True, "whitelist": ["@x"]}}})
        check("owner set → 200 ok", st == 200 and j.get("ok"), j)
        check("set применился (neuro.public=True)", bot._access_cache["neuro"]["public"] is True)
        # вернём обратно для чистоты дальнейших проверок
        bot._access_cache["neuro"]["public"] = False

        print("== /api/neuro — гейт + DeepSeek ==")
        st, j = await post("/neuro", {"initData": idata(ALICE), "meaning": "терпение"})
        check("alice (нет доступа к neuro) → 403", st == 403, st)
        st, j = await post("/neuro", {"initData": idata(OWNER), "meaning": "терпение"})
        check("owner → 200 + фразы", st == 200 and j.get("phrases"), j)
        check("фразы только арабские, мусор очищен", j["phrases"] == ["الصبر", "الصلاة", "النية"], j.get("phrases"))

        print("== /api/translate — публичный ==")
        st, j = await post("/translate", {"action": "x", "text": "السلام"})  # без initData
        check("аноним + translate.public → 200", st == 200, st)
        st, j = await post("/translate", {"initData": idata(ALICE), "text": "السلام"})
        check("alice → 200 (public)", st == 200, st)

        print("== /api/search — гейт = вход в приложение ==")
        st, j = await get("/search?q=صبر")  # без initData, app не публичный
        check("аноним → 403 (app закрыт)", st == 403, st)
        st, j = await get("/search?q=صبر&initData=" + quote(idata(OWNER), safe=""))
        check("owner → 200 + результаты", st == 200 and j.get("results"), j)

        print("== rate-limit ==")
        codes = []
        for i in range(22):
            st, _ = await post("/translate", {"text": "x"})
            codes.append(st)
        check("после лимита появляется 429", 429 in codes, codes[-3:])

    print(f"\nИТОГ: {OK} OK / {FAIL} FAIL  ({round(100*OK/max(1,OK+FAIL))}% прошло)")
    return 1 if FAIL else 0

sys.exit(asyncio.run(main()))
