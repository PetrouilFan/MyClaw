"""Admin router for MyClaw."""

import os
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import JSONResponse

from config import settings
from session_manager import get_session_manager as get_global_session_manager

log = structlog.get_logger()

router = APIRouter(tags=["admin"])


@router.get("/health")
async def health(request: Request):
    """Health check endpoint."""
    from myclaw import tools, tool_functions
    
    return {
        "status": "ok",
        "workspace": str(settings.workspace),
        "version": "0.1.0",
        "tools_loaded": len(tools(request.app.state)) if tools(request.app.state) else 0,
        "session_enabled": settings.session_enabled,
        "stateless_mode": settings.stateless_mode,
    }


@router.get("/sessions")
async def list_sessions(a=Header(None)):
    """List all sessions."""
    if not settings.session_enabled:
        raise HTTPException(404, "Session management not available")

    sm = get_global_session_manager(
        storage_dir=settings.session_storage_path_resolved,
        token_budget=settings.session_token_budget,
    )
    sessions = []
    for path in sm.storage_dir.glob("*.json"):
        try:
            with open(path, "r") as f:
                data = f.read()
                sessions.append({"session_id": path.stem, "size": len(data)})
        except Exception:
            pass
    return {"sessions": sessions}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, a=Header(None)):
    """Delete a session."""
    if not settings.session_enabled:
        raise HTTPException(404, "Session management not available")

    sm = get_global_session_manager(
        storage_dir=settings.session_storage_path_resolved,
        token_budget=settings.session_token_budget,
    )
    path = sm.storage_dir / f"{session_id}.json"
    if path.exists():
        path.unlink()
        return {"status": "deleted", "session_id": session_id}
    else:
        raise HTTPException(404, "Session not found")


@router.post("/_invalidate_cache")
async def invalidate_cache(a=Header(None)):
    """Invalidate tool cache."""
    from tools._loader import invalidate_cache
    invalidate_cache()
    return {"status": "cache invalidated"}


@router.get("/md/{f}")
async def get_md(f: str, a=Header(None)):
    """Get markdown file content."""
    if not settings.session_enabled or f not in settings.mds:
        raise HTTPException(404 if a else 401, "Not found")

    path = settings.workspace / f
    if not path.exists():
        raise HTTPException(404, "File not found")

    return {"content": path.read_text()}


@router.put("/md/{f}")
async def put_md(f: str, request: Request, a=Header(None)):
    """Update markdown file content."""
    if not settings.session_enabled or f not in settings.mds:
        raise HTTPException(404 if a else 401, "Not found")

    data = await request.json()
    content = data.get("content", "")

    if len(content) > 10000:
        raise HTTPException(400, "File too large")

    path = settings.workspace / f
    path.write_text(content)

    return {"status": "updated", "file": f}
