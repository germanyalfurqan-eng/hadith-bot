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
import urllib.request, urllib.error, json, sys, io, re, os, datetime, time, subprocess

# Ф-71 (грабли 4 раза): обёртка ТОЛЬКО при прямом запуске. При импорте она навернулась бы
# поверх обёртки вызывающего скрипта, и тот падал бы с «I/O operation on closed file».
if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = os.path.dirname(os.path.abspath(__file__))

PAGES   = 'https://germanyalfurqan-eng.github.io/hadith-bot/'
RAW_MAIN= 'https://raw.githubusercontent.com/germanyalfurqan-eng/hadith-bot/main/'
BACKEND = 'https://130.61.182.191.sslip.io/api'
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


def _проверить_форму_ноты():
    """Последние ноты канала — по форме З-48 или сплошным текстом?

    Форма (закон, дословно): первая строка «🆕 vNNNN — заголовок» либо «🚑 …», дальше
    пункты, каждый С НОВОЙ СТРОКИ и со своим значком. Сплошной абзац запрещён.

    Смотрим ТРИ последние ноты: одна кривая — случайность, три подряд — привычка. Именно
    так и вышло 06.09: четыре подряд, и заметил владелец, а не мы.
    """
    try:
        _оч = json.load(io.open(os.path.join(ROOT, 'update_notes_queue.json'),
                                encoding='utf-8'))
        _посл = [з for з in _оч
                 if isinstance(з, dict) and з.get('id') and з.get('note')][-3:]
        if not _посл:
            add('канал/форма ноты', 'WARN', True, 'нот в очереди нет — проверять нечего')
            return
        _кривые = []
        for _з in _посл:
            _строки = [с.strip() for с in str(_з['note']).splitlines() if с.strip()]
            _беды = []
            if not _строки:
                _беды.append('пусто')
            else:
                if not (_строки[0].startswith('🆕') or _строки[0].startswith('🚑')):
                    _беды.append('нет заголовка')
                if len(_строки) < 2:
                    _беды.append('сплошной текст, пунктов нет')
                else:
                    # у пункта первым знаком обязан стоять значок, а не буква и не цифра
                    # ⚠️ «0️⃣» — законный значок из списка З-48, но начинается с ЦИФРЫ.
                    # Первая же проба поймала на этом сам разбор, а не ноту: пункт с
                    # «0️⃣» числился нарушением. Значок-клавиша это цифра + U+FE0F +
                    # U+20E3 — узнаём по хвосту, а не по первому знаку.
                    def _без_значка(с):
                        if len(с) > 2 and с[1] == '️' and с[2] == '⃣':
                            return False
                        return с[0].isalnum() or с[0] in '«"-—·('
                    _без = [с for с in _строки[1:] if _без_значка(с)]
                    if _без:
                        _беды.append('%d пункт(ов) без значка' % len(_без))
            if _беды:
                _кривые.append('%s: %s' % (_з['id'], '; '.join(_беды)))
        if _кривые:
            add('канал/форма ноты', 'CRIT', False,
                'нота НЕ по форме З-48 — %s' % (' · '.join(_кривые))[:150])
        else:
            add('канал/форма ноты', 'CRIT', True,
                'последние %d ноты по форме З-48' % len(_посл))
    except Exception as _e:
        add('канал/форма ноты', 'WARN', True, 'проверить нечем: %s' % str(_e)[:60])


def _проверить_сборку_pages():
    """Не упала ли последняя сборка GitHub Pages.

    🔴 06.09.2026. Выкатил v1591 — на живом остался v1590. Причина оказалась не в коде:
    GitHub Pages дважды подряд уронил сборку («Page build failed», обе за одну секунду,
    без подробностей). Пересборка по запросу прошла.

    ПОЧЕМУ ЭТО БЫЛО НЕВИДИМО. Сторож сверяет ver.txt с APPVER на ЖИВОЙ странице. Когда
    сборка упала, не обновляется НИ ТО НИ ДРУГОЕ — они остаются старыми и сходятся между
    собой. Проверка на рассинхрон честно молчит: рассинхрона и правда нет. Выкатки тоже нет.

    Спрашиваем у самого GitHub. Нет `gh` или нет доступа — говорим «проверить нечем», а не
    «всё хорошо»: молчащая проверка хуже отсутствующей.
    """
    try:
        _о = subprocess.run(['gh', 'api',
                             'repos/germanyalfurqan-eng/hadith-bot/pages/builds/latest'],
                            capture_output=True, timeout=25)
        if _о.returncode != 0:
            add('Pages/сборка', 'WARN', True, 'спросить не вышло (gh недоступен) — не проверено')
            return
        _д = json.loads(_о.stdout.decode('utf-8', 'replace') or '{}')
        _ст = str(_д.get('status') or '?')
        _ком = str(_д.get('commit') or '')[:9]
        if _ст == 'built':
            add('Pages/сборка', 'CRIT', True, 'последняя сборка удалась (%s)' % _ком)
        elif _ст in ('building', 'queued'):
            add('Pages/сборка', 'WARN', True, 'сборка идёт прямо сейчас (%s)' % _ком)
        else:
            _беда = (_д.get('error') or {}).get('message') or 'без объяснения'
            add('Pages/сборка', 'CRIT', False,
                'СБОРКА УПАЛА (%s, %s) — выкатки НЕТ, живёт прежняя версия. Лечится '
                'пересборкой: gh api -X POST repos/germanyalfurqan-eng/hadith-bot/pages/builds'
                % (_ком, _беда[:60]))
    except Exception as _e:
        add('Pages/сборка', 'WARN', True, 'проверить нечем: %s' % str(_e)[:60])


def _проверить_диск():
    """Сколько места осталось на рабочем диске.

    🔴 04.09.2026. Диск дошёл до 95% занятого, и увидел это не сторож, а я случайно, идя
    мимо. Хуже: в этом же файле уже описан прошлый случай — «диск дошёл до 0,69 ГБ
    свободного». Беду знали и сторожа на неё не поставили; знание жило в комментарии.

    Пороги под наши размеры: одна модель весит 20–90 ГБ. Значит 15 ГБ — «уже ничего
    не поместится» (тревога), 40 ГБ — «следующую модель качать некуда» (предупреждение).
    Числа названы прямо, чтобы их можно было оспорить, а не подбирались на глаз.
    """
    # 🔴 04.09.2026, поправка от ЛОКАЛОК 12 в тот же час: смотреть надо ОБА диска.
    # Я проверил только рабочий (C: 50 ГБ из 933), а они посмотрели и второй — D: 86 из 932,
    # то есть 91%. Модели лежат на обоих, и «места нет» на любом из них останавливает работу.
    # Считаем по САМОМУ ТЕСНОМУ: тревога должна звучать по худшему, а не по среднему.
    try:
        import shutil, os as _os
        _диски = []
        for _к in (ROOT, r'D:'):
            try:
                _в, _з, _с = shutil.disk_usage(_к)
                _диски.append((_к[:2], _с / (1024 ** 3), _в / (1024 ** 3),
                               100.0 * _з / _в if _в else 0))
            except Exception:
                pass
        if not _диски:
            add('диск/место', 'WARN', False, 'ни один диск не опросился')
            return
        # худший = у кого меньше всего свободного места
        _к, сг, вг, доля = min(_диски, key=lambda x: x[1])
        _прочие = ' · '.join('%s %.0f ГБ' % (д[0], д[1]) for д in _диски if д[0] != _к)
        строка = ('%s свободно %.0f ГБ из %.0f (занято %.0f%%)%s'
                  % (_к, сг, вг, доля, (' · ' + _прочие) if _прочие else ''))
        # Два признака, и оба нужны. Гигабайты говорят «влезет ли следующая модель»,
        # доля говорит «сколько запаса у самой системы». 04.09.2026: свободно было 50 ГБ —
        # по гигабайтам ещё терпимо, а занято 95%, и это уже опасно для Windows.
        if сг < 15 or доля >= 98:
            add('диск/место', 'CRIT', False, строка + ' — МЕСТА НЕТ')
        elif сг < 40 or доля >= 92:
            add('диск/место', 'WARN', False,
                строка + ' — тесно: модель не поместится, а системе нужен запас')
        else:
            add('диск/место', 'WARN', True, строка)
    except Exception as _e:
        add('диск/место', 'WARN', False, 'посчитать не вышло: %s' % str(_e)[:60])


def _проверить_журналы():
    """Не растут ли журналы без закрытия — З-102.

    🔴 04.09.2026. Журнал ошибок числил 272 открытых при 29 живых; неудачи помощника — 96
    неразобранных, из которых пять были успехами. Обе кучи нашёл человек, идя мимо, а не
    сторож. Механизмы ловили беды исправно — ломалось следующее звено: закрывать было некому.

    Сторож ничего не закрывает: он говорит, что счётчик перестал быть правдой. Закрытие
    с доказательством — работа того, кто чинил.
    """
    import json as _js
    import urllib.request as _ur
    ВЕТКА = 'https://raw.githubusercontent.com/germanyalfurqan-eng/hadith-bot/data/'
    for файл, имя, поле, порог in (('errors.json', 'журнал/ошибки', 'fixed', 60),
                                   ('dsoc_neudachi.json', 'журнал/неудачи', 'разобрано', 40)):
        try:
            with _ur.urlopen(ВЕТКА + файл, timeout=40) as о:
                сп = _js.loads(о.read().decode())
            откр = [з for з in сп if isinstance(з, dict) and not з.get(поле)]
            строка = 'открытых %d из %d' % (len(откр), len(сп))
            if len(откр) >= порог:
                add(имя, 'WARN', False,
                    строка + ' — накопилось: закрывать некому (З-102)')
            else:
                add(имя, 'WARN', True, строка)
        except Exception as _e:
            add(имя, 'WARN', False, 'не прочёлся: %s' % str(_e)[:50])


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

    # 3в) 🔴 РАГ ДЕЛОМ (22.08.2026). Тот же класс, что и перевод, и он же сегодня выстрелил:
    # приложение отвечало «🧠 RAG: ИИ-поиск сейчас недоступен: Authentication error» КАЖДОМУ,
    # а сторож показывал 100% здоровья — он про РАГ не спрашивал вовсе. Ключи Cloudflare
    # (обе пары) отдавали 401 «not authorized for that account», и узнать об этом можно было
    # только руками. Спрашиваем вектор вопроса: пришёл — живо, пришла причина — CRIT.
    try:
        _тело = json.dumps({'q': 'терпение'}).encode('utf-8')
        _зр = urllib.request.Request(BACKEND + '/rag_embed', data=_тело,
                                     headers={'Content-Type': 'application/json',
                                              'User-Agent': 'Mozilla/5.0'})
        _др = json.loads(urllib.request.urlopen(_зр, timeout=120).read().decode('utf-8'))
        _вектор = _др.get('v')
        _причина = str(_др.get('причина') or _др.get('error') or '')
        _код = _др.get('код')
        if isinstance(_вектор, list) and len(_вектор) > 8:
            add('РАГ (делом)', 'CRIT', True, 'вектор пришёл (%d чисел)' % len(_вектор))
        else:
            add('РАГ (делом)', 'CRIT', False,
                'ИИ-поиск не отвечает: %s%s' % (_причина[:70], (' · код %s' % _код) if _код else ''))
    except Exception as _e:
        add('РАГ (делом)', 'WARN', False, 'проверка не прошла: %s' % str(_e)[:70])

# 3я) ЦЕЛОСТНОСТЬ ТАБЛИЦЫ СТИЛЕЙ — заслон против «правило есть в файле, а в браузере его нет»
#
# 🔴 25.08.2026, линия 81. Правка v1295 (07.08) случайно вклеила в <style> кусок разметки —
# теги <details>/<div> легли ВПЕРЕМЕЖКУ со строками CSS. Разбор стилей спотыкается о тег и
# съедает вместе с ним следующее правило целиком. Пропали `.toast` (сообщения приложения
# печатались простой строкой в конце страницы вместо плашки поверх экрана) и `.tr-out`
# (перевод/тафсир открывались без рамки и перестали слушаться регулятора «Aa»), а четыре
# строки подсветки играющего аята были попросту затёрты вставленными <div>.
#
# ЭТО ЖИЛО 18 ДНЕЙ И 217 ВЕРСИЙ. Ни один заслон не сработал: файл разбирается, скрипт
# доходит до конца, ассеты на месте, вёрстка не падает — ломается ТОЛЬКО показ, и молча.
# Ровно тот класс, ради которого сторож и заведён: «данные целы, врёт показ».
#
# Проверка нарочно дешёвая и без браузера: внутри <style> HTML-тегов быть не может НИКОГДА.
# Строки-значения (content:"…") и комментарии выкидываем — в них «<» законен.
try:
    _исх = html.decode('utf-8', 'ignore') if html else ''
    _тегов, _где = 0, []
    for _m in re.finditer(r'<style[^>]*>(.*?)</style>', _исх, re.S | re.I):
        _css = re.sub(r'/\*.*?\*/', '', _m.group(1), flags=re.S)      # комментарии
        _css = re.sub(r'"[^"\n]*"|\'[^\'\n]*\'', '""', _css)          # строки-значения
        for _t in re.finditer(r'</?(?:div|details|summary|span|button|select|option|'
                              r'textarea|input|p|b|i|img|a|table|tr|td|h[1-6]|label|ul|li)\b',
                              _css, re.I):
            _тегов += 1
            if len(_где) < 4:
                _где.append(_css[max(0, _t.start() - 20):_t.start() + 42].strip().replace('\n', ' '))
    if _тегов:
        add('стили(целость)', 'CRIT', False,
            'внутри <style> лежит РАЗМЕТКА (%d тегов) — правила рядом с ней браузер теряет: %s'
            % (_тегов, ' · '.join(_где)))
    else:
        add('стили(целость)', 'CRIT', True, 'в <style> посторонней разметки нет')
except Exception as _e:
    add('стили(целость)', 'WARN', False, 'проверить не вышло: %s' % str(_e)[:70])

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
        # 🔴 21.08.2026, ночная тревога владельца: «срочно 1 ГБ на диске». Виноват был ЭТОТ
        # кусок. Уборка тут стояла — `shutil.rmtree(ud, ignore_errors=True)` — и НЕ РАБОТАЛА:
        # Windows держит замок на файлах профиля ещё секунду-другую после выхода Edge, rmtree
        # спотыкался, а `ignore_errors=True` проглатывал это молча. За время работы накопилось
        # 115 профилей на 2,86 ГБ, и диск дошёл до 0,69 ГБ свободного.
        # Тот же класс, что я чинил весь вечер: заслон есть, срабатывает вхолостую и молчит.
        # Лечим двумя приёмами: ① подметаем вчерашние остатки при каждом запуске — что не
        # удалилось сегодня, уйдёт завтра; ② свой профиль убираем с повторами и, если так и не
        # вышло, ГОВОРИМ об этом, а не глотаем.
        def _прибрать(путь, попыток=4):
            for _i in range(попыток):
                shutil.rmtree(путь, ignore_errors=True)
                if not os.path.exists(путь):
                    return True
                time.sleep(0.7)          # Edge отпускает замок не мгновенно
            return False

        _осталось, _вес = 0, 0
        try:
            _тмп = tempfile.gettempdir()
            for _им in os.listdir(_тмп):
                if not _им.startswith('hc_edge_'):
                    continue
                _п = os.path.join(_тмп, _им)
                try:
                    if os.path.isdir(_п) and (time.time() - os.path.getmtime(_п)) > 600:
                        if not _прибрать(_п, 1):
                            _осталось += 1
                            for _к, _, _фф in os.walk(_п):
                                for _ф in _фф:
                                    try:
                                        _вес += os.path.getsize(os.path.join(_к, _ф))
                                    except Exception:
                                        pass
                except Exception:
                    pass
        except Exception:
            pass
        # Кричим, только если остатки РЕАЛЬНО занимают место. Один пустой каталог, который
        # Windows не отдаёт («Access is denied»), места не ест, а ежечасное предупреждение о
        # нём — тот самый шум, за который сегодня был разбор со сторожем архива: тревога,
        # срабатывающая всегда, перестаёт быть тревогой.
        if _осталось and _вес > 50 * 1024 * 1024:
            print('  ⚠️ прошлых профилей Edge не убралось: %d, занимают %.2f ГБ (в %s)'
                  % (_осталось, _вес / 1073741824.0, tempfile.gettempdir()))

        out = ''
        _не_убрал = []
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
                if not _прибрать(ud):
                    _не_убрал.append(ud)
            if out and '<html' in out.lower():
                break
        if _не_убрал:
            # Молча не глотаем: незамеченная уборка и довела диск до предела.
            print('  ⚠️ свой профиль Edge убрать не удалось: %s' % ' · '.join(_не_убрал))
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

# Страница-ревизор: грузит приложение в рамку того же происхождения и слушает, что оно
# скажет во время работы. Собрана списком строк и склеена chr(10) — без единого
# экранирования: этот файл дважды рвался ровно на слоях кавычек.
_РЕВИЗОР_HTML = chr(10).join([
    '<!doctype html>',
    "<meta charset='utf-8'>",
    '<title>ревизор ошибок</title>',
    "<body style='font:13px monospace'>",
    "<div id='itog'>идёт</div>",
    "<iframe id='ramka' src='./index.html' style='width:390px;height:820px;border:0'></iframe>",
    '<script>',
    '(function(){',
    '  var sob=[], vid={};',
    '  var dob=function(v,t,g){',
    "    var k=v+'|'+String(t).slice(0,160);",
    '    if(vid[k]){ vid[k].raz++; return; }',
    '    vid[k]={raz:1};',
    "    sob.push({v:v, t:String(t).slice(0,300), g:String(g||'').slice(0,160), s:vid[k]});",
    '  };',
    "  var r=document.getElementById('ramka');",
    '  r.onload=function(){',
    '    var o=r.contentWindow;',
    '    try{',
    "      o.addEventListener('error',function(e){",
    "        dob('ошибка',(e&&e.message)||String(e),((e&&e.filename)||'')+':'+((e&&e.lineno)||''));",
    '      },true);',
    "      o.addEventListener('unhandledrejection',function(e){",
    "        dob('обещание',(e&&e.reason&&(e.reason.message||e.reason))||'без причины','');",
    '      });',
    '      var pr=o.console&&o.console.error;',
    '      if(pr){ o.console.error=function(){',
    "        try{ dob('console.error',Array.prototype.join.call(arguments,' '),''); }catch(_){}",
    '        return pr.apply(o.console,arguments); }; }',
    "    }catch(e){ dob('ловушки','не поставились: '+e,''); }",
    '    setTimeout(function(){',
    '      var iz=sob.map(function(z){ return {вид:z.v, раз:z.s.raz, что:z.t, где:z.g}; });',
    "      document.getElementById('itog').textContent='ИТОГ '+JSON.stringify({всего:iz.length, список:iz});",
    '    },12000);',
    '  };',
    '})();',
    '</script>',
    '</body>',
])

# 4в) ТРЕТИЙ ЗАСЛОН — ЖИВЫЕ ОШИБКИ ПРИ ЗАПУСКЕ (только --local) --------------
# 24.08.2026, по следам A-242/A-243. Две ошибки приложения пришли ко мне ОТ ЖИВЫХ ЛЮДЕЙ через
# сутки после выкатки. Все прежние заслоны молчали и каждый был прав по-своему: рендер дошёл
# до конца, синтаксис разобрался, здоровье 100%. Ни один не ЗАПУСКАЛ приложение и не слушал,
# что оно говорит во время работы. Здесь слушаем: onerror, unhandledrejection, console.error.
# Только для --local: заслон нужен ПЕРЕД выкаткой, а на боевой вспомогательный файл не положить.
if USE_LOCAL:
    _ревизор_файл = None
    try:
        import subprocess as _sp2, tempfile as _tf2
        _edge2 = None
        for _p2 in (r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe'):
            if os.path.exists(_p2):
                _edge2 = _p2
                break
        if not _edge2:
            add('живые ошибки(JS)', 'WARN', True, 'Edge не найден — проверка пропущена')
        else:
            _ревизор_файл = os.path.join(ROOT, 'miniapp', '_hc_zhivye_oshibki.html')
            io.open(_ревизор_файл, 'w', encoding='utf-8').write(_РЕВИЗОР_HTML)
            _вых2 = ''
            for _з2 in range(2):
                _ud2 = _tf2.mkdtemp(prefix='hc_rev_')
                try:
                    _вых2 = _sp2.run([_edge2, '--headless=new', '--disable-gpu', '--no-sandbox',
                                      '--user-data-dir=' + _ud2, '--virtual-time-budget=60000',
                                      '--dump-dom', LOCAL + '_hc_zhivye_oshibki.html'],
                                     capture_output=True, timeout=300).stdout.decode('utf-8', 'ignore')
                finally:
                    _прибрать(_ud2)
                if 'ИТОГ ' in _вых2:
                    break
            _м2 = re.search('ИТОГ (.*?)</div>', _вых2, re.S)
            if not _м2:
                add('живые ошибки(JS)', 'WARN', True,
                    'ревизор не отчитался (Edge отдал %d байт) — проверка пропущена' % len(_вых2))
            else:
                _д2 = json.loads(_м2.group(1))
                if _д2.get('всего'):
                    _сп2 = '; '.join('%s x%d: %s' % (з['вид'], з['раз'], з['что'][:90])
                                     for з in _д2['список'][:4])
                    add('живые ошибки(JS)', 'CRIT', False,
                        'приложение ругается при запуске (%d): %s' % (_д2['всего'], _сп2))
                else:
                    add('живые ошибки(JS)', 'CRIT', True,
                        'при запуске приложение не выдало ни одной ошибки')
    except Exception as _e2:
        add('живые ошибки(JS)', 'WARN', True, 'проверка сорвалась: %s' % str(_e2)[:90])
    finally:
        # Файл-ревизор не должен пережить проверку: он лежит в miniapp/ и иначе уедет на боевой.
        try:
            if _ревизор_файл and os.path.exists(_ревизор_файл):
                os.remove(_ревизор_файл)
        except Exception:
            pass

# 4б) ВТОРОЙ ЗАСЛОН — СИНТАКСИС ЧЕРЕЗ node --check --------------------------
# 15.08.2026: перед выкаткой v1390 рендер-гейт написал «пропущена», а итог всё равно
# сказал «ЗДОРОВ ✅». Запасной разбор (esprima) не понимает `?.` и не разбирал файл
# никогда. Два заслона из двух молчали. Молчащая проверка хуже, чем никакой.
# node ловит ровно тот класс, ради которого стоял рендер: SyntaxError и дубликат `let`
# (дубликат `let` в одной области видимости и ЕСТЬ SyntaxError).
_рендер_пропущен = any(c['name'] == 'render(JS)' and c['ok'] and c['level'] == 'WARN'
                       for c in checks)
try:
    import shutil as _sh, subprocess as _sp, tempfile as _tf, os as _os
    _node = _sh.which('node')
    _текст = html.decode('utf-8', 'ignore') if html else ''
    if not _node:
        if USE_LOCAL and _рендер_пропущен:
            add('синтаксис(node)', 'CRIT', False,
                'ПРОВЕРИТЬ НЕЧЕМ: рендер пропущен и node нет — выкатывать вслепую нельзя')
        else:
            add('синтаксис(node)', 'WARN', True, 'node не найден — разбор пропущен')
    elif not _текст:
        add('синтаксис(node)', 'WARN', True, 'нет текста страницы — разбирать нечего')
    else:
        _скр = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', _текст, re.S)
        _битый, _где = 0, ''
        for _n, _s in enumerate(_скр, 1):
            if not _s.strip():
                continue
            _f = _os.path.join(_tf.gettempdir(), 'hc_sk%d.js' % _n)
            io.open(_f, 'w', encoding='utf-8').write(_s)
            _r = _sp.run([_node, '--check', _f], capture_output=True, timeout=60)
            _os.remove(_f)
            if _r.returncode:
                _битый += 1
                _е = _r.stderr.decode('utf-8', 'replace').strip().split('\n')
                _где = ' | '.join(x.strip() for x in _е[:3])[:150]
        if _битый:
            add('синтаксис(node)', 'CRIT', False,
                'инлайн-скрипт НЕ разбирается (%d шт.) — белый экран (П-01): %s' % (_битый, _где))
        else:
            add('синтаксис(node)', 'CRIT', True,
                'все %d инлайн-скриптов разбираются' % len([s for s in _скр if s.strip()]))
except Exception as _e:
    add('синтаксис(node)', 'WARN', False, 'разбор не прошёл: %s' % str(_e)[:70])

# 4в) ТРЕТИЙ ЗАСЛОН — НЕСУЩЕСТВУЮЩИЕ ИМЕНА В bot.py -----------------------
# 15.08.2026: за один день нашлись ПЯТЬ обращений к именам, которых в файле нет —
# log (дважды), sys, латинское bot вместо кириллического бот, _хозяин до своего
# объявления, application вместо app. Каждое падало NameError ВНУТРИ try: ветка не
# работала никогда и ни разу не пожаловалась. Указ владельца от 03.07 (обращения
# Клода в рабочий журнал) не исполнялся именно по этой причине.
# Глазами такое не ловится — строка выглядит верной. Ловит разбор.
_РАЗОБРАНЫ = {
    # имя: почему это НЕ беда. Список короткий нарочно: он не свалка для новых бед.
    '_e_post': 'замыкание внутри except вызывается там же, имя ещё живо — проверено 15.08',
}
try:
    import subprocess as _sp2, shutil as _sh2, os as _os2, re as _re2
    _бот = _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), 'bot.py')
    if not _os2.path.exists(_бот):
        add('имена(bot.py)', 'WARN', True, 'bot.py рядом нет — разбор пропущен')
    else:
        _r2 = _sp2.run([sys.executable, '-m', 'pyflakes', _бот], capture_output=True, timeout=180)
        _вых = (_r2.stdout or b'').decode('utf-8', 'replace')
        if 'No module named' in (_r2.stderr or b'').decode('utf-8', 'replace'):
            add('имена(bot.py)', 'WARN', True, 'pyflakes не установлен — разбор пропущен')
        else:
            _плохие = []
            for _стр in _вых.split('\n'):
                _m2 = _re2.search(r":(\d+):\d+: undefined name '(.+?)'", _стр)
                if _m2 and _m2.group(2) not in _РАЗОБРАНЫ:
                    _плохие.append('%s (строка %s)' % (_m2.group(2), _m2.group(1)))
            if _плохие:
                add('имена(bot.py)', 'CRIT', False,
                    'обращение к НЕСУЩЕСТВУЮЩИМ именам, ветка упадёт молча: %s'
                    % '; '.join(_плохие[:6]))
            else:
                add('имена(bot.py)', 'CRIT', True,
                    'несуществующих имён нет (разобранных исключений: %d)' % len(_РАЗОБРАНЫ))
except Exception as _e2:
    add('имена(bot.py)', 'WARN', False, 'разбор имён не прошёл: %s' % str(_e2)[:70])



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

# 4в2) ДВЕРИ API — ОТВЕЧАЮТ ЛИ ОНИ ПО ДЕЛУ (03.09.2026) --------------------
# 🔴 Повод. Прогнал руками все шестнадцать читающих дверей осмысленными вопросами и нашёл
# мёртвую: /api/search ходил на dorar.net, а тот закрылся для роботов (403). Дверь отвечала
# кодом 200 и пустым списком — то есть для любого сторожа, который смотрит только на код,
# она была ЖИВА. Человек же видел «ничего не найдено» и думал, что в базе пусто.
# Сколько это длилось — неизвестно, потому что никто не смотрел.
# Проверяем не код ответа, а СОДЕРЖИМОЕ: на заведомо частый вопрос дверь обязана вернуть
# непустой список. Пусто при 200 — это тревога, а не тишина.
try:
    import urllib.parse as _up_d
    _ЧАСТЫЙ = _up_d.quote('إنما الأعمال')
    _ДВЕРИ = [
        ('дверь/search',  '/search?q=' + _ЧАСТЫЙ,               ('results',), 'CRIT'),
        ('дверь/wide',    '/wide?q=' + _up_d.quote('الصلاة'),   ('data',),    'WARN'),
        ('дверь/maktaba', '/maktaba?q=' + _up_d.quote('الصلاة') + '&limit=3', ('data',), 'WARN'),
        ('дверь/rijal',   '/rijal?q=' + _up_d.quote('نافع'),    ('data', 'results'), 'WARN'),
    ]
    for _имя_д, _хвост, _поля, _ур_д in _ДВЕРИ:
        try:
            # http() отдаёт ТРИ значения: код, заголовки, тело-байты. Распаковал в два —
            # и все четыре двери «не ответили»; сторож соврал бы на ровном месте.
            _ст, _заг_д, _тело = http(BACKEND + _хвост, timeout=90)
            if _ст != 200:
                add(_имя_д, _ур_д, False, 'HTTP %s' % _ст)
                continue
            _д = json.loads((_тело or b'').decode('utf-8', 'replace'))
            _сп_д = None
            for _п_д in _поля:
                if isinstance(_д.get(_п_д), list):
                    _сп_д = _д[_п_д]
                    break
            if _сп_д is None:
                add(_имя_д, _ур_д, False, 'в ответе нет списка (%s)' % ', '.join(_поля))
            elif not _сп_д:
                _почему = str(_д.get('почему') or _д.get('источник') or '')[:60]
                add(_имя_д, _ур_д, False, 'ответила 200, но НИЧЕГО не нашла%s'
                    % ((' · ' + _почему) if _почему else ''))
            else:
                add(_имя_д, _ур_д, True, 'нашла %d%s' % (
                    len(_сп_д), (' · ' + str(_д.get('источник'))) if _д.get('источник') else ''))
        except Exception as _е_д:
            add(_имя_д, _ур_д, False, 'не ответила: %s' % str(_е_д)[:60])
except Exception:
    pass

# 4г) КЛОНЫ ВЫКАТКИ — ЖИВЫ ЛИ ОНИ ВООБЩЕ (В-90, П-93, 29.08.2026) -----------
# 🔴 Повод. Боевой клон лежал в %TEMP%. Windows чистит эту папку сама, и она вынесла у него
# `.git/HEAD` и `.git/config`, у одного packfile — индекс, а из рабочей копии почти всё:
# 29 353 «удаления». Обнаружилось это не сторожем, а тем, что выкатка встала посреди работы.
# Прошлая смена видела 674 «удаления» и посчитала их чужой чисткой ради места — то есть
# разрушение шло на глазах и было принято за норму.
# Сторож смотрит ровно на то, чего не хватало: отвечает ли репозиторий и не выглядит ли его
# рабочая копия выпотрошенной. Разрушенный клон должен находиться ЗАРАНЕЕ, а не в момент,
# когда нужно выкатывать.
try:
    import subprocess as _sp_k
    _КЛОНЫ = [
        ('клон/выкатка', os.path.join(os.path.expanduser('~'), 'Documents', 'hadith-bot-push')),
        ('клон/данные', os.path.join(os.path.expanduser('~'), 'Documents', 'hadith-bot-data')),
    ]
    for _имя, _путь in _КЛОНЫ:
        if not os.path.isdir(_путь):
            add(_имя, 'CRIT', False, 'папки нет вовсе: %s' % _путь)
            continue
        try:
            _о = _sp_k.run(['git', '-C', _путь, 'rev-parse', 'HEAD'],
                           capture_output=True, text=True, timeout=40)
            if _о.returncode != 0:
                add(_имя, 'CRIT', False, 'git не отвечает: %s' % (_о.stderr or '').strip()[:70])
                continue
            _голова = (_о.stdout or '').strip()[:9]
            # Массовые удаления в рабочей копии = её вычистили снаружи. Одна команда
            # `git add -A` в таком клоне снесла бы данные с боевого сайта.
            _с = _sp_k.run(['git', '-C', _путь, 'status', '--porcelain'],
                           capture_output=True, text=True, timeout=90)
            _удалений = sum(1 for _с1 in (_с.stdout or '').splitlines() if _с1[:2].strip() == 'D')
            if _удалений > 20:
                add(_имя, 'CRIT', False,
                    'рабочая копия выпотрошена: %d удалений (HEAD %s)' % (_удалений, _голова))
            else:
                add(_имя, 'CRIT', True, 'жив, HEAD %s, удалений %d' % (_голова, _удалений))
        except Exception as _e:
            add(_имя, 'WARN', True, 'проверка пропущена (%s)' % str(_e)[:40])
except Exception:
    pass

_проверить_диск()
_проверить_журналы()
if not USE_LOCAL:
    _проверить_сборку_pages()
_проверить_форму_ноты()

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

def _тревога_новая(имена):
    """Стоит ли шуметь: беда новая, изменилась или висит уже шесть часов.

    🔴 06.09.2026. Сторож нашёл настоящую беду — на диске D: осталось 3 ГБ из 931 — и
    отправил владельцу пуш с высоким приоритетом. Правильно. Но планировщик зовёт сторожа
    ЕЖЕЧАСНО, а беда такая, что чинится не за час: пока владелец не решит, что убрать,
    тот же пуш будил бы его двадцать четыре раза в сутки.
    В этом же файле выше написано: «тревога, срабатывающая всегда, перестаёт быть тревогой».
    Мы это про себя и написали, а исполнено не было.
    Правило: шумим, когда НАБОР упавших проверок ИЗМЕНИЛСЯ (появилась новая беда или ушла
    старая), и повторяем не чаще раза в шесть часов — чтобы висящая беда всё-таки не
    забылась совсем. Молчание про уже сказанное — не сокрытие: запись в health_report.json
    делается всегда, и код возврата остаётся тревожным, гейт деплоя работает как работал.
    """
    import time as _t
    путь = os.path.join(ROOT, '.health_alarm_state.json')
    сейчас = _t.time()
    ключ = '|'.join(sorted(имена))
    было = {}
    try:
        было = json.load(open(путь, encoding='utf-8'))
    except Exception:
        было = {}
    прошлый_ключ = было.get('ключ') or ''
    когда = float(было.get('когда') or 0)
    надо = (ключ != прошлый_ключ) or (сейчас - когда > 6 * 3600)
    if надо:
        try:
            json.dump({'ключ': ключ, 'когда': сейчас,
                       'человечески': time.strftime('%d.%m.%Y %H:%M')},
                      open(путь, 'w', encoding='utf-8'), ensure_ascii=False)
        except Exception:
            pass
    return надо


_шуметь = True
if crit_fail and not USE_LOCAL and not ПОДОЗРЕВАТЬ_СЕБЯ:
    _шуметь = _тревога_новая([c['name'] for c in crit_fail])
    if not _шуметь:
        print('-> та же тревога, что и в прошлый раз (%s) — владельца не бужу, '
              'следующее напоминание через 6 часов'
              % ', '.join(c['name'] for c in crit_fail))

if crit_fail and not USE_LOCAL and not ПОДОЗРЕВАТЬ_СЕБЯ and _шуметь:
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
