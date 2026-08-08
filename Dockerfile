# C32: свой Dockerfile вместо nixpacks (тот стал флакать на сборке image, хотя конфиг не менялся с рабочего v613).
# Бот тянет ВСЕ данные удалённо (raw.githubusercontent/jsdelivr) → в образе нужен только bot.py + зависимости. Лёгкий, быстрый, надёжный.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ffmpeg — для аудио-команд бота (pydub). Надёжный Debian-apt.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Зависимости (manylinux-wheels cp312 — компиляция не нужна).
COPY requirements.txt .
RUN pip install -r requirements.txt

# Код бота И ЕГО ПРОМТ. 🔴 08.08.2026: здесь стояло только «COPY bot.py .», и файлы
# dsoc_promt.md / КАРТА_ПРИЛОЖЕНИЯ.md НИКОГДА НЕ ПОПАДАЛИ В КОНТЕЙНЕР. Значит помощник в
# проде месяцами жил на ЗАПАСНОМ промте, вшитом в код, — примитивном «каталоге команд».
# Все правила С-01…С-35, весь регламент Р-NN, карта приложения на 9772 токена — всё это
# правилось, обсуждалось, утверждалось владельцем и НЕ РАБОТАЛО НИ ДНЯ.
# Поймано по цифре в подписи: «системный промт 4669 токенов» — ровно размер запасного,
# тогда как настоящий 11 731 плюс карта 9 772.
COPY bot.py .
COPY dsoc_promt.md КАРТА_ПРИЛОЖЕНИЯ.md ./
RUN mkdir -p data

# Бот: long-polling Telegram + aiohttp API на $PORT (Railway задаёт PORT).
CMD ["python", "bot.py"]
