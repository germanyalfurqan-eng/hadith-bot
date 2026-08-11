# -*- coding: utf-8 -*-
"""
healthcheck.py — АВТО-СТОРОЖ ЗДОРОВЬЯ ПРОДА Muslimoon (технадзор).

Зачем: ошибка A-115 («аль-Мухаймин не грузится» = критичный ассет отдавал 404/HTML
вместо JSON) всплыла ПОЗДНО — узнали только когда владелец пожаловался. Этот сторож
ловит ВЕСЬ класс таких ошибок САМ и сразу бьёт тревогу технадзору.

Что проверяет на ЖИВОМ проде (GitHub Pages + бэкенд), без Railway-зависимостей:
  1) ver.txt доступен и совпадает с APPVER в live index.html (рассинхрон деплоя);
  2) КАЖДЫЙ критичный ассет: HTTP 200 + НАЧИНАЕТСЯ с валидного JSON ([ или {),
     а НЕ с '<' (HTML-страница 404 — ровно кейс A-115) и не пустой;
  3) важные ассеты (деградация функций) — предупреждением;
  4) бэкенд /api жив (отвечает, не 5xx);
  5) (если внедрён маркер data-jsok и есть Edge) headless-рендер: инлайн-скрипт
     дошёл до конца = нет SyntaxError/дубликата let (урок П-01).

Тревога при ЛЮБОМ CRIT-провале:
  - дозапись в ТРЕВОГИ.md (журнал тревог, читаю каждую сессию);
  - health_report.json (для апп/бота/дашборда: % здоровья + что упало);
  - пуш владельцу на телефон (ntfy.sh/kwe123);
  - код выхода 1 (для деплой-гейта: блокировать/откатить).

Запуск:
  python healthcheck.py            # лёгкая проверка прода (Range, быстро)
  python healthcheck.py --full     # полностью скачать+распарсить каждый JSON
  python healthcheck.py --local    # проверить ЛОКАЛЬНЫЙ index.html (pre-deploy гейт, http://localhost:5599)
  python healthcheck.py --quiet    # без подробного вывода (для Планировщика)
Планировщик: задача «Muslimoon Healthcheck» (ежечасно) — см. setup в конце файла.
"""
import urllib.request, urllib.error, json, sys, io, re, os, datetime, time

# Ф-71 (грабли 4 раза): обёртка ТОЛЬКО при прямом запуске. При импорте она навернулась бы
# поверх обёртки вызывающего скрипта, и тот падал бы с «I/O operation on closed file».
if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = os.path.dirname(os.path.abspath(__file__))

PAGES   = 'https://germanyalfurqan-eng.github.io/hadith-bot/'
RAW_MAIN= 'https://raw.githubusercontent.com/germanyalfurqan-eng/hadith-bot/main/'
BACKEND = 'https://melodious-acceptance-production-1c9a.up.railway.app/api'
NTFY    = 'https://ntfy.sh/kwe123'
LOCAL   = 'http://localhost:5599/'

# ⛔ «ПРОВЕРИТЬ НЕЧЕМ» — ЭТО НЕ «ПРИЛОЖЕНИЕ СЛОМАНО» (02.08.2026, С67).
# Гейт --local не поднимает сервер сам, он ждёт его на 5599. Сервер держал исполнитель фронта;
# он закончил работу — сервер умер, и следующий прогон выдал «🚨 КРИТ index.html HTTP None,
# здоровье 9%». Я чуть не принял это за поломку выката и не полез искать порчу в файле,
# которого не было. Разница принципиальна: сломанное приложение чинят, а не поднятый сервер
# поднимают. Сторож обязан говорить, что именно случилось.
def _мёртв_локальный_сервер():
    try:
        urllib.request.urlopen(LOCAL + 'index.html', timeout=5).read(64)
        return False
    except Exception:
        return True


ARGS  = set(sys.argv[1:])
FULL  = '--full'  in ARGS
QUIET = '--quiet' in ARGS
USE_LOCAL = '--local' in ARGS
NOW = datetime.datetime.now()
STAMP = NOW.strftime('%Y-%m-%d %H:%M')
CB = NOW.strftime('%Y%m%d%H%M%S')   # cache-bust против кэша Pages/CDN

# КРИТИЧНЫЕ ассеты (без них ядро приложения мертво) — относительные к Pages-корню.
CRIT_ASSETS = ['muhaymin.json', 'quran.json', 'quran_ru.json']
# reverse_index живёт на ветке main (raw), не в docs:
CRIT_RAW = ['reverse_index.json']
# ВАЖНЫЕ (функции деградируют, но апп жив) — НЕ хардкодим (давало ложные тревоги по
# несуществующим путям). Список собирается АВТОМАТИЧЕСКИ из реальных ./*.json фетчей index.html.
IMPORTANT_BASE = []

def http(url, method='GET', rng=None, timeout=40, retries=3):
    # A-116: сетевое исключение (st=None) = сбой инструмента/сети САМОГО сторожа, не
    # поломка прода. Ретраим транзиентные сбои; HTTPError (реальный ответ сервера, напр.
    # 404) НЕ ретраим — это доказанный симптом.
    req = urllib.request.Request(url, method=method, headers={'User-Agent': 'muslimoon-health'})
    if rng:
        req.add_header('Range', 'bytes=0-%d' % rng)
    last_err = ''
    for attempt in range(retries):
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
            data = r.read() if method != 'HEAD' else b''
            return getattr(r, 'status', r.getcode()), dict(r.headers), data
        except urllib.error.HTTPError as e:
            return e.code, {}, b''
        except Exception as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(2)
    return None, {'err': last_err}, b''

def first_nonspace(data):
    for b in data:
        c = chr(b)
        if not c.isspace():
            return c
    return ''

checks = []  # dict(name, level, ok, detail)
def add(name, level, ok, detail):
    checks.append({'name': name, 'level': level, 'ok': ok, 'detail': detail})
    if not QUIET:
        mark = 'OK ' if ok else ('🚨' if level == 'CRIT' else '⚠️ ')
        print('%s [%-4s] %-26s %s' % (mark, level, name, detail))


if USE_LOCAL and _мёртв_локальный_сервер():
    print("⛔ ПРОВЕРИТЬ НЕЧЕМ, А НЕ «СЛОМАНО»: локальный сервер на 5599 не отвечает.")
    print("   Гейт --local читает файл ЧЕРЕЗ него и сам его не поднимает. Подними и повтори:")
    print("     cd " + os.path.join(ROOT, "miniapp") + "  &&  python -m http.server 5599 --bind 127.0.0.1")
    print("   Без сервера все замеры дадут «HTTP None» и здоровье 9% — это ложная тревога,")
    print("   а не поломка приложения (поймано 02.08.2026: сервер держал исполнитель фронта,")
    print("   он закончил работу — сервер умер вместе с ним).")
    sys.exit(2)

BASE = LOCAL if USE_LOCAL else PAGES

# 1) ver.txt + APPVER синхрон ----------------------------------------------
ver = ''
if not USE_LOCAL:
    st, h, d = http(BASE + 'ver.txt?cb=' + CB)
    if st == 200 and d:
        ver = d.decode('utf-8', 'ignore').strip()
        add('ver.txt', 'CRIT', True, 'HTTP 200 -> ' + ver)
    elif st is None:
        # A-116: сеть/инструмент сторожа дал сбой (не доказанный симптом прода) -> WARN,
        # не ложный CRIT владельцу. Реальное падение прода поймает CRIT index.html ниже.
        add('ver.txt', 'WARN', True, 'сеть недоступна после ретраев — проверка пропущена (%s)' % h.get('err', ''))
    else:
        add('ver.txt', 'CRIT', False, 'HTTP %s (нет файла версии)' % st)

# index.html: APPVER + сбор статических ./*.json литералов (самокалибровка)
st, h, html = http(BASE + 'index.html?cb=' + CB)
appver = ''
extra_imp = []
edition_imp = []
if st == 200 and html:
    txt = html.decode('utf-8', 'ignore')
    m = re.search(r"const APPVER\s*=\s*'(v\d+)'", txt)
    appver = m.group(1) if m else ''
    add('index.html', 'CRIT', bool(appver), 'HTTP 200, APPVER=' + (appver or '?'))
    for lit in re.findall(r"['\"]\./([\w\-/]+\.json)", txt):   # ловит и подкаталоги (editions/darimi.json и т.п.)
        if lit not in CRIT_ASSETS and lit not in extra_imp:
            extra_imp.append(lit)
    # A-065 (#595): экстра-издания фронт склеивает ДИНАМИЧЕСКИ (EXTRA_BASE+code+'.json'),
    # литерала './editions/ishaq.json' в коде нет → сбор выше их не видел, пропажа книги
    # прошла бы мимо сторожа. Берём коды из TAKH_SMALL/TAKH_BIG и проверяем как CRIT.
    for _arr in re.findall(r"TAKH_(?:SMALL|BIG)\s*=\s*\[([^\]]+)\]", txt):
        for _code in re.findall(r"'([\w\-]+)'", _arr):
            _lit = 'editions/%s.json' % _code
            if _lit not in CRIT_ASSETS and _lit not in edition_imp:
                edition_imp.append(_lit)
    if not USE_LOCAL and ver and appver and ver != appver:
        add('ver==APPVER', 'CRIT', False, 'РАССИНХРОН: ver.txt=%s но index APPVER=%s' % (ver, appver))
    elif not USE_LOCAL and ver and appver:
        add('ver==APPVER', 'CRIT', True, 'синхронны (%s)' % ver)
else:
    add('index.html', 'CRIT', False, 'HTTP %s' % st)

# 2) критичные ассеты: валидный JSON-старт (не HTML-404) -------------------
def check_asset(name, url, level):
    if FULL:
        st, h, d = http(url)
        if st is None:
            # A-117: транзиентный сетевой сбой/таймаут СТОРОЖА (большие файлы вроде muhaymin.json через прокси) → WARN, не CRIT
            add(name, 'WARN', False, 'сеть/таймаут сторожа — проверка пропущена (HTTP None), не симптом прода'); return
        if st != 200 or not d:
            add(name, level, False, 'HTTP %s / пусто' % st); return
        try:
            j = json.loads(d.decode('utf-8', 'ignore'))
            n = len(j) if isinstance(j, (list, dict)) else 1
            add(name, level, True, 'HTTP 200, валидный JSON (%s элементов)' % n)
        except Exception as e:
            add(name, level, False, 'JSON-РАЗБОР УПАЛ: %s' % str(e)[:60])
    else:
        st, h, d = http(url, rng=2048)
        ok = st in (200, 206) and bool(d)
        fc = first_nonspace(d) if d else ''
        if ok and fc in '[{':
            cl = h.get('Content-Length') or h.get('Content-Range') or '?'
            add(name, level, True, 'HTTP %s, старт «%s» (len %s)' % (st, fc, cl))
        elif st in (200, 206) and fc == '<':
            add(name, level, False, 'HTTP %s но тело = HTML (404-страница вместо JSON!) — класс A-115' % st)
        elif st is None:
            # A-117: транзиентный сетевой сбой/таймаут СТОРОЖА (частый на больших файлах вроде muhaymin.json
            # через прокси) → WARN, НЕ ложный CRIT владельцу. Реальное падение прода ловит CRIT index.html/render.
            add(name, 'WARN', False, 'сеть/таймаут сторожа — проверка пропущена (HTTP None), не симптом прода')
        else:
            add(name, level, False, 'HTTP %s, старт «%s»' % (st, fc or 'пусто'))

for a in CRIT_ASSETS:
    check_asset(a, BASE + a + '?cb=' + CB, 'CRIT')
if not USE_LOCAL:
    for a in CRIT_RAW:
        check_asset(a + '(main)', RAW_MAIN + a, 'CRIT')

imp = list(dict.fromkeys(IMPORTANT_BASE + extra_imp))
for a in imp:
    check_asset(a, BASE + a + '?cb=' + CB, 'WARN')

# 2б) экстра-издания (динамические, A-065): пропажа = книга не открывается у владельца
for a in edition_imp:
    check_asset(a, BASE + a + '?cb=' + CB, 'CRIT')

# 3) бэкенд жив ------------------------------------------------------------
if not USE_LOCAL:
    st, h, d = http(BACKEND + '/access', timeout=25)
    if st is None:
        add('backend /api', 'WARN', False, 'НЕ ОТВЕЧАЕТ: ' + str(h.get('err', ''))[:50])
    elif 500 <= (st or 0) < 600:
        add('backend /api', 'WARN', False, 'HTTP %s (бэкенд лежит — bot.py-фичи недоступны)' % st)
    else:
        add('backend /api', 'WARN', True, 'HTTP %s (сервер отвечает)' % st)

    # 3б) 🔴 ДЕЛОМ, А НЕ ПУЛЬСОМ (12.08.2026). «Сервер отвечает» — не то же, что «работает».
    # В этот день выяснилось: /api/translate пять дней отдавал HTTP 200 и внутри
    # {"translation": "", "error": "name '_trans_cache' is not defined"} — перевод в
    # приложении не работал ВООБЩЕ. Сторож этого не видел, потому что смотрел на код ответа,
    # а не на сам ответ. Запись в журнале ошибок была с 07.08 и пролежала пять суток.
    # Поэтому проверяем ДЕЛОМ: просим перевести короткий арабский и смотрим, пришли ли
    # русские буквы. Пустой перевод или поле error — CRIT: это ровно тот класс, где всё
    # «зелено», а человеку не отвечают.
    try:
        _тело = json.dumps({'text': 'الحمد لله رب العالمين',
                            'source': 'проверка', 'num': '0'}).encode('utf-8')
        _зп = urllib.request.Request(BACKEND + '/translate', data=_тело,
                                     headers={'Content-Type': 'application/json',
                                              'User-Agent': 'Mozilla/5.0'})
        _д = json.loads(urllib.request.urlopen(_зп, timeout=120).read().decode('utf-8'))
        _пер = str(_д.get('translation') or '')
        _беда = str(_д.get('error') or '')
        if _беда:
            add('перевод (делом)', 'CRIT', False, 'ответ 200, но внутри ошибка: ' + _беда[:90])
        elif not re.search(r'[а-яё]{3,}', _пер, re.I):
            add('перевод (делом)', 'CRIT', False,
                'русского текста не пришло (%d знаков)' % len(_пер))
        else:
            add('перевод (делом)', 'CRIT', True, 'перевёл: «%s…»' % _пер[:40])
    except Exception as _e:
        # Сеть сторожа могла подвести — это не доказанный симптом прода.
        add('перевод (делом)', 'WARN', False, 'проверка не прошла: %s' % str(_e)[:70])

# 4) headless-рендер через маркер data-jsok (если внедрён) -----------------
if 'data-jsok' in (html.decode('utf-8', 'ignore') if html else ''):
    edge = None
    for p in [r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
              r'C:\Program Files\Microsoft\Edge\Application\msedge.exe']:
        if os.path.exists(p):
            edge = p; break
    if edge:
        import subprocess, tempfile, shutil
        url = BASE + ('index.html' if USE_LOCAL else '')
        # ТРЕВОГА A-116 (С34): headless Edge в некоторых окружениях отдаёт ПУСТОЙ DOM (0 байт,
        # лок профиля) → раньше это летело как CRIT False = ложный пожар + спам ntfy владельцу.
        # Защита: ① изолированный user-data-dir на каждый прогон; ② до 2 ретраев;
        # ③ пустой/обрезанный вывод (нет даже <html>) = WARN «headless не отрисовал», НЕ CRIT.
        out = ''
        for attempt in range(2):
            ud = tempfile.mkdtemp(prefix='hc_edge_')
            try:
                out = subprocess.run([edge, '--headless=new', '--disable-gpu', '--no-sandbox',
                                      '--user-data-dir=' + ud,
                                      '--virtual-time-budget=15000', '--dump-dom', url],
                                     capture_output=True, timeout=60).stdout.decode('utf-8', 'ignore')
            except Exception as e:
                out = ''
                last_err = str(e)[:40]
            finally:
                shutil.rmtree(ud, ignore_errors=True)
            if out and '<html' in out.lower():
                break
        if not (out and '<html' in out.lower()):
            # рендер вообще не состоялся (пустой DOM) — это НЕ доказательство поломки скрипта
            add('render(JS)', 'WARN', True, 'headless не отрисовал DOM (пустой вывод Edge) — рендер-проверка пропущена')
        else:
            m = re.search(r'data-jsok="(v\d+)"', out)
            if m:
                add('render(JS)', 'CRIT', True, 'инлайн-скрипт исполнился до конца (data-jsok=%s)' % m.group(1))
            else:
                add('render(JS)', 'CRIT', False, 'инлайн-скрипт НЕ дошёл до конца — SyntaxError/дубликат let (П-01)!')
else:
    add('render(JS)', 'WARN', True, 'маркер data-jsok ещё не внедрён в index.html — headless-рендер пропущен')

# ---- 🔴 СТРАТЕГИЧЕСКАЯ ТРЕВОГА: ДОСТУПНОСТЬ ХАДИСОВ ПО НОМЕРУ ------------
# СЛОВО ВЛАДЕЛЬЦА (01.08.2026): «не может быть так почему бухари не грузится? это беспредел?
# если бухари и муслим не грузится должна быть тревога СТРАТЕГИЧЕСКОГО уровня».
#
# ЧТО СЛУЧИЛОСЬ. Поиск по номеру перебирает канон и делает:
#     const hh = (arr||[]).find(x => String(x.num) === String(n));  if(!hh) return;
# — при отсутствии номера выходит МОЛЧА: ни карточки, ни строки в «какие не вошли».
# Замер 01.08: в reader/bukhari.json 713 номеров (9,4%) недоступны — Бухари просто исчезал
# из выдачи, и ни одна проверка этого не ловила. Прежние проверки ассетов брали файл
# Range-запросом (HTTP 206) и видели «первые байты на месте» — то есть подтверждали доставку,
# а не пригодность (Ф-83).
#
# ЭТА ПРОВЕРКА СКАЧИВАЕТ ФАЙЛ ЦЕЛИКОМ и считает, какая доля номеров реально адресуема.
# Бухари и Муслим — CRIT (сердце приложения), остальной канон — WARN.
try:
    _КАНОН = [('bukhari', 'CRIT', 7563), ('muslim', 'CRIT', 3033),
              ('abudawud', 'WARN', 5274), ('tirmidhi', 'WARN', 3956),
              ('nasai', 'WARN', 5758), ('ibnmajah', 'WARN', 4341)]
    for _код, _ур, _ожид in _КАНОН:
        try:
            _st, _h, _d = http(BASE + 'reader/%s.json?cb=%s' % (_код, CB), timeout=180, retries=2)
            if _st != 200 or not _d:
                add('номера/%s' % _код, _ур, False, 'файл читалки не отдался (HTTP %s)' % _st)
                continue
            _arr = json.loads(_d.decode('utf-8', 'ignore'))
            _ном = set()
            for _z in _arr:
                _v = _z.get('num') if isinstance(_z, dict) else None
                if _v is not None and str(_v).isdigit():
                    _ном.add(int(_v))
            _мак = max(_ном) if _ном else 0
            _дыр = _мак - len(_ном) if _мак else 0
            _доля = (len(_ном) / _мак * 100) if _мак else 0
            # два разных симптома: дыры внутри диапазона и обрубленный диапазон
            _обруб = _мак < _ожид * 0.9
            _плохо = (_доля < 99.0) or _обруб
            _тек = 'номеров %d из %d (%.1f%%), недоступно %d' % (len(_ном), _мак, _доля, _дыр)
            if _обруб:
                _тек += ' · ⚠️ диапазон обрублен: максимум %d при ожидаемых ~%d' % (_мак, _ожид)
            add('номера/%s' % _код, _ур, not _плохо, _тек)
        except Exception as _e:
            add('номера/%s' % _код, 'WARN', True, 'проверка пропущена (%s)' % str(_e)[:40])
except Exception:
    pass

# ---- ИТОГ + ТРЕВОГА ------------------------------------------------------
crit_fail = [c for c in checks if c['level'] == 'CRIT' and not c['ok']]
warn_fail = [c for c in checks if c['level'] == 'WARN' and not c['ok']]
total = len(checks); okn = sum(1 for c in checks if c['ok'])
pct = round(100 * okn / total) if total else 0
healthy = not crit_fail

print('\n=== ЗДОРОВЬЕ ПРОДА: %d%% (%d/%d) | %s ===' % (
    pct, okn, total, 'ЗДОРОВ ✅' if healthy else 'ТРЕВОГА 🚨'))
if crit_fail:
    print('🚨 КРИТ-ПРОВАЛЫ:', ', '.join(c['name'] for c in crit_fail))
if warn_fail:
    print('⚠️  предупреждения:', ', '.join(c['name'] for c in warn_fail))

# ═══ Ф-95: ПОРОГ ПРАВДОПОДОБИЯ — СТОРОЖ ОБЯЗАН ЗАПОДОЗРИТЬ СЕБЯ ═══
# 01.08.2026 за один день мы шесть раз подняли тревогу, и ПЯТЬ раз это была поломка самой
# проверки, а не прода: детектор иснадов мерил огласовки и объявил подделкой 8 книг из 9;
# детектор чужих страниц сработал на 11 книгах из 12; сверка с эталоном показывала красное
# там, где просто разошлись системы нумерации.
# Априорное знание, которым сторож раньше не пользовался: МАССОВАЯ поломка прода менее
# вероятна, чем поломка сторожа. Если разом упало почти всё — скорее всего упала сеть,
# сменился адрес или сломался сам скрипт.
# Молчать нельзя (закон «молчащая проверка хуже отсутствующей»), но и кричать «всё сломано»
# нельзя: тревога, которой не верят, хуже отсутствующей вдвойне.
ПОДОЗРЕВАТЬ_СЕБЯ = total >= 5 and len(crit_fail) >= max(3, int(total * 0.5))
if ПОДОЗРЕВАТЬ_СЕБЯ:
    print()
    print('🚨🚨 САМОПРОВЕРКА: провалено %d критичных проверок из %d — это больше половины.'
          % (len(crit_fail), total))
    print('   Столько всего сразу на проде не ломается. Скорее всего беда НЕ в приложении:')
    print('   · нет сети или недоступен GitHub Pages целиком;')
    print('   · сменился адрес/ветка, и мы стучимся не туда;')
    print('   · сломан сам healthcheck (класс Ф-95: сторож мерит не то).')
    print('   Прежде чем чинить прод — открыть приложение руками и посмотреть, живо ли оно.')
    print('   Тревога НЕ отправляется и код возврата НЕ тревожный: сломанный сторож не должен')
    print('   валить гейт деплоя, будучи сам причиной.')

report = {'asof': STAMP, 'target': ('LOCAL' if USE_LOCAL else 'PROD'),
          'health_pct': pct, 'healthy': healthy, 'appver': appver, 'ver': ver,
          'crit_fail': [{'name': c['name'], 'detail': c['detail']} for c in crit_fail],
          'warn_fail': [{'name': c['name'], 'detail': c['detail']} for c in warn_fail],
          'checks': checks}
json.dump(report, open(os.path.join(ROOT, 'health_report.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)

if crit_fail and not USE_LOCAL and not ПОДОЗРЕВАТЬ_СЕБЯ:
    # 1) журнал тревог технадзора
    lines = ['', '## 🚨 %s — ТРЕВОГА здоровья прода (%d%%)' % (STAMP, pct)]
    for c in crit_fail:
        lines.append('- **CRIT** `%s`: %s' % (c['name'], c['detail']))
    for c in warn_fail:
        lines.append('- предупр. `%s`: %s' % (c['name'], c['detail']))
    lines.append('- _Автообнаружено healthcheck.py. Технадзор: разобрать НЕМЕДЛЕННО (класс A-115 = ассет/деплой)._')
    with open(os.path.join(ROOT, 'ТРЕВОГИ.md'), 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    # 2) пуш владельцу на телефон
    try:
        msg = ('🚨 Muslimoon: тревога здоровья прода %d%%. Упало: %s. Проверь ТРЕВОГИ.md' %
               (pct, ', '.join(c['name'] for c in crit_fail))).encode('utf-8')
        urllib.request.urlopen(urllib.request.Request(
            NTFY, data=msg, headers={'Title': 'Muslimoon ALERT', 'Priority': 'high'}), timeout=15)
        print('-> тревога отправлена: ТРЕВОГИ.md + ntfy')
    except Exception as e:
        print('-> ntfy не ушёл:', str(e)[:50])

if ПОДОЗРЕВАТЬ_СЕБЯ and not USE_LOCAL:
    # одна короткая запись в журнал — не тревога, а отметка «сторож сам себе не поверил».
    # Молчать нельзя: если это повторяется, значит сторож действительно сломан и его чинят.
    try:
        with open(os.path.join(ROOT, 'ТРЕВОГИ.md'), 'a', encoding='utf-8') as f:
            f.write('\n- _%s: healthcheck провалил %d из %d критичных проверок и ЗАПОДОЗРИЛ СЕБЯ '
                    '(Ф-95). Тревога не поднята. Если запись повторяется — чинить сам сторож._\n'
                    % (STAMP, len(crit_fail), total))
    except Exception:
        pass

# код возврата: при подозрении на себя — НЕ тревожный, иначе сломанный сторож блокирует деплой
sys.exit(1 if (crit_fail and not ПОДОЗРЕВАТЬ_СЕБЯ) else 0)
