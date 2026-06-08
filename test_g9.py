# -*- coding: utf-8 -*-
"""Автотест G9: проверка initData (HMAC) и логики гранулярного доступа.
Импортирует РЕАЛЬНЫЕ функции из bot.py, заглушив тяжёлые модули (telegram/requests).
"""
import sys, os, types, json, hmac, hashlib, time
from urllib.parse import urlencode
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TEST_TOKEN = "123456:TEST-abcDEF_ghi"
os.environ["TOKEN"] = TEST_TOKEN
os.environ["GITHUB_TOKEN"] = ""          # сеть отключена → load_access = дефолт

# ---------- заглушки тяжёлых модулей ----------
def _mk(name):
    m = types.ModuleType(name); sys.modules[name] = m; return m

class _Resp:
    status_code = 404; text = ""
    def json(self): return {}
req = _mk("requests")
req.get = req.post = req.put = lambda *a, **k: _Resp()

tg = _mk("telegram")
tg.Update = object
tg.ReplyKeyboardMarkup = lambda *a, **k: None

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
ext.filters = types.SimpleNamespace(
    TEXT=0, COMMAND=0, AUDIO=0, VOICE=0, VIDEO=0, PHOTO=0,
    Document=types.SimpleNamespace(ALL=0), ChatType=types.SimpleNamespace(CHANNEL=0))

import bot   # <-- реальный модуль

OK = 0; FAIL = 0
def check(name, cond):
    global OK, FAIL
    if cond: OK += 1; print(f"  [OK] {name}")
    else:    FAIL += 1; print(f"  [FAIL] {name}")

def make_init_data(token, user, age=0):
    data = {"user": json.dumps(user, separators=(",", ":")),
            "auth_date": str(int(time.time()) - age), "query_id": "AAHtest"}
    check_str = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)

OWNER = {"id": bot.OWNER_ID, "username": "owner", "first_name": "Murshid"}
ALICE = {"id": 555000111, "username": "Alice", "first_name": "Alice"}
BOB   = {"id": 777000222, "username": "bob", "first_name": "Bob"}

print("== 1. verify_init_data (HMAC по TOKEN) ==")
u = bot.verify_init_data(make_init_data(TEST_TOKEN, OWNER))
check("валидная подпись owner → user", u and u.get("id") == bot.OWNER_ID)
u2 = bot.verify_init_data(make_init_data(TEST_TOKEN, ALICE))
check("валидная подпись alice → user", u2 and u2.get("id") == 555000111)
bad = make_init_data(TEST_TOKEN, ALICE)[:-3] + "000"
check("подделанный hash → None", bot.verify_init_data(bad) is None)
check("чужой токен → None", bot.verify_init_data(make_init_data("999:WRONG", ALICE)) is None)
check("пустой initData → None", bot.verify_init_data("") is None)
check("протухший auth_date → None", bot.verify_init_data(make_init_data(TEST_TOKEN, ALICE, age=999999)) is None)

print("== 2. feature_allowed (гранулярный доступ) ==")
# Сценарий владельца: всё закрыто, кроме: перевод публичный; нейро по списку (@alice); полный список = bob
bot._access_cache = bot._merge_access({
    "all":       {"whitelist": ["777000222"]},          # Боб = полный доступ (id)
    "app":       {"public": False, "whitelist": ["@alice"]},
    "translate": {"public": True,  "whitelist": []},
    "neuro":     {"public": False, "whitelist": ["@alice"]},
    "bot":       {"public": False, "whitelist": []},
})
check("owner → app", bot.feature_allowed("app", OWNER))
check("owner → neuro", bot.feature_allowed("neuro", OWNER))
check("alice в app.whitelist (@ник) → app", bot.feature_allowed("app", ALICE))
check("alice НЕ в translate-списке, но translate.public → translate", bot.feature_allowed("translate", ALICE))
check("alice в neuro.whitelist → neuro", bot.feature_allowed("neuro", ALICE))
check("alice НЕ в bot.whitelist и bot не публичный → НЕТ bot", not bot.feature_allowed("bot", ALICE))
check("bob в полном списке (all) → app", bot.feature_allowed("app", BOB))
check("bob в полном списке (all) → neuro", bot.feature_allowed("neuro", BOB))
check("bob в полном списке (all) → bot", bot.feature_allowed("bot", BOB))
check("аноним (None) → translate (публичный)", bot.feature_allowed("translate", None))
check("аноним (None) → НЕТ app (не публичный)", not bot.feature_allowed("app", None))

print("== 2b. 🌐 главный рубильник all.public (всё всем, M63) ==")
bot._access_cache = bot._merge_access({"all": {"public": True, "whitelist": []},
    "app": {"public": False}, "translate": {"public": False}, "neuro": {"public": False}, "bot": {"public": False}})
check("рубильник ON → alice получает app", bot.feature_allowed("app", ALICE))
check("рубильник ON → alice получает neuro", bot.feature_allowed("neuro", ALICE))
check("рубильник ON → аноним (None) получает translate", bot.feature_allowed("translate", None))
check("рубильник ON → аноним получает bot", bot.feature_allowed("bot", None))
bot._access_cache = bot._merge_access({"all": {"public": False}})
check("рубильник OFF → аноним снова без app", not bot.feature_allowed("app", None))
check("рубильник OFF → owner всё равно внутри", bot.feature_allowed("app", OWNER))

print("== 2c. botsearch (поиск в боте: Бухари 333…) по умолчанию открыт всем ==")
bot._access_cache = bot._merge_access({})
check("botsearch.public по умолчанию True", bot._access_cache["botsearch"]["public"] is True)
check("аноним → botsearch разрешён (бот открыт)", bot.feature_allowed("botsearch", None))
bot._access_cache = bot._merge_access({"botsearch": {"public": False, "whitelist": ["@jpe_m"]}})
check("выключил botsearch.public → аноним НЕТ", not bot.feature_allowed("botsearch", None))
check("@jpe_m в списке botsearch → да", bot.feature_allowed("botsearch", {"id": 1, "username": "jpe_m"}))
check("owner всегда → botsearch", bot.feature_allowed("botsearch", OWNER))

print("== 3. _in_list: @ник без @, регистр, id как число/строка ==")
check("id числом vs строкой", bot._in_list({"id": 777000222}, ["777000222"]))
check("@Alice vs alice (регистр)", bot._in_list({"id": 1, "username": "Alice"}, ["alice"]))
check("ник с @ в списке", bot._in_list({"id": 1, "username": "x"}, ["@X"]))
check("нет совпадения", not bot._in_list({"id": 2, "username": "y"}, ["@z", "333"]))
check("«Id: 6370910451» матчит id 6370910451", bot._in_list({"id": 6370910451}, ["Id: 6370910451", "@jpe_m"]))
check("«ид 12345» матчит id 12345", bot._in_list({"id": 12345}, ["ид 12345"]))
check("username «idris» НЕ ломается префиксом id", bot._in_list({"id": 9, "username": "idris"}, ["idris"]))

print("== 4. _merge_access: чистка/дефолты ==")
m = bot._merge_access({"app": {"public": "yes", "whitelist": ["  @Joe ", "", 123]}, "junk": 1})
check("public приводится к bool", m["app"]["public"] is True)
check("whitelist чистится (trim, без пустых)", m["app"]["whitelist"] == ["@Joe", "123"])
check("неизвестные ключи отброшены", "junk" not in m)
check("дефолтные секции на месте", set(m.keys()) == set(bot.DEFAULT_ACCESS.keys()))

print("== 5. контроль качества накопления (_good_ru: мусор не копим) ==")
check("пустой → не копим", not bot._good_ru(""))
check("короткий → не копим", not bot._good_ru("ок"))
check("ошибка ❌ → не копим", not bot._good_ru("❌ API недоступен"))
check("«ключ не настроен» → не копим", not bot._good_ru("❌ API-ключ не настроен."))
check("только арабский (нет русского) → не копим", not bot._good_ru("نص عربي فقط بدون ترجمة"))
check("нормальный русский перевод → копим", bot._good_ru("Посланник Аллаха сказал: кто обманул нас, тот не из нас"))

print(f"\nИТОГ: {OK} OK / {FAIL} FAIL  ({round(100*OK/max(1,OK+FAIL))}% прошло)")
sys.exit(1 if FAIL else 0)
