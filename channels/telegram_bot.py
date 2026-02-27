#!/usr/bin/env python3
import os, json, asyncio, httpx, logging, sys, re
from pathlib import Path
from datetime import datetime
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

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
)
from tools._loader import load_tools

http = httpx.AsyncClient(timeout=300)
histories: dict[int, list] = {}
MAX_HISTORY_LENGTH = 100
SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)


def _load_tools():
    return load_tools(project_root=Path(__file__).parent.parent, workspace=WS)


def md():
    return "\n\n".join(
        f"<!-- {n} -->\n{(WS / n).read_text().strip()}"
        for n in MDS
        if (WS / n).exists()
    )


def save_session(uid: int, chat_history: list) -> str | None:
    if not chat_history:
        return None
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_data = {
        "created_at": datetime.now().isoformat(),
        "user_id": uid,
        "model": OLLAMA_MODEL,
        "endpoint": MYCLAW_URL,
        "message_count": len(chat_history),
        "messages": chat_history,
    }
    session_file = SESSIONS_DIR / f"{timestamp}_{uid}.json"
    session_file.write_text(json.dumps(session_data, indent=2), encoding="utf-8")
    return str(session_file)


async def handle_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in histories and histories[uid]:
        saved = save_session(uid, histories[uid])
        histories[uid] = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{md()}"}]
        if saved:
            await update.message.reply_text(f"✅ Session saved to {Path(saved).name}")
        else:
            await update.message.reply_text(
                "✅ New session started (previous was empty)"
            )
    else:
        await update.message.reply_text("✅ New session started (no previous history)")


async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        return await handle_inner(update, ctx)
    except Exception as e:
        logger.error(f"Unexpected error in handle: {e}", exc_info=True)
        await update.message.reply_text(f"Error: {e}")
        return


async def handle_inner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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

    tools, tool_funcs = _load_tools()
    payload = {
        "model": OLLAMA_MODEL,
        "messages": histories[uid],
        "tools": tools if tools else None,
    }
    logger.debug(f"Sending payload with {len(tools or [])} tools to {MYCLAW_URL}")

    try:
        r = await http.post(
            f"{MYCLAW_URL}/v1/chat/completions", json=payload, headers=headers
        )
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
    except:
        logger.error(f"Invalid JSON from MyClaw: {r.text[:500]}")
        await update.message.reply_text(f"Invalid response from API: {r.text[:200]}")
        return

    if "choices" not in R:
        logger.error(f"No choices in response: {R}")
        await update.message.reply_text(R.get("error", f"API error: {R}"))
        return

    msg = R["choices"][0]["message"]
    logger.debug(f"Full message response: {msg}")

    tool_calls = msg.get("tool_calls", [])
    if not tool_calls:
        combined = (
            (msg.get("reasoning", "") or "") + "\n" + (msg.get("content", "") or "")
        )
        matches = re.findall(r"<tool_call>(.*?)</tool_call>", combined, re.DOTALL)
        trailing = re.findall(r"(.*?)\s*</tool_call>", combined, re.DOTALL)
        for t in trailing:
            if t not in matches:
                matches.append(t)
        json_matches = re.findall(
            r'\{[^{}]*"name"\s*:\s*"[^"]+"[^{}]*"arguments"\s*:\s*\{.*?\}', combined
        )
        for j in json_matches:
            if j not in matches:
                matches.append(j)
        for raw in matches:
            try:
                parsed = json.loads(raw.strip().replace("'", '"'))
                name = parsed.get("name", "")
                args = parsed.get("arguments", {})
                if name:
                    tool_calls.append({"function": {"name": name, "arguments": args}})
            except:
                try:
                    raw_fixed = re.sub(r",[^}]*$", "", raw.strip().replace("'", '"'))
                    parsed = json.loads(raw_fixed)
                    name = parsed.get("name", "")
                    args = parsed.get("arguments", {})
                    if name:
                        tool_calls.append(
                            {"function": {"name": name, "arguments": args}}
                        )
                except:
                    pass

    content = msg.get("content", "") or ""
    reasoning = msg.get("reasoning", "") or ""
    logger.debug(f"Tool calls in response: {tool_calls}")

    for _ in range(10):
        if not tool_calls:
            break

        assistant_msg = msg.get("content", "") or ""
        assistant_reasoning = msg.get("reasoning", "") or ""
        if assistant_reasoning and not assistant_msg:
            assistant_msg = re.sub(
                r"<tool_call>.*?</tool_call>",
                "",
                assistant_reasoning.strip(),
                flags=re.DOTALL,
            ).strip()
            assistant_msg = re.sub(r"</tool_call>\s*$", "", assistant_msg).strip()
        histories[uid].append({"role": "assistant", "content": assistant_msg})

        for tc in tool_calls:
            fn = tc.get("function", {}).get("name", "")
            args = tc.get("function", {}).get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except:
                    args = {}
            logger.debug(f"Executing tool: {fn} with args: {args}")
            if fn in tool_funcs:
                try:
                    result = tool_funcs[fn](**args)
                except Exception as e:
                    result = {"error": str(e), "success": False}
            else:
                result = {"error": f"Tool {fn} not found", "success": False}
            histories[uid].append({"role": "tool", "name": fn, "content": str(result)})

        payload["messages"] = histories[uid]
        try:
            r = await http.post(
                f"{MYCLAW_URL}/v1/chat/completions", json=payload, headers=headers
            )
            R = r.json()
            msg = R["choices"][0]["message"]
            tool_calls = msg.get("tool_calls", [])
            if not tool_calls:
                content = msg.get("content", "") or ""
                reasoning = msg.get("reasoning", "") or ""
                combined = reasoning + "\n" + content
                matches = re.findall(
                    r"<tool_call>(.*?)</tool_call>", combined, re.DOTALL
                )
                trailing = re.findall(r"(.*?)\s*</tool_call>", combined, re.DOTALL)
                for t in trailing:
                    if t not in matches:
                        matches.append(t)
                json_matches = re.findall(
                    r'\{[^{}]*"name"\s*:\s*"[^"]+"[^{}]*"arguments"\s*:\s*\{.*?\}',
                    combined,
                )
                for j in json_matches:
                    if j not in matches:
                        matches.append(j)
                for raw in matches:
                    try:
                        parsed = json.loads(raw.strip().replace("'", '"'))
                        name = parsed.get("name", "")
                        args = parsed.get("arguments", {})
                        if name:
                            tool_calls.append(
                                {"function": {"name": name, "arguments": args}}
                            )
                    except:
                        try:
                            raw_fixed = re.sub(
                                r",[^}]*$", "", raw.strip().replace("'", '"')
                            )
                            parsed = json.loads(raw_fixed)
                            name = parsed.get("name", "")
                            args = parsed.get("arguments", {})
                            if name:
                                tool_calls.append(
                                    {"function": {"name": name, "arguments": args}}
                                )
                        except:
                            pass
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            content = f"Tool execution error: {e}"
            break

    final_content = msg.get("content", "") or ""
    final_reasoning = msg.get("reasoning", "") or ""
    logger.debug(
        f"Final content: {repr(final_content[:100])}, reasoning: {repr(final_reasoning[:100])}"
    )
    if final_reasoning and not final_content:
        final_content = re.sub(
            r"<tool_call>.*?</tool_call>", "", final_reasoning.strip(), flags=re.DOTALL
        ).strip()
        final_content = re.sub(r"</tool_call>\s*$", "", final_content).strip()
    content = final_content
    logger.debug(f"Content after: '{content[:200] if content else 'empty'}'")

    reply = content.strip() if content else ""
    logger.debug(f"Reply before guard: '{reply[:200] if reply else 'empty'}'")
    if (
        not reply
        or reply.startswith("<tool_call>")
        or (reply.startswith("{") and '"name"' in reply[:60])
    ):
        logger.warning(f"Empty or invalid response. Raw msg: {msg}")
        reply = f"⚠️ Model returned no readable response. (content={repr(content)[:100]}, reasoning={repr(reasoning)[:100]})"
    logger.debug(f"Final reply: '{reply[:200] if reply else 'empty'}'")

    histories[uid].append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)


if __name__ == "__main__":
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("new", handle_new))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()
