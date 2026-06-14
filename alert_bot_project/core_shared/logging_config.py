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