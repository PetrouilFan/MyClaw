#!/usr/bin/env python3
import os, json, asyncio, httpx
from pathlib import Path
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from settings import TELEGRAM_BOT_TOKEN, OLLAMA_MODEL, SYSTEM_PROMPT, WS, MYCLAW_API_KEY

MDS = ["SOUL.md", "PERSONALITY.md", "MEMORIES.md"]
http = httpx.AsyncClient(timeout=300)
histories: dict[int, list] = {}


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
    histories.setdefault(
        uid, [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{md()}"}]
    )
    histories[uid].append({"role": "user", "content": update.message.text})

    await ctx.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )
    headers = {"Content-Type": "application/json"}
    if MYCLAW_API_KEY:
        headers["Authorization"] = f"Bearer {MYCLAW_API_KEY}"

    resp, full = "", ""
    try:
        async with http.stream(
            "POST",
            "http://localhost:8080/v1/chat/completions",
            json={"model": OLLAMA_MODEL, "messages": histories[uid], "stream": True},
            headers=headers,
        ) as r:
            if r.status_code != 200:
                text = await r.aread()
                await update.message.reply_text(
                    f"API error: {r.status_code} {text.decode()}"
                )
                return
            async for line in r.aiter_lines():
                if (
                    line.startswith("data:")
                    and (data := line[5:].strip())
                    and data != "[DONE]"
                ):
                    try:
                        delta = json.loads(data)["choices"][0]["delta"]
                        full += delta.get("reasoning", "") + delta.get("content", "")
                    except Exception:
                        pass
    except Exception as e:
        await update.message.reply_text(f"Connection error: {e}")
        return

    histories[uid].append({"role": "assistant", "content": full})
    await update.message.reply_text(full or "(no response)")


if __name__ == "__main__":
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()
