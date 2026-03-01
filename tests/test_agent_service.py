"""Tests for Agent Service - LLM execution for agents."""

from unittest.mock import AsyncMock

import pytest
import httpx

from agents.service import AgentService, get_agent_service


def reset_agent_service():
    """Reset the global agent service."""
    import agents.service as svc_module

    svc_module._service = None


class TestAgentServiceInit:
    """Tests for AgentService initialization."""

    def test_init_defaults(self):
        """Test initialization with default values."""
        service = AgentService()
        assert service.model is not None
        assert service.timeout == 300

    def test_init_custom(self):
        """Test initialization with custom values."""
        service = AgentService(model="custom-model", upstream="http://custom:11434", timeout=60)
        assert service.model == "custom-model"
        assert service.upstream == "http://custom:11434"
        assert service.timeout == 60


class TestGetHttp:
    """Tests for _get_http method."""

    @pytest.mark.asyncio
    async def test_get_http_creates_client(self):
        """Test _get_http creates client if none exists."""
        service = AgentService()
        service._http = None
        http = await service._get_http()
        assert http is not None
        assert isinstance(http, httpx.AsyncClient)
        await service.close()

    @pytest.mark.asyncio
    async def test_get_http_reuses_client(self):
        """Test _get_http reuses existing client."""
        service = AgentService()
        mock_http = AsyncMock()
        service._http = mock_http
        http = await service._get_http()
        assert http is mock_http


class TestClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_closes_http(self):
        """Test close properly closes HTTP client."""
        service = AgentService()
        mock_http = AsyncMock()
        service._http = mock_http
        await service.close()
        mock_http.aclose.assert_called_once()
        assert service._http is None

    @pytest.mark.asyncio
    async def test_close_handles_none(self):
        """Test close handles None HTTP client."""
        service = AgentService()
        service._http = None
        await service.close()
        assert service._http is None


class TestGetAgentService:
    """Tests for get_agent_service factory."""

    def test_get_agent_service_creates(self):
        """Test factory creates service."""
        reset_agent_service()
        service = get_agent_service()
        assert isinstance(service, AgentService)

    def test_get_agent_service_reuses(self):
        """Test factory reuses existing service."""
        reset_agent_service()
        service1 = get_agent_service()
        service2 = get_agent_service()
        assert service1 is service2
