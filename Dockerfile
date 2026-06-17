# ============================================================
# STAGE 1: Builder
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /build

# Ставим компиляторы только если собираем Си-расширения (tgcrypto)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# FIX: Указываем точный путь к requirements.txt внутри папки проекта
COPY alert_bot_project/requirements.txt .

# Устанавливаем пакеты в изолированный путь для чистого копирования
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ============================================================
# STAGE 2: Runner
# ============================================================
FROM python:3.11-slim AS runner

LABEL description="OdesaAlert Bot — Air threat monitoring system"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# curl необходим для индивидуальных хелсчеков воркера/скрейпера
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Премиальный уровень безопасности: non-root, без домашней папки и без доступа к шеллу
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -M -s /sbin/nologin appuser

# Создаем системные папки под логи и сессии с правами для нашего юзера
RUN mkdir -p /data/session /data/logs && \
    chown -R appuser:appgroup /data /app

# Копируем чистое окружение из builder прямо в системный пути python
COPY --from=builder --chown=appuser:appgroup /install /usr/local

# Переносим исходный код
COPY --chown=appuser:appgroup alert_bot_project/ /app/alert_bot_project/

USER appuser

# Инлайновый HEALTHCHECK убран. Теперь каждый сервис в docker-compose.yml
# будет чекать свое здоровье по своему родному порту метрик.