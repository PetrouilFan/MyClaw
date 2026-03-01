from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Horizontal
from textual.widgets import Header, Footer, Input, Static, Markdown
from textual import work
import httpx
import json
import re
from settings import OLLAMA_MODEL, SYSTEM_PROMPT, WS, MYCLAW_URL


def extract_answer(text: str) -> str:
    m = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    if "Alright, here's the response:" in text:
        return text.split("Alright, here's the response:", 1)[1].strip()
    text = text.strip()
    return (
        text[:200]
        if len(text) > 200
        else (
            "\n".join([line.strip() for line in text.split("\n") if line.strip()])
            if "\n" in text
            else text
        )
    )


def parse_response(result) -> str:
    if isinstance(result, dict):
        msg = (
            (result.get("message") or result.get("choices", [{}])[0].get("message"))
            if result.get("choices")
            else result.get("message", {})
        )
        if isinstance(msg, dict):
            return (msg.get("reasoning") or "") + (msg.get("content") or "")
    return ""


class ChatMessage(Static):
    def __init__(self, role: str, text: str, model_name: str = None):
        super().__init__()
        self.role, self.raw_text, self.model_name = role, text, model_name or "AI"
        self.markdown = Markdown(f"**{role}**: {text}")

    def on_mount(self) -> None:
        self.add_class(f"message-{self.role.lower()}")
        if self.role == "System":
            self.border_title, self.add_class = (
                "System",
                self.add_class("message-warning"),
            )
        elif self.role in ("Assistant", "DAN"):
            self.border_title, self.add_class = (
                self.model_name,
                self.add_class("message-error"),
            )
        else:
            self.border_title, self.add_class = "You", self.add_class("message-success")

    def compose(self) -> ComposeResult:
        yield self.markdown

    def append_text(self, text_chunk: str):
        self.raw_text += text_chunk
        self.markdown.update(f"**{self.role}**: {self.raw_text}")


class DANApp(App):
    CSS = """
    Screen { layout: vertical; }
    #chat_container { height: 1fr; padding: 1 2; overflow-y: scroll; }
    #input_container { height: auto; padding: 1 2; dock: bottom; }
    ChatMessage { width: 100%; margin-bottom: 1; border: round white; padding: 0 1; height: auto; }
    .message-system { border: double #d4b553; border-title-color: #d4b553; }
    .message-user { border: solid #5db85c; border-title-color: #5db85c; }
    .message-dan { border: solid #d9534f; border-title-color: #d9534f; }
    """
    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ScrollableContainer(id="chat_container")
        with Horizontal(id="input_container"):
            yield Input(id="chat_input", placeholder="Share your message...")
        yield Footer()

    def on_unmount(self) -> None:
        if hasattr(self, "http"):
            self.http.close()

    def on_mount(self) -> None:
        self.title, self.model_id, self.myclaw_url = (
            "Dan Chat",
            OLLAMA_MODEL,
            MYCLAW_URL,
        )
        self.http, self.chat_history = httpx.Client(timeout=300), []
        system_prompt = SYSTEM_PROMPT
        for md_file in [
            "identity.md",
            "personality.md",
            "user.md",
            "soul.md",
            "bootstrap.md",
        ]:
            md_path = WS / md_file
            if md_path.exists():
                try:
                    md_content = md_path.read_text(encoding="utf-8")
                    system_prompt += f"\n\n--- {md_file.replace('.md', '').replace('_', ' ').title()} ---\n{md_content}"
                    if md_file == "bootstrap.md":
                        try:
                            md_path.unlink()
                            self.add_message("System", f"Loaded and deleted {md_file}.")
                        except Exception as e:
                            self.add_message(
                                "System", f"Loaded {md_file} but failed to delete: {e}"
                            )
                    else:
                        self.add_message("System", f"Loaded {md_file}.")
                except Exception as e:
                    self.add_message("System", f"Failed to process {md_file}: {e}")
        self.chat_history.append({"role": "system", "content": system_prompt})
        self.add_message("System", f"Ready to chat with MyClaw. Endpoint: {self.myclaw_url}")

    def add_message(self, role: str, text: str, model_name: str = None) -> ChatMessage:
        msg = ChatMessage(role, text, model_name)
        container = self.query_one("#chat_container")
        container.mount(msg)
        container.scroll_end()
        return msg

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        if not user_input:
            return
        self.query_one("#chat_input", Input).value = ""
        self.add_message("User", user_input)
        self.chat_history.append({"role": "user", "content": user_input})
        dan_msg = self.add_message("Assistant", "", self.model_id)
        self.generate_response(dan_msg)

    def _make_request(self, stream: bool = True):
        url, headers = (
            f"{self.myclaw_url}/v1/chat/completions",
            {"Content-Type": "application/json"},
        )
        payload = {
            "model": self.model_id,
            "messages": self.chat_history,
            "stream": stream,
        }
        return (
            self.http.stream("POST", url, json=payload, headers=headers)
            if stream
            else self.http.post(url, json=payload, headers=headers)
        )

    @work(thread=True)
    def generate_response(self, dan_msg: ChatMessage) -> None:
        try:
            with self._make_request(stream=True) as response:
                if response.status_code != 200:
                    raise Exception(f"HTTP {response.status_code}")
                full_response = ""
                for line in response.iter_lines():
                    if not line:
                        continue
                    line_str = line.decode("utf-8") if isinstance(line, bytes) else line
                    if not line_str.strip() or not line_str.startswith("data"):
                        continue
                    data = line_str[5:].strip() if line_str.startswith("data:") else line_str
                    if data == "[DONE]" or not data:
                        continue
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        chunk_text = (delta.get("reasoning") or "") + (delta.get("content") or "")
                        if chunk_text:
                            full_response += chunk_text
                            self.app.call_from_thread(dan_msg.append_text, chunk_text)
                            self.app.call_from_thread(self.query_one("#chat_container").scroll_end)
                    except json.JSONDecodeError:
                        continue
                self.chat_history.append({"role": "assistant", "content": full_response})
        except Exception as e:
            err_msg = str(e)
            self.app.call_from_thread(self.system_message, f"Stream error: {err_msg}")
            if "connection" in err_msg.lower() or "closed" in err_msg.lower():
                self.app.call_from_thread(self.system_message, "Retrying with non-streaming...")
                self.generate_response_fallback(dan_msg)

    def generate_response_fallback(self, dan_msg: ChatMessage) -> None:
        try:
            response = self._make_request(stream=False)
            if response.status_code != 200:
                self.app.call_from_thread(self.system_message, f"Server error: {response.text}")
                return
            result = response.json()
            if "error" in result:
                self.app.call_from_thread(
                    self.system_message, f"MyClaw error: {result.get('error')}"
                )
                return
            full_response = parse_response(result)
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

    def system_message(self, text: str) -> None:
        self.add_message("System", text)


if __name__ == "__main__":
    DANApp().run()
