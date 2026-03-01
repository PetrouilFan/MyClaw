"""Tests for Tool Validator."""

import pytest
from unittest.mock import patch
from tools.tool_validator import (
    ToolValidator,
    ToolValidationError,
    get_tool_validator,
    reset_tool_validator,
    validate_tool_call,
)


class TestToolValidationError:
    """Tests for ToolValidationError exception."""

    def test_error_stores_properties(self):
        """Test error stores message, tool_name, and errors."""
        error = ToolValidationError(
            message="Validation failed", tool_name="tool1", errors=["Missing param", "Wrong type"]
        )
        assert error.message == "Validation failed"
        assert error.tool_name == "tool1"
        assert error.errors == ["Missing param", "Wrong type"]

    def test_error_str_message(self):
        """Test __str__ returns message."""
        error = ToolValidationError(message="Test error", tool_name="tool1", errors=[])
        assert str(error) == "Test error"


class TestToolValidator:
    """Tests for ToolValidator class."""

    @pytest.fixture
    def sample_schemas(self):
        """Sample tool schemas for testing."""
        return [
            {
                "function": {
                    "name": "read_file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
                        "required": ["path"],
                    },
                }
            },
            {
                "function": {
                    "name": "write_file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["path", "content"],
                    },
                }
            },
            {
                "function": {
                    "name": "get_time",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }
            },
        ]

    def test_constructor_builds_schema(self, sample_schemas):
        """Test constructor builds schema dictionary."""
        validator = ToolValidator(sample_schemas)
        assert "read_file" in validator.schemas
        assert "write_file" in validator.schemas
        assert "get_time" in validator.schemas

    def test_validate_unknown_tool(self, sample_schemas):
        """Test validation returns False for unknown tool."""
        validator = ToolValidator(sample_schemas)
        is_valid, errors = validator.validate("nonexistent", {})
        assert is_valid is False
        assert any("not found" in e.lower() for e in errors)

    def test_validate_missing_required(self, sample_schemas):
        """Test validation detects missing required parameters."""
        validator = ToolValidator(sample_schemas)
        is_valid, errors = validator.validate("read_file", {})
        assert is_valid is False
        assert any("missing" in e.lower() and "path" in e.lower() for e in errors)

    def test_validate_unknown_param(self, sample_schemas):
        """Test validation detects unknown parameters."""
        validator = ToolValidator(sample_schemas)
        is_valid, errors = validator.validate("read_file", {"path": "/test", "unknown": "value"})
        assert is_valid is False
        assert any("unknown" in e.lower() for e in errors)

    def test_validate_type_mismatch_string_to_int(self, sample_schemas):
        """Test validation detects type mismatch."""
        validator = ToolValidator(sample_schemas)
        is_valid, errors = validator.validate("read_file", {"path": 123})
        assert is_valid is False
        assert any("should be string" in e.lower() for e in errors)

    def test_validate_type_mismatch_int_to_string(self, sample_schemas):
        """Test validation detects int where string expected."""
        validator = ToolValidator(sample_schemas)
        is_valid, errors = validator.validate("write_file", {"path": "/test", "content": 123})
        assert is_valid is False
        assert any("should be string" in e.lower() for e in errors)

    def test_validate_valid_args(self, sample_schemas):
        """Test validation passes for valid arguments."""
        validator = ToolValidator(sample_schemas)
        is_valid, errors = validator.validate("read_file", {"path": "/test"})
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_valid_with_optional(self, sample_schemas):
        """Test validation passes with optional params."""
        validator = ToolValidator(sample_schemas)
        is_valid, errors = validator.validate("read_file", {"path": "/test", "limit": 100})
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_valid_no_params(self, sample_schemas):
        """Test validation passes when no params required."""
        validator = ToolValidator(sample_schemas)
        is_valid, errors = validator.validate("get_time", {})
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_or_raise_invalid(self, sample_schemas):
        """Test validate_or_raise raises on invalid."""
        validator = ToolValidator(sample_schemas)
        with patch("tools.tool_validator.log") as mock_log:
            with pytest.raises(ToolValidationError) as exc:
                validator.validate_or_raise("read_file", {})
            assert exc.value.tool_name == "read_file"

    def test_validate_or_raise_valid(self, sample_schemas):
        """Test validate_or_raise passes on valid."""
        validator = ToolValidator(sample_schemas)
        validator.validate_or_raise("read_file", {"path": "/test"})
        # No exception means pass

    def test_get_schema_exists(self, sample_schemas):
        """Test get_schema returns schema for known tool."""
        validator = ToolValidator(sample_schemas)
        schema = validator.get_schema("read_file")
        assert schema is not None
        assert "properties" in schema

    def test_get_schema_missing(self, sample_schemas):
        """Test get_schema returns None for unknown tool."""
        validator = ToolValidator(sample_schemas)
        schema = validator.get_schema("nonexistent")
        assert schema is None


class TestToolValidatorFactory:
    """Tests for validator factory functions."""

    def setup_method(self):
        """Reset validator before each test."""
        reset_tool_validator()

    def teardown_method(self):
        """Reset validator after each test."""
        reset_tool_validator()

    def test_get_tool_validator_creates(self):
        """Test factory creates validator."""
        schemas = [
            {
                "function": {
                    "name": "tool1",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }
            }
        ]
        validator = get_tool_validator(schemas)
        assert isinstance(validator, ToolValidator)

    def test_get_tool_validator_reuses(self):
        """Test factory reuses existing validator."""
        schemas1 = [
            {
                "function": {
                    "name": "tool1",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }
            }
        ]
        schemas2 = [
            {
                "function": {
                    "name": "tool2",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }
            }
        ]
        validator1 = get_tool_validator(schemas1)
        validator2 = get_tool_validator(schemas2)
        assert validator1 is validator2
        assert "tool1" in validator2.schemas

    def test_reset_tool_validator(self):
        """Test reset clears global instance."""
        schemas = [
            {
                "function": {
                    "name": "tool1",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }
            }
        ]
        validator1 = get_tool_validator(schemas)
        reset_tool_validator()
        validator2 = get_tool_validator(schemas)
        assert validator1 is not validator2


class TestValidateToolCall:
    """Tests for validate_tool_call convenience function."""

    def setup_method(self):
        """Reset validator before each test."""
        reset_tool_validator()

    def teardown_method(self):
        """Reset validator after each test."""
        reset_tool_validator()

    def test_validate_tool_call_valid(self):
        """Test validate_tool_call passes for valid call."""
        schemas = [
            {
                "function": {
                    "name": "test_tool",
                    "parameters": {
                        "type": "object",
                        "properties": {"arg": {"type": "string"}},
                        "required": ["arg"],
                    },
                }
            }
        ]
        get_tool_validator(schemas)
        validate_tool_call("test_tool", {"arg": "value"})

    def test_validate_tool_call_invalid(self):
        """Test validate_tool_call raises for invalid call."""
        schemas = [
            {
                "function": {
                    "name": "test_tool",
                    "parameters": {
                        "type": "object",
                        "properties": {"arg": {"type": "string"}},
                        "required": ["arg"],
                    },
                }
            }
        ]
        get_tool_validator(schemas)
        with patch("tools.tool_validator.log"):
            with pytest.raises(ToolValidationError):
                validate_tool_call("test_tool", {})
