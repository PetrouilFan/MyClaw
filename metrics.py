"""Prometheus metrics for MyClaw."""

from prometheus_client import Counter, Histogram, Gauge

requests_total = Counter(
    "myclaw_requests_total", "Total number of requests", ["endpoint", "method", "status"]
)

tool_calls_total = Counter(
    "myclaw_tool_calls_total", "Total number of tool calls", ["tool_name", "status"]
)

request_duration_seconds = Histogram(
    "myclaw_request_duration_seconds",
    "Request duration in seconds",
    ["endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

active_connections = Gauge("myclaw_active_connections", "Number of active connections")

upstream_errors_total = Counter(
    "myclaw_upstream_errors_total", "Total number of upstream errors", ["error_type"]
)

tools_loaded = Gauge("myclaw_tools_loaded", "Number of tools currently loaded")
