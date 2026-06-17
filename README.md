# 🛡️ OdesaAlert Bot

> **Система персонального нічного моніторингу повітряних загроз для Одеси та Одеської області**

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://python.org)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-orange?logo=telegram&logoColor=white)](https://aiogram.dev)
[![Redis](https://img.shields.io/badge/Redis-Streams-red?logo=redis&logoColor=white)](https://redis.io)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-blue?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Prometheus](https://img.shields.io/badge/Prometheus-Monitoring-orange?logo=prometheus&logoColor=white)](https://prometheus.io)
[![Grafana](https://img.shields.io/badge/Grafana-Dashboards-f2f2f2?logo=grafana&logoColor=orange)](https://grafana.com)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker&logoColor=white)](https://docker.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red?logo=python&logoColor=white)](https://docs.sqlalchemy.org)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?logo=pydantic&logoColor=white)](https://docs.pydantic.dev)
[![Ruff](https://img.shields.io/badge/Linter-Ruff-purple?logo=ruff&logoColor=white)](https://docs.astral.sh/ruff)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 📖 Зміст

- [Про проєкт](#-про-проєкт)
- [Як це працює](#-як-це-працює)
- [Архітектура системи](#-архітектура-системи)
- [Підсистеми та компоненти](#-підсистеми-та-компоненти)
- [Стек технологій](#-стек-технологій)
- [Швидкий старт](#-швидкий-старт)
- [Конфігурація](#-конфігурація)
- [Налаштування бота](#-налаштування-бота)
- [Моніторинг та Observability](#-моніторинг-та-observability)
- [Тестування](#-тестування)
- [CI/CD та якість коду](#-cicd-та-якість-коду)
- [Структура проєкту](#-структура-проєкту)
- [Безпека](#-безпека)

---

## 🎯 Про проєкт

**OdesaAlert Bot** — це автономна система реального часу, яка перехоплює повідомлення тактичних Telegram-каналів, аналізує їх за допомогою побудованих регулярних виразів і надсилає **персоналізовані нічні сповіщення** користувачам, чиї обрані зони перебувають під загрозою.

### Ключові особливості

- 🌙 **Режим нічного будильника** — система мовчить вдень і примусово будить вночі при виявленні загрози
- 📍 **Гіперлокальний моніторинг** — 35+ відстежуваних районів Одеси та Одеської області
- 🔤 **Двомовний аналіз** — автоматичне розпізнавання топонімів українською та російською мовами
- ✍️ **Кастомні тригери** — до 5 власних ключових слів (вулиці, орієнтири, мікрорайони)
- 🔕 **Гнучкий MUTE** — заглушення на 1/2/4 год., до ранку або підтвердженням отримання
- 🦅 **Категорії загроз** — окремі фільтри для дронів (Мопеди) та ракет (Ракети)
- 📊 **Повний observability-стек** — Prometheus + Grafana + Alertmanager

---

## ⚙️ Як це працює

```
Telegram-канал (джерело) 
        │
        ▼
  ┌─────────────┐
  │   SCRAPER   │  ← Pyrogram userbot, перехоплює пости
  │ (Pyrogram)  │
  └──────┬──────┘
         │ JSON payload → Redis Streams (xadd)
         ▼
  ┌─────────────┐
  │  Redis      │  ← Персистентна черга повідомлень
  │  Streams    │     (maxlen=10 000, XREADGROUP)
  └──────┬──────┘
         │ xreadgroup
         ▼
  ┌─────────────┐
  │   WORKER    │  ← TextProcessor: regex-аналіз тексту
  │  (asyncio)  │     → Виборка цільових user_id з Supabase
  └──────┬──────┘     → Redis-кеш таргетів (5с TTL)
         │ fire_and_forget
         ▼
  ┌─────────────┐
  │ Broadcaster │  ← asyncio.Queue(maxsize=10000)
  │  (15 tasks) │     15 паралельних воркерів розсилки
  └──────┬──────┘     + відкладені сирени [2/3] та [3/3]
         │
         ▼
  Telegram-користувач 📱
```

### Алгоритм обробки одного посту

1. **Pyrogram Scraper** перехоплює новий пост із цільового каналу
2. Пост серіалізується у [`AlertMessage`](alert_bot_project/core_shared/schemas.py) (Pydantic v2) і відправляється у Redis Stream
3. **Worker** зчитує повідомлення через `XREADGROUP`, перевіряє дедуплікацію (ключ TTL=600с)
4. [`TextProcessor.parse_message()`](alert_bot_project/core_shared/text_processor.py) запускає прекомпільовані regex по категоріях та локаціях
5. Якщо знайдено збіги — запит до Supabase (з кешуванням чексуми таргетів на 5с)
6. Перевірка нічного вікна (`NIGHT_START_HOUR`..`NIGHT_END_HOUR`)
7. **Broadcaster** надсилає `ALERT_FIRST` + планує `ALERT_SECOND`/`ALERT_THIRD` через Redis ZSET
8. Після підтвердження від користувача — система глушиться на 10 хвилин

---

## 🏗️ Архітектура системи

```
┌────────────────────────────────────────────────────────────────┐
│                        Docker Network                          │
│                                                                │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐  │
│  │ scraper  │   │  worker  │   │  bot_ui  │   │migrator  │  │
│  │:8001     │   │:8000     │   │:8002     │   │(one-shot)│  │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └──────────┘  │
│       │              │              │                          │
│       └──────────────┼──────────────┘                         │
│                      │                                         │
│              ┌───────┴────────┐                               │
│              │  Redis :6379   │ ← Streams + Cache + Mute      │
│              └───────┬────────┘                               │
│                      │                                         │
│         ┌────────────┴────────────┐                           │
│         │    Supabase PostgreSQL  │ ← user_settings +         │
│         │    (external cloud)     │   user_triggers            │
│         └─────────────────────────┘                           │
│                                                                │
│  ┌──────────────┐  ┌────────────┐  ┌──────────┐              │
│  │  Prometheus  │  │Alertmanager│  │ Grafana  │              │
│  │    :9090     │  │   :9093    │  │  :3000   │              │
│  └──────────────┘  └────────────┘  └──────────┘              │
│                                                                │
│  ┌───────────────┐                                            │
│  │ redis-exporter│ ← redis_up метрика для Prometheus          │
│  │    :9121      │                                            │
│  └───────────────┘                                            │
└────────────────────────────────────────────────────────────────┘
```

### Схема бази даних

```sql
-- Налаштування користувача
CREATE TABLE user_settings (
    user_id     BIGINT PRIMARY KEY,
    potvory     VARCHAR[]  DEFAULT ARRAY['Мопеди', 'Ракети'],
    muted_until TIMESTAMPTZ,          -- INDEX: B-Tree для швидкої фільтрації
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Тригерні локації (інваріантні ключі + кастомні фрази)
CREATE TABLE user_triggers (
    user_id      BIGINT REFERENCES user_settings(user_id) ON DELETE CASCADE,
    trigger_word VARCHAR(50),
    created_at   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, trigger_word)
);
```

---

## 📦 Підсистеми та компоненти

### 🛰️ Scraper (`alert_bot_project/scraper/`)

Реалізований на [Pyrogram](https://docs.pyrogram.org/) — неофіційному userbot-клієнті Telegram. Підписується на вказаний канал через `filters.chat(GROUP_ID)` і відправляє кожен новий пост у Redis Stream.

- Підтримка `PYROGRAM_SESSION_STRING` для stateless деплою в PaaS/K8s
- Exponential backoff при збоях публікації (3 спроби, 2^n секунд)
- При втраті TCP-з'єднання з Redis — примусове скидання пулу для чистого переконекту
- Метрики: `scraper_messages_total`, `scraper_errors_total`

### ⚙️ Worker (`alert_bot_project/worker/`)

Серце системи. Asyncio-воркер з `XREADGROUP` читає Redis Stream і запускає повний конвеєр обробки.

- **Дедуплікація** — Redis ключ `processed_msg:{chat_id}:{message_id}` з TTL=600с
- **TextProcessor** — прекомпільовані regex з `\w{0,3}` суфіксом для відмінювання
- **Кешування таргетів** — MD5-чексума `cats+triggers` як ключ, TTL=5с
- **XAUTOCLAIM** — автоматичне перехоплення завислих повідомлень (idle > 60с)
- **Dead Letter Queue** — після 5 невдалих спроб запис у `dead_letter_queue` stream
- **Broadcaster** — 15 паралельних asyncio-воркерів, `asyncio.Queue(maxsize=10000)`
- **Відкладені сирени** — ZSET `delayed_alerts_queue` з Lua-скриптом атомарного pop

### 🤖 Bot UI (`alert_bot_project/bot/`)

Telegram-бот на [aiogram 3.x](https://docs.aiogram.dev/) з FSM, inline-клавіатурами та middleware для ін'єкції сесій БД.

| Команда / Callback | Функція |
|---|---|
| `/start` | Реєстрація та головне меню |
| `🌍 Обрати дислокацію` | Пагінований список з 35+ районів |
| `✍️ Мої кастомні фрази` | Менеджмент власних ключових слів |
| `🦅 Крилаті потвори` | Вибір категорій: Мопеди / Ракети |
| `🔕 Режим тиші (MUTE)` | Пресети: 1г / 2г / 4г / до ранку |
| `✅ Сповіщення прийнято` | Підтвердження + заглушення на 10 хв |

### 📍 TextProcessor (`alert_bot_project/core_shared/text_processor.py`)

Ядро аналізу тексту. Усі regex прекомпільовані один раз при імпорті модуля.

```python
# Патерн з підтримкою до 3 символів закінчення (відмінки, роди, множина)
rf"(?<![\w])({escaped_words})\w{{0,3}}(?![\w])"

# Приклади збігів:
# "шахед" → "шахеда", "шахеди", "шахедів"
# "ракет" → "ракета", "ракети", "ракетами" (ні, +ами > 3)
# "центр" → "центру", "центром", "центрі"
```

**Покриті локації (35+):**

| Група | Локації |
|---|---|
| Одеса — райони | Центр, Черемушки, Порт, Молдованка, Бугаєвка, Слобідка, Таїрове, Совіньйон, Ланжерон, Котовського, Південний р-н, Фонтанка, Пересип, Аркадія, Узбережжя, Місто (загально) |
| Передмістя / Область | Усатове, Южне, Біляївка, Овідіополь, Чорноморськ, Чорноморка, Нові Білярі, Рені, Ізмаїл, Татарбунари, Березівка, Вилкове, Авангард, Лиманка, Затока, Білгород-Дністровський, Теплодар, Доброслав, Тузли |

---

## 🔧 Стек технологій

| Компонент | Технологія | Версія | Призначення |
|---|---|---|---|
| Telegram Bot API | [aiogram](https://aiogram.dev) | 3.29.0 | UI бота, FSM, inline-клавіатури |
| Telegram Userbot | [Pyrogram](https://docs.pyrogram.org) | 2.0.106 | Перехоплення постів каналу |
| Брокер повідомлень | [Redis Streams](https://redis.io/docs/data-types/streams/) | 7.2 | Черга + кеш + MUTE-ключі |
| База даних | [Supabase](https://supabase.com) (PostgreSQL) | — | Налаштування користувачів |
| ORM | [SQLAlchemy](https://docs.sqlalchemy.org) | 2.0.51 | Async ORM з asyncpg |
| Валідація | [Pydantic](https://docs.pydantic.dev) v2 | 2.13.4 | Схеми даних, конфіг |
| Моніторинг | [Prometheus](https://prometheus.io) + [Grafana](https://grafana.com) | latest | Метрики, дашборди, алерти |
| Контейнеризація | [Docker Compose](https://docs.docker.com/compose/) | v2 | Оркестрація всіх сервісів |
| Лінтер / Форматер | [Ruff](https://docs.astral.sh/ruff) | 0.9.5 | Статичний аналіз + форматування |
| Типи | [mypy](https://mypy.readthedocs.io) | 1.11.2 | Строга перевірка типів |
| Безпека | [Bandit](https://bandit.readthedocs.io) | 1.7.9 | Аудит безпеки коду |
| Тестування | [pytest](https://docs.pytest.org) + [Hypothesis](https://hypothesis.readthedocs.io) | 8.2.2 / 6.103.1 | Unit + Property-based тести |

---

## 🚀 Швидкий старт

### Передумови

- [Docker](https://docs.docker.com/get-docker/) і [Docker Compose v2](https://docs.docker.com/compose/install/)
- Telegram Bot Token від [@BotFather](https://t.me/BotFather)
- Telegram API credentials з [my.telegram.org](https://my.telegram.org)
- Supabase проєкт (або будь-який PostgreSQL з asyncpg)

### 1. Клонування репозиторію

```bash
git clone https://github.com/your-username/alert-bot-project.git
cd alert-bot-project
```

### 2. Конфігурація оточення

```bash
cp env.example .env
# Відкрийте .env та заповніть усі змінні (деталі нижче)
nano .env
```

### 3. Першочергова Pyrogram-авторизація

```bash
# Запустіть локально для створення файлу .session
pip install pyrogram
python -c "
from pyrogram import Client
app = Client('twink_account', api_id=YOUR_API_ID, api_hash='YOUR_API_HASH')
app.run()
"
# Скопіюйте twink_account.session до ./data/session/
mkdir -p data/session
mv twink_account.session data/session/
```

### 4. Запуск усіх сервісів

```bash
make up
# або
docker compose up -d --build
```

### 5. Перевірка стану

```bash
# Логи всіх контейнерів
make logs

# Стан сервісів
docker compose ps

# Метрики воркера
curl http://localhost:8000/metrics

# Grafana Dashboard
open http://localhost:3000  # admin / $GRAFANA_PASSWORD
```

---

## ⚙️ Конфігурація

Усі налаштування зберігаються в `.env` файлі та валідуються через [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) при старті.

```dotenv
# ─── Telegram ────────────────────────────────────────────────────────────────
BOT_TOKEN=1234567890:ABCdefGhIJKlmNoPQRsTUVwXyZ     # Токен від @BotFather
ADMIN_CHAT_ID=987654321                              # Ваш Telegram ID для Alertmanager
API_ID=1234567                                       # API ID з my.telegram.org
API_HASH=abcdef0123456789abcdef0123456789           # API Hash з my.telegram.org
GROUP_ID=-1001234567890                              # ID цільового Telegram-каналу

# Опціонально: рядок сесії Pyrogram для stateless деплою (PaaS/K8s)
PYROGRAM_SESSION_STRING=

# ─── Інфраструктура ──────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
REDIS_URL=redis://redis:6379/0

# ─── Порти метрик (мають бути УНІКАЛЬНИМИ — перевіряється Pydantic) ──────────
METRICS_PORT_WORKER=8000
METRICS_PORT_SCRAPER=8001
METRICS_PORT_BOT=8002

# ─── Нічний режим ────────────────────────────────────────────────────────────
NIGHT_START_HOUR=22                 # Початок роботи (0–23)
NIGHT_END_HOUR=7                    # Завершення роботи (0–23)
TELEGRAM_MAX_RETRY_SECONDS=180      # Максимум очікування при Flood Control (429)

# ─── Логування ───────────────────────────────────────────────────────────────
LOG_LEVEL=INFO
LOG_DIR=/data/logs
LOG_MAX_BYTES=20971520              # 20 МБ
LOG_BACKUP_COUNT=5

# ─── Observability ───────────────────────────────────────────────────────────
GRAFANA_PASSWORD=super_secure_admin_password_2026
```

> **Важливо:** Валідатор Pydantic перевіряє унікальність портів метрик та діапазони значень (`NIGHT_START_HOUR` 0–23, порти 1024–65535) на етапі ініціалізації контейнера.

---

## 🎛️ Налаштування бота

### Вибір локацій

Навігація побудована на пагінованому inline-меню (по 8 локацій на сторінці):

```
Головне меню
├── 🌍 Обрати дислокацію
│   ├── 🏙️ Одеса (Райони)    → список районів Одеси
│   └── 🏞️ Передмістя / Область → список передмість
├── ✍️ Мої кастомні фрази    → додати/видалити власні ключові слова
├── 🦅 Крилаті потвори       → перемикачі: Мопеди / Ракети
├── 🔕 Режим тиші (MUTE)     → 1г / 2г / 4г / до ранку / вимкнути
└── ℹ️ Інформація
```

### Кастомні тригери

Підтримує до **5 власних ключових слів**. Алгоритм автоматично матчить до 3 символів закінчення:

```
Ввід: "малиновськ"  → матчить: малиновська, малиновського, малиновській
Ввід: "олександрівк" → матчить: олександрівка, олександрівці, олександрівку
```

Кастомні тригери синхронізуються у Redis Set `global_custom_triggers` і перевіряються воркером у реальному часі.

### Алгоритм сповіщення

Кожна виявлена загроза генерує **3 хвилі сповіщень**:

```
t+0с  → 🚨 ALERT_FIRST  "Увага! Загроза у вашому напрямку!"  [+ кнопка підтвердження]
t+5с  → 🔔 ALERT_SECOND "[2/3] Загроза все ще актуальна!"
t+65с → 🔔 ALERT_THIRD  "[3/3] Будь ласка, підтвердіть отримання"
```

Якщо користувач натиснув **"✅ Сповіщення прийнято"** — система глушиться на 10 хвилин автоматично.

---

## 📊 Моніторинг та Observability

### Prometheus метрики

| Метрика | Тип | Опис |
|---|---|---|
| `scraper_messages_total` | Counter | Всього перехоплених постів |
| `scraper_errors_total` | Counter | Помилки публікації в Redis |
| `worker_alerts_processed_total` | Counter | Розісланих сповіщень |
| `worker_errors_total` | Counter | Помилки основного циклу |
| `worker_dlq_size` | Gauge | Глибина Dead Letter Queue |
| `worker_processing_duration_seconds` | Histogram | Latency обробки (p50/p95) |

### Grafana Dashboard

Готові дашборди у `grafana/provisioning/dashboards/`:

- **Real-time Alert Flow** — порівняння швидкості перехоплення та розсилки
- **Processing Latency** — середній час та p95 Histogram воркера
- **Error Rate** — частота помилок scraper та worker в реальному часі
- **DLQ Gauge** — поточна глибина черги битих повідомлень
- **Total Alerts (24h)** — кількість сповіщень за добу

### Alertmanager правила

```yaml
# Критичні (негайне сповіщення в Telegram адміна):
- ServiceDown      → сервіс не відповідає > 3 хв
- RedisDown        → брокер недоступний > 1 хв  
- HighWorkerErrors → рівень помилок > 10% від потоку > 1 хв
- HighScraperErrors → > 5 збоїв за 5 хвилин

# Попередження:
- DeadLetterQueueGrows → > 10 повідомлень у DLQ > 2 хв
```

---

## 🧪 Тестування

### Запуск тестів

```bash
# Усі unit-тести
make test

# Інтеграційний E2E тест пайплайну
make integration

# Стрес-тест Redis Streams (2000 повідомлень)
make stress

# Повна перевірка якості (format + lint + test + integration)
make check
```

### Структура тестів

| Файл | Покриття | Підхід |
|---|---|---|
| `test_text_processor.py` | TextProcessor: normalize, parse_message | pytest parametrize + Hypothesis fuzzing |
| `test_crud.py` | CRUD операції БД | AsyncMock + Hypothesis property-based |
| `test_user_service.py` | UserService: toggle, mute, ack | AsyncMock + patch |
| `test_handlers.py` | aiogram handlers: /start, settings FSM | AsyncMock + patch |
| `test_middleware.py` | DatabaseMiddleware: commit/rollback | AsyncMock + SQLAlchemyError |
| `test_integration_pipeline.py` | E2E: Scraper → Redis → Worker → Broadcaster | повний конвеєр з моками |

### Property-based тестування (Hypothesis)

```python
@given(st.text())
def test_parse_message_invariant_never_crashes(text: str):
    result = TextProcessor.parse_message(text)
    assert "categories" in result and "locations" in result
```

Hypothesis генерує сотні рандомних Unicode-рядків, перевіряючи що ядро аналізу ніколи не падає на непередбачених вхідних даних.

---

## 🔄 CI/CD та якість коду

### GitHub Actions Pipeline (`.github/workflows/ci.yaml`)

```
push/PR → main
    │
    ├── Checkout + Python 3.11 + Redis service container
    ├── pip install (requirements.txt + requirements-dev.txt)
    ├── ruff check .          (лінтинг + importsort)
    ├── ruff format --check . (перевірка форматування)
    ├── mypy alert_bot_project/ (строгі типи)
    ├── bandit -c pyproject.toml (аудит безпеки)
    └── pytest (unit + integration з реальним Redis)
```

### Pre-commit хуки (`.pre-commit-config.yaml`)

```bash
# Встановлення хуків
pip install pre-commit
pre-commit install

# Перевірки при кожному git commit:
# ✅ trailing-whitespace
# ✅ end-of-file-fixer
# ✅ check-yaml / check-json
# ✅ check-added-large-files (>500KB)
# ✅ detect-private-key
# ✅ ruff (lint + fix + format)
# ✅ mypy (strict type checking)
# ✅ bandit (security audit)
```

### Makefile команди

```bash
make up          # Зібрати та запустити всі сервіси у фоні
make down        # Зупинити та видалити контейнери
make restart     # Перезапустити всі сервіси
make logs        # Стрим логів усіх контейнерів
make format      # Автоформатування коду (Ruff)
make lint        # Статичний аналіз (Ruff + mypy + Bandit)
make test        # Unit-тести
make integration # E2E тест пайплайну
make stress      # Стрес-тест Redis (2000 повідомлень)
make check       # Повний аудит: format → lint → test → integration
```

---

## 📁 Структура проєкту

```
alert-bot-project/
│
├── alert_bot_project/
│   ├── bot/                        # Telegram Bot UI (aiogram)
│   │   ├── handlers/
│   │   │   ├── start.py            # /start команда та головне меню
│   │   │   └── settings.py         # FSM-налаштування локацій, MUTE, тригерів
│   │   ├── keyboards/
│   │   │   ├── builders.py         # Фабрики inline-клавіатур
│   │   │   └── messages.py         # Централізоване сховище текстів
│   │   ├── middlewares/
│   │   │   └── db.py               # DatabaseMiddleware (ін'єкція AsyncSession)
│   │   ├── loader.py               # Lazy-singleton: Bot, Dispatcher, Redis (PEP 562)
│   │   └── main.py                 # Точка входу бота
│   │
│   ├── core_shared/                # Спільний код між підсистемами
│   │   ├── callbacks.py            # CallbackData фабрики + FSM States
│   │   ├── config.py               # Pydantic Settings (валідація .env)
│   │   ├── constants.py            # ODESA_LOCS, OUTSIDE_LOCS, KR_POTVORY
│   │   ├── logging_config.py       # Dual-channel logging (console + JSON file)
│   │   ├── metrics.py              # Prometheus Counter/Gauge/Histogram
│   │   ├── schemas.py              # AlertMessage (Pydantic v2)
│   │   └── text_processor.py       # Ядро regex-аналізу тексту
│   │
│   ├── database/                   # Шар даних
│   │   ├── crud.py                 # Async CRUD операції (SQLAlchemy 2.0)
│   │   ├── engine.py               # AsyncEngine + AsyncSessionLocal
│   │   ├── migration.py            # Міграція legacy-ключів
│   │   └── models.py               # ORM моделі: UserSettings, UserTrigger
│   │
│   ├── scraper/                    # Pyrogram userbot
│   │   ├── publisher.py            # RedisPublisher (xadd + retry)
│   │   └── main.py                 # Точка входу скрейпера
│   │
│   ├── worker/                     # Asyncio воркер
│   │   ├── broadcaster.py          # Broadcaster (Queue + delayed alerts + Lua)
│   │   └── main.py                 # Конвеєр обробки + XREADGROUP loop
│   │
│   └── scripts/
│       └── stress_test.py          # Бенчмарк Redis Streams (2000 msg)
│
├── tests/                          # Тестова suite
│   ├── test_text_processor.py
│   ├── test_crud.py
│   ├── test_user_service.py
│   ├── test_handlers.py
│   ├── test_middleware.py
│   └── test_integration_pipeline.py
│
├── grafana/
│   └── provisioning/               # Авто-провізіонінг datasources + dashboards
│
├── prometheus/
│   ├── prometheus.yml              # Scrape конфіг
│   ├── alerts.yml                  # Правила алертів
│   └── alertmanager.yml            # Маршрутизація → Telegram
│
├── .github/workflows/ci.yaml       # GitHub Actions CI pipeline
├── .pre-commit-config.yaml         # Pre-commit хуки
├── docker-compose.yml              # Оркестрація всіх 9 сервісів
├── Dockerfile                      # Multi-stage build (builder + runner)
├── Makefile                        # DevOps команди
├── pyproject.toml                  # Ruff + mypy + Bandit + pytest конфіг
├── requirements.txt                # Production залежності
└── requirements-dev.txt            # Dev залежності (pytest, hypothesis)
```

---

## 🔒 Безпека

- **Non-root контейнер** — сервіси запускаються від `appuser:appgroup` (uid=10001)
- **Multi-stage Docker build** — production образ не містить компіляторів та dev-інструментів
- **SSL для PostgreSQL** — примусовий `ssl: require` у `connect_args`
- **Секрети через .env** — `.gitignore` виключає всі `.env*` файли, `detect-private-key` хук блокує їх коміт
- **HMAC-хешування** — ідентифікатори peer у логах хешуються через HMAC-SHA256 для приватності
- **Bandit аудит** — автоматичний пошук вразливостей (eval, pickle, захардкоджені секрети) у CI
- **Rate-limit захист** — Broadcaster обробляє Telegram 429 з кумулятивним backoff до `TELEGRAM_MAX_RETRY_SECONDS`
- **Fail-Fast** — сервер метрик Prometheus при збої викликає `sys.exit(1)` для негайного рестарту оркестратором

---

---

<div align="center">

Розроблено з ❤️ для захисту людей Одеси

**[⬆ Повернутися нагору](#️-odesaalert-bot)**

</div>