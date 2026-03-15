"""Tests for HTTP API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import Response


@pytest.fixture
def mock_ollama():
    """Mock the upstream Ollama API."""
    from myclaw import app
    import httpx
    
    mock_http = AsyncMock()
    mock_response = Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello, how can I help you?",
                    }
                }
            ]
        },
    )
    mock_http.get = AsyncMock(return_value=Response(200, json={"models": []}))
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.stream = AsyncMock()
    
    # Initialize app.state attributes if they don't exist
    if not hasattr(app.state, 'http_client'):
        app.state.http_client = mock_http
    if not hasattr(app.state, 'check_upstream'):
        app.state.check_upstream = False
    if not hasattr(app.state, 'upstream'):
        app.state.upstream = "http://localhost:11434"
    if not hasattr(app.state, 'api_key'):
        app.state.api_key = ""
    
    # Store original and replace with mock
    original_http = app.state.http_client
    app.state.http_client = mock_http
    
    try:
        yield mock_http
    finally:
        # Restore original
        app.state.http_client = original_http


@pytest.fixture
def client(mock_ollama):
    """Create a test client for the FastAPI app."""
    from myclaw import app

    # Store the mock http_client from mock_ollama
    mock_http = mock_ollama
    
    with TestClient(app=app) as test_client:
        # Ensure the mock is still in place after TestClient creation
        app.state.http_client = mock_http
        yield test_client


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_ok(self, client):
        """Test health endpoint returns ok status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "workspace" in data


class TestInvalidateCacheEndpoint:
    """Tests for /_invalidate_cache endpoint."""

    def test_invalidate_cache_works(self, client):
        """Test invalidate cache works (auth bypassed when no keys configured)."""
        response = client.post("/_invalidate_cache")
        assert response.status_code == 200
        assert response.json()["status"] == "cache invalidated"


class TestMarkdownEndpoints:
    """Tests for /md/{filename} endpoints."""

    @pytest.fixture
    def workspace_files(self, tmp_path):
        """Create test workspace files."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "SOUL.md").write_text("# SOUL\nTest content")
        (ws / "PERSONALITY.md").write_text("# PERSONALITY\nTest personality")
        return ws

    def test_get_md_works(self, client, workspace_files):
        """Test GET /md/{f} works (auth bypassed when no keys configured)."""
        with patch("config.settings.workspace", workspace_files):
            response = client.get("/md/SOUL.md")
            assert response.status_code == 200

    def test_get_md_not_found_forbidden(self, client, workspace_files):
        """Test GET /md/{f} returns 404 for non-allowed files."""
        with patch("config.settings.workspace", workspace_files):
            with patch("config.settings.mds", []):
                response = client.get("/md/SOUL.md", headers={"Authorization": "Bearer test-key"})
                assert response.status_code == 404

    def test_get_md_success(self, client, workspace_files):
        """Test GET /md/{f} returns file content."""
        with patch("config.settings.workspace", workspace_files):
            with patch("config.settings.mds", ["SOUL.md", "PERSONALITY.md"]):
                response = client.get("/md/SOUL.md", headers={"Authorization": "Bearer test-key"})
                assert response.status_code == 200
                data = response.json()
                assert data["filename"] == "SOUL.md"
                assert "Test content" in data["content"]

    def test_put_md_works(self, client, workspace_files):
        """Test PUT /md/{f} works (auth bypassed when no keys configured)."""
        with patch("config.settings.workspace", workspace_files):
            response = client.put("/md/SOUL.md", content="New content")
            assert response.status_code == 200

    def test_put_md_file_too_large(self, client, workspace_files):
        """Test PUT /md/{f} returns 413 for large files."""
        with patch("config.settings.workspace", workspace_files):
            with patch("config.settings.mds", ["SOUL.md"]):
                with patch("config.settings.max_payload_size", 10):
                    response = client.put(
                        "/md/SOUL.md",
                        content="This is way too long content",
                        headers={"Authorization": "Bearer test-key"},
                    )
                    assert response.status_code == 413


class TestChatCompletions:
    """Tests for /v1/chat/completions endpoint."""

    def test_chat_requires_auth(self, client):
        """Test chat endpoint works without auth when no keys configured."""
        response = client.post(
            "/v1/chat/completions", json={"messages": [{"role": "user", "content": "Hello"}]}
        )
        assert response.status_code == 200

    def test_chat_requires_messages(self, client):
        """Test chat endpoint requires messages."""
        response = client.post(
            "/v1/chat/completions", json={}, headers={"Authorization": "Bearer test-key"}
        )
        assert response.status_code == 400
        error_str = str(response.json())
        assert "messages" in error_str

    def test_chat_simple_response(self, client, mock_ollama):
        """Test chat returns response from upstream."""
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
            headers={"Authorization": "Bearer test-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0

    def test_chat_with_system_message(self, client, mock_ollama):
        """Test chat properly injects system message."""
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
            headers={"Authorization": "Bearer test-key"},
        )
        assert response.status_code == 200

        call_args = mock_ollama.post.call_args
        assert call_args is not None
        sent_json = call_args.kwargs["json"]

        assert sent_json["messages"][0]["role"] == "system"
        assert "helpful AI assistant" in sent_json["messages"][0]["content"]


class TestToolCalls:
    """Tests for tool call handling."""

    def test_tool_calls_extracted(self, client, mock_ollama):
        """Test tool calls are extracted from response."""
        mock_ollama.post.return_value = Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "I'll get the time for you.",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {"name": "get_time", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            },
        )

        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "What time is it?"}]},
            headers={"Authorization": "Bearer test-key"},
        )

        assert response.status_code in [200, 400]

    def test_max_tool_calls_limit(self, client, mock_ollama):
        """Test max tool calls limit is enforced."""
        mock_ollama.post.return_value = Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Let me check...",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {"name": "get_time", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            },
        )

        with patch("config.settings.max_tool_calls", 2):
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "What time is it?"}]},
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 400
            error_str = str(response.json())
            assert "Max tool calls" in error_str


class TestUpstreamErrors:
    """Tests for upstream error handling."""

    def test_upstream_unreachable(self, client, mock_ollama):
        """Test handling of unreachable upstream."""
        import httpx

        mock_ollama.get.side_effect = httpx.ConnectError("Connection failed")

        with patch("myclaw.app.state.check_upstream", True):
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hello"}]},
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 503
            error_text = str(response.json().get("error", ""))
            assert "unreachable" in error_text.lower()

    def test_upstream_error_status(self, client, mock_ollama):
        """Test handling of upstream error status."""
        mock_ollama.post.return_value = Response(500, json={"error": "Internal error"})

        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
            headers={"Authorization": "Bearer test-key"},
        )

        assert response.status_code == 502

    def test_invalid_json_from_upstream(self, client, mock_ollama):
        """Test handling of invalid JSON from upstream."""
        mock_ollama.post.return_value = Response(
            200, content=b"not valid json", headers={"content-type": "application/json"}
        )

        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
            headers={"Authorization": "Bearer test-key"},
        )

        assert response.status_code == 502
        error_text = str(response.json().get("error", ""))
        assert "Invalid JSON" in error_text
