# -*- coding: utf-8 -*-
"""Архив КАЖДОГО сообщения чата @jamaat_ru на Оракле (ЛОКАЛКИ 37, 22.10.2026).

Владелец 22.10: «ассистент должен читать каждое смс и осваивать… но чтобы не переполнял свой контекст —
сохранять оригиналы в Оракле, бэкап в Телеграме в облачный архив; летопись, картина чата, карточки
участников — постоянно обновлять».
Этот модуль — первая ступень: тихо пишет оригинал каждого сообщения (и правки) в
/obmen/chat_arhiv/ГГГГ-ММ.jsonl, по строке на событие. Ничего не отвечает и ничего не меняет в разборе:
отдельная группа обработчиков (group=13), исключения глотаются — бот в чатах людей не сломается.
Читает архив Гермес на Оракле через мост (most_germesa.py → /chat/novye), пачками, а не целиком.
Бэкап — вместе с /opt/muslimoon в ночном архиве (ne_v_git).
"""
import asyncio, io, json, os, time
from telegram.ext import MessageHandler, filters

CHATY = {-1001925828112}          # @jamaat_ru
PAPKA = next((p for p in ('/obmen/chat_arhiv', '/opt/muslimoon/obmen/chat_arhiv') if os.path.isdir(os.path.dirname(p))),
             os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat_arhiv'))


def _zapis(update):
    m = update.edited_message or update.message
    if not m or m.chat.id not in CHATY:
        return None
    u = m.from_user
    sc = m.sender_chat
    media = next((k for k in ('photo', 'video', 'voice', 'audio', 'document', 'sticker', 'animation', 'video_note', 'poll')
                  if getattr(m, k, None)), None)
    fid = None
    if media == 'photo':
        fid = m.photo[-1].file_id
    elif media and media != 'poll':
        fid = getattr(getattr(m, media), 'file_id', None)
    return {
        'id': m.message_id, 'chat': m.chat.id, 'kogda': int(m.date.timestamp()) if m.date else int(time.time()),
        'pravka': bool(update.edited_message), 'pravka_kogda': int(m.edit_date.timestamp()) if m.edit_date else None,
        'kto_id': u.id if u else None, 'kto': ((u.full_name or '') if u else '') or None,
        'nik': (u.username if u else None), 'bot': bool(u and u.is_bot),
        'ot_kanala': ({'id': sc.id, 'nazvanie': sc.title} if sc else None),
        'tekst': m.text or m.caption or '', 'otvet_na': m.reply_to_message.message_id if m.reply_to_message else None,
        'nit': m.message_thread_id if getattr(m, 'is_topic_message', False) else None,
        'media': media, 'file_id': fid,
        'pereslano': bool(getattr(m, 'forward_origin', None)),
        'dlit': getattr(getattr(m, media, None), 'duration', None) if media in ('voice', 'audio', 'video', 'video_note') else None,
    }


async def _arhiv(update, context):
    try:
        z = _zapis(update)
        if not z:
            return
        os.makedirs(PAPKA, exist_ok=True)
        imya = time.strftime('%Y-%m', time.localtime(z['kogda'])) + '.jsonl'
        with io.open(os.path.join(PAPKA, imya), 'a', encoding='utf-8') as f:
            f.write(json.dumps(z, ensure_ascii=False) + '\n')
        if not z['pravka'] and ARHIV_CHAT:
            _zapustit_rabotnika()
            _ochered.put_nowait((z['chat'], z['id']))
    except Exception as e:
        print('chat_arhiv: не записал —', e, flush=True)


# ── Пересылка в облачный архивный чат (владелец 22.10.2026: «каждое смс он пересылает и сохраняет в архив
# облачный чат, а оттуда, если надо, видео, аудио, файлы возьмёт… только теперь идущие, старое уже скачано…
# не перепутай мои файлы — именно пересланные с чата джм»). В архивном чате лежат и файлы самого владельца,
# поэтому номер КАЖДОГО пересланного ботом сообщения пишется в svyaz.jsonl: ассистент берёт из архива ТОЛЬКО
# сообщения с номерами из этого списка — файлы владельца для него невидимы.
# Правки не пересылаются (Telegram не даёт переслать правку) — новая версия текста есть в jsonl.
# Темп — не чаще раза в 3,5 с: у Telegram предел ~20 сообщений в минуту в одну группу; очередь не теряет пачки.
ARHIV_CHAT = int(os.environ.get('ARHIV_JAMAAT_CHAT') or -1002142402317)
_ochered = asyncio.Queue()
_app = None


async def _peresylka():
    from telegram.error import RetryAfter
    while True:
        chat, mid = await _ochered.get()
        for _ in range(3):
            try:
                m = await _app.bot.forward_message(ARHIV_CHAT, chat, mid, disable_notification=True)
                with io.open(os.path.join(PAPKA, 'svyaz.jsonl'), 'a', encoding='utf-8') as f:
                    f.write(json.dumps({'chat': chat, 'id': mid, 'arhiv_chat': ARHIV_CHAT, 'arhiv_id': m.message_id,
                                        'kogda': int(time.time())}) + '\n')
                break
            except RetryAfter as e:
                await asyncio.sleep(float(getattr(e, 'retry_after', 5)) + 1)
            except Exception as e:
                print('chat_arhiv: не переслал #%s —' % mid, e, flush=True)
                break
        await asyncio.sleep(3.5)


_rabotnik = []


def _zapustit_rabotnika():
    """Работник пересылки поднимается первым же сообщением чата (в цикле событий бота) и живёт до конца процесса."""
    if not _rabotnik or _rabotnik[0].done():
        _rabotnik[:] = [asyncio.get_running_loop().create_task(_peresylka())]


def podklyuchit(app):
    global _app
    _app = app
    app.add_handler(MessageHandler(filters.Chat(chat_id=list(CHATY)) & (filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE),
                                   _arhiv), group=13)

