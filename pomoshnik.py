# -*- coding: utf-8 -*-
"""ПОМОЩНИК: маленькая нейронка отвечает владельцу — но ТОЛЬКО ПО НАШЕЙ БАЗЕ.

Задача владельца 05.09.2026: «сделай чтобы в оракл сервере всегда работала нейронка
маленькая… в том числе как ассистента».

🔴 ПОЧЕМУ НЕ ПРОСТО «СПРОСИТЬ У МОДЕЛИ». Проверено на ней же в тот же день: на свободный
вопрос «что такое тахридж» gemma-4-E2B ответила «это 40-й хадис, один из самых известных» —
чистая выдумка. Двухмиллиардная модель помнит плохо, а звучит уверенно. В проекте о
ДОСТОВЕРНОСТИ хадисов такой помощник хуже, чем никакого.

Поэтому порядок такой: сперва ИЩЕМ в нашей базе (26 сводов, 171 тысяча мест), потом отдаём
найденное модели и велим отвечать ТОЛЬКО по нему. Модель здесь делает то, что умеет —
читает данный текст и излагает; и не делает того, чего не умеет — не вспоминает.
Не нашлось в базе — так и говорим, а не сочиняем.

Живёт на ХОСТЕ, а не в контейнере: отсюда виден и движок нейронки, и файл-флаг паузы,
которым помощник останавливает фоновый перевод, — нейронка одна, и хозяин у неё владелец.

    python3 pomoshnik.py            служба на 8098
    curl -X POST localhost:8098/sprosit -d '{"q":"..."}'
"""
import json
import os
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

МОЗГ = 'http://127.0.0.1:8097/completion'
ПОИСК = 'http://127.0.0.1:8080/api/rag_find'
ПАУЗА = '/opt/muslimoon/rabotnik.pauza'
ПОРТ = 8098
СКОЛЬКО_ХАДИСОВ = 4
ДЛИНА_ХАДИСА = 700

УКАЗАНИЕ = (
    'Ты помощник в проекте о хадисах. Ответь на вопрос, опираясь ТОЛЬКО на приведённые ниже '
    'хадисы из нашей базы. Ничего не добавляй от себя и не вспоминай постороннее. '
    'Если в приведённых хадисах ответа нет — так и напиши. '
    'Отвечай по-русски, коротко, и ссылайся на номера хадисов.')


def искать(вопрос):
    """Спросить нашу базу. Русский шлём явным utf-8: иначе вопрос до двери не доходит,
    а она подставляет своё умолчание и честно отвечает не на то (проверено 05.09)."""
    тело = json.dumps({'q': вопрос, 'книга': 'все', 'top': СКОЛЬКО_ХАДИСОВ},
                      ensure_ascii=False).encode('utf-8')
    з = urllib.request.Request(ПОИСК, data=тело, headers={'Content-Type': 'application/json'})
    о = json.loads(urllib.request.urlopen(з, timeout=180).read().decode('utf-8'))
    return о.get('нашёл') or []


def спросить_мозг(промпт, начало, сколько=-1):
    тело = json.dumps({'prompt': промпт + начало, 'n_predict': сколько, 'temperature': 0.2,
                       'stop': ['<end_of_turn>', '<start_of_turn>', '</end_of_turn>', '</start_of_turn>', '<|im_end|>', '<|im_start|>']}).encode('utf-8')
    з = urllib.request.Request(МОЗГ, data=тело, headers={'Content-Type': 'application/json'})
    о = json.loads(urllib.request.urlopen(з, timeout=600).read().decode('utf-8'))
    return (начало + (о.get('content') or '')).strip()


def ответить(вопрос):
    т0 = time.time()
    try:
        найдено = искать(вопрос)
    except Exception as б:
        return {'ответ': 'Поиск по базе не ответил: %s' % str(б)[:120],
                'источники': [], 'секунд': round(time.time() - т0, 1)}
    if not найдено:
        return {'ответ': 'В нашей базе по этому вопросу ничего не нашлось. '
                         'Ничего не выдумываю — попробуйте спросить иначе.',
                'источники': [], 'секунд': round(time.time() - т0, 1)}

    куски, источники = [], []
    for з in найдено:
        имя = '%s №%s' % (з.get('книга'), з.get('n'))
        источники.append(имя)
        текст = (з.get('r') or '').strip() or (з.get('a') or '').strip()
        куски.append('[%s] %s' % (имя, текст[:ДЛИНА_ХАДИСА]))

    промпт = ('<start_of_turn>user\n' + УКАЗАНИЕ + '\n\nХадисы из нашей базы:\n'
              + '\n\n'.join(куски) + '\n\nВопрос: ' + вопрос
              + '<end_of_turn>\n<start_of_turn>model\n')
    # ответ начинаем за неё: Gemma иначе рассуждает вслух и до ответа не доходит
    try:
        ответ = спросить_мозг(промпт, 'По нашей базе: ')
    except Exception as б:
        return {'ответ': 'Нейронка не ответила: %s' % str(б)[:120],
                'источники': источники, 'секунд': round(time.time() - т0, 1)}
    return {'ответ': ответ, 'источники': источники, 'секунд': round(time.time() - т0, 1)}


class Дверь(BaseHTTPRequestHandler):
    def _отдать(self, код, тело):
        сырое = json.dumps(тело, ensure_ascii=False).encode('utf-8')
        self.send_response(код)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(сырое)))
        self.end_headers()
        self.wfile.write(сырое)

    def do_GET(self):
        if self.path.startswith('/health'):
            self._отдать(200, {'состояние': 'жив', 'порт': ПОРТ,
                               'работник_на_паузе': os.path.exists(ПАУЗА)})
        else:
            self._отдать(404, {'ошибка': 'нет такой двери'})

    def do_POST(self):
        if not self.path.startswith('/sprosit'):
            self._отдать(404, {'ошибка': 'нет такой двери'})
            return
        try:
            длина = int(self.headers.get('Content-Length') or 0)
            тело = json.loads(self.rfile.read(длина).decode('utf-8')) if длина else {}
        except Exception as б:
            self._отдать(400, {'ошибка': 'не разобрал запрос: %s' % str(б)[:100]})
            return
        вопрос = (тело.get('q') or тело.get('вопрос') or '').strip()[:600]
        if not вопрос:
            # умолчания тут НЕ ставим: подставленный вопрос даёт правдоподобный ответ
            # не на то, что спрашивали (урок 05.09 — час разбора на ровном месте)
            self._отдать(400, {'ошибка': 'вопрос не пришёл'})
            return
        # уступить дорогу: фоновый перевод встаёт, пока отвечаем владельцу
        try:
            open(ПАУЗА, 'w').write(str(int(time.time())))
        except Exception:
            pass
        try:
            self._отдать(200, ответить(вопрос))
        finally:
            try:
                os.remove(ПАУЗА)
            except Exception:
                pass

    def log_message(self, формат, *аргументы):
        sys.stderr.write('%s %s\n' % (time.strftime('%H:%M:%S'), формат % аргументы))


if __name__ == '__main__':
    сервер = ThreadingHTTPServer(('0.0.0.0', ПОРТ), Дверь)
    print('помощник слушает на %d (мозг %s, поиск %s)' % (ПОРТ, МОЗГ, ПОИСК), flush=True)
    сервер.serve_forever()
