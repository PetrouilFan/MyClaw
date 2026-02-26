import inspect
from tools.get_time import get_time
from tools.search_memories import search_memories
from tools.read_file import read_file
from tools.append_to_file import append_to_file
from tools.overwrite_file import overwrite_file
from tools.terminal import (
    TOOLS as TERMINAL_TOOLS,
    TOOL_FUNCTIONS as TERMINAL_TOOL_FUNCTIONS,
)


def _build_tool_schema(func):
    sig = inspect.signature(func)
    props, required = {}, []
    for name, param in sig.parameters.items():
        ptype = (
            param.annotation.__name__
            if param.annotation != param.empty and isinstance(param.annotation, type)
            else "string"
        )
        props[name] = {"type": ptype, "description": f"Parameter {name}"}
        if param.default == param.empty:
            required.append(name)
    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": func.__doc__.strip() if func.__doc__ else "",
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


TOOL_FUNCTIONS = {
    **dict.fromkeys(
        ["get_time", "search_memories", "read_file", "append_to_file", "overwrite_file"]
    ),
    **TERMINAL_TOOL_FUNCTIONS,
}
TOOL_FUNCTIONS["get_time"] = get_time
TOOL_FUNCTIONS["search_memories"] = search_memories
TOOL_FUNCTIONS["read_file"] = read_file
TOOL_FUNCTIONS["append_to_file"] = append_to_file
TOOL_FUNCTIONS["overwrite_file"] = overwrite_file

TOOLS = [
    _build_tool_schema(f)
    for f in [get_time, search_memories, read_file, append_to_file, overwrite_file]
] + TERMINAL_TOOLS
