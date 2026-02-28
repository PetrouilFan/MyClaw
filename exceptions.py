"""Custom exceptions and error handling for MyClaw."""

from typing import Any


class MyClawError(Exception):
    """Base exception for MyClaw errors."""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class UpstreamError(MyClawError):
    """Exception for upstream Ollama API errors."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message, status_code)


class ToolExecutionError(MyClawError):
    """Exception for tool execution errors."""

    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' failed: {message}", 500)


class AuthenticationError(MyClawError):
    """Exception for authentication errors."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, 401)


class ValidationError(MyClawError):
    """Exception for validation errors."""

    def __init__(self, message: str):
        super().__init__(message, 400)


class RateLimitError(MyClawError):
    """Exception for rate limiting errors."""

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, 429)


def error_response(message: str, status_code: int = 500, details: Any = None) -> dict:
    """Create a structured error response."""
    response = {
        "error": {
            "message": message,
            "code": status_code,
        }
    }
    if details:
        response["error"]["details"] = details
    return response
