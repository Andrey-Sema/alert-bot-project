# ============================================================
# STAGE 1: Builder
# ============================================================
FROM python:3.11.9-slim@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317 AS builder

WORKDIR /build

# Ставим компиляторы и утилиты сборки для Си-расширений (tgcrypto)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Сначала копируем ТОЛЬКО файл зависимостей для правильного кэширования слоёв
COPY requirements.lock .

# Объединяем апгрейд pip и установку пакетов в один RUN.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --require-hashes --prefix=/install -r requirements.lock

# ============================================================
# STAGE 2: Runner
# ============================================================
FROM python:3.11.9-slim@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317 AS runner

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
    && mkdir -p /data/session /data/logs /data/outbox \
    && chown -R appuser:appgroup /data /app

# Копируем чистое окружение из builder прямо в системные пути python
COPY --from=builder --chown=appuser:appgroup /install /usr/local

# Переносим исходный код приложения (лежит в самом низу, чтобы не инвалидировать кэш либ)
COPY --chown=appuser:appgroup alert_bot_project/ /app/alert_bot_project/
COPY --chown=appuser:appgroup migrations/ /app/migrations/
COPY --chown=appuser:appgroup alembic.ini /app/alembic.ini

USER appuser

# Инлайновый HEALTHCHECK убран. Теперь каждый сервис в docker-compose.yml
# будет чекать свое здоровье по своему родному порту метрик.
