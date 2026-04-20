import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def log_query_received(session_id: str, question: str) -> None:
    logger.info(
        "query_received",
        extra={
            "event": "query_received",
            "session_id": session_id,
            "question_length": len(question),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def log_query_completed(session_id: str, duration_ms: float) -> None:
    logger.info(
        "query_completed",
        extra={
            "event": "query_completed",
            "session_id": session_id,
            "duration_ms": round(duration_ms, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def log_query_failed(session_id: str, error: str) -> None:
    logger.error(
        "query_failed",
        extra={
            "event": "query_failed",
            "session_id": session_id,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
