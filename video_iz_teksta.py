#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Текст → вертикальный ролик 9:16: озвучка, КАРАОКЕ по словам и тематические картинки.

Обращение владельца #79 (07.08.2026) и уточнение в 16:06: «я же в чате просил, он должен быть
исполнен в чате. Причём КАРАОКЕ должен быть и ТЕМАТИЧЕСКИЕ КАРТИНКИ. И всё это надо
бесплатные ресурсы, чтобы делалось».

ТРИ ТРЕБОВАНИЯ И ЧЕМ ОНИ ЗАКРЫТЫ — всё даром, без единого ключа и без чужих подписок:
① Речь        — edge-tts (голос Эндрю, выбран владельцем на слух 05.08).
② Караоке     — faster-whisper НА ЭТОЙ МАШИНЕ, с границами КАЖДОГО СЛОВА.
                Первая моя версия делила время фразы пропорционально длине слов. Смотрится
                похоже, но это подделка: слово «и» и слово «несправедливо» произносятся не
                по числу букв. Караоке, которое подсвечивает не то слово, хуже отсутствия
                караоке — глаз спорит с ухом.
③ Картинки    — Викисклад (commons.wikimedia.org), поиск без ключа, свободные лицензии.
                Не Unsplash и не Pexels: у них бесплатный тариф ТРЕБУЕТ КЛЮЧ, а ключ — это
                чужой счёт и чужое разрешение, которое однажды отзовут.

    python video_iz_teksta.py --текст "..." --заголовок "Коран 17:59" --темы "пустыня,верблюд"
    python video_iz_teksta.py --файл matn.txt --выход rolik.mp4
"""
import argparse
import asyncio
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ГОЛОС = 'en-US-AndrewMultilingualNeural'
ШИРИНА, ВЫСОТА = 1080, 1920
ПОДСВЕТ = '&H00A0A62E'     # бирюзовый приложения, в ASS цвет пишется задом наперёд: BBGGRR
НЕСПЕТОЕ = '&H00FFFFFF'    # белый — слово, до которого речь ещё не дошла
ЮЗЕР = {'User-Agent': 'Muslimoon-bot/1.0 (video builder; contact via t.me/muslimoonapp)'}


def _ffmpeg():
    п = shutil.which('ffmpeg')
    if not п:
        sys.exit('⛔ ffmpeg не найден — без него ролик не собрать')
    return п


def _шрифт():
    for п in (r'C:\Windows\Fonts\arialbd.ttf', r'C:\Windows\Fonts\arial.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'):
        if os.path.exists(п):
            return п
    return None


async def _озвучить(текст, путь_mp3):
    import edge_tts
    ком = edge_tts.Communicate(текст, ГОЛОС)
    with open(путь_mp3, 'wb') as ф:
        async for кус in ком.stream():
            if кус['type'] == 'audio':
                ф.write(кус['data'])
    return путь_mp3


def _слова_по_слуху(mp3):
    """Границы КАЖДОГО СЛОВА — распознаём собственную озвучку локально.

    Кажется странным: озвучили сами и сами же слушаем. Но edge-tts в нынешней версии отдаёт
    только границы ПРЕДЛОЖЕНИЙ, а караоке живёт словами. Считать их пропорцией букв нельзя —
    получится красиво и неверно.
    Модель `base` на процессоре: 45 секунд речи разбирает секунд за двадцать, качество границ
    для караоке достаточное. Всё локально: чужой звук никуда не уходит.
    """
    from faster_whisper import WhisperModel
    м = WhisperModel('base', device='cpu', compute_type='int8')
    сег, _ = м.transcribe(mp3, language='ru', word_timestamps=True, vad_filter=False)
    сл = []
    for с in сег:
        for w in (с.words or []):
            т = (w.word or '').strip()
            if т:
                сл.append((т, float(w.start), float(w.end)))
    return сл


def _строки(слова, макс_знаков=38, макс_пауза=0.55):
    """Слова → строки караоке. Рвём по паузе и по длине; пауза важнее."""
    стр, тек, прош = [], [], None
    for сл in слова:
        разрыв = прош is not None and (сл[1] - прош) > макс_пауза
        длинно = тек and len(' '.join(w[0] for w in тек) + ' ' + сл[0]) > макс_знаков
        if тек and (разрыв or длинно):
            стр.append(тек); тек = []
        тек.append(сл); прош = сл[2]
    if тек:
        стр.append(тек)
    return стр


def _ass_караоке(строки, заголовок, путь):
    """ASS с тегами \\k: слово загорается ровно в свой миг, остальные ждут белыми."""
    def вр(с):
        ч = int(с // 3600); м = int((с % 3600) // 60)
        return '%d:%02d:%05.2f' % (ч, м, с % 60)
    шапка = (
        '[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n'
        'ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n'
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,'
        ' BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR,'
        ' MarginV\n'
        # PrimaryColour — цвет УЖЕ СПЕТОГО, SecondaryColour — ещё не спетого. Именно так, а не
        # наоборот: в ASS \k «проявляет» Primary поверх Secondary.
        'Style: Кар,Arial,76,%s,%s,&H00101418,&H90000000,1,0,1,5,3,2,80,80,300\n'
        'Style: Шапка,Arial,50,&H00C8C8C8,&H00C8C8C8,&H00000000,&H80000000,1,0,1,3,0,8,80,80,110\n'
        '\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV,'
        ' Effect, Text\n' % (ШИРИНА, ВЫСОТА, ПОДСВЕТ, НЕСПЕТОЕ))
    соб = []
    if заголовок and строки:
        соб.append('Dialogue: 0,0:00:00.00,%s,Шапка,,0,0,0,,%s'
                   % (вр(строки[-1][-1][2] + 1.2), заголовок.replace('\n', ' ')))
    for гр in строки:
        н, к = гр[0][1], гр[-1][2]
        куски = []
        пред = н
        for т, с1, с2 in гр:
            # Пауза перед словом тоже «поётся» — иначе подсветка убежит вперёд речи.
            if с1 - пред > 0.02:
                куски.append('{\\k%d}' % int(round((с1 - пред) * 100)))
            дл = max(1, int(round((с2 - с1) * 100)))
            куски.append('{\\k%d}%s ' % (дл, т.replace('{', '(').replace('}', ')')))
            пред = с2
        соб.append('Dialogue: 0,%s,%s,Кар,,0,0,0,,%s' % (вр(н), вр(к + 0.3), ''.join(куски).strip()))
    io.open(путь, 'w', encoding='utf-8').write(шапка + '\n'.join(соб) + '\n')


def _картинки(темы, сколько, куда):
    """Тематические картинки с Викисклада: бесплатно, без ключа, свободные лицензии."""
    пути = []
    for тема in темы:
        if len(пути) >= сколько:
            break
        try:
            u = ('https://commons.wikimedia.org/w/api.php?action=query&generator=search'
                 '&gsrsearch=' + urllib.parse.quote('filetype:bitmap ' + тема) +
                 '&gsrlimit=4&gsrnamespace=6&prop=imageinfo&iiprop=url&iiurlwidth=1400&format=json')
            д = json.loads(urllib.request.urlopen(
                urllib.request.Request(u, headers=ЮЗЕР), timeout=45).read().decode())
            for _, стр in ((д.get('query') or {}).get('pages') or {}).items():
                ссыл = ((стр.get('imageinfo') or [{}])[0].get('thumburl') or '')
                if not ссыл:
                    continue
                п = os.path.join(куда, 'fon_%d.jpg' % len(пути))
                try:
                    with urllib.request.urlopen(
                            urllib.request.Request(ссыл, headers=ЮЗЕР), timeout=60) as о, \
                            open(п, 'wb') as ф:
                        ф.write(о.read())
                    if os.path.getsize(п) > 20000:
                        пути.append(п)
                        break            # по одной картинке на тему — иначе всё об одном
                except Exception:
                    pass
        except Exception:
            pass
    return пути


def _темы_из_текста(текст, заданные):
    if заданные:
        return [т.strip() for т in заданные.split(',') if т.strip()]
    # Без подсказки берём общие, заведомо уместные виды: небо, горы, пустыня, книга.
    # Угадывать тему по словам текста я не берусь — ошибка тут видна сразу и выглядит нелепо.
    return ['desert dunes', 'night sky stars', 'mountains dawn', 'old arabic manuscript']


def собрать(текст, выход, заголовок='', темы=''):
    текст = re.sub(r'\s+', ' ', (текст or '')).strip()
    if len(текст) < 4:
        sys.exit('⛔ текста нет')
    if not _шрифт():
        sys.exit('⛔ нет шрифта с кириллицей — вместо букв будут квадраты')
    врем = tempfile.mkdtemp(prefix='rolik_')
    mp3 = os.path.join(врем, 'zvuk.mp3')
    ass = os.path.join(врем, 'kar.ass')

    print('① озвучиваю (%d знаков)…' % len(текст))
    asyncio.new_event_loop().run_until_complete(_озвучить(текст, mp3))

    print('② слушаю свою же озвучку ради границ КАЖДОГО слова…')
    слова = _слова_по_слуху(mp3)
    if not слова:
        sys.exit('⛔ границы слов не получены — караоке было бы подделкой, останавливаюсь')
    строки = _строки(слова)
    длит = слова[-1][2] + 1.3
    print('   слов %d, строк %d, длительность %.1f сек' % (len(слова), len(строки), длит))
    _ass_караоке(строки, заголовок, ass)

    сп_тем = _темы_из_текста(текст, темы)
    надо = max(1, min(5, int(длит // 9) + 1))
    print('③ беру %d картинки с Викисклада (бесплатно, без ключа): %s'
          % (надо, ', '.join(сп_тем[:надо])))
    карт = _картинки(сп_тем, надо, врем)
    print('   скачано: %d' % len(карт))

    ассп = ass.replace('\\', '/').replace(':', r'\:')
    ff = _ffmpeg()
    if карт:
        # Каждая картинка живёт свой отрезок и медленно наезжает (эффект Кена Бёрнса):
        # неподвижная картинка под сорок секунд речи читается как зависший экран.
        доля = длит / len(карт)
        вх, фильтры = [], []
        for i, п in enumerate(карт):
            вх += ['-loop', '1', '-t', '%.2f' % (доля + 0.5), '-i', п]
            фильтры.append(
                "[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,"
                "zoompan=z='min(zoom+0.0009,1.18)':d=%d:s=%dx%d:fps=30,"
                "format=yuv420p[v%d]"
                % (i, int(ШИРИНА * 1.15), int(ВЫСОТА * 1.15), ШИРИНА, ВЫСОТА,
                   int((доля + 0.5) * 30), ШИРИНА, ВЫСОТА, i))
        цепь = ''.join('[v%d]' % i for i in range(len(карт)))
        граф = (';'.join(фильтры) + ';' + цепь + 'concat=n=%d:v=1:a=0[bg];'
                "[bg]eq=brightness=-0.16:saturation=0.85[dim];"
                "[dim]subtitles='%s':fontsdir='C\\:/Windows/Fonts'[v]" % (len(карт), ассп))
        к = [ff, '-y', '-loglevel', 'error'] + вх + ['-i', mp3,
             '-filter_complex', граф, '-map', '[v]', '-map', '%d:a' % len(карт),
             '-t', '%.2f' % длит,
             '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '25', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-b:a', '128k', выход]
    else:
        print('   ⚠️ картинок не досталось — собираю на тёмном фоне, но говорю об этом прямо')
        к = [ff, '-y', '-loglevel', 'error',
             '-f', 'lavfi', '-i', 'color=c=0x101418:s=%dx%d:d=%.2f' % (ШИРИНА, ВЫСОТА, длит),
             '-i', mp3, '-vf', "subtitles='%s':fontsdir='C\\:/Windows/Fonts'" % ассп,
             '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '25', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-b:a', '128k', '-shortest', выход]
    print('④ собираю…')
    р = subprocess.run(к, capture_output=True)
    if р.returncode != 0 or not os.path.exists(выход):
        sys.exit('⛔ ffmpeg: %s' % (р.stderr or b'').decode('utf-8', 'ignore')[-900:])
    print('✅ готово: %s — %.1f МБ, %.1f сек, картинок %d'
          % (выход, os.path.getsize(выход) / 1048576, длит, len(карт)))
    return выход


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--текст')
    p.add_argument('--файл')
    p.add_argument('--заголовок', default='')
    p.add_argument('--темы', default='', help='через запятую, по-английски: desert,camel')
    p.add_argument('--выход', default='rolik.mp4')
    a = p.parse_args()
    т = a.текст or (io.open(a.файл, encoding='utf-8').read() if a.файл else '')
    собрать(т, a.выход, a.заголовок, a.темы)
