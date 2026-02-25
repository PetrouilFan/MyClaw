# myclaw

Single-file OpenClaw-inspired LLM middleware, ~55 active lines.

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
  SOUL.md          # identity & values
  PERSONALITY.md   # communication style
  MEMORIES.md      # persistent memory snippets
  tools.py         # (optional) custom tools -> TOOLS list
```

## Install & run
```bash
pip install fastapi "uvicorn[standard]" httpx

MYCLAW_API_KEY=sk-...   python myclaw.py          # OpenAI upstream
MYCLAW_UPSTREAM=http://localhost:11434  python myclaw.py  # Ollama
```

## Env vars
| Var                | Default                   |
|--------------------|---------------------------|
| MYCLAW_WORKSPACE   | ~/myclaw                  |
| MYCLAW_UPSTREAM    | https://api.openai.com    |
| MYCLAW_API_KEY     | ""                        |
| MYCLAW_HOST        | 0.0.0.0                   |
| MYCLAW_PORT        | 8080                      |

## REST API
| Method | Path                  | Description               |
|--------|-----------------------|---------------------------|
| GET    | /health               | health + workspace path   |
| GET    | /md/{filename}        | read .md file             |
| PUT    | /md/{filename}        | write .md file (raw body) |
| POST   | /v1/chat/completions  | OpenAI-compatible proxy   |
