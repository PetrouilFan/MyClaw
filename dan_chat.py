import sys
import os
from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Horizontal
from textual.widgets import Header, Footer, Input, Static, Markdown
from textual import work
import httpx
import json
from settings import OLLAMA_MODEL, OLLAMA_URL, SYSTEM_PROMPT

WS = Path(os.getenv("MYCLAW_WORKSPACE", Path.home() / "myclaw"))
MYCLAW_HOST = os.getenv("MYCLAW_HOST", "localhost")
MYCLAW_PORT = os.getenv("MYCLAW_PORT", "8080")
MYCLAW_URL = f"http://{MYCLAW_HOST}:{MYCLAW_PORT}"


def extract_answer(text: str) -> str:
    import re

    match = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Handle "Alright, here's the response:" pattern
    if "Alright, here's the response:" in text:
        after = text.split("Alright, here's the response:", 1)[1]
        return after.strip()

    text = text.strip()
    if "\n" in text:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return lines[-1] if lines else text[:200]

    return text[:200] if len(text) > 200 else text


class ChatMessage(Static):
    """A widget for displaying chat messages, styled based on role."""

    def __init__(self, role: str, text: str):
        super().__init__()
        self.role = role
        self.raw_text = text
        self.markdown = Markdown(f"**{role}**: {text}")

    def on_mount(self) -> None:
        self.add_class(f"message-{self.role.lower()}")
        if self.role == "System":
            self.border_title = "System"
            self.add_class("message-warning")
        elif self.role == "DAN":
            self.border_title = "DAN-Qwen3-1.7B"
            self.add_class("message-error")
        else:
            self.border_title = "You"
            self.add_class("message-success")

    def compose(self) -> ComposeResult:
        yield self.markdown

    def append_text(self, text_chunk: str):
        """Append text to the message and update the markdown."""
        self.raw_text += text_chunk
        self.markdown.update(f"**{self.role}**: {self.raw_text}")


class DANApp(App):
    """Textual App to chat with DAN-Qwen3-1.7B via MyClaw."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #chat_container {
        height: 1fr;
        padding: 1 2;
        overflow-y: scroll;
    }

    #input_container {
        height: auto;
        padding: 1 2;
        dock: bottom;
    }

    ChatMessage {
        width: 100%;
        margin-bottom: 1;
        border: round white;
        padding: 0 1;
        height: auto;
    }

    .message-system { border: double #d4b553; border-title-color: #d4b553; }
    .message-user { border: solid #5db85c; border-title-color: #5db85c; }
    .message-dan { border: solid #d9534f; border-title-color: #d9534f; }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ScrollableContainer(id="chat_container")
        with Horizontal(id="input_container"):
            yield Input(id="chat_input", placeholder="Share your message...")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Dan Chat"
        self.model_id = OLLAMA_MODEL
        self.myclaw_url = MYCLAW_URL

        self.chat_history = []
        system_prompt = SYSTEM_PROMPT

        md_files = [
            "identity.md",
            "personality.md",
            "user.md",
            "soul.md",
            "bootstrap.md",
        ]

        for md_file in md_files:
            md_path = WS / md_file
            if md_path.exists():
                try:
                    with md_path.open("r", encoding="utf-8") as f:
                        md_content = f.read()

                    section_name = md_file.replace(".md", "").replace("_", " ").title()
                    system_prompt += f"\n\n--- {section_name} ---\n{md_content}"

                    if md_file == "bootstrap.md":
                        md_path.unlink()
                        self.add_message("System", f"Loaded and deleted {md_file}.")
                    else:
                        self.add_message("System", f"Loaded {md_file}.")
                except Exception as e:
                    self.add_message("System", f"Failed to process {md_file}: {e}")

        self.chat_history.append({"role": "system", "content": system_prompt})

        self.add_message(
            "System", f"Ready to chat with MyClaw. Endpoint: {self.myclaw_url}"
        )

    def add_message(self, role: str, text: str) -> ChatMessage:
        msg = ChatMessage(role, text)
        container = self.query_one("#chat_container")
        container.mount(msg)
        container.scroll_end()
        return msg

    def system_message(self, text: str) -> None:
        self.add_message("System", text)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        if not user_input:
            return

        # Clear input field
        self.query_one("#chat_input", Input).value = ""

        # Display user message
        self.add_message("User", user_input)
        self.chat_history.append({"role": "user", "content": user_input})

        # Create empty DAN message for streaming
        dan_msg = self.add_message("DAN", "")
        self.generate_response(dan_msg)

    @work(thread=True)
    def generate_response(self, dan_msg: ChatMessage) -> None:
        try:
            url = f"{self.myclaw_url}/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model_id,
                "messages": self.chat_history,
                "stream": True,
            }

            full_response = ""

            with httpx.Client(timeout=300) as client:
                with client.stream(
                    "POST", url, json=payload, headers=headers
                ) as response:
                    if response.status_code != 200:
                        raise Exception(f"HTTP {response.status_code}")

                    for line in response.iter_lines():
                        if not line:
                            continue

                        line_str = (
                            line.decode("utf-8") if isinstance(line, bytes) else line
                        )

                        # Skip empty or non-data lines
                        if not line_str.strip() or not line_str.startswith("data"):
                            continue

                        # Extract JSON from data: prefix
                        data = line_str
                        if line_str.startswith("data:"):
                            data = line_str[5:].strip()

                        if data == "[DONE]":
                            break
                        if not data:
                            continue

                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        # Get delta content from chunk
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "") or ""
                        reasoning = delta.get("reasoning", "") or ""

                        if content or reasoning:
                            chunk_text = reasoning + content if reasoning else content
                            full_response += chunk_text
                            # Only pass the new chunk to append
                            self.app.call_from_thread(dan_msg.append_text, chunk_text)
                            self.app.call_from_thread(
                                self.query_one("#chat_container").scroll_end
                            )

            # Extract answer at the end
            final_response = extract_answer(full_response)
            # Store full response in history so model sees its full output
            self.chat_history.append({"role": "assistant", "content": full_response})

        except Exception as e:
            err_msg = str(e)
            self.app.call_from_thread(self.system_message, f"Stream error: {err_msg}")
            if "connection" in err_msg.lower() or "closed" in err_msg.lower():
                self.app.call_from_thread(
                    self.system_message, "Retrying with non-streaming..."
                )
                self.generate_response_fallback(dan_msg)

    def generate_response_fallback(self, dan_msg: ChatMessage) -> None:
        try:
            url = f"{self.myclaw_url}/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model_id,
                "messages": self.chat_history,
                "stream": False,
            }

            with httpx.Client(timeout=300) as client:
                response = client.post(url, json=payload, headers=headers)
                if response.status_code != 200:
                    self.app.call_from_thread(
                        self.system_message, f"Server error: {response.text}"
                    )
                    return

                result = response.json()

                if "error" in result:
                    self.app.call_from_thread(
                        self.system_message,
                        f"MyClaw error: {result.get('error')}\n{result.get('traceback', '')}",
                    )
                    return

                content = ""
                reasoning = ""
                if isinstance(result, dict):
                    if "message" in result:
                        msg = result.get("message", {})
                        if isinstance(msg, dict):
                            content = msg.get("content", "") or ""
                            reasoning = msg.get("reasoning", "") or ""
                    elif "choices" in result:
                        choices = result.get("choices", [])
                        if choices and isinstance(choices[0], dict):
                            msg = choices[0].get("message", {})
                            if isinstance(msg, dict):
                                content = msg.get("content", "") or ""
                                reasoning = msg.get("reasoning", "") or ""

                full_response = reasoning + content if reasoning else content
                answer_text = extract_answer(full_response)

                if not answer_text:
                    self.app.call_from_thread(
                        self.system_message, f"Unexpected response format: {result}"
                    )
                    return

                self.app.call_from_thread(dan_msg.append_text, answer_text)
                self.app.call_from_thread(self.query_one("#chat_container").scroll_end)

                self.chat_history.append({"role": "assistant", "content": answer_text})

        except Exception as e:
            self.app.call_from_thread(self.system_message, f"Fallback also failed: {e}")


if __name__ == "__main__":
    app = DANApp()
    app.run()
