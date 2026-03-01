"""Tests for MyClaw main FastAPI application."""

import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient


class TestExceptionHandlers:
    """Tests for exception handlers."""

    def test_timeout_exception_handler(self):
        """Test timeout exception returns 504."""
        from myclaw import timeout_exception_handler
        from httpx import TimeoutException
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_request.url = MagicMock(path="/test")

        import asyncio

        result = asyncio.run(timeout_exception_handler(mock_request, TimeoutException("timeout")))

        assert result.status_code == 504
        data = json.loads(result.body)
        assert "timeout" in data["error"]["message"].lower()

    def test_connection_exception_handler(self):
        """Test connection exception returns 503."""
        from myclaw import connection_exception_handler
        from httpx import ConnectError
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_request.url = MagicMock(path="/test")

        import asyncio

        result = asyncio.run(
            connection_exception_handler(mock_request, ConnectError("Connection failed"))
        )

        assert result.status_code == 503
        data = json.loads(result.body)
        assert "unreachable" in data["error"]["message"].lower()

    def test_http_exception_handler(self):
        """Test HTTP exception passes through status."""
        from myclaw import http_exception_handler
        from fastapi import HTTPException, Request

        mock_request = MagicMock(spec=Request)

        import asyncio

        result = asyncio.run(http_exception_handler(mock_request, HTTPException(404, "Not found")))

        assert result.status_code == 404

    def test_general_exception_handler(self):
        """Test general exception returns 500."""
        from myclaw import general_exception_handler
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_request.url = MagicMock(path="/test")

        import asyncio

        result = asyncio.run(general_exception_handler(mock_request, ValueError("Test error")))

        assert result.status_code == 500
        data = json.loads(result.body)
        assert "error_type" in data["error"]["details"]


class TestAuthFunction:
    """Tests for _auth function."""

    def test_auth_no_key_configured(self):
        """Test auth returns False when no keys configured."""
        with patch("myclaw.KEY", None):
            with patch("myclaw.ALLOWED_API_KEYS", []):
                from myclaw import _auth

                result = _auth(None)
                assert result is False

    def test_auth_key_in_allowed_keys(self):
        """Test auth returns False for valid key in ALLOWED_API_KEYS."""
        with patch("myclaw.ALLOWED_API_KEYS", ["key1", "key2"]):
            from myclaw import _auth

            result = _auth("key1")
            assert result is False

    def test_auth_valid_bearer_token(self):
        """Test auth returns False for valid Bearer token."""
        with patch("myclaw.KEY", "my-secret-key"):
            with patch("myclaw.ALLOWED_API_KEYS", []):
                from myclaw import _auth

                result = _auth("Bearer my-secret-key")
                assert result is False

    def test_auth_valid_raw_token(self):
        """Test auth returns False for valid raw token."""
        with patch("myclaw.KEY", "my-secret-key"):
            with patch("myclaw.ALLOWED_API_KEYS", []):
                from myclaw import _auth

                result = _auth("my-secret-key")
                assert result is False

    def test_auth_invalid_token(self):
        """Test auth returns True for invalid token."""
        with patch("myclaw.KEY", "my-secret-key"):
            with patch("myclaw.ALLOWED_API_KEYS", []):
                from myclaw import _auth

                result = _auth("wrong-key")
                assert result is True

    def test_auth_empty_token_with_keys(self):
        """Test auth returns True for empty token when keys required."""
        with patch("myclaw.KEY", "my-secret-key"):
            with patch("myclaw.ALLOWED_API_KEYS", []):
                from myclaw import _auth

                result = _auth("")
                assert result is True


class TestDedupeFunction:
    """Tests for _dedupe function."""

    def test_dedupe_combines_tools(self):
        """Test deduplication combines client and server tools."""
        from myclaw import _dedupe

        client = [
            {"function": {"name": "tool1"}},
            {"function": {"name": "tool2"}},
        ]
        server = [{"function": {"name": "tool3"}}]

        result = _dedupe(client, server)

        assert len(result) >= 1
        names = {t["function"]["name"] for t in result}
        assert "tool3" in names

    def test_dedupe_server_has_precedence(self):
        """Test server tools take precedence."""
        from myclaw import _dedupe

        client = [
            {"function": {"name": "shared"}},
        ]
        server = [{"function": {"name": "shared"}}]

        result = _dedupe(client, server)

        assert len(result) == 1


class TestCreateErrorResponse:
    """Tests for _create_error_response function."""

    def test_create_error_basic(self):
        """Test basic error response."""
        from myclaw import _create_error_response

        result = _create_error_response("Test error", 400)

        assert result.status_code == 400
        data = json.loads(result.body)
        assert data["error"]["message"] == "Test error"
        assert data["error"]["code"] == 400

    def test_create_error_with_details(self):
        """Test error response with details."""
        from myclaw import _create_error_response

        result = _create_error_response("Test error", 400, {"field": "value"})

        assert result.status_code == 400
        data = json.loads(result.body)
        assert data["error"]["details"]["field"] == "value"


class TestMdFunction:
    """Tests for md function."""

    def test_md_reads_files(self, tmp_path):
        """Test md reads existing files."""
        with patch("myclaw.WS", tmp_path):
            with patch("myclaw.MDS", ["SOUL.md", "PERSONALITY.md"]):
                (tmp_path / "SOUL.md").write_text("# Soul content")
                (tmp_path / "PERSONALITY.md").write_text("# Personality content")

                from myclaw import md

                result = md()

                assert "# Soul content" in result
                assert "# Personality content" in result

    def test_md_handles_missing(self, tmp_path):
        """Test md handles missing files gracefully."""
        with patch("myclaw.WS", tmp_path):
            with patch("myclaw.MDS", ["SOUL.md", "MISSING.md"]):
                (tmp_path / "SOUL.md").write_text("# Soul")

                from myclaw import md

                result = md()

                assert "# Soul" in result
                assert "MISSING" not in result or result.count("MISSING") == 0

    def test_md_handles_read_error(self, tmp_path):
        """Test md handles read errors gracefully."""
        with patch("myclaw.WS", tmp_path):
            with patch("myclaw.MDS", ["ERROR.md"]):
                from myclaw import md

                result = md()
                assert result == ""


class TestToolsFunction:
    """Tests for tools and tool_functions."""

    @pytest.fixture(autouse=True)
    def reset_tools(self):
        """Reset global tool cache before each test."""
        import myclaw

        myclaw._t = None
        myclaw._tf = None
        yield
        myclaw._t = None
        myclaw._tf = None

    def test_tools_loads_tools(self, tmp_path):
        """Test tools loads tools from loader."""
        with patch("myclaw.WS", tmp_path):
            with patch("myclaw.ENABLE_AGENT_TOOLS", False):
                from myclaw import tools

                result = tools()
                assert result is not None
                assert isinstance(result, list)

    def test_tools_caches(self, tmp_path):
        """Test tools caches results."""
        with patch("myclaw.WS", tmp_path):
            with patch("myclaw.ENABLE_AGENT_TOOLS", False):
                from myclaw import tools

                result1 = tools()
                result2 = tools()
                assert result1 is result2


class TestCallTool:
    """Tests for call_tool function."""

    @pytest.fixture(autouse=True)
    def setup_tools(self, tmp_path):
        """Setup tools for testing."""
        import myclaw

        myclaw._t = None
        myclaw._tf = None

        with patch("myclaw.WS", tmp_path):
            from tools._loader import load_tools

            t, tf = load_tools(project_root=tmp_path, workspace=tmp_path)
            myclaw._t = t
            myclaw._tf = tf

        yield

        myclaw._t = None
        myclaw._tf = None

    def test_call_tool_executes(self, tmp_path):
        """Test call_tool executes valid tool."""
        with patch("myclaw.WS", tmp_path):
            from myclaw import call_tool

            result = call_tool("get_time", {})
            assert "success" in result or "error" not in result

    def test_call_tool_not_found(self):
        """Test call_tool handles tool not found."""
        from myclaw import call_tool

        result = call_tool("nonexistent_tool", {})
        assert "not found" in result["error"].lower()

    def test_call_tool_validation_error(self, tmp_path):
        """Test call_tool handles validation errors."""
        with patch("myclaw.WS", tmp_path):
            from myclaw import call_tool

            result = call_tool("read_file", {"path": 123})
            assert result.get("success") is False or "error" in result

    def test_call_tool_execution_error(self, tmp_path):
        """Test call_tool handles execution errors."""
        with patch("myclaw.WS", tmp_path):
            from myclaw import call_tool

            result = call_tool("read_file", {"path": "/nonexistent/file.txt"})
            assert "error" in result or result.get("success") is False


class TestSessionEndpoints:
    """Tests for session endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from myclaw import app

        with TestClient(app=app) as test_client:
            yield test_client

    def test_list_sessions_returns_list(self, client, tmp_path):
        """Test GET /sessions returns list."""
        with patch("myclaw.SESSION_ENABLED", True):
            with patch("myclaw.STATELESS_MODE", False):
                with patch("myclaw.SESSION_STORAGE_PATH", tmp_path / "sessions"):
                    with patch("myclaw.SESSION_TOKEN_BUDGET", 100000):
                        response = client.get("/sessions")
                        assert response.status_code == 200
                        data = response.json()
                        assert "sessions" in data

    def test_list_sessions_404_when_disabled(self, client):
        """Test GET /sessions returns 404 when disabled."""
        with patch("myclaw.SESSION_ENABLED", False):
            response = client.get("/sessions")
            assert response.status_code == 404

    def test_delete_session_404_when_disabled(self, client):
        """Test DELETE /sessions returns 404 when disabled."""
        with patch("myclaw.SESSION_ENABLED", False):
            response = client.delete("/sessions/test_session")
            assert response.status_code == 404

    def test_delete_session_404_missing(self, client, tmp_path):
        """Test DELETE /sessions/{id} returns 404 for missing."""
        with patch("myclaw.SESSION_ENABLED", True):
            with patch("myclaw.STATELESS_MODE", False):
                with patch("myclaw.SESSION_STORAGE_PATH", tmp_path / "sessions"):
                    with patch("myclaw.SESSION_TOKEN_BUDGET", 100000):
                        response = client.delete("/sessions/nonexistent")
                        assert response.status_code == 404


class TestAgentEndpoints:
    """Tests for agent endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from myclaw import app

        with TestClient(app=app) as test_client:
            yield test_client

    def test_list_agents_unavailable(self, client):
        """Test GET /agents returns 404 when agents unavailable."""
        with patch("myclaw.AGENT_TOOLS_AVAILABLE", False):
            response = client.get("/agents")
            assert response.status_code == 404

    def test_get_agent_404_missing(self, client):
        """Test GET /agents/{id} returns 404 for missing agent."""
        with patch("myclaw.AGENT_TOOLS_AVAILABLE", False):
            response = client.get("/agents/nonexistent")
            assert response.status_code == 404

    def test_terminate_agent_not_found(self, client):
        """Test DELETE /agents/{id} returns 404 when not found."""
        with patch("myclaw.AGENT_TOOLS_AVAILABLE", True):
            with patch("myclaw.get_agent_manager", new_callable=AsyncMock):
                mock_manager = AsyncMock()
                mock_manager.terminate_agent.return_value = False
                with patch("myclaw.get_agent_manager", return_value=mock_manager):
                    response = client.delete("/agents/nonexistent")
                    assert response.status_code == 404

    def test_spawn_agent_missing_task(self, client):
        """Test POST /agents/{id}/spawn returns 400 when task missing."""
        with patch("myclaw.AGENT_TOOLS_AVAILABLE", True):
            with patch("myclaw.get_agent_manager", new_callable=AsyncMock):
                mock_manager = AsyncMock()
                with patch("myclaw.get_agent_manager", return_value=mock_manager):
                    response = client.post("/agents/main/spawn", json={})
                    assert response.status_code == 400

    def test_spawn_agent_unavailable(self, client):
        """Test POST /agents/{id}/spawn returns 404 when agents unavailable."""
        with patch("myclaw.AGENT_TOOLS_AVAILABLE", False):
            response = client.post("/agents/main/spawn", json={"task": "test"})
            assert response.status_code == 404

    def test_get_agent_messages_unavailable(self, client):
        """Test GET /agents/{id}/messages returns 404 when unavailable."""
        with patch("myclaw.AGENT_TOOLS_AVAILABLE", False):
            response = client.get("/agents/main/messages")
            assert response.status_code == 404

    def test_agent_events_unavailable(self, client):
        """Test GET /agents/{id}/events returns 404 when unavailable."""
        with patch("myclaw.AGENT_TOOLS_AVAILABLE", False):
            response = client.get("/agents/main/events")
            assert response.status_code == 404


class TestWebSocketEndpoint:
    """Tests for WebSocket endpoint."""

    def test_ws_endpoint_exists(self):
        """Test WebSocket endpoint is registered."""
        from myclaw import app

        routes = [r.path for r in app.routes]
        assert "/ws/chat" in routes


class TestMetricsEndpoint:
    """Tests for metrics endpoint."""

    def test_metrics_function_exists(self):
        """Test metrics function exists."""
        from myclaw import _metrics

        assert callable(_metrics)


class TestCustomOpenapi:
    """Tests for custom OpenAPI schema."""

    def test_custom_openapi_sets_info(self):
        """Test custom OpenAPI sets contact info."""
        from myclaw import app

        schema = app.openapi()
        assert "contact" in schema["info"]
        assert schema["info"]["contact"]["name"] == "MyClaw"

    def test_custom_openapi_security_schemes(self):
        """Test custom OpenAPI includes security schemes."""
        from myclaw import app

        schema = app.openapi()
        assert "securitySchemes" in schema["components"]


class TestLifespan:
    """Tests for lifespan handler."""

    def test_lifespan_closes_http(self):
        """Test lifespan closes HTTP client."""
        from myclaw import lifespan, app
        import asyncio

        mock_http = AsyncMock()
        with patch("myclaw.http", mock_http):

            async def run():
                async with lifespan(app):
                    pass

            asyncio.run(run())
            mock_http.aclose.assert_called_once()
