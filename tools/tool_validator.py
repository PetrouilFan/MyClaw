"""Tool validation for MyClaw.

Validates tool arguments against their JSON schema definitions.
"""

import logging
from typing import Optional

log = logging.getLogger("myclaw.tool_validator")

_TYPE_MAPPING = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


class ToolValidationError(Exception):
    """Raised when tool validation fails."""

    def __init__(self, message: str, tool_name: str, errors: list[str]):
        self.message = message
        self.tool_name = tool_name
        self.errors = errors
        super().__init__(message)


class ToolValidator:
    """Validates tool arguments against their schema definitions."""

    def __init__(self, tool_schemas: list[dict]):
        self.schemas = {}
        for schema in tool_schemas:
            func = schema.get("function", {})
            name = func.get("name")
            if name:
                self.schemas[name] = func.get("parameters", {})

    def validate(self, tool_name: str, arguments: dict) -> tuple[bool, list[str]]:
        """Validate tool arguments against schema.

        Args:
            tool_name: Name of the tool
            arguments: Arguments to validate

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        if tool_name not in self.schemas:
            return False, [f"Tool '{tool_name}' not found in schema"]

        schema = self.schemas[tool_name]
        errors = []

        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for req_param in required:
            if req_param not in arguments:
                errors.append(f"Missing required parameter: '{req_param}'")

        for param_name, param_value in arguments.items():
            if param_name not in properties:
                errors.append(f"Unknown parameter: '{param_name}'")
                continue

            param_schema = properties[param_name]
            expected_type = param_schema.get("type", "string")

            python_type = _TYPE_MAPPING.get(expected_type)
            if python_type and not isinstance(param_value, python_type):
                errors.append(
                    f"Parameter '{param_name}' should be {expected_type}, "
                    f"got {type(param_value).__name__}"
                )

        return len(errors) == 0, errors

    def validate_or_raise(self, tool_name: str, arguments: dict) -> None:
        """Validate and raise exception if invalid.

        Raises:
            ToolValidationError: If validation fails
        """
        is_valid, errors = self.validate(tool_name, arguments)
        if not is_valid:
            log.warning("Tool validation failed for '%s': %s", tool_name, errors)
            raise ToolValidationError(
                message=f"Tool validation failed for '{tool_name}'",
                tool_name=tool_name,
                errors=errors,
            )

    def get_schema(self, tool_name: str) -> Optional[dict]:
        """Get schema for a tool."""
        return self.schemas.get(tool_name)


_validator: Optional[ToolValidator] = None


def get_tool_validator(tool_schemas: list[dict] = None) -> ToolValidator:
    """Get or create the global tool validator."""
    global _validator

    if _validator is None:
        if tool_schemas is None:
            from tools import get_tool_schemas

            tool_schemas = get_tool_schemas()
        _validator = ToolValidator(tool_schemas)

    return _validator


def reset_tool_validator() -> None:
    """Reset the tool validator (useful for testing)."""
    global _validator
    _validator = None


def validate_tool_call(tool_name: str, arguments: dict) -> None:
    """Validate a tool call.

    Raises:
        ToolValidationError: If validation fails
    """
    validator = get_tool_validator()
    validator.validate_or_raise(tool_name, arguments)
