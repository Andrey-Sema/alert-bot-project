"""
Інтеграція з офіційним API api.ukrainealarm.com (застосунок «Повітряна тривога»).

Модуль виконує дві задачі:
  1. UkraineAlarmClient — тонкий асинхронний HTTP-клієнт до /api/v3 (aiohttp).
  2. AlarmStatePoller — фоновий демон, що опитує статус тривоги по Одеській
     області та кладе булевий стан у Redis під ключем OFFICIAL_ALARM_KEY.

Воркер читає цей ключ у check_official_air_alarm() і на його підставі
ескалує/послаблює пороги матчингу тексту від юзербота.

Довідка по API (перевірено 2026):
  * Хост:                 https://api.ukrainealarm.com
  * База:                 /api/v3
  * Авторизація:          заголовок  Authorization: <API_KEY>   (БЕЗ префікса Bearer)
  * GET /alerts/status    -> {"lastActionIndex": <int>}  дешева перевірка "чи є зміни"
  * GET /alerts/{regionId}-> [ {..., "activeAlerts":[{"type":"AIR",...}, ...]} ]
  * GET /regions          -> {"states":[{"regionId","regionName", ...}, ...]}
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import aiohttp
from prometheus_client import Gauge
from redis.asyncio import Redis

from alert_bot_project.core_shared.config import config

logger = logging.getLogger("services.ukrainealarm")

# =========================================================================
#  КОНСТАНТИ
# =========================================================================

API_HOST = "https://api.ukrainealarm.com"
API_BASE = f"{API_HOST}/api/v3"

# Ключ у Redis, який читає воркер (worker.main.check_official_air_alarm)
OFFICIAL_ALARM_KEY = "official_alarm_status:odesa"

# Типи тривог, які вважаємо «повітряними» для цього бота.
# Порожній set => будь-яка активна тривога рахується за спрацювання.
AIR_ALERT_TYPES: frozenset[str] = frozenset({"AIR"})

# Prometheus-метрики (реєструються один раз при імпорті модуля)
OFFICIAL_ALARM_STATE = Gauge(
    "official_alarm_active",
    "Official ukrainealarm.com air-raid state for the monitored oblast (1=active, 0=clear)",
)
UKRAINEALARM_POLL_ERRORS = Gauge(
    "ukrainealarm_poll_last_ok",
    "1 if the last ukrainealarm poll succeeded, 0 if it failed",
)


class UkraineAlarmError(RuntimeError):
    """Базова помилка транспорту/протоколу ukrainealarm API."""


class UkraineAlarmClient:
    """
    Асинхронний клієнт api.ukrainealarm.com.

    Ключ ніколи не логується. Сесія aiohttp створюється лениво й перевикористовується;
    обов'язково викликати await client.close() під час зупинки.
    """

    def __init__(
        self,
        api_key: str,
        *,
        timeout_total: float = 8.0,
        timeout_connect: float = 3.0,
    ) -> None:
        if not api_key:
            raise UkraineAlarmError("UKRAINEALARM_API_KEY не задано у конфігурації")
        # Ключ тримаємо приватним і не кладемо у __repr__/логи
        self.__api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout_total, connect=timeout_connect)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers={
                    # Сирий ключ у заголовку — так вимагає ukrainealarm (без Bearer)
                    "Authorization": self.__api_key,
                    "Accept": "application/json",
                },
                # SSRF-захист: жорстко фіксуємо цільовий хост, base_url не дає піти в інший домен
                base_url=API_HOST,
            )
        return self._session

    async def _get(self, path: str) -> Any:
        """
        Виконує GET до /api/v3<path>. Кидає UkraineAlarmError на HTTP != 200,
        окремо пробрасує aiohttp.ClientResponseError(status=429) для бекофу вгору.
        """
        session = await self._ensure_session()
        url = f"/api/v3{path}"
        async with session.get(url) as resp:
            if resp.status == 429:
                retry_after = int(resp.headers.get("Retry-After", "5") or "5")
                raise UkraineAlarmError(f"HTTP 429 rate limited, retry-after={retry_after}")
            if resp.status == 401 or resp.status == 403:
                raise UkraineAlarmError(f"HTTP {resp.status}: невірний або відкликаний API-ключ")
            if resp.status != 200:
                body = (await resp.text())[:200]
                raise UkraineAlarmError(f"HTTP {resp.status} on {path}: {body}")
            return await resp.json()

    async def get_status_index(self) -> int:
        """Дешевий лічильник останньої дії. Змінюється лише коли щось реально сталося."""
        data = await self._get("/alerts/status")
        # API інколи віддає {"lastActionIndex": N}
        if isinstance(data, dict):
            return int(data.get("lastActionIndex", data.get("actionIndex", 0)) or 0)
        return 0

    async def get_regions(self) -> list[dict[str, Any]]:
        """Повертає плаский список областей верхнього рівня (states)."""
        data = await self._get("/regions")
        if isinstance(data, dict):
            return list(data.get("states", []))
        if isinstance(data, list):
            return data
        return []

    async def get_region_alerts(self, region_id: str) -> list[dict[str, Any]]:
        """Активні тривоги в межах регіону (для області — включно з громадами)."""
        data = await self._get(f"/alerts/{region_id}")
        if isinstance(data, list):
            return data
        return []

    async def resolve_region_id(self, name_substr: str) -> Optional[str]:
        """
        Знаходить regionId області за підрядком назви (case-insensitive),
        напр. 'одес' -> id Одеської області. Робить код незалежним від
        зашитого числового ID, який теоретично може змінитися на боці API.
        """
        needle = name_substr.strip().lower()
        for state in await self.get_regions():
            name = str(state.get("regionName", "")).lower()
            if needle in name:
                rid = state.get("regionId")
                if rid is not None:
                    return str(rid)
        return None

    @staticmethod
    def is_air_active(region_alerts: list[dict[str, Any]]) -> bool:
        """
        Визначає, чи є активна повітряна тривога у відповіді /alerts/{regionId}.
        Якщо AIR_ALERT_TYPES порожній — рахуємо будь-яку активну тривогу.
        """
        for region in region_alerts:
            for alert in region.get("activeAlerts", []) or []:
                if not AIR_ALERT_TYPES:
                    return True
                if str(alert.get("type", "")).upper() in AIR_ALERT_TYPES:
                    return True
        return False

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None


class AlarmStatePoller:
    """
    Фоновий демон: тримає у Redis актуальний булевий стан офіційної тривоги.

    Оптимізація трафіку: спершу читаємо дешевий /alerts/status; повний запит
    /alerts/{regionId} робимо лише коли lastActionIndex змінився, стан застарів,
    або це перша ітерація. TTL ключа = state_ttl, тож якщо демон впаде — ключ
    протухне, і воркер перейде на failsafe-режим (див. check_official_air_alarm).
    """

    def __init__(
        self,
        redis_client: Redis,
        *,
        api_key: Optional[str] = None,
        region_id: Optional[str] = None,
        region_name: str = "одес",
        poll_interval: float = 15.0,
        state_ttl: int = 90,
    ) -> None:
        self.redis = redis_client
        self.client = UkraineAlarmClient(api_key or getattr(config, "UKRAINEALARM_API_KEY", ""))
        self._region_id = region_id or getattr(config, "UKRAINEALARM_REGION_ID", None)
        self._region_name = region_name
        self._poll_interval = poll_interval
        self._state_ttl = state_ttl

        self._last_index: Optional[int] = None
        self._last_success_ts: float = 0.0
        # Скільки секунд можна не мати зв'язку з API, доки не увімкнемо failsafe
        self._failsafe_after = state_ttl * 2

    async def _resolve_region(self) -> Optional[str]:
        if self._region_id:
            return self._region_id
        rid = await self.client.resolve_region_id(self._region_name)
        if rid:
            self._region_id = rid
            logger.info("Resolved ukrainealarm region '%s' -> id=%s", self._region_name, rid)
        else:
            logger.error("Не вдалося знайти регіон '%s' у /regions", self._region_name)
        return rid

    async def _write_state(self, active: bool) -> None:
        await self.redis.set(OFFICIAL_ALARM_KEY, "1" if active else "0", ex=self._state_ttl)
        OFFICIAL_ALARM_STATE.set(1 if active else 0)
        self._last_success_ts = time.monotonic()

    async def _poll_once(self) -> None:
        region_id = await self._resolve_region()
        if not region_id:
            raise UkraineAlarmError("region_id невідомий, пропускаємо ітерацію")

        index = await self.get_status_index_safe()
        need_full = (
            index is None
            or index != self._last_index
            or (time.monotonic() - self._last_success_ts) >= (self._state_ttl / 2)
        )
        if not need_full:
            # Стан не змінився — просто продовжуємо TTL, щоб ключ не протух
            await self.redis.expire(OFFICIAL_ALARM_KEY, self._state_ttl)
            return

        alerts = await self.client.get_region_alerts(region_id)
        active = UkraineAlarmClient.is_air_active(alerts)
        await self._write_state(active)
        if index is not None:
            self._last_index = index
        logger.info("Official air-alarm for oblast=%s -> active=%s", region_id, active)

    async def get_status_index_safe(self) -> Optional[int]:
        try:
            return await self.client.get_status_index()
        except Exception:
            # /status не критичний: якщо впав — просто зробимо повний запит
            return None

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Головний цикл. Завершується коли виставлено shutdown_event."""
        logger.info("UkraineAlarm poller started (interval=%ss)", self._poll_interval)
        try:
            while not shutdown_event.is_set():
                try:
                    await self._poll_once()
                    UKRAINEALARM_POLL_ERRORS.set(1)
                except UkraineAlarmError as exc:
                    UKRAINEALARM_POLL_ERRORS.set(0)
                    logger.warning("UkraineAlarm poll failed: %s", exc)
                    await self._maybe_failsafe()
                except Exception:
                    UKRAINEALARM_POLL_ERRORS.set(0)
                    logger.exception("Неочікувана помилка опитування ukrainealarm")
                    await self._maybe_failsafe()

                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=self._poll_interval)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.client.close()
            logger.info("UkraineAlarm poller stopped")

    async def _maybe_failsafe(self) -> None:
        """
        Якщо API недоступне довше за поріг — вмикаємо failsafe.
        Для life-safety бота безпечніше «припустити тривогу» (fail-open),
        щоб загрози від юзербота продовжували доходити. Керується конфігом.
        """
        stale_for = time.monotonic() - self._last_success_ts
        if self._last_success_ts and stale_for < self._failsafe_after:
            return  # ще тримаємо останній відомий стан (він у Redis з TTL)
        failsafe_active = bool(getattr(config, "OFFICIAL_ALARM_FAILSAFE", True))
        await self.redis.set(OFFICIAL_ALARM_KEY, "1" if failsafe_active else "0", ex=self._state_ttl)
        OFFICIAL_ALARM_STATE.set(1 if failsafe_active else 0)
        logger.error("UkraineAlarm недоступне %.0fs — failsafe active=%s", stale_for, failsafe_active)