from prometheus_client import start_http_server, Counter, Gauge, Histogram
import logging

logger = logging.getLogger("core_shared.metrics")

# --- Скрейпер Метрики ---
SCRAPER_MESSAGES = Counter(
    "scraper_messages_total",
    "Total messages intercepted by Pyrogram scraper"
)
SCRAPER_ERRORS = Counter(
    "scraper_errors_total",
    "Total errors occurred during message interception or Redis publishing"
)

# --- Воркер Метрики ---
ALERTS_PROCESSED = Counter(
    "worker_alerts_processed_total",
    "Total actionable alerts successfully dispatched to users"
)
WORKER_ERRORS = Counter(
    "worker_errors_total",
    "Total errors caught inside the main worker execution loop"
)
DLQ_SIZE = Gauge(
    "worker_dlq_size",
    "Current absolute depth of the Dead Letter Queue in Redis"
)
PROCESSING_TIME = Histogram(
    "worker_processing_duration_seconds",
    "Time spent analyzing text, querying DB, and generating target user lists",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

def start_metrics_server(port: int):
    """Initializes the lightweight Prometheus exporter HTTP server."""
    try:
        start_http_server(port)
        logger.info(f"Prometheus metrics exporter successfully started on port {port}")
    except Exception as e:
        logger.error(f"Failed to start Prometheus metrics server on port {port}: {e}")