#!/usr/bin/env python3
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import settings
from tools._loader import load_tools
from tools.tool_parser import clean_content, extract_tool_calls

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("telegram")

http = httpx.AsyncClient(timeout=300)
histories: dict[int, list] = {}
MAX_HISTORY_LENGTH = 100
SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)


def _load_tools() -> tuple[list, dict]:
    return load_tools(project_root=Path(__file__).parent.parent, workspace=settings.workspace)


def md() -> str:
    return "\n\n".join(
        f"<!-- {n} -->\n{(settings.workspace / n).read_text().strip()}" for n in settings.mds if (settings.workspace / n).exists()
    )


def save_session(uid: int, chat_history: list) -> str | None:
    if not chat_history:
        return None
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_data = {
        "created_at": datetime.now().isoformat(),
        "user_id": uid,
        "model": settings.model,
        "endpoint": settings.myclaw_url,
        "message_count": len(chat_history),
        "messages": chat_history,
    }
    session_file = SESSIONS_DIR / f"{timestamp}_{uid}.json"
    session_file.write_text(json.dumps(session_data, indent=2), encoding="utf-8")
    return str(session_file)


def _init_history(uid: int) -> list[dict[str, Any]]:
    if uid not in histories or len(histories[uid]) > MAX_HISTORY_LENGTH:
        histories[uid] = [{"role": "system", "content": f"{settings.system_prompt}\n\n{md()}"}]
    return histories[uid]


def _build_payload(messages: list[dict[str, Any]], tools: list | None) -> dict[str, Any]:
    return {
        "model": settings.model,
        "messages": messages,
        "tools": tools if tools else None,
    }


def _get_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    return headers


async def handle_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in histories and histories[uid]:
        saved = save_session(uid, histories[uid])
        histories[uid] = [{"role": "system", "content": f"{settings.system_prompt}\n\n{md()}"}]
        if saved:
            await update.message.reply_text(f"✅ Session saved to {Path(saved).name}")
        else:
            await update.message.reply_text("✅ New session started (previous was empty)")
    else:
        await update.message.reply_text("✅ New session started (no previous history)")


async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        return await handle_inner(update, ctx)
    except Exception as e:
        logger.error(f"Unexpected error in handle: {e}", exc_info=True)
        await update.message.reply_text(f"Error: {e}")
        return


async def _execute_tool_calls(
    tool_calls: list,
    tool_funcs: dict,
    history: list,
    headers: dict,
) -> tuple[dict, str]:
    for _ in range(10):
        if not tool_calls:
            break

        assistant_msg = clean_content(history[-1])
        history.append({"role": "assistant", "content": assistant_msg})

        for tc in tool_calls:
            fn = tc.get("function", {}).get("name", "")
            args = tc.get("function", {}).get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            logger.debug(f"Executing tool: {fn} with args: {args}")
            if fn in tool_funcs:
                try:
                    result = tool_funcs[fn](**args)
                except Exception as e:
                    result = {"error": str(e), "success": False}
            else:
                result = {"error": f"Tool {fn} not found", "success": False}
            history.append({"role": "tool", "name": fn, "content": str(result)})

        try:
            r = await http.post(
                f"{settings.myclaw_url}/v1/chat/completions",
                json={"model": settings.model, "messages": history, "tools": None},
                headers=headers,
            )
            R = r.json()
            msg = R["choices"][0]["message"]
            tool_calls = extract_tool_calls(msg)
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return {}, f"Tool execution error: {e}"

    return msg, ""


async def handle_inner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" or not update.message.text:
        return
    uid = update.effective_user.id

    history = _init_history(uid)
    history.append({"role": "user", "content": update.message.text})
    if len(history) > MAX_HISTORY_LENGTH:
        history = [{"role": "system", "content": f"{settings.system_prompt}\n\n{md()}"}] + history[
            -(MAX_HISTORY_LENGTH - 1) :
        ]

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    tools, tool_funcs = _load_tools()
    headers = _get_headers()
    payload = _build_payload(history, tools)
    logger.debug(f"Sending payload with {len(tools or [])} tools to {settings.myclaw_url}")

    try:
        r = await http.post(f"{settings.myclaw_url}/v1/chat/completions", json=payload, headers=headers)
    except Exception as e:
        logger.error(f"Connection error: {e}")
        await update.message.reply_text(f"Connection error: {e}")
        return

    logger.debug(f"MyClaw response status: {r.status_code}, body: {r.text[:200]}")
    if r.status_code != 200:
        logger.error(f"MyClaw error {r.status_code}: {r.text}")
        await update.message.reply_text(f"API error {r.status_code}: {r.text[:200]}")
        return

    try:
        R = r.json()
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON from MyClaw: {r.text[:500]}")
        await update.message.reply_text(f"Invalid response from API: {r.text[:200]}")
        return

    if "choices" not in R:
        logger.error(f"No choices in response: {R}")
        await update.message.reply_text(R.get("error", f"API error: {R}"))
        return

    msg = R["choices"][0]["message"]
    logger.debug(f"Full message response: {msg}")

    tool_calls = extract_tool_calls(msg)
    logger.debug(f"Tool calls in response: {tool_calls}")

    if tool_calls:
        msg, error = await _execute_tool_calls(tool_calls, tool_funcs, history, headers)
        if error:
            await update.message.reply_text(error)
            return

    content = clean_content(msg)
    logger.debug(f"Content after: '{content[:200] if content else 'empty'}'")

    reply = content.strip() if content else ""
    logger.debug(f"Reply before guard: '{reply[:200] if reply else 'empty'}'")
    if (
        not reply
        or reply.startswith("<tool_call>")
        or (reply.startswith("{") and '"name"' in reply[:60])
    ):
        logger.warning(f"Empty or invalid response. Raw msg: {msg}")
        reply = "⚠️ Model returned no readable response."
    logger.debug(f"Final reply: '{reply[:200] if reply else 'empty'}'")

    histories[uid] = history
    history.append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)


if __name__ == "__main__":
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("new", handle_new))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()
