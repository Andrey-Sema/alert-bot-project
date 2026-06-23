# ============================================================
# STAGE 1: Builder
# ============================================================
FROM python:3.11.9-slim AS builder

WORKDIR /build

# Ставим компиляторы и утилиты сборки для Си-расширений (tgcrypto)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Сначала копируем ТОЛЬКО файл зависимостей для правильного кэширования слоёв
COPY alert_bot_project/requirements.txt .

# ✅ СЕНЬОР-ФИКС: Объединяем апгрейд pip и установку пакетов в один RUN.
# Добавлена жесткая проверка хэшей (--require-hashes) для защиты от подмены пакетов на PyPI.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --require-hashes --prefix=/install -r requirements.txt

# ============================================================
# STAGE 2: Runner
# ============================================================
FROM python:3.11.9-slim AS runner

LABEL description="OdesaAlert Bot — Air threat monitoring system"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# ✅ СЕНЬОР-ФИКС: Атомарно ставим curl и чистим списки apt сразу же,
# не дожидаясь выполнения сторонних системных команд
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ✅ СЕНЬОР-ФИКС: Выносим создание групп, юзера, папок и пермиссий в отдельный изолированный слой
RUN groupadd -g 10001 appgroup \
    && useradd -u 10001 -g appgroup -M -s /sbin/nologin appuser \
    && mkdir -p /data/session /data/logs \
    && chown -R appuser:appgroup /data /app

# Копируем чистое окружение из builder прямо в системные пути python
COPY --from=builder --chown=appuser:appgroup /install /usr/local

# Переносим исходный код приложения (лежит в самом низу, чтобы не инвалидировать кэш либ)
COPY --chown=appuser:appgroup alert_bot_project/ /app/alert_bot_project/

USER appuser

# Инлайновый HEALTHCHECK убран. Теперь каждый сервис в docker-compose.yml
# будет чекать свое здоровье по своему родному порту метрик.