# -*- coding: utf-8 -*-
"""ТЕМЫ ХАДИСОВ: нейронка пишет каждому хадису строку «о чём он» — для поиска.

Зачем. 89% промахов поиска — не «не нашли», а «нашли и не показали»: верный хадис прошёл
порог, но встал ниже третьей строки. Причина в том, ЧТО мы сравниваем: вопрос человека
короткий и про смысл, а отпечаток снят с полного текста, где половина — цепочка передатчиков.

ЗАМЕРЕНО ДО НАЧАЛА РАБОТЫ (proba_temy.py, 20 случаев, вопросы мерки с известным ответом):
строка темы ближе к вопросу, чем полный русский перевод, у 16 из 20; средняя прибавка
близости +0,037. Скромно, но в одну сторону.

⚠️ Первый замер дал 18 из 20 и +0,092 — и был ВРАНЬЁМ: ключ `stop` содержал перенос строки,
модель обрывалась на нулевом слове, и в сравнении участвовала одна моя затравка «Этот хадис
о том,». Русский вопрос к любой русской фразе ближе, чем к арабскому тексту, — мерилась
разница языков. Здесь `stop` без переноса, а пустые ответы отбраковываются.

Порядок: сперва своды, у которых ЕСТЬ русский перевод (по нему можно и тему написать, и
пользу замерить), потом остальные — там тему пишем по арабскому.

Пишет в свою папку, боевых баз не трогает. Уступает дорогу помощнику и сторожу.

    python3 temy_hadisov.py bukhari      один свод
    python3 temy_hadisov.py              по порядку, пока есть работа
"""
import glob
import io
import json
import os
import sys
import time
import urllib.request

МОЗГ = 'http://127.0.0.1:8097/completion'
БАЗА = '/opt/muslimoon/rag'
ВЫХОД = '/opt/muslimoon/temy'
ПАУЗЫ = '/opt/muslimoon/rabotnik.pauza*'
МОДЕЛЬ = ''          # заполняется на старте: спрашиваем у движка
ЗАТРАВКА = 'Этот хадис о том, '

ПОРЯДОК = ['bukhari', 'abudawud', 'muhaymin', 'muslim', 'tirmidhi', 'ibnmajah', 'nasai',
           'malik', 'darimi', 'adabmufrad', 'humaydi', 'ibnmubarak', 'jihad', 'ismail',
           'tayalisi', 'ishaq', 'ibnkhuzayma', 'ibnaljad', 'muqbil', 'abdbinhumayd',
           'ibnhibban', 'abuyala', 'nasaikubra', 'abuawana', 'ahmad', 'ibnabishayba']

УКАЗАНИЕ = ('Прочитай хадис и напиши ОДНОЙ строкой, о чём он — простыми словами, как сказал '
            'бы человек, который ищет этот хадис. Без цепочки передатчиков, без имён, '
            'без арабских слов. Не пересказывай целиком: только суть, 5-12 слов.')



def какая_модель():
    """Имя модели спрашиваем У ДВИЖКА, а не помним наизусть.

    🔴 06.09.2026: в записях стояло «gemma-4-E2B», потому что так было написано в файле,
    а работала уже E4B — я переключил её накануне и забыл про эту строку. Запись, которая
    помнит своё, рано или поздно соврёт; запись, которая спрашивает, — нет.
    """
    try:
        о = json.loads(urllib.request.urlopen(
            'http://127.0.0.1:8097/props', timeout=20).read().decode('utf-8'))
        путь = (о.get('model_path')
                or (о.get('default_generation_settings') or {}).get('model') or '')
        имя = os.path.basename(путь)
        if имя:
            return имя
    except Exception:
        pass
    return 'gemma-4 (имя не спросилось)'

def послать(тело, тайм=600):
    сырое = json.dumps(тело, ensure_ascii=False).encode('utf-8')
    з = urllib.request.Request(МОЗГ, data=сырое,
                               headers={'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(з, timeout=тайм).read().decode('utf-8'))


def тема(текст):
    промпт = ('<start_of_turn>user\n' + УКАЗАНИЕ + '\n\n' + текст[:3000]
              + '<end_of_turn>\n<start_of_turn>model\n' + ЗАТРАВКА)
    о = послать({'prompt': промпт, 'n_predict': 200, 'temperature': 0.2,
                 'stop': ['<end_of_turn>', '<start_of_turn>', '</end_of_turn>', '</start_of_turn>', '<|im_end|>', '<|im_start|>']})
    написанное = (о.get('content') or '').strip()
    if len(написанное) < 12:
        return ''                     # модель ничего не написала — такую тему не берём
    return (ЗАТРАВКА + написанное).replace('\n', ' ').strip()


ОТМЕТКА_ЧЕЛОВЕКА = '/opt/muslimoon/obmen/chelovek_zhdyot.txt'


def человек_сейчас_ждёт(окно=20):
    """Живой вопрос в приложении был меньше `окно` секунд назад?

    🔴 06.09.2026. Сервер двухъядерный, а работ три: бот, движок векторов и я. Замер
    показал load average 2,7 при двух ядрах, и бот в момент поиска забирает 98% процессора.
    Значит человек у кнопки и мои темы делят одни и те же два ядра — и он ждёт дольше
    ровно потому, что я «заодно» пишу своё.
    Бот кладёт отметку времени в общий том перед каждым поиском. Я её читаю и пережидаю.
    Работа 24/7 остаётся: пауза длится секунды, а не часы.
    """
    try:
        с = io.open(ОТМЕТКА_ЧЕЛОВЕКА, encoding='utf-8').read().strip()
        return (time.time() - float(с)) < окно
    except Exception:
        return False


def ждать_очереди():
    """Помощник и сторож важнее: пока они заняли нейронку, стоим.

    И человек важнее всех: пока он ждёт ответа приложения, мы не считаем.
    """
    while glob.glob(ПАУЗЫ):
        time.sleep(3)
    while человек_сейчас_ждёт():
        time.sleep(2)


def сделанные(книга):
    п = os.path.join(ВЫХОД, книга + '.jsonl')
    есть = set()
    if os.path.exists(п):
        for строка in io.open(п, encoding='utf-8'):
            try:
                есть.add(json.loads(строка)['ключ'])
            except Exception:
                continue
    return есть


def работа(книга):
    п = os.path.join(БАЗА, книга + '.meta.json')
    if not os.path.exists(п):
        return []
    м = json.load(io.open(п, encoding='utf-8')).get('м') or {}
    из = []
    for к, з in м.items():
        # тему пишем по РУССКОМУ, если он есть: и модели легче, и вопрос человека по-русски
        текст = (з.get('r') or '').strip() or (з.get('a') or '').strip()
        if len(текст) < 60:
            continue
        из.append((к, з.get('n'), текст))
    из.sort(key=lambda x: str(x[0]))
    return из


def свод(книга):
    все = работа(книга)
    if not все:
        return 0
    уже = сделанные(книга)
    осталось = [(к, н, т) for к, н, т in все if к not in уже]
    if not осталось:
        return 0
    путь = os.path.join(ВЫХОД, книга + '.jsonl')
    print('📗 %s: всего %d, сделано %d, осталось %d'
          % (книга, len(все), len(уже), len(осталось)), flush=True)
    т0 = time.time()
    написано = пусто = 0
    for i, (ключ, номер, текст) in enumerate(осталось, 1):
        ждать_очереди()
        try:
            строка = тема(текст)
        except Exception as б:
            print('   %s: движок молчит (%s) — жду минуту' % (ключ, str(б)[:60]), flush=True)
            time.sleep(60)
            continue
        if not строка:
            пусто += 1
            continue
        with io.open(путь, 'a', encoding='utf-8', newline='\n') as ф:
            ф.write(json.dumps({'ключ': ключ, 'n': номер, 'тема': строка,
                                'модель': МОДЕЛЬ,
                                'дата': time.strftime('%d.%m.%Y %H:%M')},
                               ensure_ascii=False) + '\n')
        написано += 1
        if i % 50 == 0:
            прошло = time.time() - т0
            доля = 100.0 * (len(уже) + i) / max(1, len(все))
            осталось_ч = (len(осталось) - i) * (прошло / i) / 3600
            print('   %s %d/%d (%.1f%%) · %.1f с на тему · осталось ~%.1f ч'
                  % (книга, len(уже) + i, len(все), доля, прошло / i, осталось_ч), flush=True)
    print('📗 %s готово: написано %d, пустых %d, за %.1f ч'
          % (книга, написано, пусто, (time.time() - т0) / 3600), flush=True)
    return написано


if __name__ == '__main__':
    МОДЕЛЬ = какая_модель()
    print('работаю моделью: %s' % МОДЕЛЬ, flush=True)
    os.makedirs(ВЫХОД, exist_ok=True)
    книги = [а for а in sys.argv[1:] if not а.startswith('--')] or ПОРЯДОК
    while True:
        сделано = 0
        for к in книги:
            сделано += свод(к)
        if not сделано:
            print('вся работа по темам сделана — жду час', flush=True)
            time.sleep(3600)
