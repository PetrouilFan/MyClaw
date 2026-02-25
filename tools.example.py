# ~/myclaw/tools.py  — expose a TOOLS list in OpenAI function-calling format
TOOLS = [
    {"type":"function","function":{
        "name":"get_time",
        "description":"Current UTC time.",
        "parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{
        "name":"search_memories",
        "description":"Search MEMORIES.md for a term.",
        "parameters":{"type":"object","properties":{
            "query":{"type":"string","description":"search term"}},
            "required":["query"]}}},
]
