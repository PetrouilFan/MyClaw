"""Tests for HTTP API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import Response, ASGITransport


@pytest.fixture
def mock_ollama():
    """Mock the upstream Ollama API."""
    with patch("myclaw.http") as mock_http:
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
        yield mock_http


@pytest.fixture
def client(mock_ollama):
    """Create a test client for the FastAPI app."""
    from myclaw import app

    transport = ASGITransport(app=app)
    with TestClient(transport) as test_client:
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

    def test_invalidate_cache_requires_auth(self, client):
        """Test invalidate cache requires authentication."""
        response = client.post("/_invalidate_cache")
        assert response.status_code == 401

    def test_invalidate_cache_success(self, client):
        """Test invalidate cache works with valid auth."""
        response = client.post("/_invalidate_cache", headers={"Authorization": "Bearer test-key"})
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

    def test_get_md_requires_auth(self, client, workspace_files):
        """Test GET /md/{f} requires authentication."""
        with patch("myclaw.WS", workspace_files):
            response = client.get("/md/SOUL.md")
            assert response.status_code == 401

    def test_get_md_not_found(self, client, workspace_files):
        """Test GET /md/{f} returns 404 for non-allowed files."""
        with patch("myclaw.WS", workspace_files):
            response = client.get("/md/SOUL.md", headers={"Authorization": "Bearer test-key"})
            assert response.status_code == 404

    def test_get_md_success(self, client, workspace_files):
        """Test GET /md/{f} returns file content."""
        with patch("myclaw.WS", workspace_files):
            with patch("myclaw.MDS", ["SOUL.md", "PERSONALITY.md"]):
                response = client.get("/md/SOUL.md", headers={"Authorization": "Bearer test-key"})
                assert response.status_code == 200
                data = response.json()
                assert data["filename"] == "SOUL.md"
                assert "Test content" in data["content"]

    def test_put_md_requires_auth(self, client, workspace_files):
        """Test PUT /md/{f} requires authentication."""
        with patch("myclaw.WS", workspace_files):
            response = client.put("/md/SOUL.md", content="New content")
            assert response.status_code == 401

    def test_put_md_file_too_large(self, client, workspace_files):
        """Test PUT /md/{f} returns 413 for large files."""
        with patch("myclaw.WS", workspace_files):
            with patch("myclaw.MDS", ["SOUL.md"]):
                with patch("myclaw.MAX_PAYLOAD_SIZE", 10):
                    response = client.put(
                        "/md/SOUL.md",
                        content="This is way too long content",
                        headers={"Authorization": "Bearer test-key"},
                    )
                    assert response.status_code == 413


class TestChatCompletions:
    """Tests for /v1/chat/completions endpoint."""

    def test_chat_requires_auth(self, client):
        """Test chat endpoint requires authentication."""
        response = client.post(
            "/v1/chat/completions", json={"messages": [{"role": "user", "content": "Hello"}]}
        )
        assert response.status_code == 401

    def test_chat_requires_messages(self, client):
        """Test chat endpoint requires messages."""
        response = client.post(
            "/v1/chat/completions", json={}, headers={"Authorization": "Bearer test-key"}
        )
        assert response.status_code == 400
        assert "messages required" in response.json()["error"]

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

    def test_chat_streaming(self, client, mock_ollama):
        """Test streaming chat works."""
        from unittest.mock import MagicMock

        mock_stream = MagicMock()
        mock_stream.status_code = 200
        mock_stream.aiter_lines = AsyncMock(
            return_value=iter(
                [
                    'data: {"choices":[{"delta":{"content":"Hello"}}]}',
                    'data: {"choices":[{"delta":{"content":" World"}}]}',
                    "data: [DONE]",
                ]
            )
        )
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=None)

        mock_ollama.stream.return_value = mock_stream

        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}], "stream": True},
            headers={"Authorization": "Bearer test-key"},
            stream=True,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"


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

        assert response.status_code == 200
        assert mock_ollama.post.call_count == 2

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

        with patch("myclaw.MAX_TOOL_CALLS", 2):
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "What time is it?"}]},
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 400
            assert "Max tool calls" in response.json()["error"]


class TestUpstreamErrors:
    """Tests for upstream error handling."""

    def test_upstream_unreachable(self, client, mock_ollama):
        """Test handling of unreachable upstream."""
        import httpx

        mock_ollama.get.side_effect = httpx.ConnectError("Connection failed")

        with patch("myclaw.CHECK_UPSTREAM", True):
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hello"}]},
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 503
            assert "unreachable" in response.json()["error"].lower()

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
        assert "Invalid JSON" in response.json()["error"]
