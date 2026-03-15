"""Enhanced error handling for MyClaw.

Provides error categorization, retry logic, and dead letter queue.
"""

import asyncio
import json
import logging
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel

log = logging.getLogger("myclaw.errors")


class ErrorCategory(str, Enum):
    """Categories of errors for handling decisions."""

    RETRYABLE = "retryable"
    PERMANENT = "permanent"
    TRANSIENT = "transient"
    AUTH = "auth"
    VALIDATION = "validation"
    UPSTREAM = "upstream"
    TOOL = "tool"
    INTERNAL = "internal"


class ErrorSeverity(str, Enum):
    """Severity levels for errors."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorDetail(BaseModel):
    """Structured error information."""

    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    code: Optional[str] = None
    details: dict[str, Any] = {}
    retry_after: Optional[int] = None
    is_retryable: bool = True


class DeadLetterEntry(BaseModel):
    """Entry in the dead letter queue."""

    id: str
    timestamp: str
    error: ErrorDetail
    context: dict[str, Any]
    retry_count: int = 0


class DeadLetterQueue:
    """Dead letter queue for failed messages."""

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _get_path(self, entry_id: str) -> Path:
        return self.storage_path / f"{entry_id}.json"

    def add(self, entry: DeadLetterEntry) -> None:
        """Add an entry to the dead letter queue."""
        path = self._get_path(entry.id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry.model_dump(), f, indent=2, default=str)
        log.warning("dlq_entry_added", entry_id=entry.id, category=entry.error.category)

    def get(self, entry_id: str) -> Optional[DeadLetterEntry]:
        """Get an entry from the dead letter queue."""
        path = self._get_path(entry_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return DeadLetterEntry(**data)
        except (json.JSONDecodeError, IOError):
            return None

    def list_all(self) -> list[DeadLetterEntry]:
        """List all entries in the dead letter queue."""
        entries = []
        for path in self.storage_path.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entries.append(DeadLetterEntry(**data))
            except (json.JSONDecodeError, IOError):
                pass
        return sorted(entries, key=lambda x: x.timestamp, reverse=True)

    def remove(self, entry_id: str) -> bool:
        """Remove an entry from the dead letter queue."""
        path = self._get_path(entry_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def clear(self) -> int:
        """Clear all entries from the dead letter queue."""
        count = 0
        for path in self.storage_path.glob("*.json"):
            path.unlink()
            count += 1
        return count


def categorize_error(error: Exception, context: dict = {}) -> ErrorDetail:
    """Categorize an error and determine handling strategy."""
    error_str = str(error).lower()

    if isinstance(error, TimeoutError):
        return ErrorDetail(
            category=ErrorCategory.TRANSIENT,
            severity=ErrorSeverity.MEDIUM,
            message=str(error),
            is_retryable=True,
            retry_after=5,
        )

    if isinstance(error, ConnectionError):
        return ErrorDetail(
            category=ErrorCategory.TRANSIENT,
            severity=ErrorSeverity.MEDIUM,
            message=str(error),
            is_retryable=True,
            retry_after=10,
        )

    if "auth" in error_str or "unauthorized" in error_str or "401" in error_str:
        return ErrorDetail(
            category=ErrorCategory.AUTH,
            severity=ErrorSeverity.HIGH,
            message=str(error),
            is_retryable=False,
            code="AUTH_ERROR",
        )

    if "403" in error_str or "forbidden" in error_str:
        return ErrorDetail(
            category=ErrorCategory.AUTH,
            severity=ErrorSeverity.HIGH,
            message=str(error),
            is_retryable=False,
            code="FORBIDDEN",
        )

    if "404" in error_str or "not found" in error_str:
        return ErrorDetail(
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.MEDIUM,
            message=str(error),
            is_retryable=False,
            code="NOT_FOUND",
        )

    if "429" in error_str or "rate limit" in error_str:
        return ErrorDetail(
            category=ErrorCategory.RETRYABLE,
            severity=ErrorSeverity.MEDIUM,
            message=str(error),
            is_retryable=True,
            retry_after=60,
            code="RATE_LIMITED",
        )

    if "500" in error_str or "502" in error_str or "503" in error_str:
        return ErrorDetail(
            category=ErrorCategory.UPSTREAM,
            severity=ErrorSeverity.HIGH,
            message=str(error),
            is_retryable=True,
            retry_after=30,
            code="UPSTREAM_ERROR",
        )

    if "validation" in error_str or "invalid" in error_str:
        return ErrorDetail(
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.LOW,
            message=str(error),
            is_retryable=False,
            code="VALIDATION_ERROR",
        )

    if "tool" in error_str:
        return ErrorDetail(
            category=ErrorCategory.TOOL,
            severity=ErrorSeverity.MEDIUM,
            message=str(error),
            is_retryable=False,
            code="TOOL_ERROR",
        )

    return ErrorDetail(
        category=ErrorCategory.INTERNAL,
        severity=ErrorSeverity.MEDIUM,
        message=str(error),
        is_retryable=True,
        retry_after=5,
    )


async def retry_with_backoff(
    func: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
) -> Any:
    """Retry a function with exponential backoff.

    Args:
        func: Async function to retry
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff

    Returns:
        Result of the function

    Raises:
        Last exception if all retries fail
    """
    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            return await func()
        except Exception as e:
            last_error = e
            error_detail = categorize_error(e)

            if not error_detail.is_retryable or attempt >= max_retries:
                log.error(
                    "retry_exhausted",
                    attempt=attempt,
                    max_retries=max_retries,
                    error=str(e),
                )
                raise

            delay = min(base_delay * (exponential_base**attempt), max_delay)
            if error_detail.retry_after:
                delay = min(delay, error_detail.retry_after)

            log.warning(
                "retry_attempt",
                attempt=attempt + 1,
                max_retries=max_retries,
                delay=delay,
                error=str(e),
            )
            await asyncio.sleep(delay)

    if last_error is not None:
        raise last_error
    raise RuntimeError("No error to raise")


_dlq: Optional[DeadLetterQueue] = None


def get_dead_letter_queue(workspace: Optional[Path] = None) -> DeadLetterQueue:
    """Get or create the dead letter queue."""
    global _dlq

    if _dlq is None:
        if workspace is None:
            from settings import WS

            workspace = WS
        _dlq = DeadLetterQueue(workspace / "dead_letter_queue")

    return _dlq
