# myclaw

OpenClaw-inspired LLM middleware with tool execution and terminal command support.

## How it works
```
Client ──POST /v1/chat/completions──► myclaw ──► Upstream LLM
                                        │
                           injects: SOUL.md + PERSONALITY.md + MEMORIES.md
                           merges:  tools.py TOOLS list
```
Files are read **on every request** — edit them live, no restart needed.

## Workspace
```
~/myclaw/
  SOUL.md           # identity & values
  PERSONALITY.md    # communication style
  MEMORIES.md      # persistent memory snippets
  tools.py          # (optional) custom tools -> TOOLS list
```

## Install & run
```bash
pip install fastapi "uvicorn[standard]" httpx

python myclaw.py                              # uses settings from settings.py
MYCLAW_UPSTREAM=http://localhost:11434 python myclaw.py  # Ollama upstream
```

## Env vars
| Var                      | Default                                           |
|--------------------------|---------------------------------------------------|
| MYCLAW_WORKSPACE        | ~/myclaw                                         |
| MYCLAW_MODEL            | hf.co/MaziyarPanahi/Qwen3-4B-Instruct-2507-GGUF:Q6_K |
| MYCLAW_UPSTREAM         | http://100.92.128.50:11434                       |
| MYCLAW_API_KEY          | ""                                                |
| MYCLAW_HOST             | 0.0.0.0                                           |
| MYCLAW_PORT             | 8080                                              |
| MYCLAW_MAX_TOOL_CALLS   | 10                                                |
| MYCLAW_MAX_PAYLOAD_SIZE | 10485760 (10MB)                                   |

## Tools
Built-in tools available to the LLM:
- `get_time` - Current UTC time
- `search_memories` - Search MEMORIES.md
- `read_file` - Read file contents
- `append_to_file` - Append to file
- `overwrite_file` - Overwrite file
- `run_terminal_command` - Execute terminal commands
- `wait_terminal_command` - Wait for background command
- `read_command_output` - Read command output
- `kill_terminal_command` - Kill running command
- `list_terminal_commands` - List tracked processes
- `cleanup_terminal_processes` - Cleanup completed processes
- `get_terminal_help` - Get terminal tool usage guide

## REST API
| Method | Path                  | Description               |
|--------|-----------------------|---------------------------|
| GET    | /health               | health + workspace path   |
| GET    | /md/{filename}        | read .md file             |
| PUT    | /md/{filename}        | write .md file (raw body) |
| POST   | /v1/chat/completions  | OpenAI-compatible proxy   |
| POST   | /_invalidate_cache   | invalidate tool cache     |
