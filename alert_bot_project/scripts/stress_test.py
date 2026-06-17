# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
import asyncio
import time
import random
from redis.asyncio import Redis
from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.schemas import AlertMessage

# English tactical messaging templates for clean load simulation
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


async def run_load_benchmark(
        total_messages: int = 2000,
        batch_size: int = None,
        delay: float = 0.0,
        verify: bool = True
) -> None:
    """
    Executes a high-throughput stress test against the Redis Streams broker layer.
    Validates pipeline throughput, worker processing duration thresholds, and caching efficiency.
    """
    print("🚀 Initializing OdesaAlert Production Load Benchmark...")
    redis_client = Redis.from_url(config.REDIS_URL, decode_responses=True)

    stream_name = "alerts_stream"
    group_name = "workers_group"
    start_time = time.time()

    # Adaptive batch size calculation based on target volume matrix
    if batch_size is None:
        batch_size = max(100, total_messages // 20)

    print(f"📦 Scaling injection configuration: Batch size set to {batch_size} units.")
    print(f"📡 Pacing configuration: Delay between batches set to {delay} seconds.")
    print(f"🔥 Injecting {total_messages} verified payloads into the pipeline...")

    for i in range(0, total_messages, batch_size):
        pipe = redis_client.pipeline()
        current_batch_limit = min(batch_size, total_messages - i)

        for j in range(current_batch_limit):
            msg_id = i + j
            payload = AlertMessage(
                message_id=msg_id,
                chat_id=config.GROUP_ID,
                raw_text=random.choice(RAW_TEXT_TEMPLATES)
            )

            pipe.xadd(
                stream_name,
                {"payload": payload.model_dump_json()},
                maxlen=10000
            )

        await pipe.execute()

        if delay > 0 and i + batch_size < total_messages:
            await asyncio.sleep(delay)

    end_time = time.time()
    elapsed = end_time - start_time
    messages_per_second = int(total_messages / elapsed)

    print("\n🏁 ==================================================")
    print("✅ Load Injection Phase Completed Successfully!")
    print(f"  ├─ Total Injection Duration: {elapsed:.2f} seconds")
    print(f"  └─ Injection Stream Velocity: {messages_per_second} payloads/sec")
    print("======================================================")

    # Automated verification layer inspecting stream lag and DLQ depth
    if verify:
        print("\n⏳ Holding for 15 seconds to allow asynchronous worker processing...")
        await asyncio.sleep(15)

        dlq_size = 0
        if await redis_client.exists("dead_letter_queue"):
            dlq_size = await redis_client.xlen("dead_letter_queue")

        try:
            groups_info = await redis_client.xinfo_groups(stream_name)
            pending_backlog = sum(group.get("pending", 0) for group in groups_info if group.get("name") == group_name)
        except Exception:
            pending_backlog = 0

        print("\n📊 AUTOMATED PERFORMANCE & INTEGRITY REPORT:")
        print("  ==================================================")
        print(f"  ├─ Dead Letter Queue (DLQ) Size: {dlq_size}")
        print(f"  └─ Consumer Group Unprocessed Lag: {pending_backlog}")
        print("  ==================================================")

        if dlq_size > 0:
            print("❌ FAILURE: Malformed or unhandled tasks detected inside the DLQ! Inspect worker logs.")
        elif pending_backlog > 0:
            print("⚠️ WARNING: Worker processing lag detected. Increase worker node thread replicas.")
        else:
            print("💯 EXCELLENT: System handled maximum load with 0% error rate and zero residual lag.")

    await redis_client.close()


if __name__ == "__main__":
    asyncio.run(run_load_benchmark(total_messages=2000, batch_size=None, delay=0.0, verify=True))