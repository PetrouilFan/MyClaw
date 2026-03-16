"""Tool execution service for MyClaw.

Handles the complex tool execution loop with retries, planning, and reflection.
"""

import json
import logging
from typing import Optional, Dict, Any, List

import structlog
from httpx import AsyncClient

from config import settings
from api_models import ChatCompletionRequest, Message
from agent_loop import get_planning_agent, ErrorFormatter, add_planning_to_system_prompt
from tools.tool_parser import clean_content, extract_tool_calls
from session_manager import SessionManager

log = structlog.get_logger()


class ToolExecutor:
    """Executes tool calls with retries, planning, and reflection."""

    def __init__(
        self,
        http_client: AsyncClient,
        upstream_url: str,
        api_key: str,
        session_manager: Optional[SessionManager] = None,
        session_id: Optional[str] = None,
        session_history: Optional[List[Dict[str, Any]]] = None,
    ):
        self.http_client = http_client
        self.upstream_url = upstream_url.rstrip("/")
        self.api_key = api_key
        self.session_manager = session_manager
        self.session_id = session_id
        self.session_history = session_history or []

        self.planning_agent = get_planning_agent(
            enable_planning=settings.enable_planning,
            enable_reflection=settings.enable_reflection,
        )
        self.error_formatter = ErrorFormatter()

    async def execute_loop(
        self,
        request_data: ChatCompletionRequest,
        tool_funcs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute the tool execution loop with retries and planning.

        Args:
            request_data: The chat completion request with messages
            tool_funcs: Dictionary of available tool functions

        Returns:
            The final response from upstream
        """
        if settings.enable_planning:
            system_msg = request_data.messages[0]
            system_msg.content = add_planning_to_system_prompt(system_msg.content or "")

        tc = 0
        while tc < settings.max_tool_calls:
            x = await self.http_client.post(
                f"{self.upstream_url}/v1/chat/completions",
                json=request_data.model_dump(),
                headers={
                    "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
                    "Content-Type": "application/json",
                },
            )

            if x.status_code >= 400:
                log.error("upstream_error", status_code=x.status_code)
                return {
                    "error": {
                        "message": f"Upstream error: {x.status_code}",
                        "code": 502,
                        "details": {"status_code": x.status_code},
                    }
                }

            try:
                R = x.json()
            except Exception:
                return {
                    "error": {
                        "message": "Invalid JSON from upstream",
                        "code": 502,
                    }
                }

            if "choices" not in R:
                return R

            m = R["choices"][0]["message"]
            ts = extract_tool_calls(m)
            log.debug("tool_calls_extracted", count=len(ts))

            if not ts:
                content = clean_content(m)
                R["choices"][0]["message"]["content"] = content
                log.info("chat_response", tool_calls=0)

                if self.session_manager and self.session_id:
                    for msg in request_data.messages:
                        if msg.role not in ("system",):
                            self.session_history.append(msg.model_dump())
                    self.session_history.append({"role": "assistant", "content": content})
                    self.session_manager.save_session(self.session_id, self.session_history)

                return R

            request_data.messages.append(Message(**m))

            for t_ in ts:
                fn, ag = t_["function"]["name"], t_["function"]["arguments"]
                args = json.loads(ag) if isinstance(ag, str) else ag

                tool_result = None
                error_msg = None

                for attempt in range(settings.tool_max_retries + 1):
                    try:
                        tool_result = await self._call_tool(fn, args, tool_funcs)

                        if isinstance(tool_result, dict) and tool_result.get("error"):
                            error_msg = tool_result.get("error", "Unknown error")
                            if attempt < settings.tool_max_retries:
                                log.warning("tool_retry", tool=fn, attempt=attempt, error=error_msg)
                                formatted_error = self.error_formatter.format_tool_error(
                                    fn, error_msg, args
                                )
                                request_data.messages.append(
                                    Message(role="tool", name=fn, content=formatted_error)
                                )
                                continue
                        else:
                            break
                    except Exception as e:
                        error_msg = str(e)
                        if attempt < settings.tool_max_retries:
                            log.warning(
                                "tool_error_retry", tool=fn, attempt=attempt, error=error_msg
                            )
                            formatted_error = self.error_formatter.format_tool_error(
                                fn, error_msg, args
                            )
                            request_data.messages.append(
                                Message(role="tool", name=fn, content=formatted_error)
                            )
                            continue
                        tool_result = {"error": error_msg, "success": False}
                        break

                result_str = str(tool_result) if tool_result else ""

                if settings.enable_reflection and self.planning_agent.should_reflect(result_str):
                    reflection = self.planning_agent.create_reflection(fn, args, result_str)
                    request_data.messages.append(Message(role="user", content=reflection))

                log.info("tool_call", tool=fn, arguments=ag)
                request_data.messages.append(Message(role="tool", name=fn, content=result_str))

                if self.session_manager and self.session_id and not settings.stateless_mode:
                    self.session_history.append(m)
                    self.session_history.append({"role": "tool", "name": fn, "content": result_str})

            tc += 1

        return R

    async def _call_tool(
        self,
        name: str,
        args: Dict[str, Any],
        tool_funcs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Call a single tool function."""
        from tools.tool_validator import validate_tool_call

        if name not in tool_funcs:
            return {"error": f"Tool {name} not found", "success": False}

        try:
            validate_tool_call(name, args)
        except Exception as e:
            log.error("tool_validation_error", tool=name, error=str(e))
            return {"error": f"Validation failed: {str(e)}", "success": False, "tool": name}

        try:
            func = tool_funcs[name]
            import inspect

            if inspect.iscoroutinefunction(func):
                return await func(**args)
            return func(**args)
        except Exception as e:
            log.error("tool_execution_error", tool=name, error=str(e))
            return {"error": str(e), "success": False, "tool": name}
