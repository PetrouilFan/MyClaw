#!/usr/bin/env python3
import os, json, asyncio, httpx, logging, sys
from pathlib import Path
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, MessageHandler, ContextTypes, filters

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("telegram")

from settings import (
    TELEGRAM_BOT_TOKEN,
    OLLAMA_MODEL,
    SYSTEM_PROMPT,
    WS,
    MYCLAW_API_KEY,
    MDS,
    MYCLAW_URL,
    MAX_TOOL_CALLS,
)
from tools._loader import load_tools

http = httpx.AsyncClient(timeout=300)
histories: dict[int, list] = {}
MAX_HISTORY_LENGTH = 100


def _load_tools():
    return load_tools(project_root=Path(__file__).parent.parent, workspace=WS)


def call_tool(n, a):
    _, tf = _load_tools()
    if tf and n in tf:
        try:
            return tf[n](**a)
        except Exception as e:
            return {"error": str(e), "success": False}
    return {"error": f"Tool {n} not found", "success": False}


def md():
    return "\n\n".join(
        f"<!-- {n} -->\n{(WS / n).read_text().strip()}"
        for n in MDS
        if (WS / n).exists()
    )


async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private" or not update.message.text:
        return
    uid = update.effective_user.id
    if uid not in histories or len(histories[uid]) > MAX_HISTORY_LENGTH:
        histories[uid] = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{md()}"}]
    histories[uid].append({"role": "user", "content": update.message.text})
    if len(histories[uid]) > MAX_HISTORY_LENGTH:
        histories[uid] = [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{md()}"}
        ] + histories[uid][-(MAX_HISTORY_LENGTH - 1) :]

    await ctx.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )
    headers = {"Content-Type": "application/json"}
    if MYCLAW_API_KEY:
        headers["Authorization"] = f"Bearer {MYCLAW_API_KEY}"

    tools, _ = _load_tools()
    payload = {
        "model": OLLAMA_MODEL,
        "messages": histories[uid],
        "tools": tools if tools else None,
    }
    logger.debug(f"Sending payload with {len(tools)} tools")

    tc = 0
    while tc < MAX_TOOL_CALLS:
        try:
            logger.debug(
                f"API call {tc + 1}, messages count: {len(payload['messages'])}"
            )
            r = await http.post(
                f"{MYCLAW_URL}/v1/chat/completions", json=payload, headers=headers
            )
        except Exception as e:
            await update.message.reply_text(f"Connection error: {e}")
            return

        if r.status_code != 200:
            await update.message.reply_text(f"API error: {r.status_code} {r.text}")
            return

        try:
            R = r.json()
        except:
            await update.message.reply_text("Invalid response from API")
            return

        if "choices" not in R:
            await update.message.reply_text(R.get("error", "Unknown error"))
            return

        msg = R["choices"][0]["message"]
        tool_calls = msg.get("tool_calls", [])
        logger.debug(f"Response: {json.dumps(msg, indent=2)[:500]}")

        if not tool_calls:
            full = msg.get("content", "")
            break

        payload["messages"].append(msg)
        for t in tool_calls:
            fn, ag = t["function"]["name"], t["function"]["arguments"]
            args = json.loads(ag) if isinstance(ag, str) else ag
            payload["messages"].append(
                {"role": "tool", "name": fn, "content": str(call_tool(fn, args))}
            )
        tc += 1
    else:
        await update.message.reply_text(f"Max tool calls ({MAX_TOOL_CALLS}) reached")
        return

    histories[uid].append({"role": "assistant", "content": full})
    await update.message.reply_text(full or "(no response)")


if __name__ == "__main__":
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()
