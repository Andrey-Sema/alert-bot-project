# PROJECT CONTEXT DUMP: .
Generated on: Sun Jun 14 17:17:32 2026

Это единый файл контекста проекта для анализа LLM.
---

## FILE: alert_bot_project\.dockerignore
```text
**/.git
**/.env
**/__pycache__
**/*.pyc
**/*.pyo
**/*.pyd
**/.venv
**/venv
**/.idea
**/.vscode
**/*.session
**/*.session-journal
```

---

## FILE: alert_bot_project\.gitignore
```text
# ============================================================
#  Python
# ============================================================
__pycache__/
*.py[cod]
*$py.class
*.so
*.egg
*.egg-info/
dist/
build/
eggs/
parts/
var/
sdist/
wheels/
pip-wheel-metadata/
share/python-wheels/
.installed.cfg
MANIFEST

# ============================================================
#  Virtual environments
# ============================================================
.venv/
venv/
env/
ENV/
env.bak/
venv.bak/
.python-version

# ============================================================
#  Environment & Secrets
# ============================================================
.env
.env.*
*.env
!*.env.example
!*.env.template

# ============================================================
#  Telegram / Pyrogram sessions
# ============================================================
*.session
*.session-journal

# ============================================================
#  PyCharm / JetBrains
# ============================================================
.idea/
*.iml
*.iws
*.ipr
out/
.idea_modules/

# ============================================================
#  VS Code
# ============================================================
.vscode/
*.code-workspace
.history/

# ============================================================
#  Logs & runtime data
# ============================================================
/data/
logs/
*.log
*.log.*
*.json.log

# ============================================================
#  Docker
# ============================================================
.dockerignore.local

# ============================================================
#  OS artefacts
# ============================================================
# macOS
.DS_Store
.AppleDouble
.LSOverride
._*
.Spotlight-V100
.Trashes

# Windows
Thumbs.db
Thumbs.db:encryptable
ehthumbs.db
Desktop.ini
$RECYCLE.BIN/
*.lnk

# Linux
*~
.fuse_hidden*
.directory
.Trash-*
.nfs*

# ============================================================
#  Testing & coverage
# ============================================================
.pytest_cache/
.coverage
.coverage.*
coverage.xml
htmlcov/
.tox/
.nox/
nosetests.xml
test-results/
*.pytest_cache

# ============================================================
#  Type checkers & linters
# ============================================================
.mypy_cache/
.dmypy.json
dmypy.json
.pyre/
.pytype/
.ruff_cache/

# ============================================================
#  Jupyter / IPython
# ============================================================
.ipynb_checkpoints/
profile_default/
ipython_config.py
*.ipynb

# ============================================================
#  Misc
# ============================================================
*.bak
*.swp
*.swo
*.tmp
*.pid
```

---

## FILE: alert_bot_project\docker-compose.yml
```yaml
version: '3.8'

services:
  migrator:
    build:
      context: .
      dockerfile: Dockerfile
    command: python -m alert_bot_project.database.migration
    env_file:
      - .env
    restart: "no"

  scraper:
    build:
      context: .
      dockerfile: Dockerfile
    command: python -m alert_bot_project.scraper.main
    env_file:
      - .env
    restart: unless-stopped
    deploy:
      restart_policy:
        condition: on-failure
        max_attempts: 10
        window: 300s
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
    volumes:
      - pyrogram_session:/data/session
      - shared_logs:/data/logs
    depends_on:
      migrator:
        condition: service_completed_successfully

  worker:
    build:
      context: .
      dockerfile: Dockerfile
    command: python -m alert_bot_project.worker.main
    env_file:
      - .env
    restart: unless-stopped
    deploy:
      restart_policy:
        condition: on-failure
        max_attempts: 10
        window: 300s
      resources:
        limits:
          cpus: '1.5'
          memory: 512M
        reservations:
          cpus: '0.5'
          memory: 256M
    volumes:
      - shared_logs:/data/logs
    healthcheck:
      test: ["CMD", "python", "-c", "import redis; r=redis.from_url('${REDIS_URL}'); r.ping()"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    depends_on:
      migrator:
        condition: service_completed_successfully

  bot_ui:
    build:
      context: .
      dockerfile: Dockerfile
    command: python -m alert_bot_project.bot.main
    env_file:
      - .env
    restart: unless-stopped
    deploy:
      restart_policy:
        condition: on-failure
        max_attempts: 10
        window: 300s
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
    volumes:
      - shared_logs:/data/logs
    healthcheck:
      test: ["CMD", "python", "-c", "import asyncio; asyncio.get_event_loop()"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    depends_on:
      migrator:
        condition: service_completed_successfully

volumes:
  pyrogram_session:
    driver: local
  shared_logs:
    driver: local
```

---

## FILE: alert_bot_project\requirements.txt
```text
aiogram==3.18.0
pydantic==2.10.4
pydantic-settings==2.7.1
SQLAlchemy==2.0.37
asyncpg==0.30.0
redis==5.2.1
pyrogram==2.0.106
tgcrypto==1.2.5
```

---

## FILE: alert_bot_project\bot\loader.py
```python
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from redis.asyncio import Redis
from alert_bot_project.core_shared.config import config

logger = logging.getLogger("bot.loader")

# Single instance definition for the official Bot API client
bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# Central framework update router initialization
dp = Dispatcher()

# Shared production-grade Redis connection pool singleton
redis_client = Redis.from_url(config.REDIS_URL, decode_responses=True)
```

---

## FILE: alert_bot_project\bot\main.py
```python
import asyncio
import logging
import sys
from alert_bot_project.core_shared.logging_config import setup_logging
from alert_bot_project.bot.loader import bot, dp
from alert_bot_project.bot.handlers import start, settings

# Setup logging architecture parameters directly for bot scope
setup_logging("tg_bot_ui")
logger = logging.getLogger("bot.main")


async def main():
    logger.info("Configuring routers mapping parameters arrays...")

    # Include functional feature logic modules blocks
    dp.include_router(start.router)
    dp.include_router(settings.router)

    logger.info("Dropping webhooks configurations parameters to sync cleanly...")
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Starting long polling interfaces updates tracking routines...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot application UI destroyed smoothly.")
```

---

## FILE: alert_bot_project\bot\__init__.py
```python

```

---

## FILE: alert_bot_project\bot\handlers\admin.py
```python

```

---

## FILE: alert_bot_project\bot\handlers\settings.py
```python
import logging
import html
from datetime import datetime, timedelta, timezone
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from alert_bot_project.database.crud import get_or_create_user
from alert_bot_project.services.user_service import UserService
from alert_bot_project.bot.loader import redis_client
from alert_bot_project.core_shared.constants import ODESA_LOCS, OUTSIDE_LOCS, KYIV_TZ
from alert_bot_project.core_shared.callbacks import (
    GroupNavCallback, LocationToggleCallback, ThreatCategoryCallback,
    MutePresetCallback, CustomActionCallback, CustomTriggerStates
)
from alert_bot_project.bot.keyboards.builders import (
    build_group_selection_menu, build_locations_paginated_keyboard,
    build_threat_categories_keyboard, build_mute_options_keyboard,
    build_custom_triggers_management_keyboard
)

logger = logging.getLogger("bot.handlers.settings")
router = Router(name="settings_router")


@router.callback_query(F.data == "menu:choose_group")
async def show_group_selection(callback: CallbackQuery):
    await callback.message.edit_text("Оберіть регіональну групу дислокацій для налаштування:",
                                     reply_markup=build_group_selection_menu())
    await callback.answer()


@router.callback_query(F.data == "menu:custom_manage")
async def show_custom_phrases_menu(callback: CallbackQuery, db_session: AsyncSession):
    async with db_session.begin():
        user = await get_or_create_user(db_session, callback.from_user.id)
        static_keys = set(ODESA_LOCS.keys()) | set(OUTSIDE_LOCS.keys())
        custom_phrases = {t for t in user.triggers_set if t not in static_keys}

    await callback.message.edit_text(
        text="✍️ <b>Ваші кастомні фрази для відстеження:</b>\n\nНатисніть на фразу, щоб видалити її з бази.",
        reply_markup=build_custom_triggers_management_keyboard(custom_phrases)
    )
    await callback.answer()


@router.callback_query(GroupNavCallback.filter())
async def show_paginated_locations(callback: CallbackQuery, callback_data: GroupNavCallback, db_session: AsyncSession):
    async with db_session.begin():
        user = await get_or_create_user(db_session, callback.from_user.id)
        triggers = user.triggers_set

    await callback.message.edit_text(
        text="Оберіть точні локації для моніторингу:",
        reply_markup=build_locations_paginated_keyboard(callback_data.group, triggers, callback_data.page)
    )
    await callback.answer()


@router.callback_query(LocationToggleCallback.filter())
async def toggle_location_trigger(callback: CallbackQuery, callback_data: LocationToggleCallback,
                                  db_session: AsyncSession):
    async with db_session.begin():
        service = UserService(db_session, redis_client)
        await service.toggle_location(callback.from_user.id, callback_data.inv_key)
        user = await get_or_create_user(db_session, callback.from_user.id)
        updated_triggers = user.triggers_set

    await callback.message.edit_reply_markup(
        reply_markup=build_locations_paginated_keyboard(callback_data.group, updated_triggers, callback_data.page)
    )
    await callback.answer()


@router.callback_query(F.data == "menu:potvory")
async def show_threat_categories(callback: CallbackQuery, db_session: AsyncSession):
    async with db_session.begin():
        user = await get_or_create_user(db_session, callback.from_user.id)
        categories = user.potvory

    await callback.message.edit_text(
        text="🦅 <b>Налаштування категорій повітряних загроз:</b>",
        reply_markup=build_threat_categories_keyboard(categories)
    )
    await callback.answer()


@router.callback_query(ThreatCategoryCallback.filter())
async def toggle_threat_category(callback: CallbackQuery, callback_data: ThreatCategoryCallback,
                                 db_session: AsyncSession):
    async with db_session.begin():
        service = UserService(db_session, redis_client)
        user = await get_or_create_user(db_session, callback.from_user.id)
        categories = list(user.potvory)

        if callback_data.category in categories:
            categories.remove(callback_data.category)
        else:
            categories.append(callback_data.category)

        msg = await service.set_threat_categories(callback.from_user.id, categories)

    await callback.message.edit_reply_markup(reply_markup=build_threat_categories_keyboard(categories))
    await callback.answer(text=msg)


@router.callback_query(F.data == "menu:mute")
async def show_mute_options(callback: CallbackQuery):
    await callback.message.edit_text(text="🔕 <b>Режим тиші (MUTE):</b>", reply_markup=build_mute_options_keyboard())
    await callback.answer()


@router.callback_query(MutePresetCallback.filter())
async def process_mute_action(callback: CallbackQuery, callback_data: MutePresetCallback, db_session: AsyncSession):
    user_id = callback.from_user.id
    now_utc = datetime.now(timezone.utc)

    async with db_session.begin():
        service = UserService(db_session, redis_client)
        if callback_data.preset == "clear":
            msg = await service.apply_mute_timeout(user_id, None, "Звук увімкнено")
            await redis_client.delete(f"user_mute:{user_id}")
        else:
            mapping = {"1": 1, "2": 2, "4": 4}
            if callback_data.preset in mapping:
                ttl_seconds = mapping[callback_data.preset] * 3600
                until = now_utc + timedelta(hours=mapping[callback_data.preset])
                text_reply = f"Сповіщення вимкнено на {callback_data.preset} год."
            else:
                from zoneinfo import ZoneInfo
                kyiv_now = datetime.now(ZoneInfo(KYIV_TZ))
                kyiv_target = kyiv_now.replace(hour=7, minute=0, second=0, microsecond=0)
                if kyiv_now >= kyiv_target:
                    kyiv_target += timedelta(days=1)
                until = kyiv_target.astimezone(timezone.utc)
                ttl_seconds = int((until - now_utc).total_seconds())
                text_reply = "Сповіщення вимкнено до ранку"

            msg = await service.apply_mute_timeout(user_id, until, text_reply)
            await redis_client.set(f"user_mute:{user_id}", "1", ex=max(1, ttl_seconds))

    await callback.answer(text=msg)


@router.callback_query(F.data == "custom:add")
async def initiate_custom_trigger_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomTriggerStates.waiting_for_keyword)
    await callback.message.answer("✍️ <b>Введіть назву вашої кастомної локації:</b>")
    await callback.answer()


@router.message(CustomTriggerStates.waiting_for_keyword)
async def store_custom_user_keyword(message: Message, state: FSMContext, db_session: AsyncSession):
    cleaned_input = message.text.strip().lower()
    if len(cleaned_input) < 3 or len(cleaned_input) > 30:
        await message.reply("⚠️ Назва локації повинна містити від 3 до 30 символів. Спробуйте ще раз:")
        return

    async with db_session.begin():
        service = UserService(db_session, redis_client)
        success, message_text = await service.add_custom_trigger(message.from_user.id, cleaned_input)

    safe_output = html.escape(cleaned_input)
    final_reply = message_text if not success else f"✅ Кастомну локацію <b>«{safe_output}»</b> успішно додано."

    await message.answer(final_reply)
    await state.clear()


@router.callback_query(CustomActionCallback.filter(F.action == "delete"))
async def delete_custom_user_keyword(callback: CallbackQuery, callback_data: CustomActionCallback,
                                     db_session: AsyncSession):
    async with db_session.begin():
        service = UserService(db_session, redis_client)
        await service.delete_custom_trigger(callback.from_user.id, callback_data.phrase)
        user = await get_or_create_user(db_session, callback.from_user.id)
        static_keys = set(ODESA_LOCS.keys()) | set(OUTSIDE_LOCS.keys())
        custom_phrases = {t for t in user.triggers_set if t not in static_keys}

    await callback.message.edit_text(
        text="✍️ <b>Ваші кастомні фрази для відстеження:</b>",
        reply_markup=build_custom_triggers_management_keyboard(custom_phrases)
    )
    await callback.answer(text="Локацію видалено")


@router.callback_query(F.data == "alert:ack")
async def process_alert_acknowledgement(callback: CallbackQuery, db_session: AsyncSession):
    until = datetime.now(timezone.utc) + timedelta(minutes=10)
    async with db_session.begin():
        service = UserService(db_session, redis_client)
        await service.apply_mute_timeout(callback.from_user.id, until, "Сигнал прийнято")
        await redis_client.set(f"user_mute:{callback.from_user.id}", "1", ex=600)

    await callback.message.edit_text(text=f"{callback.message.text}\n\n✅ <i>Сигнал прийнято.</i>")
    await callback.answer(text="Сповіщення заглушено на 10 хвилин.")
```

---

## FILE: alert_bot_project\bot\handlers\start.py
```python
import logging
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from sqlalchemy.exc import SQLAlchemyError, OperationalError

from alert_bot_project.database.engine import AsyncSessionLocal
from alert_bot_project.database.crud import get_or_create_user
from alert_bot_project.bot.keyboards.builders import build_main_menu

logger = logging.getLogger("bot.handlers.start")
router = Router(name="start_router")


@router.message(CommandStart())
async def process_start_command(message: Message):
    """Registers user profiles natively with explicit database exception traps."""
    user_id = message.from_user.id

    async with AsyncSessionLocal() as session:
        # Fix: Replaced broad generic exception traps with precise SQLAlchemy constraint boundaries mapping
        try:
            async with session.begin():
                await get_or_create_user(session, user_id)
        except (SQLAlchemyError, OperationalError) as db_err:
            logger.error("Database transport failure during user session initialization: %s", db_err)
            await message.answer("⚠️ Виникла помилка під час реєстрації. Будь ласка, спробуйте пізніше.")
            return
        except Exception as unexpected_err:
            logger.critical("Unexpected framework thread exception inside start handler context: %s", unexpected_err, exc_info=True)
            await message.answer("⚠️ Критична помилка системи. Спробуйте пізніше.")
            return

    welcome_text = (
        "🛡️ <b>Вітаємо у системі персонального моніторингу загроз!</b>\n\n"
        "Цей бот призначений для миттєвого інформування про небезпеку у конкретно обраних вами зонах "
        "на основі оперативного аналізу інформаційних каналів.\n\n"
        "ℹ️ <b>Важливо:</b> Бот є допоміжним інструментом і не замінює державну повітряну тривогу. "
        "У разі отримання сигналу небезпеки завжди прямуйте до найближчого укриття.\n\n"
        "Скористайтеся меню нижче для налаштування моніторингу:"
    )
    await message.answer(welcome_text, reply_markup=build_main_menu())


@router.callback_query(F.data == "menu:main")
async def process_return_to_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        text="🛡️ <b>Головне меню налаштувань:</b>",
        reply_markup=build_main_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "menu:info")
async def process_info_menu(callback: CallbackQuery):
    info_text = (
        "ℹ️ <b>Інформація про роботу системи:</b>\n\n"
        "• <b>Принцип дії:</b> Наш автономний модуль перехоплює повідомлення інформаційних пабліків "
        "та аналізує їх на наявність специфічних географічних і тактичних ключових слів.\n\n"
        "• <b>Двомовність:</b> Система автоматично розпізнає назви локацій як українською, "
        "та ко російською мовами, зводячи їх до єдиного внутрішнього ідентифікатора.\n\n"
        "• <b>Кастомні триггери:</b> Ви можете додати до 5 власних точних назв вулиць, орієнтирів "
        "або селищ. Якщо це слово з'явиться у звітах адмінів — ви миттєво отримаєте попередження."
    )
    # Fix: Replaced unexported transitive reference lookups with direct native class definition calls
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="menu:main")

    await callback.message.edit_text(text=info_text, reply_markup=kb.as_markup())
    await callback.answer()
```

---

## FILE: alert_bot_project\bot\keyboards\builders.py
```python
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup
from alert_bot_project.core_shared.constants import ODESA_LOCS, OUTSIDE_LOCS, KR_POTVORY, DISLOCS_PER_PAGE
from alert_bot_project.core_shared.callbacks import (
    GroupNavCallback, LocationToggleCallback, ThreatCategoryCallback,
    MutePresetCallback, CustomActionCallback
)


def build_main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌍 Обрати дислокацію", callback_data="menu:choose_group")
    kb.button(text="✍️ Мої кастомні фрази", callback_data="menu:custom_manage")
    kb.button(text="🦅 Крилаті потвори", callback_data="menu:potvory")
    kb.button(text="🔕 Режим тиші (MUTE)", callback_data="menu:mute")
    kb.button(text="ℹ️ Інформація", callback_data="menu:info")
    kb.adjust(1)
    return kb.as_markup()


def build_group_selection_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏙️ Одеса (Райони)", callback_data=GroupNavCallback(group="odesa", page=0).pack())
    kb.button(text="🏞️ Передмістя / Область", callback_data=GroupNavCallback(group="outside", page=0).pack())
    kb.button(text="⬅️ Назад", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def build_locations_paginated_keyboard(group: str, active_user_triggers: set[str], page: int = 0) -> InlineKeyboardMarkup:
    source_map = ODESA_LOCS if group == "odesa" else OUTSIDE_LOCS
    items = list(source_map.items())
    total_items = len(items)

    start_index = page * DISLOCS_PER_PAGE
    end_index = min(start_index + DISLOCS_PER_PAGE, total_items)

    kb = InlineKeyboardBuilder()

    for inv_key, meta in items[start_index:end_index]:
        is_active = inv_key in active_user_triggers
        status_marker = "✅" if is_active else "❌"
        button_label = f"{status_marker} {meta['emoji']} {meta['display']}"
        kb.button(text=button_label, callback_data=LocationToggleCallback(group=group, inv_key=inv_key, page=page).pack())

    if page > 0:
        kb.button(text="⬅️ Попередні", callback_data=GroupNavCallback(group=group, page=page - 1).pack())
    if end_index < total_items:
        kb.button(text="Наступні ➡️", callback_data=GroupNavCallback(group=group, page=page + 1).pack())

    kb.button(text="➕ Додати власну локацію", callback_data="custom:add")
    kb.button(text="⬅️ Назад до груп", callback_data="menu:choose_group")
    kb.adjust(2)
    return kb.as_markup()


def build_custom_triggers_management_keyboard(custom_phrases: set[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for phrase in custom_phrases:
        kb.button(text=f"❌ {phrase}", callback_data=CustomActionCallback(action="delete", phrase=phrase).pack())
    kb.button(text="➕ Додати нову фразу", callback_data="custom:add")
    kb.button(text="⬅️ Головне меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def build_threat_categories_keyboard(active_categories: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for cat_name in KR_POTVORY.keys():
        is_enabled = cat_name in active_categories
        status_marker = "✅" if is_enabled else "❌"
        kb.button(text=f"{status_marker} {cat_name}", callback_data=ThreatCategoryCallback(category=cat_name).pack())
    kb.button(text="⬅️ Назад", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def build_mute_options_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔕 1 година", callback_data=MutePresetCallback(preset="1").pack())
    kb.button(text="🔕 2 години", callback_data=MutePresetCallback(preset="2").pack())
    kb.button(text="🔕 4 години", callback_data=MutePresetCallback(preset="4").pack())
    kb.button(text="😴 До ранку (07:00)", callback_data=MutePresetCallback(preset="morning").pack())
    kb.button(text="🔔 Увімкнути звук", callback_data=MutePresetCallback(preset="clear").pack())
    kb.button(text="⬅️ Назад", callback_data="menu:main")
    kb.adjust(2)
    return kb.as_markup()


def build_acknowledge_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Сповіщення прийнято", callback_data="alert:ack")
    return kb.as_markup()
```

---

## FILE: alert_bot_project\bot\keyboards\static.py
```python

```

---

## FILE: alert_bot_project\bot\middlewares\db.py
```python
import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from alert_bot_project.database.engine import AsyncSessionLocal

logger = logging.getLogger("bot.middlewares.db")


class DatabaseMiddleware(BaseMiddleware):
    """
    Implements the clean Unit of Work pattern via aiogram middleware execution bounds.
    Ensures a single atomic transaction context per incoming update lifecycle.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        async with AsyncSessionLocal() as session:
            # Fix: Open an explicit atomic transaction context for the duration of the request
            async with session.begin():
                data["db_session"] = session
                return await handler(event, data)
```

---

## FILE: alert_bot_project\core_shared\callbacks.py
```python
from typing import Optional
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import StatesGroup, State


class CustomTriggerStates(StatesGroup):
    """FSM states tracking custom phrase user registration flows."""
    waiting_for_keyword = State()


class GroupNavCallback(CallbackData, prefix="nav_group"):
    group: str
    page: int


class LocationToggleCallback(CallbackData, prefix="loc_toggle"):
    group: str
    inv_key: str
    page: int


class ThreatCategoryCallback(CallbackData, prefix="cat_toggle"):
    category: str


class MutePresetCallback(CallbackData, prefix="mute_set"):
    preset: str


class CustomActionCallback(CallbackData, prefix="custom_act"):
    action: str
    phrase: Optional[str] = None
```

---

## FILE: alert_bot_project\core_shared\config.py
```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Telegram Bot Settings
    BOT_TOKEN: str = Field(..., description="Official UI bot token obtained from BotFather")
    GROUP_ID: int = Field(..., description="Target channel or group ID to parse threat monitoring data from")

    # Userbot (Pyrogram) Settings
    API_ID: int = Field(..., description="API ID from my.telegram.org")
    API_HASH: str = Field(..., description="API Hash from my.telegram.org")

    # Infrastructure Settings (Supabase & Redis)
    DATABASE_URL: str = Field(..., description="Connection string for PostgreSQL / Supabase")
    REDIS_URL: str = Field("redis://localhost:6379/0", description="Connection string for Redis instance")

    # Quiet Hours (Night Mode) Settings
    NIGHT_START_HOUR: int = Field(22, description="Start hour for quiet hours/night mode status")
    NIGHT_END_HOUR: int = Field(7, description="End hour for quiet hours/night mode status")

    # Production Logging Engine Configuration
    LOG_LEVEL: str = Field("INFO", description="Global application logging threshold level")
    LOG_DIR: str = Field("/data/logs", description="Directory where production rotational log files are persistent")
    LOG_MAX_BYTES: int = Field(20971520, description="Maximum individual file size boundary before rotation triggers")
    LOG_BACKUP_COUNT: int = Field(5, description="Ceiling buffer count of historical rotated log files to retain")

    # Fix: Removed magic numbers by adding configurable network threshold parameters
    TELEGRAM_MAX_RETRY_SECONDS: int = Field(180, description="Maximum total allowed cumulative sleep duration for Telegram 429 backoff")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


config = Settings()
```

---

## FILE: alert_bot_project\core_shared\constants.py
```python
# Target time zones and pagination configurations
KYIV_TZ = "Europe/Kyiv"
DISLOCS_PER_PAGE = 8
MAX_CUSTOM_TRIGGERS = 5

# Odesa municipal locations mapping with bilingual regex patterns
ODESA_LOCS = {
    "city": {"emoji": "🏙️", "display": "Місто (Загально)", "patterns": ["город", "місто", "одеса", "одесі"]},
    "center": {"emoji": "⚡", "display": "Центр", "patterns": ["центр"]},
    "cheremushki": {"emoji": "🏢", "display": "Черемушки", "patterns": ["черемушки", "черьомушки"]},
    "port": {"emoji": "⚓", "display": "Порт", "patterns": ["порт"]},
    "moldovanka": {"emoji": "🚏", "display": "Молдованка", "patterns": ["молдаванка", "молдовка", "молдаванці"]},
    "bugaevka": {"emoji": "🚂", "display": "Бугаєвка", "patterns": ["бугаевка", "бугаївка", "бугаївці"]},
    "slobodka": {"emoji": "🏘️", "display": "Слобідка", "patterns": ["слободка", "слобідка", "слобідці"]},
    "tairovo": {"emoji": "🌆", "display": "Таїрове", "patterns": ["таирово", "таїров"]},
    "sovignon": {"emoji": "🏖️", "display": "Совіньйон", "patterns": ["совиньон", "совіньйон"]},
    "lanzheron": {"emoji": "🌊", "display": "Ланжерон", "patterns": ["ланжерон"]},
    "kotovskogo": {"emoji": "🏚️", "display": "Селище Котовського", "patterns": ["поселок", "поскот", "котовского", "котовського"]},
    "yuzhny_dist": {"emoji": "🌞", "display": "Південний район", "patterns": ["южный", "південний"]},
    "fontanka": {"emoji": "⛲", "display": "Фонтанка", "patterns": ["фонтанка"]},
    "peresyp": {"emoji": "🌉", "display": "Пересип", "patterns": ["пересыпь", "пересип"]},
    "arkadia": {"emoji": "🌴", "display": "Аркадія", "patterns": ["аркадия", "аркадія"]},
    "coast": {"emoji": "🌊", "display": "Узбережжя", "patterns": ["берег", "побережье", "узбережжя"]}
}

# Regional / Suburb locations mapping with bilingual regex patterns
OUTSIDE_LOCS = {
    "usatovo": {"emoji": "🌾", "display": "Усатове", "patterns": ["усатово", "усатове"]},
    "yuzhne": {"emoji": "🌻", "display": "Южне", "patterns": ["южное", "южне", "южного"]},
    "belyaevka": {"emoji": "🌾", "display": "Біляївка", "patterns": ["беляевк", "біляївк"]},
    "ovidiopol": {"emoji": "🌅", "display": "Овідіополь", "patterns": ["овидиополь", "овідіополь"]},
    "chernomorsk": {"emoji": "⚓", "display": "Чорноморськ", "patterns": ["черноморс", "чорноморськ"]},
    "chernomorka": {"emoji": "🌊", "display": "Чорноморка", "patterns": ["черноморк", "чорноморка"]},
    "novi_belyari": {"emoji": "🌳", "display": "Нові Білярі", "patterns": ["новые беляр", "ніві біляр", "нові біляр"]},
    "reni": {"emoji": "🛳️", "display": "Рені", "patterns": ["рени", "рені"]},
    "izmail": {"emoji": "🚢", "display": "Ізмаїл", "patterns": ["измаил", "ізмаїл"]},
    "tatarbunary": {"emoji": "🏞️", "display": "Татарбунари", "patterns": ["татарбунар"]},
    "berezovka": {"emoji": "🌳", "display": "Березівка", "patterns": ["березовк", "березівк"]},
    "vilkovo": {"emoji": "🚤", "display": "Вилкове", "patterns": ["вилково", "вилкове"]},
    "avangard": {"emoji": "🎯", "display": "Авангард", "patterns": ["авангард"]},
    "limanka": {"emoji": "🏞️", "display": "Лиманка", "patterns": ["лиманк"]},
    "zatoka": {"emoji": "🏖️", "display": "Затока", "patterns": ["заток"]},
    "belgorod": {"emoji": "🏰", "display": "Білгород-Дністровський", "patterns": ["белгород", "білгород"]},
    "teplodar": {"emoji": "🔥", "display": "Теплодар", "patterns": ["теплодар"]},
    "dobroslav": {"emoji": "🌄", "display": "Доброслав", "patterns": ["доброслав"]},
    "tuzly": {"emoji": "🌊", "display": "Тузли", "patterns": ["тузлы", "тузли"]}
}

# Threat classifications mapped to multi-language structural lexical tokens
KR_POTVORY = {
    "Мопеди": [
        "мопед", "дрон", "шахед", "табун", "бпла", "літачок", "атака", "шахід"
    ],
    "Ракети": [
        "ракета", "балумба", "балістика", "балистика", "іскандер", "искандер", "касета", "кассета", "вихід", "выход", "пуск", "х101", "калібр", "калибр"
    ]
}

# Notification structural text templates (Clean Ukrainian UI)
ALERT_FIRST = "🚨 <b>Увага! Загроза у вашому напрямку!</b> Негайно прямуйте до укриття!"
ALERT_SECOND = "🔔 <b>[2/3] Загроза все ще актуальна!</b> Повідомлення дублюється для вашої безпеки."
ALERT_THIRD = "🔔 <b>[3/3] Будь ласка, підтвердіть отримання</b> та перебування в безпечному місці!"

# Notification step delay configuration (seconds)
ALERT_DELAY_1 = 5
ALERT_DELAY_2 = 60
```

---

## FILE: alert_bot_project\core_shared\logging_config.py
```python
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from alert_bot_project.core_shared.config import config


class StructuredJsonFormatter(logging.Formatter):
    """
    Custom structural formatter that translates internal logging record
    states into explicit production-grade JSON lines payload mapping.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Build core structured fields payload contract
        log_payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
            "process_id": record.process,
            "thread_name": record.threadName
        }

        # Safely extract and inject exceptions tracebacks if execution scope failed
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        # Inject extra dynamic attributes if attached to log invocation dict
        if hasattr(record, "extra_metadata"):
            log_payload["metadata"] = record.extra_metadata

        return json.dumps(log_payload, ensure_ascii=False)


def setup_logging(service_name: str):
    """
    Orchestrates centralized dual-channel logging topologies.
    Routes clean human-readable text to stdout and safe structural JSON to rolling files.
    """
    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clean existing default handlers to avoid message duplication issues
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Channel 1: High-performance Human-Readable Console Stream
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Channel 2: Structural Production Rotational File Engine
    try:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        file_path = os.path.join(config.LOG_DIR, f"{service_name}.json.log")

        file_handler = RotatingFileHandler(
            filename=file_path,
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8"
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(StructuredJsonFormatter())
        root_logger.addHandler(file_handler)

        logging.getLogger("logging_system").info(f"Persistent logging engine mapped to: {file_path}")
    except Exception as exc:
        # Fallback security alert vector if physical filesystem mounting layer fails
        logging.getLogger("logging_system").error(f"Critical failure initializing physical file storage logs: {exc}")
```

---

## FILE: alert_bot_project\core_shared\schemas.py
```python
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class AlertMessage(BaseModel):
    """Data contract for message serialization between scraper and worker."""
    message_id: int = Field(..., description="Telegram message ID")
    chat_id: int = Field(..., description="Source channel ID")
    # Fix: Added max_length to protect worker memory from massive spam posts
    raw_text: str = Field(..., max_length=4000, description="Raw text message content")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC time when the message was captured"
    )

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "AlertMessage":
        return cls.model_validate_json(json_str)
```

---

## FILE: alert_bot_project\core_shared\text_processor.py
```python
import re
from typing import Set, Dict, Any
from alert_bot_project.core_shared.constants import ODESA_LOCS, OUTSIDE_LOCS, KR_POTVORY

CLEAN_PATTERN = re.compile(r"[^\w\s-]")

# Precompile integrated lookup regex strings for multi-language category tracking
COMPILED_CATEGORIES = {
    category: re.compile(rf"(?<![\w])({'|'.join(re.escape(word) for word in keywords)})(?![\w])")
    for category, keywords in KR_POTVORY.items()
}

# Precompile and map bilingual text patterns directly to invariant database location keys
COMPILED_LOCATIONS = {
    loc_key: re.compile(rf"(?<![\w])({'|'.join(re.escape(p) for p in data['patterns'])})(?![\w])")
    for loc_key, data in {**ODESA_LOCS, **OUTSIDE_LOCS}.items()
}


class TextProcessor:
    @staticmethod
    def normalize(text: str) -> str:
        if not text:
            return ""
        return CLEAN_PATTERN.sub("", text.lower())

    @classmethod
    def parse_message(cls, raw_text: str) -> Dict[str, Any]:
        """
        Parses incoming text feeds against combined Russian and Ukrainian patterns,
        returning static invariant tracking keys to downstream services.
        """
        normalized_text = cls.normalize(raw_text)
        matched_categories: Set[str] = set()
        matched_locations: Set[str] = set()

        if not normalized_text:
            return {"categories": matched_categories, "locations": matched_locations}

        # Scan text against compiled category rules
        for cat_name, pattern in COMPILED_CATEGORIES.items():
            if pattern.search(normalized_text):
                matched_categories.add(cat_name)

        # Scan text against bilingual location variations mapped to exact invariant keys
        for loc_key, pattern in COMPILED_LOCATIONS.items():
            if pattern.search(normalized_text):
                matched_locations.add(loc_key)

        return {
            "categories": matched_categories,
            "locations": matched_locations
        }
```

---

## FILE: alert_bot_project\core_shared\__init__.py
```python

```

---

## FILE: alert_bot_project\database\crud.py
```python
from datetime import datetime, timezone
from typing import Sequence, Optional, List, Set
from sqlalchemy import select, delete, or_, and_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from alert_bot_project.database.models import UserSettings, UserTrigger


async def get_or_create_user(session: AsyncSession, user_id: int) -> UserSettings:
    """Retrieves user settings or populates default layout entries via atomic Upsert."""
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        return user

    insert_stmt = (
        insert(UserSettings)
        .values(user_id=user_id, potvory=["Мопеди", "Ракети"])
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    await session.execute(insert_stmt)
    await session.flush()

    result = await session.execute(stmt)
    return result.scalar_one()


async def add_user_trigger(session: AsyncSession, user_id: int, trigger_word: str) -> bool:
    """Appends explicit keyword search parameter linked to target user identifier mapping."""
    stmt = (
        insert(UserTrigger)
        .values(user_id=user_id, trigger_word=trigger_word)
        .on_conflict_do_nothing(index_elements=["user_id", "trigger_word"])
    )
    res = await session.execute(stmt)
    return res.rowcount > 0


async def remove_user_trigger(session: AsyncSession, user_id: int, trigger_word: str) -> None:
    """Removes a specific granular custom tracking phrase from database tables."""
    stmt = delete(UserTrigger).where(
        UserTrigger.user_id == user_id,
        UserTrigger.trigger_word == trigger_word
    )
    await session.execute(stmt)


async def update_user_potvory(session: AsyncSession, user_id: int, potvory_list: List[str]) -> None:
    """Updates active categories lists mapping tracking parameters."""
    user = await get_or_create_user(session, user_id)
    user.potvory = potvory_list


async def update_user_mute(session: AsyncSession, user_id: int, muted_until: Optional[datetime]) -> None:
    """Updates user silence duration ceiling threshold limits parameters."""
    user = await get_or_create_user(session, user_id)
    user.muted_until = muted_until


async def get_users_by_trigger_and_category(
        session: AsyncSession,
        location_keys: Set[str],
        category_names: Set[str],
        phrase_candidates: List[str],
        all_static_keys: List[str]
) -> Sequence[UserSettings]:
    """Fetches targeted users using fully indexed queries with strict AND intersection filters."""
    now = datetime.now(timezone.utc)
    base_conditions = or_(UserSettings.muted_until == None, UserSettings.muted_until < now)

    match_conditions = []

    if phrase_candidates:
        match_conditions.append(
            and_(
                UserTrigger.trigger_word.in_(phrase_candidates),
                UserTrigger.trigger_word.not_in(all_static_keys)
            )
        )

    if location_keys and category_names:
        match_conditions.append(
            and_(
                UserTrigger.trigger_word.in_(list(location_keys)),
                UserSettings.potvory.overlap(list(category_names))
            )
        )

    if not match_conditions:
        return []

    stmt = (
        select(UserSettings)
        .join(UserTrigger, UserTrigger.user_id == UserSettings.user_id)
        .where(and_(base_conditions, or_(*match_conditions)))
    )

    result = await session.execute(stmt)
    return result.scalars().unique().all()
```

---

## FILE: alert_bot_project\database\engine.py
```python
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from alert_bot_project.core_shared.config import config

# Production-grade async engine configuration targeting Supabase instance
# Relies on host-provided system certificates natively or direct standard connection topologies
engine = create_async_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,  # Probes standard connectivity status checks before executing calls
    pool_size=10,        # Default persistent base limits allocation sizes
    max_overflow=20,     # Spike connection boundaries ceiling limit configurations
    echo=False
)

# Shared factory generating isolated state transaction parameters
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False  # Crucial safety parameter handling long-lived asynchronous tasks
)


async def get_db_session() -> AsyncSession:
    """Asynchronous context lifecycle operational factory iterator dependency inject."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

---

## FILE: alert_bot_project\database\migration.py
```python
import logging
from sqlalchemy import update, select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from alert_bot_project.database.models import UserTrigger

logger = logging.getLogger("database.migration")

MIGRATION_MAP = {
    "город": "city", "центр": "center", "черемушки": "cheremushki", "порт": "port",
    "молдованка": "moldovanka", "бугаевка": "bugaevka", "слободка": "slobodka",
    "таирово": "tairovo", "совиньон": "sovignon", "ланжерон": "lanzheron",
    "поселок": "kotovskogo", "поскот": "kotovskogo", "южный": "yuzhny_dist",
    "фонтанка": "fontanka", "пересыпь": "peresyp", "аркадия": "arkadia", "берег": "coast",
    "усатово": "usatovo", "южное": "yuzhne", "беляевк": "belyaevka", "овидиополь": "ovidiopol",
    "черноморск": "chernomorsk", "черноморка": "chernomorka", "новые беляр": "novi_belyari",
    "рени": "reni", "измаил": "izmail", "татарбунар": "tatarbunary", "березовк": "berezovka",
    "вилково": "vilkovo", "авангард": "avangard", "лиманк": "limanka", "заток": "zatoka",
    "белгород": "belgorod", "теплодар": "teplodar", "доброслав": "dobroslav", "тузлы": "tuzly"
}


async def run_legacy_keys_migration(session: AsyncSession):
    """Executes atomic batch migration for legacy location keys."""
    async with session.begin():
        stmt_check = select(UserTrigger).where(UserTrigger.trigger_word.in_(list(MIGRATION_MAP.keys())))
        res = await session.execute(stmt_check)
        legacy_entries = res.scalars().all()

        if not legacy_entries:
            logger.info("No legacy keys found.")
            return

        for entry in legacy_entries:
            new_key = MIGRATION_MAP.get(entry.trigger_word)
            try:
                # Attempt to update to the new invariant key
                stmt_update = update(UserTrigger).where(
                    UserTrigger.user_id == entry.user_id,
                    UserTrigger.trigger_word == entry.trigger_word
                ).values(trigger_word=new_key)
                await session.execute(stmt_update)
            except IntegrityError:
                # Key already exists: remove old one
                await session.execute(delete(UserTrigger).where(
                    UserTrigger.user_id == entry.user_id,
                    UserTrigger.trigger_word == entry.trigger_word
                ))
    logger.info("Migration finalized.")
```

---

## FILE: alert_bot_project\database\models.py
```python
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserTrigger(Base):
    """Stores verified invariant location keys and multi-word custom phrases."""
    __tablename__ = "user_triggers"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_settings.user_id", ondelete="CASCADE"),
        primary_key=True
    )
    trigger_word: Mapped[str] = mapped_column(String(50), primary_key=True)

    user_setting: Mapped["UserSettings"] = relationship(back_populates="triggers_rel")


class UserSettings(Base):
    """Core user settings schema mapping active categories and silencing rules."""
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    # Fix: Resolved array declaration syntax anomaly using explicit SQL expressions cast mapping
    potvory: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        server_default=text("ARRAY['Мопеди', 'Ракети']::VARCHAR[]")
    )

    muted_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    triggers_rel: Mapped[List[UserTrigger]] = relationship(
        back_populates="user_setting",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    @property
    def triggers_set(self) -> set[str]:
        return {t.trigger_word for t in self.triggers_rel}
```

---

## FILE: alert_bot_project\database\__init__.py
```python

```

---

## FILE: alert_bot_project\scraper\main.py
```python
import asyncio
import logging
import signal
import sys
from pyrogram import Client, filters
from pyrogram.types import Message

from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.scraper.publisher import RedisPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("scraper.main")

# Dedicated session storage directory configured for mounting host Docker Volumes
SESSION_DIR = "/data/session"

app = Client(
    name="twink_account",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    workdir=SESSION_DIR
)

publisher = RedisPublisher()
shutdown_event = asyncio.Event()


@app.on_message(filters.chat(config.GROUP_ID) & (filters.text | filters.caption))
async def handle_channel_post(client: Client, message: Message):
    """Intercepts broadcast events and safely structures them to transient stream pipelines."""
    raw_text = message.text or message.caption
    if not raw_text:
        return

    logger.info("Captured raw source payload feed ID: %s", message.id)

    alert_payload = AlertMessage(
        message_id=message.id,
        chat_id=message.chat.id,
        raw_text=raw_text
    )

    # Wrap the publication invocation inside defensive boundaries
    try:
        await publisher.publish_message(alert_payload.to_json())
    except Exception as exc:
        logger.error("Failed downstream message transmission pipeline: %s", exc)


async def stop_services():
    """Handles orchestration shutdown gracefully to protect session persistence mapping layers."""
    logger.info("Initiating graceful teardown protocol stack...")
    try:
        await app.stop()
        logger.info("Pyrogram listener runtime stopped safely.")
    except Exception as e:
        logger.error("Error destroying engine operational worker: %s", e)

    try:
        await publisher.close()
        logger.info("Redis link destroyed safely.")
    except Exception as e:
        logger.error("Error winding down stream publisher interface: %s", e)

    shutdown_event.set()


def setup_signal_handlers():
    """Configures system operational signals intercepts."""
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(stop_services()))
    except NotImplementedError:
        # Graceful fallback handler support for edge platform execution constraints
        pass


async def main():
    setup_signal_handlers()
    await publisher.connect()

    logger.info("Starting Pyrogram client infrastructure tracking layer...")
    await app.start()
    logger.info("Scraper background subsystem engine online.")

    await shutdown_event.wait()
    logger.info("Subsystem execution terminated.")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## FILE: alert_bot_project\scraper\publisher.py
```python
import logging
from typing import Optional
from redis.asyncio import Redis
from alert_bot_project.core_shared.config import config

logger = logging.getLogger("scraper.publisher")


class RedisPublisher:
    def __init__(self):
        self.redis_url = config.REDIS_URL
        self.stream_name = "alerts_stream"
        self._redis: Optional[Redis] = None

    async def connect(self):
        if not self._redis:
            self._redis = Redis.from_url(self.redis_url, decode_responses=True)
            logger.info("🔌 Подключение к Redis Streams установлено")

    async def publish_message(self, json_data: str):
        """Отправка в персистентный Redis Stream с ограничением длины (чтобы не забить память)"""
        if not self._redis:
            await self.connect()

        try:
            # 🔥 Principal fix: XADD вместо PUBLISH. maxlen=10000 обрезает старые данные.
            msg_id = await self._redis.xadd(self.stream_name, {"payload": json_data}, maxlen=10000)
            logger.info(f"📨 Сообщение записано в Stream (ID: {msg_id})")
        except Exception as e:
            logger.error(f"❌ Ошибка записи в Redis: {e}", exc_info=True)

    async def close(self):
        if self._redis:
            await self._redis.close()
```

---

## FILE: alert_bot_project\scraper\__init__.py
```python

```

---

## FILE: alert_bot_project\services\user_service.py
```python
import logging
from datetime import datetime
from typing import Optional, List, Set
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from alert_bot_project.core_shared.constants import MAX_CUSTOM_TRIGGERS, ODESA_LOCS, OUTSIDE_LOCS
from alert_bot_project.database.crud import (
    get_or_create_user, add_user_trigger, remove_user_trigger,
    update_user_potvory, update_user_mute
)

logger = logging.getLogger("services.user_service")


class UserService:
    """
    Fix: Completely stripped out session control keywords (begin/commit) to conform to the Unit of Work pattern.
    Transactions are now explicitly owned by calling middleware/handler contexts.
    """

    def __init__(self, db_session: AsyncSession, redis_client: Redis):
        self.session = db_session
        self.redis = redis_client

    async def toggle_location(self, user_id: int, location_key: str) -> tuple[bool, str]:
        user = await get_or_create_user(self.session, user_id)

        if location_key in user.triggers_set:
            await remove_user_trigger(self.session, user_id, location_key)
            return False, "Локацію видалено з моніторингу"
        else:
            await add_user_trigger(self.session, user_id, location_key)
            return True, "Локацію додано до моніторингу"

    async def add_custom_trigger(self, user_id: int, trigger_word: str) -> tuple[bool, str]:
        """Fix: Counts strictly non-static keywords using unified service layer validation schemas."""
        user = await get_or_create_user(self.session, user_id)

        static_keys = set(ODESA_LOCS.keys()) | set(OUTSIDE_LOCS.keys())
        custom_count = len([t for t in user.triggers_set if t not in static_keys])

        if custom_count >= MAX_CUSTOM_TRIGGERS:
            return False, "🚫 Ви вже досягли ліміту у 5 кастомних локацій. Видаліть старі для додавання нових."

        success = await add_user_trigger(self.session, user_id, trigger_word)
        if success:
            await self.redis.sadd("has_custom_triggers", str(user_id))
            return True, "Локацію додано"

        return False, "⚠️ Не вдалося зберегти кастомну локацію."

    async def delete_custom_trigger(self, user_id: int, trigger_word: str) -> tuple[bool, str]:
        await remove_user_trigger(self.session, user_id, trigger_word)

        user = await get_or_create_user(self.session, user_id)
        static_keys = set(ODESA_LOCS.keys()) | set(OUTSIDE_LOCS.keys())
        remaining_custom = [t for t in user.triggers_set if t not in static_keys]

        if not remaining_custom:
            await self.redis.srem("has_custom_triggers", str(user_id))

        return True, "Локацію видалено"

    async def set_threat_categories(self, user_id: int, categories: List[str]) -> str:
        await update_user_potvory(self.session, user_id, categories)
        return "Налаштування категорій повітряних загроз оновлено"

    async def apply_mute_timeout(self, user_id: int, expiration: Optional[datetime], message_text: str) -> str:
        await update_user_mute(self.session, user_id, expiration)
        return message_text
```

---

## FILE: alert_bot_project\services\__init__.py
```python

```

---

## FILE: alert_bot_project\worker\broadcaster.py
```python
import asyncio
import logging
import json
import time
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError
from redis.asyncio import Redis
from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.constants import (
    ALERT_FIRST, ALERT_SECOND, ALERT_THIRD,
    ALERT_DELAY_1, ALERT_DELAY_2
)

logger = logging.getLogger("worker.broadcaster")
BACKPRESSURE_TIMEOUT = 5.0


class Broadcaster:
    def __init__(self, bot: Bot, redis_client: Redis, max_tasks: int = 1000):
        self.bot = bot
        self.redis = redis_client
        self.rate_limiter = asyncio.Semaphore(25)
        self.delayed_queue_key = "delayed_alerts_queue"
        self.background_tasks: set[asyncio.Task] = set()
        self.max_bg_tasks = max_tasks

    async def send_single_message(self, chat_id: int, text: str, reply_markup=None,
                                  disable_notification: bool = False) -> bool:
        total_time_waited = 0
        max_wait_seconds = config.TELEGRAM_MAX_RETRY_SECONDS

        while total_time_waited < max_wait_seconds:
            try:
                async with self.rate_limiter:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                        disable_notification=disable_notification
                    )
                    await asyncio.sleep(0.04)
                    return True
            except TelegramRetryAfter as e:
                wait_duration = min(e.retry_after, max_wait_seconds - total_time_waited)
                logger.warning("Telegram API 429 caught. Waiting %s s on destination %s", wait_duration, chat_id)
                await asyncio.sleep(wait_duration)
                total_time_waited += wait_duration
            except TelegramAPIError as e:
                logger.error("Telegram API exception encountered for peer %s: %s", chat_id, e)
                return False
            except Exception as e:
                logger.error("Transport error during message routing to %s: %s", chat_id, e)
                return False

        logger.error("Canceled transmission stack targeting %s after hitting timeout window limits.", chat_id)
        return False

    def fire_and_forget_message(self, chat_id: int, text: str, reply_markup=None, disable_notification: bool = False):
        """Fix: Synchronous spawner wrapper creating un-awaited background tasks cleanly without thread blocks."""
        if len(self.background_tasks) >= self.max_bg_tasks:
            logger.error("Local background task pool saturated (%d tasks). Shedding load for user %s",
                         len(self.background_tasks), chat_id)
            return

        task = asyncio.create_task(self.send_single_message(chat_id, text, reply_markup, disable_notification))
        task.set_name(f"msg_{chat_id}_{int(time.time())}")
        self.background_tasks.add(task)

        def cleanup_callback(completed_future: asyncio.Task):
            self.background_tasks.discard(completed_future)
            if completed_future.exception():
                logger.error("Background text notification failed for user peer %s: %s", chat_id,
                             completed_future.exception())

        task.add_done_callback(cleanup_callback)

    async def _execute_scheduling(self, chat_id: int, disable_notification: bool):
        try:
            now_unix = int(time.time())
            task_step_2 = {"chat_id": chat_id, "step": 2, "text": ALERT_SECOND, "silent": disable_notification}
            task_step_3 = {"chat_id": chat_id, "step": 3, "text": ALERT_THIRD, "silent": disable_notification}

            await self.redis.zadd(self.delayed_queue_key, {
                json.dumps(task_step_2): now_unix + ALERT_DELAY_1,
                json.dumps(task_step_3): now_unix + ALERT_DELAY_1 + ALERT_DELAY_2
            })
        except Exception as e:
            logger.error("Failed to write delayed alerts to Redis for user %s: %s", chat_id, e)

    def schedule_delayed_alerts(self, chat_id: int, disable_notification: bool):
        task = asyncio.create_task(self._execute_scheduling(chat_id, disable_notification))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def process_delayed_alerts(self):
        while True:
            try:
                now_unix = int(time.time())
                tasks = await self.redis.zpopmin(self.delayed_queue_key, count=50)

                if not tasks:
                    await asyncio.sleep(1)
                    continue

                requeue_buffer = {}
                for task_raw, score in tasks:
                    try:
                        if score > now_unix:
                            requeue_buffer[task_raw] = score
                            continue

                        task_data = json.loads(task_raw)
                        user_id = task_data["chat_id"]

                        if await self.redis.exists(f"user_mute:{user_id}"):
                            continue

                        is_silent = task_data.get("silent", False)
                        self.fire_and_forget_message(
                            chat_id=user_id,
                            text=task_data["text"],
                            reply_markup=None,
                            disable_notification=is_silent
                        )
                    except Exception as inner_err:
                        logger.error("Error processing individual popped delayed alert item: %s", inner_err)

                if requeue_buffer:
                    await self.redis.zadd(self.delayed_queue_key, requeue_buffer)

            except Exception as exc:
                logger.error("Catastrophic error in scheduled alert daemon loop: %s", exc, exc_info=True)
                await asyncio.sleep(2)
```

---

## FILE: alert_bot_project\worker\main.py
```python
import asyncio
import logging
import signal
import time
import json
import hashlib
import random
import itertools
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.logging_config import setup_logging
from alert_bot_project.core_shared.schemas import AlertMessage
from alert_bot_project.core_shared.text_processor import TextProcessor
from alert_bot_project.core_shared.constants import ALERT_FIRST, KYIV_TZ, ODESA_LOCS, OUTSIDE_LOCS
from alert_bot_project.database.engine import AsyncSessionLocal
from alert_bot_project.database.crud import get_users_by_trigger_and_category
from alert_bot_project.worker.broadcaster import Broadcaster
from alert_bot_project.bot.keyboards.builders import build_acknowledge_keyboard

setup_logging("worker")
logger = logging.getLogger("worker.main")

LOCAL_TZ = ZoneInfo(KYIV_TZ)
STREAM_NAME = "alerts_stream"
GROUP_NAME = "workers_group"
CONSUMER_NAME = "worker_node_primary"

is_running = True


def is_quiet_hours_active() -> bool:
    now = datetime.now(LOCAL_TZ).time()
    start = datetime.strptime(f"{config.NIGHT_START_HOUR}:00", "%H:%M").time()
    end = datetime.strptime(f"{config.NIGHT_END_HOUR}:00", "%H:%M").time()
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end


def generate_phrase_candidates_generator(words_list: list[str], max_phrase_length: int = 4):
    for i in range(len(words_list)):
        for j in range(1, min(max_phrase_length + 1, len(words_list) - i + 1)):
            yield " ".join(words_list[i:i + j])


async def init_redis_consumer_group(redis_client: Redis):
    try:
        if await redis_client.exists(STREAM_NAME):
            groups = await redis_client.xinfo_groups(STREAM_NAME)
            if any(g['name'] == GROUP_NAME for g in groups):
                return
        await redis_client.xgroup_create(name=STREAM_NAME, groupname=GROUP_NAME, id="$", mkstream=True)
        logger.info(f"Persistent Redis Consumer Group established: {GROUP_NAME}")
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise e


async def monitor_dlq_backlog(redis_client: Redis):
    try:
        if await redis_client.exists("dead_letter_queue"):
            startup_depth = await redis_client.xlen("dead_letter_queue")
            if startup_depth > 0:
                logger.error("Initial absolute state tracker check: dead_letter_queue holds %s entries.", startup_depth)
    except Exception as e:
        logger.error(f"Failed pulling absolute DLQ depth parameters: {e}")

    while is_running:
        try:
            if await redis_client.exists("dead_letter_queue"):
                dlq_depth = await redis_client.xlen("dead_letter_queue")
                prev_depth_raw = await redis_client.get("dlq:prev_depth")
                prev_depth = int(prev_depth_raw or 0)

                if dlq_depth != prev_depth:
                    logger.error("DLQ depth transformation detected: %s -> %s entries present.", prev_depth, dlq_depth)
                    await redis_client.set("dlq:prev_depth", str(dlq_depth))
        except Exception as e:
            logger.error(f"Error checking DLQ logs limits depth metrics: {e}")
        await asyncio.sleep(60)


async def auto_claim_pending_tasks(redis_client: Redis, broadcaster: Broadcaster):
    while is_running:
        try:
            await asyncio.sleep(30 + random.uniform(0.0, 10.0))
            res = await redis_client.xautoclaim(
                name=STREAM_NAME, groupname=GROUP_NAME, consumername=CONSUMER_NAME,
                min_idle_time=60000, start_id="0-0", count=10
            )
            if res and res[1]:
                for msg_id, payload in res[1]:
                    raw_json = payload.get("payload")
                    if not raw_json:
                        await redis_client.xack(STREAM_NAME, GROUP_NAME, msg_id)
                        continue

                    try:
                        alert_data = AlertMessage.from_json(raw_json)
                        dedup_key = f"processed_msg:{alert_data.message_id}"
                        if await redis_client.get(dedup_key):
                            await redis_client.xack(STREAM_NAME, GROUP_NAME, msg_id)
                            continue
                    except Exception:
                        pass

                    await process_single_stream_payload(msg_id, raw_json, redis_client, broadcaster)
        except Exception as e:
            logger.error("Exception occurred inside PEL XAUTOCLAIM tracking loop: %s", e)


async def process_single_stream_payload(redis_msg_id: str, raw_json: str, redis_client: Redis, broadcaster: Broadcaster):
    try:
        alert_data = AlertMessage.from_json(raw_json)
    except Exception as err:
        logger.warning("Dropped corrupted structural input stream item: %s", err)
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    if (datetime.now(timezone.utc) - alert_data.timestamp).total_seconds() > 600:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    dedup_key = f"processed_msg:{alert_data.message_id}"
    analysis = TextProcessor.parse_message(alert_data.raw_text)
    normalized_text = TextProcessor.normalize(alert_data.raw_text)

    # Fix: Corrected conditional check to evaluate global custom trigger presence cleanly per-user scale context paths
    has_custom_triggers = await redis_client.exists("has_custom_triggers") > 0

    if not analysis["categories"] and not analysis["locations"] and not has_custom_triggers:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    phrase_candidates = []
    if has_custom_triggers:
        words = normalized_text.split()
        phrase_candidates = list(itertools.islice(generate_phrase_candidates_generator(words, max_phrase_length=4), 100))

    sorted_locs = sorted(list(analysis["locations"]))
    sorted_cats = sorted(list(analysis["categories"]))

    hash_payload = f"locs:{sorted_locs}|cats:{sorted_cats}"
    checksum = hashlib.md5(hash_payload.encode("utf-8")).hexdigest()

    cache_version = await redis_client.get("cache:generation_version") or "0"
    cache_hash_key = f"cache:alert_targets_v{cache_version}:{checksum}"

    cached_targets = await redis_client.get(cache_hash_key)

    if cached_targets:
        user_ids_list = json.loads(cached_targets)
    else:
        all_static_keys = list(ODESA_LOCS.keys()) + list(OUTSIDE_LOCS.keys())
        async with AsyncSessionLocal() as session:
            try:
                target_users = await get_users_by_trigger_and_category(
                    session=session, location_keys=analysis["locations"],
                    category_names=analysis["categories"], phrase_candidates=phrase_candidates,
                    all_static_keys=all_static_keys
                )
                user_ids_list = [u.user_id for u in target_users]

                if not user_ids_list:
                    await redis_client.setex(cache_hash_key, 30, json.dumps([]))
                else:
                    await redis_client.setex(cache_hash_key, 30, json.dumps(user_ids_list))
            except Exception as db_err:
                retry_key = f"retry_count:{redis_msg_id}"
                current_retries = await redis_client.incr(retry_key)
                await redis_client.expire(retry_key, 3600)

                if current_retries > 5:
                    logger.error("Task message ID %s dropped after exceeding retry limit. Relocating to DLQ.", redis_msg_id)
                    await redis_client.xadd("dead_letter_queue", {"payload": raw_json, "error": str(db_err)}, maxlen=10000)
                    await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
                    await redis_client.delete(retry_key)
                else:
                    logger.warning("Database transient exception recorded on iteration %s/5. Leaving task inside PEL loop.", current_retries)
                return

    if not user_ids_list:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    is_fresh_lock = await redis_client.set(dedup_key, "1", nx=True, ex=300)
    if not is_fresh_lock:
        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        return

    logger.info("Fresh broadcast alert payload verified. Forwarding dispatch streams downpipes safely.")
    quiet_mode = is_quiet_hours_active()
    alert_markup = build_acknowledge_keyboard()
    display_text = f"{ALERT_FIRST}\n\n🌙 <i>[Сповіщення надіслано у тихому режимі нічного часу]</i>" if quiet_mode else ALERT_FIRST

    # Fix: Resolved fatal coroutine leak by calling synchronous fire_and_forget_message cleanly without unawaited tokens
    for u_id in user_ids_list:
        broadcaster.fire_and_forget_message(u_id, display_text, reply_markup=alert_markup, disable_notification=quiet_mode)
        broadcaster.schedule_delayed_alerts(u_id, disable_notification=quiet_mode)

    await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
    await redis_client.delete(f"retry_count:{redis_msg_id}")


async def main():
    global is_running
    logger.info("Production background alert stream analysis subsystem initialization...")

    bot = Bot(token=config.BOT_TOKEN)
    redis_client = Redis.from_url(config.REDIS_URL, decode_responses=True)

    await init_redis_consumer_group(redis_client)
    broadcaster = Broadcaster(bot, redis_client)

    delayed_daemon = asyncio.create_task(broadcaster.process_delayed_alerts())
    recovery_daemon = asyncio.create_task(auto_claim_pending_tasks(redis_client, broadcaster))
    dlq_daemon = asyncio.create_task(monitor_dlq_backlog(redis_client))

    def shutdown_handler():
        global is_running
        is_running = False

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown_handler)
    except NotImplementedError:
        logger.warning("System platform environment restricts native direct POSIX signal handlers assignments.")

    logger.info("Clearing outstanding internal consumer PEL backlogs...")
    backlog_data = await redis_client.xreadgroup(groupname=GROUP_NAME, consumername=CONSUMER_NAME, streams={STREAM_NAME: "0"}, count=100, block=10)
    if backlog_data:
        for stream, messages in backlog_data:
            for redis_msg_id, payload in messages:
                raw_json = payload.get("payload")
                if raw_json:
                    await process_single_stream_payload(redis_msg_id, raw_json, redis_client, broadcaster)

    logger.info("Worker processing loop listening for target stream pipelines...")
    while is_running:
        try:
            streams_data = await redis_client.xreadgroup(groupname=GROUP_NAME, consumername=CONSUMER_NAME, streams={STREAM_NAME: ">"}, count=1, block=1000)
            if not streams_data:
                continue
            for stream, messages in streams_data:
                for redis_msg_id, payload in messages:
                    raw_json = payload.get("payload")
                    if raw_json:
                        await process_single_stream_payload(redis_msg_id, raw_json, redis_client, broadcaster)
                    else:
                        await redis_client.xack(STREAM_NAME, GROUP_NAME, redis_msg_id)
        except Exception as e:
            logger.error("Core engine execution loop error: %s", e, exc_info=True)
            await asyncio.sleep(2)

    delayed_daemon.cancel()
    recovery_daemon.cancel()
    dlq_daemon.cancel()
    await redis_client.close()
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## FILE: alert_bot_project\worker\matcher.py
```python

```

---

## FILE: alert_bot_project\worker\__init__.py
```python

```

---

