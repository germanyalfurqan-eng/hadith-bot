# -*- coding: utf-8 -*-
"""Генерация картинок из Telegram: «ботяра нарисуй / измени / генерация вкл|выкл|статус».

ЗАЧЕМ: Claude Code · ЛОКАЛКИ 37 · 21.10.2026. Слово владельца: «делай ты по короткому пути: сначала
только на меня» и «доделай его грамотно» — после оценки плана Кодекса
(scratch_marathon/_l37/OCENKA_PLANA_KODEKSA_BOT_KARTINOK.md в рабочей папке).

КАК УСТРОЕНО (ноутбук НЕ открыт наружу ни одним портом):
  Telegram → этот модуль ставит задание в очередь /obmen/generaciya →
  работник на ноутбуке (rabotnik_shlyuza.py) САМ ходит сюда по HTTPS: /api/gen/vzyat →
  отдаёт задание окну генерации 127.0.0.1:8830 (там очередь, замок карты, улучшитель, правка) →
  /api/gen/gotovo с готовой картинкой → бот отвечает в тот же чат reply'ем.
Из Telegram приходит только вид (нарисуй/измени), текст просьбы и картинка — ни графов ComfyUI,
ни путей, ни команд. Ключ работника — свой (GEN_SECRET), не общий BACKUP_SECRET: утечка одного
не открывает другое. Нет GEN_SECRET в окружении — дверь работника закрыта (503).

ДОСТУП (этап 1): только владелец по is_owner бота (личный ID, второй аккаунт, его канал «MUSLIMOON»), только
личка и группа @jamaat_ru. Никому больше —
сообщение чужого просто идёт дальше по обычному пути бота, как будто модуля нет.
"""
import asyncio, base64, io, json, os, re, time, uuid

import aiohttp
from aiohttp import web
from telegram.error import TimedOut
from telegram.ext import ApplicationHandlerStop, MessageHandler, filters

GRUPPA_JAMAAT = -1001925828112          # @jamaat_ru — проверено getChat (план Кодекса, 21.10)
# /state в контейнере смонтирован ТОЛЬКО НА ЧТЕНИЕ (vykatka.sh: -v state:/state:ro) — пишем в /obmen
PAPKA = next((p for p in ('/obmen/generaciya', '/opt/muslimoon/obmen/generaciya') if os.path.isdir(os.path.dirname(p))),
             os.path.join(os.path.dirname(os.path.abspath(__file__)), 'state_generaciya'))
FAYL = os.path.join(PAPKA, 'zadaniya.json')
NASTR = os.path.join(PAPKA, 'nastroyki.json')
ARENDA_S = 20 * 60          # сколько задание числится за работником: холодный подъём с W: ~3 мин + улучшитель + запас
POPYTOK = 2                 # работник пропал дважды — задание закрываем ошибкой, а не крутим вечно
OCHERED_MAX = 20
PROMT_MAX = 2000
KARTINKA_MAX = 10 * 1024 * 1024
KOMANDA = re.compile(r'^\s*ботяра[\s,:!]+(нарисуй|измени|генерация|новая\s+сессия)\b[\s,:]*(.*)$', re.I | re.S)

# ── АГЕНТ (владелец #3866, 21.10 20:57): «рисование как агент — память, сжатие контекста, основное из памяти
# помощника о чате (без моей кухни), функция новая сессия». Беседа рисования живёт ПО ЧАТУ:
#   · ходы — последние просьбы; старше HODOV_ZHIVYH сжимаются мозгом Oracle (Qwen :8097) в «сводку»;
#   · posl — последняя картинка: «ботяра измени …» без фото правит её;
#   · память о чате — выжимка из разговора помощника в этом чате (dsoc_память), очищенная от кухни;
#   · всё это уходит на ноутбук как «контекст» и попадает в улучшитель промта, а не в модель картинок.
SESSII = os.path.join(PAPKA, 'sessii')
PAMYAT_FAYL = os.path.join(PAPKA, 'pamyat_chatov.json')
HODOV_ZHIVYH = 5            # столько последних просьб идёт в контекст дословно
SZHIMAT_POSLE = 8           # ходов больше — старые сжимаются в сводку
PAMYAT_SVEZHEST = 6 * 3600  # выжимку о чате пересобираем не чаще раза в 6 ч
MOZG = ('http://172.17.0.1:8097/v1/chat/completions', 'http://127.0.0.1:8097/v1/chat/completions')
# Кухня — то, что владелец не велел давать рисовальщику: служебное, ключи, адреса, наши харнесы и машины
KUHNYA = re.compile(r'https?://|token|ключ|секрет|пароль|claude|клод|кодекс|codex|гермес|hermes|оракл|oracle|сервер|'
                    r'харнес|деплой|выкат|github|коммит|strata|llama|gpu|видеокарт|dsoc|технадзор|локалки|ssh', re.I)

_app = None
_owner = None
_svoy = None   # проверка «это владелец» из bot.py
_zamok = asyncio.Lock()
_rabotnik = {'kogda': 0.0, 'vkl_lokalno': None, 'imya': ''}
_pamyat_fn = None   # dsoc_память(chat_id) из bot.py — разговор помощника в чате
_fon = set()        # фоновые задачи (сжатие, выжимка): держим ссылки, иначе сборщик мусора их снимет


def _sekret():
    return (os.environ.get('GEN_SECRET') or '').strip()


def _chitat(p, pusto):
    try:
        return json.load(io.open(p, encoding='utf-8'))
    except Exception:
        return pusto


def _pisat(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    io.open(tmp, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def _vkl():
    return bool(_chitat(NASTR, {}).get('vkl', True))


def _ochistit_staroe(z):
    """Готовые старше 3 суток — вон из очереди вместе с файлами: копилка личных картинок не нужна."""
    srok = time.time() - 3 * 86400
    for k in [k for k, v in z.items() if v.get('status') in ('готово', 'ошибка') and v.get('sozdano', 0) < srok]:
        for f in (z[k].get('vhod'),):
            if f:
                try:
                    os.remove(os.path.join(PAPKA, f))
                except OSError:
                    pass
        del z[k]


def _vozvrat_prosrochennyh(z):
    """Работник взял и пропал (ноутбук уснул, сеть) — вернуть задание в очередь или закрыть."""
    vernut = []
    for v in z.values():
        if v.get('status') == 'у работника' and v.get('arenda_do', 0) < time.time():
            if v.get('popytka', 0) >= POPYTOK:
                v['status'], v['oshibka'] = 'ошибка', 'ноутбук взял задание и не вернул результат (%d раза)' % POPYTOK
                vernut.append(v)
            else:
                v['status'] = 'ждёт'
    return vernut


def _nomer(z):
    return max([v.get('nomer', 0) for v in z.values()] + [0]) + 1


async def _skazat(chat, tekst, otvet_na=None, nit=None):
    try:
        return await _app.bot.send_message(chat, tekst, reply_to_message_id=otvet_na, message_thread_id=nit,
                                           allow_sending_without_reply=True)
    except Exception as e:
        print('generaciya_tg: не смог написать', chat, e, flush=True)


async def _pravit(v, tekst):
    if not v.get('soob_id'):
        return
    try:
        await _app.bot.edit_message_text(tekst, chat_id=v['chat'], message_id=v['soob_id'])
    except Exception:
        pass   # «текст не изменился» и прочее — не повод ронять работу


def _rabotnik_tekst():
    if not _rabotnik['kogda']:
        return '⚠️ ноутбук ещё ни разу не выходил на связь с момента запуска бота'
    s = int(time.time() - _rabotnik['kogda'])
    kogda = '%d с назад' % s if s < 120 else '%d мин назад' % (s // 60)
    if s > 120:
        return '⚠️ ноутбук не на связи (последний раз %s) — задания подождут' % kogda
    if not _rabotnik['vkl_lokalno']:
        return '⏸ ноутбук на связи, но в окне генерации снята галочка «Telegram» — задания ждут'
    return '✅ ноутбук на связи (%s)' % kogda


async def _kartinka_iz(m):
    """Картинка из самого сообщения или из того, на которое ответили. Возвращает (байты, расширение) или (None, причина)."""
    for s in (m, m.reply_to_message):
        if not s:
            continue
        if s.photo:
            fid, rassh, razmer = s.photo[-1].file_id, 'jpg', s.photo[-1].file_size or 0
        elif s.document and (s.document.mime_type or '').startswith('image/') and s.document.mime_type != 'image/svg+xml':
            fid, razmer = s.document.file_id, s.document.file_size or 0
            rassh = {'image/png': 'png', 'image/webp': 'webp', 'image/jpeg': 'jpg'}.get(s.document.mime_type, '')
            if not rassh:
                return None, 'такой формат не беру — пришлите PNG, JPG или WEBP'
        else:
            continue
        if razmer > KARTINKA_MAX:
            return None, 'картинка больше 10 МБ'
        f = await _app.bot.get_file(fid)
        dannye = bytes(await f.download_as_bytearray())
        if len(dannye) > KARTINKA_MAX:
            return None, 'картинка больше 10 МБ'
        return dannye, rassh
    return None, 'нужна картинка: приложите её к сообщению или ответьте командой на сообщение с картинкой'


async def _obrabotchik(update, context):
    m = update.effective_message
    if not m:
        return
    # 🔴 21.10, первая живая проба владельца: он пишет в @jamaat_ru от имени своего канала «MUSLIMOON»
    # (sender_chat), его личного ID в таком сообщении НЕТ — а я такие отбрасывал, и команду перехватывал
    # общий ИИ («я текстовый ассистент»). Владельца узнаём той же проверкой, что весь бот: is_owner из
    # bot.py (личный ID, второй аккаунт OWNER_ID2, канал владельца OWNER_CHANNEL_ID).
    if not (_svoy(update) if _svoy else (update.effective_user and update.effective_user.id == _owner)):
        return                                   # чужой — модуля для него нет, сообщение идёт дальше
    if not (m.chat.type == 'private' or m.chat.id == GRUPPA_JAMAAT):
        return
    tekst = m.text or m.caption or ''
    k = KOMANDA.match(tekst)
    if not k:
        return
    vid, prosba = k.group(1).lower(), k.group(2).strip()
    nit = m.message_thread_id if getattr(m, 'is_topic_message', False) else None
    try:
        await _komanda(m, vid, prosba, nit)
    except Exception as e:
        await _skazat(m.chat.id, '⚠️ генерация: сбой — %s' % str(e)[:300], m.message_id, nit)
    raise ApplicationHandlerStop                 # команда наша — общий ИИ её не трогает


def _sess_put(chat):
    return os.path.join(SESSII, '%s.json' % chat)


def _sessiya(chat):
    return _chitat(_sess_put(chat), None) or {'hody': [], 'svodka': '', 'posl': None, 'nachalo': time.time()}


def _v_fon(korutina):
    t = asyncio.ensure_future(korutina)
    _fon.add(t)
    t.add_done_callback(_fon.discard)


async def _mozg(sistema, tekst, n=300):
    """Мозг Oracle (Qwen на :8097, без размышления). Пусто — не ответил; зовущий держит запасной путь."""
    telo = {'model': 'm', 'messages': [{'role': 'system', 'content': sistema}, {'role': 'user', 'content': tekst[:6000]}],
            'max_tokens': n, 'temperature': 0.3, 'chat_template_kwargs': {'enable_thinking': False}}
    for adres in MOZG:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=240)) as ss:
                async with ss.post(adres, json=telo) as o:
                    if o.status != 200:
                        continue
                    t = (((await o.json()).get('choices') or [{}])[0].get('message') or {}).get('content') or ''
                    t = re.sub(r'<think>.*?</think>', '', t, flags=re.S).strip()
                    if t:
                        return t
        except Exception:
            continue
    return ''


def _bez_kuhni(tekst):
    return '\n'.join(l for l in (tekst or '').splitlines() if l.strip() and not KUHNYA.search(l))


async def _obnovit_pamyat(chat):
    """Выжимка «что важно знать художнику об этом чате» из разговора помощника. Кухню режем ДВАЖДЫ:
    строки со служебным — до мозга (он их не увидит), и ещё раз в его ответе."""
    try:
        # dsoc_память при первом чтении ходит в ветку data GitHub — в отдельном потоке, чтобы не держать бота
        soob = list(await asyncio.to_thread(_pamyat_fn, chat) or [])[-40:] if _pamyat_fn else []
    except Exception:
        soob = []
    stroki = []
    for x in soob:
        t = x.get('content') if isinstance(x, dict) else x
        if isinstance(t, list):
            t = ' '.join(str(c.get('text', '')) for c in t if isinstance(c, dict))
        t = _bez_kuhni(str(t or ''))
        if t:
            stroki.append(t[:400])
    tekst = ''
    if stroki:
        tekst = _bez_kuhni(await _mozg(
            'Ты помогаешь художнику. По переписке чата выдели 3–6 коротких пунктов: о чём этот чат, какие темы, '
            'предметы, места и стиль здесь важны. Только то, что поможет рисовать по просьбам участников. '
            'Ничего технического: никаких программ, серверов, ключей, ссылок, личных данных. '
            'По-русски, пунктами, не длиннее 400 знаков.', '\n'.join(stroki)[-6000:]))[:500]
    async with _zamok:
        p = _chitat(PAMYAT_FAYL, {})
        p[str(chat)] = {'tekst': tekst, 'kogda': time.time()}
        _pisat(PAMYAT_FAYL, p)


def _kontekst(chat):
    """Что уйдёт улучшителю вместе с новой просьбой. Пустая строка — контекста нет."""
    s = _sessiya(chat)
    chasti = []
    pam = (_chitat(PAMYAT_FAYL, {}).get(str(chat)) or {}).get('tekst')
    if pam:
        chasti.append('О чате: ' + pam)
    if s.get('svodka'):
        chasti.append('Раньше в этой беседе (сжато): ' + s['svodka'])
    hody = s.get('hody', [])[-HODOV_ZHIVYH:]
    if hody:
        chasti.append('Последние просьбы, по порядку: ' + '; '.join('%s — %s' % (h['vid'], h['promt'][:200]) for h in hody))
    return '\n'.join(chasti)[:1500]


async def _szhat(chat):
    """Старые ходы → сводка мозгом. Мозг не ответил — сводка простой склейкой: память не теряем никогда."""
    s = _sessiya(chat)
    starye = s.get('hody', [])[:-HODOV_ZHIVYH]
    if not starye:
        return
    spisok = '\n'.join('%s: %s' % (h['vid'], h['promt'][:300]) for h in starye)
    nov = await _mozg('Сожми историю просьб к художнику в 2–3 предложения: что рисовали, какие предметы, стили и '
                      'правки были. Сохрани предметы и детали, на которые могут сослаться позже. По-русски, до 500 знаков.',
                      ('Прежняя сводка: %s\n' % s['svodka'] if s.get('svodka') else '') + spisok)
    if not nov:
        nov = ((s['svodka'] + ' ') if s.get('svodka') else '') + '; '.join(h['promt'][:80] for h in starye)
    nomera = {h['nomer'] for h in starye}
    async with _zamok:
        s = _sessiya(chat)
        s['hody'] = [h for h in s['hody'] if h['nomer'] not in nomera]
        s['svodka'] = nov[-700:]
        _pisat(_sess_put(chat), s)


async def _zapomnit_hod(v, dannye):
    """Удачный ход: картинку — в «последнюю» беседы, просьбу — в ходы; ходов много — сжать в фоне."""
    async with _zamok:
        s = _sessiya(v['chat'])
        posl = '%s_posl.png' % v['chat']
        os.makedirs(SESSII, exist_ok=True)
        io.open(os.path.join(SESSII, posl), 'wb').write(dannye)
        s['posl'], s['posl_nomer'] = posl, v['nomer']
        s['hody'].append({'nomer': v['nomer'], 'vid': v['vid'], 'promt': v['promt'][:600], 'kogda': time.time()})
        _pisat(_sess_put(v['chat']), s)
        dlinno = len(s['hody']) > SZHIMAT_POSLE
    if dlinno:
        _v_fon(_szhat(v['chat']))


async def _novaya_sessiya(m, nit):
    async with _zamok:
        s = _chitat(_sess_put(m.chat.id), None)
        if s:
            arhiv = os.path.join(SESSII, 'arhiv')
            metka = time.strftime('%Y%m%d_%H%M%S')
            _pisat(os.path.join(arhiv, '%s_%s.json' % (m.chat.id, metka)), s)
            if s.get('posl') and os.path.exists(os.path.join(SESSII, s['posl'])):
                os.replace(os.path.join(SESSII, s['posl']), os.path.join(arhiv, '%s_%s.png' % (m.chat.id, metka)))
            os.remove(_sess_put(m.chat.id))
    return await _skazat(m.chat.id, '🆕 новая сессия рисования: прошлые просьбы и последняя картинка убраны в архив, '
                                    'начинаю с чистого листа. Выжимка о чате остаётся.', m.message_id, nit)


async def _komanda(m, vid, prosba, nit):
    vid = re.sub(r'\s+', ' ', vid.lower())
    if vid == 'новая сессия':
        return await _novaya_sessiya(m, nit)
    if vid == 'генерация':
        slovo = prosba.lower().split()[0] if prosba else 'статус'
        if slovo in ('вкл', 'включи', 'on'):
            n = _chitat(NASTR, {}); n['vkl'] = True; _pisat(NASTR, n)
            return await _skazat(m.chat.id, '✅ генерация из Telegram включена\n' + _rabotnik_tekst(), m.message_id, nit)
        if slovo in ('выкл', 'выключи', 'off', 'стоп'):
            n = _chitat(NASTR, {}); n['vkl'] = False; _pisat(NASTR, n)
            return await _skazat(m.chat.id, '⏸ генерация из Telegram выключена: новые задания не принимаю, '
                                            'уже начатое ноутбук доделает', m.message_id, nit)
        async with _zamok:
            z = _chitat(FAYL, {})
        zhdut = sum(1 for v in z.values() if v.get('status') == 'ждёт')
        idut = sum(1 for v in z.values() if v.get('status') == 'у работника')
        return await _skazat(m.chat.id, '🎨 генерация: %s\n%s\n📊 в очереди %d, рисуется %d' % (
            'включена' if _vkl() else 'выключена', _rabotnik_tekst(), zhdut, idut), m.message_id, nit)
    if not _vkl():
        return await _skazat(m.chat.id, '⏸ генерация выключена. Включить: «ботяра генерация вкл»', m.message_id, nit)
    if not prosba:
        return await _skazat(m.chat.id, '❓ что %s? Пример: «ботяра %s %s»' % (
            'нарисовать' if vid == 'нарисуй' else 'изменить', vid,
            'горы Кавказа на рассвете' if vid == 'нарисуй' else 'сделай фон синим'), m.message_id, nit)
    if len(prosba) > PROMT_MAX:
        return await _skazat(m.chat.id, '⚠️ просьба длиннее %d знаков' % PROMT_MAX, m.message_id, nit)
    vhod = None
    if vid == 'измени':
        dannye, rassh = await _kartinka_iz(m)
        if dannye is None:
            s = _sessiya(m.chat.id)
            p = os.path.join(SESSII, s['posl']) if s.get('posl') else ''
            if m.photo or m.document or (m.reply_to_message and (m.reply_to_message.photo or m.reply_to_message.document)):
                return await _skazat(m.chat.id, '❓ ' + rassh, m.message_id, nit)   # картинка была, но не годится
            if not (p and os.path.exists(p)):
                return await _skazat(m.chat.id, '❓ ' + rassh + '. Или сначала «ботяра нарисуй …» — тогда «ботяра '
                                     'измени …» без фото поправит последнюю картинку', m.message_id, nit)
            dannye, rassh = io.open(p, 'rb').read(), 'png'   # агент: правим последнюю картинку этой беседы
    kontekst = _kontekst(m.chat.id) if vid == 'нарисуй' else ''
    if _pamyat_fn and time.time() - (_chitat(PAMYAT_FAYL, {}).get(str(m.chat.id)) or {}).get('kogda', 0) > PAMYAT_SVEZHEST:
        _v_fon(_obnovit_pamyat(m.chat.id))      # выжимка о чате устарела — обновить в фоне, ход её не ждёт
    async with _zamok:
        z = _chitat(FAYL, {})
        _ochistit_staroe(z)
        if sum(1 for v in z.values() if v.get('status') in ('ждёт', 'у работника')) >= OCHERED_MAX:
            return await _skazat(m.chat.id, '⚠️ очередь полна (%d) — подождите' % OCHERED_MAX, m.message_id, nit)
        zid = uuid.uuid4().hex[:12]
        if vid == 'измени':
            vhod = '%s_vhod.%s' % (zid, rassh)
            os.makedirs(PAPKA, exist_ok=True)
            io.open(os.path.join(PAPKA, vhod), 'wb').write(dannye)
        nomer = _nomer(z)
        pered = sum(1 for v in z.values() if v.get('status') in ('ждёт', 'у работника'))
        z[zid] = {'id': zid, 'nomer': nomer, 'vid': vid, 'promt': prosba, 'vhod': vhod, 'chat': m.chat.id,
                  'soob': m.message_id, 'nit': nit, 'kto': (m.sender_chat.id if m.sender_chat else m.from_user.id), 'status': 'ждёт', 'sozdano': time.time(),
                  'popytka': 0, 'kontekst': kontekst}
        _pisat(FAYL, z)
    s = await _skazat(m.chat.id, '🎨 №%d принято: %s%s\n%s' % (
        nomer, 'рисую' if vid == 'нарисуй' else 'правлю картинку',
        ', перед вами %d' % pered if pered else '', _rabotnik_tekst()), m.message_id, nit)
    if s:
        async with _zamok:
            z = _chitat(FAYL, {})
            if zid in z:
                z[zid]['soob_id'] = s.message_id
                _pisat(FAYL, z)


def _proverka(body):
    return _sekret() and str(body.get('secret', '')).strip() == _sekret()


async def _vzyat(r):
    """Работник ноутбука: «я жив, галочка такая-то, дай задание». Отдаёт одно задание или null."""
    if not _sekret() or _app is None:
        return web.json_response({'ok': False, 'error': 'disabled'}, status=503)
    try:
        body = await r.json()
    except Exception:
        return web.json_response({'ok': False, 'error': 'bad_json'}, status=400)
    if not _proverka(body):
        return web.json_response({'ok': False, 'error': 'auth'}, status=403)
    imya = str(body.get('rabotnik', ''))[:40]
    _rabotnik.update(kogda=time.time(), vkl_lokalno=bool(body.get('vkl_lokalno')), imya=imya)
    dat = None
    async with _zamok:
        z = _chitat(FAYL, {})
        propali = _vozvrat_prosrochennyh(z)
        if _vkl() and _rabotnik['vkl_lokalno']:
            # сперва — то, что уже за этим работником (ответ на прошлый «взять» мог потеряться в дороге),
            # потом самое старое ждущее
            svoi = [v for v in z.values() if v.get('status') == 'у работника' and v.get('rabotnik') == imya]
            zhdut = sorted((v for v in z.values() if v.get('status') == 'ждёт'), key=lambda v: v['sozdano'])
            v = (svoi or zhdut or [None])[0]
            if v:
                if v.get('status') == 'ждёт':
                    v['popytka'] = v.get('popytka', 0) + 1
                v.update(status='у работника', rabotnik=imya, arenda_do=time.time() + ARENDA_S, vzyato=time.time())
                dat = {'id': v['id'], 'nomer': v['nomer'], 'vid': v['vid'], 'promt': v['promt'],
                       'kontekst': v.get('kontekst', '')}
                if v.get('vhod'):
                    dat['kartinka_b64'] = base64.b64encode(io.open(os.path.join(PAPKA, v['vhod']), 'rb').read()).decode()
                    dat['rassh'] = v['vhod'].rsplit('.', 1)[-1]
        if propali or dat:
            _pisat(FAYL, z)
    for v in propali:
        await _pravit(v, '⚠️ №%d не вышло: %s' % (v['nomer'], v['oshibka']))
    if dat:
        await _pravit(z[dat['id']], '🎨 №%d %s на ноутбуке…' % (dat['nomer'], 'рисую' if dat['vid'] == 'нарисуй' else 'правлю'))
    return web.json_response({'ok': True, 'vkl': _vkl(), 'zadanie': dat})


async def _gotovo(r):
    """Работник ноутбука: результат задания. Повтор того же id после потерянного ответа — не дублирует отправку."""
    if not _sekret() or _app is None:
        return web.json_response({'ok': False, 'error': 'disabled'}, status=503)
    try:
        body = await r.json()
    except Exception:
        return web.json_response({'ok': False, 'error': 'bad_json'}, status=400)
    if not _proverka(body):
        return web.json_response({'ok': False, 'error': 'auth'}, status=403)
    zid = str(body.get('id', ''))
    async with _zamok:
        z = _chitat(FAYL, {})
        v = z.get(zid)
        if not v:
            return web.json_response({'ok': False, 'error': 'нет такого задания'}, status=404)
        if v.get('status') in ('готово', 'ошибка'):
            return web.json_response({'ok': True, 'povtor': True})
        if v.get('status') == 'отправляю':
            # второй «готово» пришёл, пока первый ещё шлёт фото (замечание Кодекса №3863): не слать дважды —
            # пусть работник спросит позже, к тому времени статус будет «готово» и ответ — «повтор»
            return web.json_response({'ok': False, 'error': 'идёт отправка'}, status=409)
        v['status'] = 'отправляю'
        _pisat(FAYL, z)
    sek = body.get('sek')
    try:
        if body.get('ok') and body.get('kartinka_b64'):
            dannye = base64.b64decode(body['kartinka_b64'])
            podp = '🎨 №%d · Qwen-Image 2.1 · ноутбук, 5070 Ti%s\n%s' % (
                v['nomer'], ' · %s с' % sek if sek else '', v['promt'][:800])
            await _app.bot.send_photo(v['chat'], photo=dannye, caption=podp[:1024], reply_to_message_id=v['soob'],
                                      message_thread_id=v.get('nit'), allow_sending_without_reply=True)
            itog, tekst = 'готово', '✅ №%d готово%s' % (v['nomer'], ' за %s с' % sek if sek else '')
            try:
                await _zapomnit_hod(v, dannye)
            except Exception as e:
                print('generaciya_tg: ход не запомнен —', e, flush=True)
        else:
            itog = 'ошибка'
            v['oshibka'] = str(body.get('oshibka') or 'ноутбук вернул ошибку без пояснения')[:500]
            tekst = '⚠️ №%d не вышло: %s' % (v['nomer'], v['oshibka'])
    except TimedOut:
        # ответа Telegram нет, но фото МОГЛО уйти: повтор дал бы дубль — считаем отправленным
        itog, tekst = 'готово', '✅ №%d готово (Telegram ответил с задержкой — если картинки нет, повторите просьбу)' % v['nomer']
    except Exception as e:
        async with _zamok:
            z = _chitat(FAYL, {})
            if zid in z:
                z[zid]['status'] = 'у работника'      # отправка в Telegram не прошла — работник повторит «готово»
                _pisat(FAYL, z)
        return web.json_response({'ok': False, 'error': 'telegram: %s' % str(e)[:200]}, status=502)
    async with _zamok:
        z = _chitat(FAYL, {})
        if zid in z:
            z[zid].update(status=itog, gotovo=time.time(), sek=sek, oshibka=v.get('oshibka'))
            _pisat(FAYL, z)
    await _pravit(v, tekst)
    return web.json_response({'ok': True})


def podklyuchit(app, owner_id, eto_vladelec=None, pamyat_chata=None):
    """Зовётся из bot.py сразу после сборки Application. eto_vladelec — is_owner(update) самого бота;
    pamyat_chata — dsoc_память(chat_id): разговор помощника в чате, из него берётся выжимка о чате."""
    global _app, _owner, _svoy, _pamyat_fn
    _app, _owner, _svoy, _pamyat_fn = app, int(owner_id), eto_vladelec, pamyat_chata
    app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, _obrabotchik), group=-60)


def marshruty():
    """Маршруты для aiohttp-приложения бота."""
    return [web.post('/api/gen/vzyat', _vzyat), web.post('/api/gen/gotovo', _gotovo)]
