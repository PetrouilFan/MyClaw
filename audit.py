"""Audit logging for MyClaw.

Logs all tool executions, agent spawns/terminations, and message exchanges.
"""

import json
import logging
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

logger = logging.getLogger("myclaw.audit")


class AuditEventType(str, Enum):
    """Types of audit events."""

    TOOL_EXECUTION = "tool_execution"
    AGENT_SPAWN = "agent_spawn"
    AGENT_TERMINATE = "agent_terminate"
    AGENT_MESSAGE = "agent_message"
    API_REQUEST = "api_request"
    SESSION_CREATE = "session_create"
    SESSION_EXPIRE = "session_expire"
    RATE_LIMIT = "rate_limit"
    AUTH_FAILURE = "auth_failure"
    SENSITIVE_OPERATION = "sensitive_operation"


class AuditLevel(str, Enum):
    """Audit event levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditEvent(BaseModel):
    """Audit event model."""

    id: str
    timestamp: str
    event_type: AuditEventType
    level: AuditLevel
    actor: Optional[str] = None
    target: Optional[str] = None
    action: str
    details: dict[str, Any] = {}
    success: bool = True
    duration_ms: Optional[int] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AuditLogger:
    """Audit logger with file-based storage."""

    def __init__(self, storage_path: Path, retention_days: int = 30):
        self.storage_path = storage_path
        self.retention_days = retention_days
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._event_counter = 0

    def _get_log_path(self, date: str) -> Path:
        """Get log file path for a date."""
        return self.storage_path / f"audit_{date}.jsonl"

    def log(
        self,
        event_type: AuditEventType,
        action: str,
        level: AuditLevel = AuditLevel.INFO,
        actor: Optional[str] = None,
        target: Optional[str] = None,
        details: Optional[dict] = None,
        success: bool = True,
        duration_ms: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> str:
        """Log an audit event.

        Returns:
            Event ID
        """
        with self._lock:
            self._event_counter += 1
            event_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{self._event_counter}"

            event = AuditEvent(
                id=event_id,
                timestamp=datetime.now().isoformat(),
                event_type=event_type,
                level=level,
                actor=actor,
                target=target,
                action=action,
                details=details or {},
                success=success,
                duration_ms=duration_ms,
                ip_address=ip_address,
                user_agent=user_agent,
            )

            log_path = self._get_log_path(datetime.now().strftime("%Y-%m-%d"))
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")

            if level in (AuditLevel.ERROR, AuditLevel.CRITICAL):
                logger.error(
                    "audit_event",
                    event_type=event_type.value,
                    action=action,
                    success=success,
                    actor=actor,
                    target=target,
                )
            else:
                logger.debug(
                    "audit_event",
                    event_type=event_type.value,
                    action=action,
                    success=success,
                )

            return event_id

    def log_tool_execution(
        self,
        tool_name: str,
        arguments: dict,
        result: Any,
        success: bool,
        duration_ms: Optional[int] = None,
        actor: Optional[str] = None,
    ) -> str:
        """Log tool execution."""
        return self.log(
            event_type=AuditEventType.TOOL_EXECUTION,
            action=f"execute_tool:{tool_name}",
            level=AuditLevel.INFO if success else AuditLevel.ERROR,
            actor=actor,
            target=tool_name,
            details={
                "arguments": arguments,
                "result": str(result)[:500],
            },
            success=success,
            duration_ms=duration_ms,
        )

    def log_agent_spawn(
        self,
        agent_id: str,
        agent_name: str,
        parent_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """Log agent spawn."""
        return self.log(
            event_type=AuditEventType.AGENT_SPAWN,
            action=f"spawn_agent:{agent_name}",
            level=AuditLevel.INFO,
            actor=parent_id,
            target=agent_id,
            details={"agent_name": agent_name, "metadata": metadata or {}},
        )

    def log_agent_terminate(
        self,
        agent_id: str,
        reason: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> str:
        """Log agent termination."""
        return self.log(
            event_type=AuditEventType.AGENT_TERMINATE,
            action="terminate_agent",
            level=AuditLevel.INFO,
            target=agent_id,
            details={"reason": reason},
            duration_ms=duration_ms,
        )

    def log_api_request(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        duration_ms: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> str:
        """Log API request."""
        level = AuditLevel.INFO if status_code < 400 else AuditLevel.ERROR
        return self.log(
            event_type=AuditEventType.API_REQUEST,
            action=f"{method} {endpoint}",
            level=level,
            details={"status_code": status_code},
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    def log_auth_failure(
        self,
        reason: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> str:
        """Log authentication failure."""
        return self.log(
            event_type=AuditEventType.AUTH_FAILURE,
            action="authentication_failed",
            level=AuditLevel.WARNING,
            details={"reason": reason},
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    def query(
        self,
        event_type: Optional[AuditEventType] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        actor: Optional[str] = None,
        target: Optional[str] = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Query audit events."""
        events = []

        date_format = "%Y-%m-%d"
        start = datetime.strptime(start_date or "1970-01-01", date_format) if start_date else None
        end = datetime.strptime(end_date or "2100-12-31", date_format) if end_date else None

        for log_file in sorted(self.storage_path.glob("audit_*.jsonl")):
            file_date_str = log_file.stem.replace("audit_", "")
            try:
                file_date = datetime.strptime(file_date_str, date_format)
            except ValueError:
                continue

            if start and file_date < start:
                continue
            if end and file_date > end:
                continue

            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            event = AuditEvent(**json.loads(line))

                            if event_type and event.event_type != event_type:
                                continue
                            if actor and event.actor != actor:
                                continue
                            if target and event.target != target:
                                continue

                            events.append(event)

                            if len(events) >= limit:
                                break
                        except json.JSONDecodeError:
                            continue
            except IOError:
                continue

            if len(events) >= limit:
                break

        return events[:limit]

    def cleanup_old_logs(self) -> int:
        """Remove log files older than retention period."""
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=self.retention_days)
        removed = 0

        for log_file in self.storage_path.glob("audit_*.jsonl"):
            file_date_str = log_file.stem.replace("audit_", "")
            try:
                file_date = datetime.strptime(file_date_str, "%Y-%m-%d")
                if file_date < cutoff:
                    log_file.unlink()
                    removed += 1
            except ValueError:
                continue

        return removed


_audit_logger: Optional[AuditLogger] = None


def get_audit_logger(workspace: Optional[Path] = None) -> AuditLogger:
    """Get or create the audit logger."""
    global _audit_logger

    if _audit_logger is None:
        if workspace is None:
            from config import settings

            workspace = settings.workspace

        _audit_logger = AuditLogger(workspace / "audit")

    return _audit_logger
