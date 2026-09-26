import logging
import sys

from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger("core_shared.metrics")

# --- Скрейпер Метрики ---
SCRAPER_MESSAGES = Counter("scraper_messages_total", "Total messages intercepted by Pyrogram scraper")
SCRAPER_ERRORS = Counter("scraper_errors_total", "Total errors occurred during message interception")
SCRAPER_OUTBOX_DEPTH = Gauge("scraper_outbox_depth", "Posts persisted locally pending Redis acceptance")
SOURCE_PERSISTED = Counter("scraper_source_persisted_total", "Source posts committed to the local outbox")
SOURCE_PUBLISHED = Counter("scraper_source_published_total", "Source posts accepted by Redis")

# --- Воркер Метрики ---
ALERTS_PROCESSED = Counter("worker_alerts_processed_total", "Total actionable alerts dispatched to users")
WORKER_ERRORS = Counter("worker_errors_total", "Total errors caught inside the main worker execution loop")
DLQ_SIZE = Gauge("worker_dlq_size", "Current absolute depth of the Dead Letter Queue in Redis")
DELIVERY_DLQ_SIZE = Gauge("worker_delivery_dlq_size", "Failed recipient delivery jobs awaiting review")
EXPIRED_ALERTS = Counter("worker_expired_alerts_total", "Source alerts recovered after freshness cutoff")
DELIVERY_PERMANENT_FAILURES = Counter(
    "worker_delivery_permanent_failures_total", "Permanent Telegram delivery failures"
)
SOURCE_BACKLOG = Gauge("worker_source_stream_depth", "Source stream entries waiting for safe retention")
DELIVERY_BACKLOG = Gauge("worker_delivery_stream_depth", "Pending and unseen recipient delivery jobs")
RECIPIENTS_SELECTED = Counter("worker_recipients_selected_total", "Recipient alert jobs accepted for delivery")
DELIVERY_OUTCOMES = Counter("worker_delivery_outcomes_total", "Telegram delivery outcomes", ["stage", "outcome"])
DELIVERY_LATENCY = Histogram(
    "worker_delivery_latency_seconds",
    "Source post to successful Telegram send",
    ["stage"],
    buckets=[1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600],
)
DELAYED_BACKLOG = Gauge("worker_delayed_queue_depth", "Scheduled delayed delivery jobs")
DELIVERY_OLDEST_AGE = Gauge("worker_delivery_oldest_age_seconds", "Age of oldest pending delivery job")
PROCESSING_TIME = Histogram(
    "worker_processing_duration_seconds",
    "Time spent analyzing text, querying DB, and generating target user lists",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)


def start_metrics_server(port: int) -> None:
    """Initializes the lightweight Prometheus exporter HTTP server."""
    try:
        start_http_server(port)
        logger.info(f"Prometheus metrics exporter successfully started on port {port}")
    except Exception as e:
        # ✅ ФИКС 16: Паттерн Fail-Fast. Если сервер метрик не поднялся — контейнер должен упасть,
        # чтобы оркестратор (Docker/K8s) сразу увидел ошибку конфигурации портов.
        logger.critical(f"CRITICAL REGISTRATION FAILURE on port {port}: {e}", exc_info=True)
        sys.exit(1)
