#!/usr/bin/env python3
"""myclaw — minimal OpenClaw-like LLM middleware."""

import os, importlib.util
from pathlib import Path
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
import uvicorn

WS   = Path(os.getenv("MYCLAW_WORKSPACE", Path.home()/"myclaw"))
from settings import OLLAMA_MODEL, OLLAMA_URL, SYSTEM_PROMPT
UP   = os.getenv("MYCLAW_UPSTREAM", OLLAMA_URL)
KEY  = os.getenv("MYCLAW_API_KEY", "")
MDS  = ["SOUL.md","PERSONALITY.md","MEMORIES.md"]
app  = FastAPI(title="myclaw")

def md() -> str:
    return "\n\n".join(
        f"<!-- {n} -->\n{(WS/n).read_text().strip()}"
        for n in MDS if (WS/n).exists()
    )

def tools() -> list:
    p = WS/"tools.py"
    if not p.exists(): return []
    m = importlib.util.module_from_spec(s := importlib.util.spec_from_file_location("t", p))
    s.loader.exec_module(m)
    return getattr(m,"TOOLS",[])

def inject(msgs, block):
    if not block: return msgs
    if msgs and msgs[0]["role"]=="system": msgs[0]["content"] = block+"\n\n"+msgs[0]["content"]
    else: msgs = [{"role":"system","content":block}]+msgs
    return msgs

def hdrs(req):
    return {"Authorization": req.headers.get("authorization",f"Bearer {KEY}"),
            "Content-Type": "application/json"}

@app.get("/health")
async def health(): return {"status":"ok","workspace":str(WS)}

@app.get("/md/{f}")
async def get_md(f:str):
    if f not in MDS: raise HTTPException(404)
    return {"filename":f,"content":(WS/f).read_text() if (WS/f).exists() else ""}

@app.put("/md/{f}")
async def put_md(f:str, req:Request):
    if f not in MDS: raise HTTPException(404)
    WS.mkdir(parents=True,exist_ok=True); (WS/f).write_bytes(await req.body())
    return {"status":"saved"}

@app.post("/v1/chat/completions")
async def chat(req:Request):
    p = await req.json()
    p["model"] = OLLAMA_MODEL
    block = SYSTEM_PROMPT + "\n\n" + md() if md() else SYSTEM_PROMPT
    p["messages"] = inject(p.get("messages",[]), block)
    if t := tools(): p["tools"] = p.get("tools",[])+t
    url, h = f"{UP.rstrip('/')}/v1/chat/completions", hdrs(req)
    async with httpx.AsyncClient(timeout=120) as c:
        if p.get("stream"):
            async def gen():
                async with c.stream("POST",url,json=p,headers=h) as r:
                    async for chunk in r.aiter_bytes(): yield chunk
            return StreamingResponse(gen(), media_type="text/event-stream")
        return (await c.post(url,json=p,headers=h)).json()

if __name__=="__main__":
    WS.mkdir(parents=True,exist_ok=True)
    [( (WS/f).write_text(f"# {f.removesuffix('.md')}\n") ) for f in MDS if not (WS/f).exists()]
    print(f"workspace:{WS}  upstream:{UP}  listen:{UP}:{os.getenv('MYCLAW_PORT','8080')}")
    uvicorn.run(app, host=os.getenv("MYCLAW_HOST","0.0.0.0"), port=int(os.getenv("MYCLAW_PORT","8080")))
