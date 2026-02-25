import sys
import os
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Horizontal
from textual.widgets import Header, Footer, Input, Static, Markdown
from textual import work
import ollama
from settings import OLLAMA_MODEL, OLLAMA_URL, SYSTEM_PROMPT

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
    """Textual App to chat with DAN-Qwen3-1.7B via Ollama."""
    
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

        self.chat_history = []
        system_prompt = SYSTEM_PROMPT

        bootstrap_file = "bootstrap.md"
        if os.path.exists(bootstrap_file):
            try:
                with open(bootstrap_file, "r", encoding="utf-8") as f:
                    bootstrap_content = f.read()
                system_prompt += f"\n\n--- BOOTSTRAP INSTRUCTIONS (Perform these immediately) ---\n{bootstrap_content}"
                os.remove(bootstrap_file)
                self.add_message("System", f"Loaded and deleted {bootstrap_file}.")
            except Exception as e:
                self.add_message("System", f"Failed to process {bootstrap_file}: {e}")

        self.chat_history.append({"role": "system", "content": system_prompt})
        
        self.add_message("System", f"Ready to chat with Ollama. Model: {self.model_id}")

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
            client = ollama.Client(host=OLLAMA_URL)
            stream = client.chat(
                model=self.model_id,
                messages=self.chat_history,
                stream=True,
            )
            
            full_response = ""
            is_thinking = False
            
            for chunk in stream:
                chunk_text = ""
                
                if hasattr(chunk, 'message'):
                    thinking = getattr(chunk.message, 'thinking', '') or ''
                    content = getattr(chunk.message, 'content', '') or ''
                elif isinstance(chunk, dict):
                    msg = chunk.get('message', {})
                    thinking = msg.get('thinking', '') or ''
                    content = msg.get('content', '') or ''
                else:
                    thinking = ""
                    content = ""
                    
                if thinking:
                    if not is_thinking:
                        chunk_text += "_Thinking..._\n\n> "
                        is_thinking = True
                    # Replace newlines with newlines + blockquote for formatting
                    chunk_text += thinking.replace('\n', '\n> ')
                
                if content:
                    if is_thinking:
                        chunk_text += "\n\n"
                        is_thinking = False
                    chunk_text += content
                    
                if chunk_text:
                    full_response += chunk_text
                    self.app.call_from_thread(dan_msg.append_text, chunk_text)
                    self.app.call_from_thread(self.query_one("#chat_container").scroll_end)

            self.chat_history.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            self.app.call_from_thread(self.system_message, f"Generation encountered an error: {e}")

if __name__ == "__main__":
    app = DANApp()
    app.run()
