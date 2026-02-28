"""Agent service - handles LLM execution for agents."""

import json
import logging
from typing import Any, Optional

import httpx

from settings import (
    OLLAMA_MODEL,
    OLLAMA_URL,
    SYSTEM_PROMPT,
    WS,
    MAX_TOOL_CALLS,
)

logger = logging.getLogger("myclaw.agents.service")


class AgentService:
    """Service for executing LLM tasks for agents.

    Handles the chat loop with tools for subagent execution.
    """

    def __init__(
        self,
        model: str = None,
        upstream: str = None,
        timeout: int = 300,
    ):
        self.model = model or OLLAMA_MODEL
        self.upstream = upstream or OLLAMA_URL
        self.timeout = timeout
        self._http: Optional[httpx.AsyncClient] = None

    async def _get_http(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout)
        return self._http

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http:
            await self._http.aclose()
            self._http = None

    async def run_task(
        self,
        agent_id: str,
        initial_task: str,
        parent_id: Optional[str] = None,
    ) -> str:
        """Run a task for an agent.

        Args:
            agent_id: Agent ID
            initial_task: Task description
            parent_id: Parent agent ID for context

        Returns:
            Final response
        """
        from context_builder import get_context_builder
        from tools.tool_parser import clean_content, extract_tool_calls

        http = await self._get_http()

        cb = get_context_builder(workspace=WS)

        system_content = cb.build_system_prompt(
            base_prompt=SYSTEM_PROMPT
            + "\n\nYou are a subagent handling a specific task. Communicate your progress and results to the parent agent.",
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": initial_task},
        ]

        if parent_id:
            messages.append(
                {
                    "role": "system",
                    "content": f"Parent agent ID: {parent_id}. You can communicate with the parent using tools.",
                }
            )

        from tools._loader import load_tools
        from pathlib import Path

        tools_list, tool_functions = load_tools(Path("."), WS)

        url = f"{self.upstream.rstrip('/')}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}

        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools_list,
        }

        tool_call_count = 0

        while tool_call_count < MAX_TOOL_CALLS:
            try:
                response = await http.post(url, json=payload, headers=headers)

                if response.status_code >= 400:
                    logger.error("upstream_error", status=response.status_code, text=response.text)
                    return f"Error: Upstream returned {response.status_code}"

                result = response.json()

                if "choices" not in result:
                    return f"Error: Invalid response: {result}"

                message = result["choices"][0]["message"]
                tool_calls = extract_tool_calls(message)

                if not tool_calls:
                    content = clean_content(message)
                    return content or "Task completed with no output"

                messages.append(message)

                for tool_call in tool_calls:
                    tool_name = tool_call["function"]["name"]
                    tool_args = tool_call["function"]["arguments"]

                    if isinstance(tool_args, str):
                        tool_args = json.loads(tool_args)

                    logger.info("agent_tool_call", agent_id=agent_id, tool=tool_name)

                    if tool_name == "send_message_to_agent":
                        result_content = self._handle_send_message(tool_args, agent_id)
                    elif tool_name == "spawn_subagent":
                        result_content = "Subagent spawning is not available from subagent context"
                    else:
                        if tool_functions and tool_name in tool_functions:
                            try:
                                result_content = str(tool_functions[tool_name](**tool_args))
                            except Exception as e:
                                result_content = f"Error: {str(e)}"
                        else:
                            result_content = f"Tool '{tool_name}' not found"

                    messages.append(
                        {
                            "role": "tool",
                            "name": tool_name,
                            "content": result_content,
                        }
                    )

                tool_call_count += 1

            except httpx.TimeoutException:
                return "Error: Request timeout"
            except Exception as e:
                logger.exception("agent_error", agent_id=agent_id, error=str(e))
                return f"Error: {str(e)}"

        return "Max tool calls reached"

    def _handle_send_message(self, args: dict, from_agent_id: str) -> str:
        """Handle send_message_to_agent tool call.

        Args:
            args: Tool arguments
            from_agent_id: Sender agent ID

        Returns:
            Result message
        """
        to_agent_id = args.get("agent_id")
        content = args.get("message", "")

        if not to_agent_id:
            return "Error: agent_id is required"

        from agents.manager import get_agent_manager
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            manager = loop.run_until_complete(get_agent_manager())
            manager.send_message(
                from_agent_id=from_agent_id,
                to_agent_id=to_agent_id,
                content=content,
            )
            return f"Message sent to {to_agent_id}"
        except Exception as e:
            return f"Error sending message: {str(e)}"


_service: Optional[AgentService] = None


def get_agent_service() -> AgentService:
    """Get or create the global agent service."""
    global _service

    if _service is None:
        _service = AgentService()

    return _service
