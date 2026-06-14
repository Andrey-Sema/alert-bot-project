<div align="center">

# 🛡️ OdesaAlert Bot

**Персональна система моніторингу повітряних загроз для Одеси та області**

Перехоплює повідомлення з інформаційних каналів · Аналізує загрози в реальному часі · Надсилає точкові сповіщення за вашим районом

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![aiogram](https://img.shields.io/badge/aiogram-3.18-2CA5E0?style=flat-square&logo=telegram&logoColor=white)](https://aiogram.dev)
[![Redis](https://img.shields.io/badge/Redis-Streams-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-asyncpg-336791?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)

</div>

---

## Як це працює

Система складається з чотирьох незалежних сервісів, які запускаються разом через Docker Compose:

```
Telegram-канал
      │
      ▼
 [scraper]  ← Pyrogram userbot, слухає обраний канал
      │  XADD
      ▼
 [Redis Stream]  ← персистентна черга alerts_stream
      │  XREADGROUP
      ▼
 [worker]  ← аналізує текст, підбирає користувачів, розсилає
      │
      ├─→ [PostgreSQL]  ← налаштування користувачів, тригери
      └─→ [bot_ui]  ← aiogram бот, приймає команди від користувача
```

**Scraper** (Pyrogram) слухає вказаний канал і пише кожне повідомлення в Redis Stream.  
**Worker** читає стрім, запускає regex-аналіз по двомовним патернам (UA + RU), знаходить релевантних користувачів через PostgreSQL і розсилає сповіщення трьома хвилями з затримкою.  
**Bot UI** (aiogram 3) — інтерфейс налаштувань: вибір районів, режим тиші, кастомні тригери.

---

## Можливості

**Точкові сповіщення за районом**
Користувач обирає конкретні райони Одеси або населені пункти області. Бот надсилає повідомлення лише коли загроза згадана саме у вашому напрямку.

**Двомовний аналіз**
Regex-патерни покривають назви локацій українською та російською одночасно. Все зводиться до єдиного інваріантного ключа — `"peresyp"`, `"tairovo"` тощо.

**Категорії загроз**
Окремо відстежуються БПЛА / шахеди (`Мопеди`) та ракети / балістика (`Ракети`). Кожну категорію можна вимкнути.

**Кастомні тригери**
До 5 власних слів або фраз — назва вулиці, ЖК, орієнтир. Якщо слово з'явиться в повідомленні каналу — прийде сповіщення.

**Режим тиші (MUTE)**
Вимкнути сповіщення на 1, 2, 4 години або до 07:00. Нічний режим автоматично надсилає сповіщення без звуку з 22:00 до 07:00.

**Триступеневе сповіщення**
Перше повідомлення → через 5 сек друге → через 60 сек третє з кнопкою підтвердження. При натисканні «Прийнято» бот замовкає на 10 хвилин.

**Dead Letter Queue**
Повідомлення, які не вдалося обробити 5 разів, переміщуються в `dead_letter_queue` для ручного розбору.

---

## Стек

| Шар | Технологія |
|-----|-----------|
| Telegram Bot API | aiogram 3.18 |
| Telegram Userbot | Pyrogram 2.0 + TgCrypto |
| Черга повідомлень | Redis Streams (XADD / XREADGROUP) |
| База даних | PostgreSQL через asyncpg + SQLAlchemy 2.0 async |
| Валідація конфігу | Pydantic Settings v2 |
| Інфраструктура | Docker Compose (4 сервіси) |
| Логування | JSON structured logs + RotatingFileHandler |

---

## Швидкий старт

### 1. Клонувати репозиторій

```bash
git clone https://github.com/your-username/odesa-alert-bot.git
cd odesa-alert-bot
```

### 2. Створити `.env`

```bash
cp .env.example .env
```

Заповнити змінні:

```env
# Бот (від @BotFather)
BOT_TOKEN=your_bot_token_here

# ID каналу для моніторингу (з мінусом для груп, напр. -1001234567890)
GROUP_ID=-1001234567890

# Pyrogram userbot (з my.telegram.org)
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890

# PostgreSQL (Supabase або локальний)
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname

# Redis
REDIS_URL=redis://localhost:6379/0

# Опційно
NIGHT_START_HOUR=22
NIGHT_END_HOUR=7
LOG_LEVEL=INFO
TELEGRAM_MAX_RETRY_SECONDS=180
```

### 3. Авторизувати Pyrogram (одноразово)

```bash
python -c "
from pyrogram import Client
import asyncio, os
async def auth():
    async with Client('twink_account', api_id=int(os.environ['API_ID']), api_hash=os.environ['API_HASH']):
        print('Done')
asyncio.run(auth())
"
```

Сесійний файл `twink_account.session` покласти в `./data/session/`.

### 4. Запустити

```bash
docker compose up -d
```

Docker Compose послідовно запустить:
1. `migrator` — накатить міграцію ключів (і зупиниться)
2. `scraper`, `worker`, `bot_ui` — основні сервіси

### 5. Перевірити статус

```bash
docker compose ps
docker compose logs worker --tail=50 -f
```

---

## Структура проекту

```
alert_bot_project/
├── bot/
│   ├── handlers/          # start.py, settings.py — aiogram хендлери
│   ├── keyboards/         # builders.py — inline клавіатури
│   └── middlewares/       # db.py — DatabaseMiddleware (Unit of Work)
├── core_shared/
│   ├── callbacks.py       # aiogram CallbackData типи
│   ├── config.py          # Pydantic Settings
│   ├── constants.py       # локації, патерни, шаблони повідомлень
│   ├── schemas.py         # AlertMessage (Pydantic)
│   └── text_processor.py  # regex-аналіз з precompiled patterns
├── database/
│   ├── crud.py            # async CRUD операції
│   ├── engine.py          # SQLAlchemy async engine
│   ├── migration.py       # міграція legacy ключів
│   └── models.py          # UserSettings, UserTrigger
├── scraper/
│   ├── main.py            # Pyrogram клієнт
│   └── publisher.py       # Redis XADD
├── services/
│   └── user_service.py    # бізнес-логіка (без транзакцій)
└── worker/
    ├── broadcaster.py     # розсилка + delayed queue
    └── main.py            # Redis consumer group, основний цикл
```

---

## Змінні оточення

| Змінна | Обов'язкова | За замовчуванням | Опис |
|--------|:-----------:|:----------------:|------|
| `BOT_TOKEN` | ✅ | — | Токен бота від @BotFather |
| `GROUP_ID` | ✅ | — | ID каналу для моніторингу |
| `API_ID` | ✅ | — | Pyrogram API ID |
| `API_HASH` | ✅ | — | Pyrogram API Hash |
| `DATABASE_URL` | ✅ | — | PostgreSQL connection string (asyncpg) |
| `REDIS_URL` | | `redis://localhost:6379/0` | Redis connection string |
| `NIGHT_START_HOUR` | | `22` | Початок нічного режиму |
| `NIGHT_END_HOUR` | | `7` | Кінець нічного режиму |
| `LOG_LEVEL` | | `INFO` | Рівень логування |
| `LOG_DIR` | | `/data/logs` | Директорія для лог-файлів |
| `TELEGRAM_MAX_RETRY_SECONDS` | | `180` | Максимальний час retry при 429 |

---

## ⚠️ Важливо

Цей бот є **допоміжним інструментом** і не замінює офіційну державну систему повітряної тривоги України. У разі небезпеки завжди прямуйте до найближчого укриття незалежно від сповіщень бота.

Слідкуйте за офіційними джерелами: [Повітряна тривога](https://alerts.in.ua)

---

<div align="center">

Зроблено для Одеси · Слава Україні 🇺🇦

</div>