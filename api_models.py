"""Pydantic models for HTTP API."""

from typing import Optional, Literal
from pydantic import BaseModel


class FunctionCall(BaseModel):
    """Function call information."""

    name: str
    arguments: str


class ToolCall(BaseModel):
    """Tool call information."""

    id: str
    type: Literal["function"] = "function"
    function: FunctionCall


class Message(BaseModel):
    """OpenAI-compatible message model."""

    role: Literal["user", "assistant", "system", "tool"]
    content: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    tool_call_id: Optional[str] = None

    model_config = {"extra": "allow"}


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model: Optional[str] = None
    messages: list[Message]
    tools: Optional[list[dict]] = None
    stream: bool = False
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None


class ErrorDetail(BaseModel):
    """Error detail model."""

    code: int
    message: str
    details: Optional[dict] = None


class Function(BaseModel):
    """Function information."""

    name: str
    arguments: str


class Choice(BaseModel):
    """Choice in chat completion response."""

    index: int
    message: Message
    finish_reason: Optional[str] = None


class Usage(BaseModel):
    """Usage information."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage


class ChatCompletionChunk(BaseModel):
    """OpenAI-compatible chat completion chunk for streaming."""

    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[dict]
