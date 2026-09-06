#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  ВЫКАТКА БОТА на своей машине — одной командой, с повторами и проверкой.
#
#  Зачем. Выкатка делалась вручную длинной строкой из пяти шагов, и каждый раз
#  заново. 03.09.2026 GitHub придержал загрузку («temporarily limiting some
#  unauthenticated downloads») — прошло только с ПЯТОЙ попытки, а без повторов
#  выкатка молча осталась бы на старом коммите: контейнер перезапустился бы со
#  СТАРЫМ кодом, и это выглядело бы как «правка не сработала».
#
#  Что делает: тянет свежий код (до 6 попыток), собирает образ, перезапускает
#  контейнер, ждёт и проверяет здоровье. Любой шаг не удался — говорит вслух и
#  выходит с ошибкой, а не делает вид, что всё прошло.
#
#  ⚠️ Имена переменных латиницей намеренно: bash кириллицу в именах не принимает.
# ═══════════════════════════════════════════════════════════════════════════════
set -u
HOME_DIR=/opt/muslimoon
NAME=muslimoon-bot

cd "$HOME_DIR" || { echo "нет папки $HOME_DIR"; exit 1; }

echo "① тяну свежий код"
OK=0
for i in 1 2 3 4 5 6; do
  if git fetch -q origin 2>/dev/null; then OK=1; echo "   получено с попытки $i"; break; fi
  echo "   попытка $i: GitHub придержал, жду"
  sleep 40
done
[ "$OK" = "1" ] || { echo "❌ код не скачался за шесть попыток — выкатка отменена"; exit 1; }
git reset -q --hard origin/main
NEW=$(git log --oneline -1)
echo "   на коммите: $NEW"

echo "② собираю образ"
sudo docker build -q -t "$NAME:latest" . >/dev/null 2>&1 || { echo "❌ сборка не удалась"; exit 1; }

# /obmen — единственная папка, открытая контейнеру НА ЗАПИСЬ (06.09.2026): туда бот кладёт
# отметку «человек ждёт» для фоновых работ и запомненные отказы каналов, чтобы знание
# «этот ключ мёртв» переживало перезапуск. Остальное состояние остаётся только для чтения.
# ⚠️ Правку монтирования делать ЗДЕСЬ, в репозитории: ниже выкатка выполняет
# git reset --hard origin/main и стирает любые местные изменения этого файла.
echo "③ перезапускаю"
sudo docker stop "$NAME" >/dev/null 2>&1
sudo docker rm "$NAME" >/dev/null 2>&1
sudo docker run -d --name "$NAME" --restart unless-stopped -p 8080:8080 \
  --env-file "$HOME_DIR/.env" -v "$HOME_DIR/state:/state:ro" -v "$HOME_DIR/rag:/rag:ro" -v "$HOME_DIR/obmen:/obmen" "$NAME:latest" >/dev/null \
  || { echo "❌ контейнер не запустился"; exit 1; }

echo "④ жду и проверяю здоровье"
sleep 18
CODE=$(curl -s -o /tmp/hh.json -w '%{http_code}' -m 40 http://127.0.0.1:8080/api/health)
if [ "$CODE" != "200" ]; then
  echo "❌ бот не отвечает (код $CODE). Последние строки лога:"
  sudo docker logs --tail 20 "$NAME" 2>&1 | tail -20
  exit 1
fi
python3 -c "
import json
d = json.load(open('/tmp/hh.json'))
k = d.get('код') or {}
print('   здоровье: ok=%s · снимок: %s' % (d.get('ok'), k.get('снимок') if isinstance(k, dict) else k))
"
echo "5) пишу след в журнал выкаток"
COMMIT=$(git -C "$HOME_DIR" rev-parse HEAD 2>/dev/null || echo "?")
SNAP=$(python3 - <<'PYEOF' 2>/dev/null || echo "?"
# -*- coding: utf-8 -*-
import json
d = json.load(open('/tmp/hh.json'))
k = d.get('код') or {}
print(k.get('снимок') if isinstance(k, dict) else k)
PYEOF
)
python3 "$HOME_DIR/sled_vykatki.py" "$COMMIT" "$SNAP" || echo "   [!] sled ne zapisan (vykatka proshla)"
echo "✅ выкачено"
