import io
import sys
import threading
import time
from collections import deque
from datetime import datetime

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

_WIDTH = 180
_HEIGHT = 60


class _StdoutCapture(io.TextIOBase):
    """Redirects stray print() calls into the dashboard log."""

    def __init__(self, log_fn):
        self._log = log_fn
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._log(line)
        return len(s)

    def flush(self):
        pass


class Interface:
    def __init__(self, signals):
        self.signals = signals
        self._log_entries = deque(maxlen=300)
        self._lock = threading.Lock()
        self._started = False
        self._real_stdout = sys.stdout
        self._console = Console(width=_WIDTH, highlight=False)

    # ── Public API ────────────────────────────────────────────────────────

    def log(self, message: str, source: str = ""):
        """Thread-safe drop-in for print(). source= tags the entry."""
        ts = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._log_entries.append((ts, source, str(message)))
        if not self._started:
            prefix = f"[{source}] " if source else ""
            self._real_stdout.write(f"{ts} {prefix}{message}\n")
            self._real_stdout.flush()

    def start(self):
        """Resize terminal, capture stdout, launch dashboard thread."""
        self._real_stdout.write(f"\033[8;{_HEIGHT};{_WIDTH}t")
        self._real_stdout.flush()
        time.sleep(0.15)

        self._real_stdout = sys.stdout
        sys.stdout = _StdoutCapture(self.log)
        self._started = True

        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def stop(self):
        sys.stdout = self._real_stdout

    # ── Rendering ─────────────────────────────────────────────────────────

    def _render_header(self):
        s = self.signals

        def dot(ok):
            return "[green]●[/green]" if ok else "[red]●[/red]"

        disc_up = bool(s.discord_vc and s.discord_vc.is_connected())
        system_label = (
            "[bold green]SYSTEM READY[/bold green]"
            if (s.stt_ready and s.tts_ready)
            else "[bold yellow]STARTING…[/bold yellow]"
        )

        text = Text.from_markup(
            f" {dot(s.stt_ready)} STT  "
            f"{dot(s.tts_ready)} TTS  "
            f"{dot(disc_up)} Discord  "
            f"[dim]│[/dim]  Engine: [cyan]{s.tts_engine}[/cyan]  "
            f"[dim]│[/dim]  Patience: [cyan]{s.patience}s[/cyan]  "
            f"[dim]│[/dim]  {system_label}"
        )
        return Panel(
            text,
            title="[bold white]✦ TIFERET ✦[/bold white]",
            box=box.HEAVY,
            padding=(0, 1),
        )

    def _render_status(self):
        s = self.signals

        def row(label, active, on_text="active", off_text="idle"):
            dot = "[bold green]●[/bold green]" if active else "[dim]○[/dim]"
            l_style = "bold green" if active else "dim"
            d_style = "green" if active else "dim"
            detail = on_text if active else off_text
            return Text.from_markup(
                f"  {dot} [{l_style}]{label}[/{l_style}] [dim]·[/dim] [{d_style}]{detail}[/{d_style}]\n"
            )

        text = Text()
        text.append("\n")
        text.append_text(row("Human  ", s.human_speaking, "speaking"))
        text.append_text(row("Thinking", s.AI_thinking, "thinking"))
        text.append_text(row("Speaking", s.AI_speaking, "speaking"))
        text.append("\n")

        if s.active_voice_user:
            text.append_text(
                Text.from_markup(
                    f"  [dim]Voice user[/dim]\n  [bold cyan]{s.active_voice_user}[/bold cyan]\n"
                )
            )
        text.append("\n")

        if disc_up := (s.discord_vc and s.discord_vc.is_connected()):
            text.append_text(Text.from_markup("  [green]● Discord voice[/green]\n"))
        else:
            text.append_text(Text.from_markup("  [dim]○ Discord voice[/dim]\n"))

        return Panel(text, title="[bold]Status[/bold]", box=box.ROUNDED, padding=(0, 1))

    def _render_conversation(self):
        history = list(self.signals.history)[-50:]
        text = Text(overflow="fold")
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "").strip()
            if not content:
                continue
            if role == "assistant":
                text.append("Tiferet", style="bold magenta")
                text.append(f": {content}\n", style="magenta")
            else:
                if ": " in content:
                    name, rest = content.split(": ", 1)
                    text.append(name, style="bold cyan")
                    text.append(f": {rest}\n", style="cyan")
                else:
                    text.append(f"{content}\n", style="cyan")

        return Panel(
            text, title="[bold]Conversation[/bold]", box=box.ROUNDED, padding=(0, 1)
        )

    def _render_log(self):
        with self._lock:
            entries = list(self._log_entries)
        text = Text(overflow="fold")
        for ts, source, message in entries:
            text.append(f"{ts} ", style="dim")
            if source:
                text.append(f"{source} ", style="yellow dim")
            text.append(f"{message}\n")

        return Panel(text, title="[bold]Log[/bold]", box=box.ROUNDED, padding=(0, 1))

    def _run(self):
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
        )
        layout["body"].split_row(
            Layout(name="status", ratio=2),
            Layout(name="conversation", ratio=7),
            Layout(name="log", ratio=3),
        )

        with Live(layout, console=self._console, refresh_per_second=4, screen=True):
            while not self.signals.terminate:
                try:
                    layout["header"].update(self._render_header())
                    layout["status"].update(self._render_status())
                    layout["conversation"].update(self._render_conversation())
                    layout["log"].update(self._render_log())
                except Exception:
                    pass
                time.sleep(0.25)
