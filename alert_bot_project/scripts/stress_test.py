import asyncio
import argparse
import time
import random
import sys
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from alert_bot_project.core_shared.schemas import AlertMessage

# ============================================================
#  КОНСТАНТЫ И ШАБЛОНЫ
# ============================================================

RAW_TEXT_TEMPLATES = [
    "🚨 ALERT! Air threat detected heading from the sea towards the Port area! Take cover immediately!",
    "Warning: Kalibr cruise missile launches confirmed, vector passing through Suburbs to Center!",
    "Clear sky. No active airborne threats reported across the city perimeter at this time.",
    "⚠️ Active air defense engagements against a high-speed drone near Cheremushki district. Stay in shelters.",
    "Routine update: Road maintenance works ongoing at Kotovskogo district, expect minor traffic delays.",
    "🚨 Ballistic missile threat detected from the south targeting Belgorod-Dnietsrovsky! Immediate shelter required!",
    "Shahed attack drones crossing from Chernomorka towards Tairovo municipal sector!",
    "Official admin briefing: The regional defensive airspace layout is stable and fully operational."
]

STREAM_NAME = "alerts_stream"
GROUP_NAME = "workers_group"

# CI-порог: если скорость впрыска ниже этого значения — джоб падает
CI_MIN_THROUGHPUT_RPS = 500

# Таймаут адаптивного ожидания обработки (секунды)
VERIFY_TIMEOUT_SECONDS = 60

# Интервал опроса лага во время verify-цикла (секунды)
VERIFY_POLL_INTERVAL = 2.0


# ============================================================
#  ПОДКЛЮЧЕНИЕ
# ============================================================

async def build_redis_client(redis_url: str) -> Redis:
    """Создаёт клиент Redis с явной проверкой доступности брокера."""
    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
    except (RedisConnectionError, OSError) as exc:
        print(
            f"\n❌ FATAL: Не удалось подключиться к Redis по адресу: {redis_url}\n"
            f"   Причина: {exc}\n"
            f"   Проверьте, что контейнер redis запущен (docker compose ps) и REDIS_URL задан корректно в .env\n"
        )
        sys.exit(1)
    return client


# ============================================================
#  ФАЗА 1: ИНЪЕКЦИЯ НАГРУЗКИ
# ============================================================

async def inject_load(
    redis_client: Redis,
    group_id: int,
    total_messages: int,
    batch_size: int,
    delay: float,
) -> float:
    """
    Закачивает total_messages сообщений в Redis Stream пакетами через pipeline.
    Возвращает скорость инъекции (сообщений/сек).
    """
    print(f"📦 Batch size: {batch_size} | delay между батчами: {delay}s")
    print(f"🔥 Инъекция {total_messages} payload-ов в {STREAM_NAME}...\n")

    start_time = time.time()

    for i in range(0, total_messages, batch_size):
        pipe = redis_client.pipeline()
        current_batch = min(batch_size, total_messages - i)

        for j in range(current_batch):
            payload = AlertMessage(
                message_id=i + j,
                chat_id=group_id,
                raw_text=random.choice(RAW_TEXT_TEMPLATES),
            )
            pipe.xadd(STREAM_NAME, {"payload": payload.model_dump_json()}, maxlen=10000)

        await pipe.execute()

        progress = min(i + current_batch, total_messages)
        print(f"  → {progress}/{total_messages} сообщений отправлено", end="\r")

        if delay > 0 and (i + batch_size) < total_messages:
            await asyncio.sleep(delay)

    elapsed = time.time() - start_time
    rps = int(total_messages / elapsed) if elapsed > 0 else total_messages

    print(f"\n\n🏁 Инъекция завершена за {elapsed:.2f}s  |  скорость: {rps} msg/s")
    return rps


# ============================================================
#  ФАЗА 2: АДАПТИВНОЕ ОЖИДАНИЕ И ВЕРИФИКАЦИЯ
# ============================================================

async def verify_processing(redis_client: Redis) -> tuple[int, int]:
    """
    Адаптивно ждёт, пока consumer group исчерпает pending-бэклог.

    Вместо жёсткого sleep(15) — цикл с проверкой каждые VERIFY_POLL_INTERVAL сек
    и таймаутом VERIFY_TIMEOUT_SECONDS. Надёжно работает на любом железе.

    Возвращает (dlq_size, pending_backlog) на момент завершения.
    """
    print(f"\n⏳ Ожидание обработки воркерами (таймаут: {VERIFY_TIMEOUT_SECONDS}s)...")
    deadline = time.time() + VERIFY_TIMEOUT_SECONDS

    while time.time() < deadline:
        await asyncio.sleep(VERIFY_POLL_INTERVAL)

        try:
            groups_info = await redis_client.xinfo_groups(STREAM_NAME)
            pending = sum(
                g.get("pending", 0)
                for g in groups_info
                if g.get("name") == GROUP_NAME
            )
        except Exception:
            pending = -1  # Стрим ещё не создан или временная ошибка

        elapsed_wait = VERIFY_TIMEOUT_SECONDS - (deadline - time.time())
        print(f"  [{elapsed_wait:.0f}s] pending в {GROUP_NAME}: {pending}", end="\r")

        if pending == 0:
            print(f"\n  ✅ Бэклог исчерпан за ~{elapsed_wait:.0f}s")
            break
    else:
        print(f"\n  ⚠️  Таймаут {VERIFY_TIMEOUT_SECONDS}s истёк — воркеры не успели обработать очередь.")

    # Финальный замер DLQ
    dlq_size = 0
    if await redis_client.exists("dead_letter_queue"):
        dlq_size = await redis_client.xlen("dead_letter_queue")

    try:
        groups_info = await redis_client.xinfo_groups(STREAM_NAME)
        pending_backlog = sum(
            g.get("pending", 0)
            for g in groups_info
            if g.get("name") == GROUP_NAME
        )
    except Exception:
        pending_backlog = 0

    return dlq_size, pending_backlog


# ============================================================
#  ОТЧЁТ И CI-ВЫХОД
# ============================================================

def print_report(rps: int, dlq_size: int, pending_backlog: int, ci_mode: bool) -> int:
    """Печатает итоговый отчёт. Возвращает exit code (0 = ok, 1 = fail)."""
    print("\n📊 PERFORMANCE & INTEGRITY REPORT")
    print("=" * 52)
    print(f"  Throughput (inject):            {rps} msg/s")
    print(f"  CI minimum threshold:           {CI_MIN_THROUGHPUT_RPS} msg/s")
    print(f"  Dead Letter Queue depth:        {dlq_size}")
    print(f"  Consumer group pending lag:     {pending_backlog}")
    print("=" * 52)

    failures = []

    if ci_mode and rps < CI_MIN_THROUGHPUT_RPS:
        failures.append(
            f"Throughput {rps} msg/s ниже порога {CI_MIN_THROUGHPUT_RPS} msg/s"
        )

    if dlq_size > 0:
        failures.append(
            f"DLQ содержит {dlq_size} задач — есть необработанные/битые сообщения"
        )

    if pending_backlog > 0:
        failures.append(
            f"Consumer group lag {pending_backlog} — воркеры не успели обработать очередь"
        )

    if failures:
        print("\n❌ FAILURES:")
        for f in failures:
            print(f"   • {f}")
        return 1

    print("\n✅ Система выдержала нагрузку без ошибок.")
    return 0


# ============================================================
#  ТОЧКА ВХОДА
# ============================================================

async def run_load_benchmark(
    redis_url: str,
    group_id: int,
    total_messages: int = 2000,
    batch_size: int | None = None,
    delay: float = 0.0,
    verify: bool = True,
    ci_mode: bool = False,
) -> int:
    """
    Полный цикл нагрузочного теста.
    Возвращает exit code: 0 = успех, 1 = провал.
    """
    print("🚀 OdesaAlert — Production Load Benchmark")
    print(f"   Redis: {redis_url}")
    print(f"   Messages: {total_messages} | CI mode: {ci_mode}\n")

    redis_client = await build_redis_client(redis_url)

    if batch_size is None:
        batch_size = max(100, total_messages // 20)

    try:
        rps = await inject_load(redis_client, group_id, total_messages, batch_size, delay)

        dlq_size, pending_backlog = 0, 0
        if verify:
            dlq_size, pending_backlog = await verify_processing(redis_client)

        return print_report(rps, dlq_size, pending_backlog, ci_mode)

    finally:
        await redis_client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OdesaAlert stress test — нагрузочный тест Redis Streams pipeline"
    )
    parser.add_argument("--redis-url", default=None, help="Redis URL (по умолчанию из config)")
    parser.add_argument("--group-id", type=int, default=None, help="Telegram GROUP_ID (по умолчанию из config)")
    parser.add_argument("--messages", type=int, default=2000, help="Количество сообщений (default: 2000)")
    parser.add_argument("--batch-size", type=int, default=None, help="Размер батча (default: auto)")
    parser.add_argument("--delay", type=float, default=0.0, help="Задержка между батчами в сек (default: 0)")
    parser.add_argument("--no-verify", action="store_true", help="Пропустить фазу верификации")
    parser.add_argument("--ci", action="store_true", help="CI-режим: упасть если throughput ниже порога")
    args = parser.parse_args()

    # Импортируем config только здесь — не на уровне модуля
    from alert_bot_project.core_shared.config import config

    redis_url = args.redis_url or config.REDIS_URL
    group_id = args.group_id or config.GROUP_ID

    exit_code = asyncio.run(
        run_load_benchmark(
            redis_url=redis_url,
            group_id=group_id,
            total_messages=args.messages,
            batch_size=args.batch_size,
            delay=args.delay,
            verify=not args.no_verify,
            ci_mode=args.ci,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()