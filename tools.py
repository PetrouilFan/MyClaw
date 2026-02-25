from tools.get_time import get_time
from tools.search_memories import search_memories
from tools.read_file import read_file
from tools.append_to_file import append_to_file
from tools.overwrite_file import overwrite_file

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
    {"type":"function","function":{
        "name":"read_file",
        "description":"Read content from a file.",
        "parameters":{"type":"object","properties":{
            "filepath":{"type":"string","description":"Path to the file."}},
            "required":["filepath"]}}},
    {"type":"function","function":{
        "name":"append_to_file",
        "description":"Append content to a file.",
        "parameters":{"type":"object","properties":{
            "filepath":{"type":"string","description":"Path to the file."},
            "content":{"type":"string","description":"Content to append."}},
            "required":["filepath", "content"]}}},
    {"type":"function","function":{
        "name":"overwrite_file",
        "description":"Overwrite a file with new content.",
        "parameters":{"type":"object","properties":{
            "filepath":{"type":"string","description":"Path to the file."},
            "content":{"type":"string","description":"Content to overwrite with."}},
            "required":["filepath", "content"]}}},
]

TOOL_FUNCTIONS = {
    "get_time": get_time,
    "search_memories": search_memories,
    "read_file": read_file,
    "append_to_file": append_to_file,
    "overwrite_file": overwrite_file
}
