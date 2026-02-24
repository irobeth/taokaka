import io
import math
import os
import select
import sys
import termios
import threading
import time
import tty
from collections import deque
from datetime import datetime

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

_WIDTH = 250
_HEIGHT = 75
_BODY_H = _HEIGHT - 3  # header takes 3 rows

_PANELS = ["prompt", "conversation", "trace", "online", "zeitgeist", "memories"]

# Explicit heights for every panel (including border).
# Inner content lines = height - 2.
_PANEL_H = {
    "conversation": 18,
    "prompt":       _BODY_H - 18 - 14,          # 40
    "trace":        14,
    "online":       16,
    "zeitgeist":    10,
    "memories":     _BODY_H - 16 - 10,          # 46
}
_INNER = {k: v - 2 for k, v in _PANEL_H.items()}


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
        self._entries = deque(maxlen=500)  # unified log + trace
        self._lock = threading.Lock()
        self._started = False
        self._real_stdout = sys.stdout
        self._console = Console(width=_WIDTH, highlight=False, file=sys.__stdout__)

        self._active_panel_idx = 0
        # pages_back: 0 = last page (tail / most recent), higher = further back
        self._pages = {p: 0 for p in _PANELS}

    # ── Public API ────────────────────────────────────────────────────────

    def log(self, message: str, source: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._entries.append((ts, source, str(message), None))
        if not self._started:
            prefix = f"[{source}] " if source else ""
            self._real_stdout.write(f"{ts} {prefix}{message}\n")
            self._real_stdout.flush()

    def trace(self, message: str, source: str = "", level: str = "debug"):
        ts = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._entries.append((ts, source, str(message), level.lower()))

    def start(self):
        self._real_stdout.write(f"\033[8;{_HEIGHT};{_WIDTH}t")
        self._real_stdout.flush()
        time.sleep(0.15)

        self._real_stdout = sys.stdout
        sys.stdout = _StdoutCapture(self.log)
        self._started = True

        threading.Thread(target=self._run, daemon=True).start()
        threading.Thread(target=self._read_input, daemon=True).start()

    def stop(self):
        sys.stdout = self._real_stdout

    # ── Keyboard input ────────────────────────────────────────────────────

    def _cycle_panel(self):
        with self._lock:
            self._active_panel_idx = (self._active_panel_idx + 1) % len(_PANELS)

    def _page_back(self):
        """Left arrow — go one page toward older content."""
        panel = _PANELS[self._active_panel_idx]
        with self._lock:
            self._pages[panel] += 1

    def _page_forward(self):
        """Right arrow — go one page toward newer content."""
        panel = _PANELS[self._active_panel_idx]
        with self._lock:
            self._pages[panel] = max(0, self._pages[panel] - 1)

    def _read_input(self):
        fd = sys.__stdin__.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not self.signals.terminate:
                if not select.select([sys.__stdin__], [], [], 0.05)[0]:
                    continue
                ch = os.read(fd, 1)
                if ch == b"\t":
                    self._cycle_panel()
                elif ch == b"\x1b":
                    if select.select([sys.__stdin__], [], [], 0.05)[0]:
                        seq = os.read(fd, 2)
                        if seq == b"[D":      # left arrow → page back
                            self._page_back()
                        elif seq == b"[C":    # right arrow → page forward
                            self._page_forward()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    # ── Pagination helpers ────────────────────────────────────────────────

    def _border(self, name: str) -> str:
        return "cyan" if _PANELS[self._active_panel_idx] == name else ""

    def _paginate(self, items: list, panel: str):
        """Return (visible_items, current_page_1indexed, total_pages)."""
        page_size = _INNER[panel]
        total = len(items)
        total_pages = max(1, math.ceil(total / page_size))
        pages_back = min(self._pages.get(panel, 0), total_pages - 1)
        # clamp stored value so it doesn't drift beyond content
        self._pages[panel] = pages_back
        page = total_pages - pages_back          # 1-indexed
        start = (page - 1) * page_size
        return items[start:start + page_size], page, total_pages

    def _subtitle(self, page: int, total: int):
        if total <= 1:
            return None
        return f"[dim]{page}/{total}[/dim]"

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
        active_name = _PANELS[self._active_panel_idx]

        text = Text.from_markup(
            f" {dot(s.stt_ready)} STT  "
            f"{dot(s.tts_ready)} TTS  "
            f"{dot(disc_up)} Discord  "
            f"[dim]│[/dim]  Engine: [cyan]{s.tts_engine}[/cyan]  "
            f"[dim]│[/dim]  Patience: [cyan]{s.patience}s[/cyan]  "
            f"[dim]│[/dim]  {system_label}"
            f"  [dim]│[/dim]  [cyan]{active_name}[/cyan]"
        )
        return Panel(
            text,
            title="[bold white]✦ TAOKAKA ✦[/bold white]",
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

        if s.discord_vc and s.discord_vc.is_connected():
            text.append_text(Text.from_markup("  [green]● Discord voice[/green]\n"))
        else:
            text.append_text(Text.from_markup("  [dim]○ Discord voice[/dim]\n"))

        if s.stt_workers:
            text.append("\n")
            text.append_text(Text.from_markup("  [dim]STT recorders[/dim]\n"))
            for entry in s.stt_workers:
                name = entry.get("name", "?")
                status = entry.get("status", "idle")
                if status == "speaking":
                    text.append_text(Text.from_markup(f"  [bold green]●[/bold green] [green]{name}[/green] [green]speaking[/green]\n"))
                elif status == "transcribing":
                    text.append_text(Text.from_markup(f"  [bold yellow]●[/bold yellow] [yellow]{name}[/yellow] [yellow]transcribing[/yellow]\n"))
                else:
                    text.append_text(Text.from_markup(f"  [dim]○ {name} idle[/dim]\n"))

        return Panel(text, title="[bold]Status[/bold]", box=box.ROUNDED, padding=(0, 1))

    def _render_prompt(self):
        prompt = self.signals.last_full_prompt
        text = Text(overflow="fold")
        if prompt:
            lines = prompt.splitlines()
            visible, pg, total = self._paginate(lines, "prompt")
            text.append("\n".join(visible), style="dim white")
        else:
            visible, pg, total = [], 1, 1
            text.append("No prompt sent yet", style="dim")
        return Panel(
            text,
            title="[bold dim]Last Prompt Details[/bold dim]",
            subtitle=self._subtitle(pg, total),
            subtitle_align="right",
            box=box.ROUNDED,
            padding=(0, 1),
            border_style=self._border("prompt"),
        )

    def _render_conversation(self):
        all_history = list(self.signals.history)
        history, pg, total = self._paginate(all_history, "conversation")
        text = Text(overflow="fold")
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "").strip()
            if not content:
                continue
            if role == "assistant":
                text.append("Taokaka", style="bold magenta")
                text.append(f": {content}\n", style="magenta")
            else:
                if ": " in content:
                    name, rest = content.split(": ", 1)
                    text.append(name, style="bold cyan")
                    text.append(f": {rest}\n", style="cyan")
                else:
                    text.append(f"{content}\n", style="cyan")

        return Panel(
            text,
            title="[bold]Conversation[/bold]",
            subtitle=self._subtitle(pg, total),
            subtitle_align="right",
            box=box.ROUNDED,
            padding=(0, 1),
            border_style=self._border("conversation"),
        )

    _LEVEL_STYLES = {
        None:      ("dim",        "yellow dim", "default"),
        "debug":   ("dim",        "dim cyan",   "dim"),
        "info":    ("dim",        "cyan",       "default"),
        "warn":    ("dim yellow", "yellow",     "yellow"),
        "error":   ("dim red",    "bold red",   "bold red"),
    }

    def _render_log(self):
        with self._lock:
            all_entries = list(self._entries)
        entries, pg, total = self._paginate(all_entries, "trace")
        text = Text(overflow="fold")
        for ts, source, message, level in entries:
            ts_style, src_style, msg_style = self._LEVEL_STYLES.get(
                level, self._LEVEL_STYLES[None]
            )
            text.append(f"{ts} ", style=ts_style)
            if source:
                text.append(f"{source} ", style=src_style)
            text.append(f"{message}\n", style=msg_style)

        return Panel(
            text,
            title="[bold]Log[/bold]",
            subtitle=self._subtitle(pg, total),
            subtitle_align="right",
            box=box.ROUNDED,
            padding=(0, 1),
            border_style=self._border("trace"),
        )

    def _render_online(self):
        text = Text()
        vc = self.signals.discord_vc
        pg, total = 1, 1
        if not vc or not vc.is_connected():
            text.append("\n  Not in a voice channel\n", style="dim")
        else:
            all_members = [m for m in vc.channel.members if not m.bot]
            members, pg, total = self._paginate(all_members, "online")
            if not members:
                text.append("\n  No one here\n", style="dim")
            else:
                text.append("\n")
                for m in members:
                    vs = m.voice
                    muted = vs and (vs.self_mute or vs.mute)
                    deafened = vs and (vs.self_deaf or vs.deaf)
                    if deafened:
                        indicator = "[dim]🔇[/dim]"
                    elif muted:
                        indicator = "[dim]🔕[/dim]"
                    else:
                        indicator = "[green]●[/green]"
                    text.append_text(
                        Text.from_markup(f"  {indicator} [cyan]{m.display_name}[/cyan]\n")
                    )
        return Panel(
            text,
            title="[bold]Online[/bold]",
            subtitle=self._subtitle(pg, total),
            subtitle_align="right",
            box=box.ROUNDED,
            padding=(0, 1),
            border_style=self._border("online"),
        )

    def _render_zeitgeist(self):
        z = self.signals.zeitgeist
        text = Text(overflow="fold")
        if z:
            lines = z.splitlines()
            visible, pg, total = self._paginate(lines, "zeitgeist")
            text.append("\n".join(visible), style="italic dim white")
        else:
            pg, total = 1, 1
            text.append("Waiting for enough conversation…", style="dim")
        return Panel(
            text,
            title="[bold]Zeitgeist[/bold]",
            subtitle=self._subtitle(pg, total),
            subtitle_align="right",
            box=box.ROUNDED,
            padding=(0, 1),
            border_style=self._border("zeitgeist"),
        )

    def _render_memories(self):
        # Build all lines as (text, style) pairs, then paginate
        all_lines = []
        recalled = self.signals.last_recalled
        all_lines.append(("Recalled", "bold dim"))
        if recalled:
            for doc in recalled:
                all_lines.append((f"  · {doc}", "dim"))
        else:
            all_lines.append(("  none yet", "dim"))
        all_lines.append(("", ""))
        recent = self.signals.recent_memories
        all_lines.append(("Generated", "bold dim"))
        if recent:
            for pair in reversed(recent):
                all_lines.append((f"  · {pair}", "dim cyan"))
        else:
            all_lines.append(("  none yet", "dim"))

        visible, pg, total = self._paginate(all_lines, "memories")
        text = Text(overflow="fold")
        for content, style in visible:
            text.append(f"{content}\n", style=style)

        return Panel(
            text,
            title="[bold]Memory[/bold]",
            subtitle=self._subtitle(pg, total),
            subtitle_align="right",
            box=box.ROUNDED,
            padding=(0, 1),
            border_style=self._border("memories"),
        )

    def _run(self):
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
        )
        layout["body"].split_row(
            Layout(name="status", ratio=2),
            Layout(name="center", ratio=7),
            Layout(name="right", ratio=3),
        )
        layout["center"].split_column(
            Layout(name="conversation", size=_PANEL_H["conversation"]),
            Layout(name="prompt", size=_PANEL_H["prompt"]),
            Layout(name="trace", size=_PANEL_H["trace"]),
        )
        layout["right"].split_column(
            Layout(name="online", size=_PANEL_H["online"]),
            Layout(name="zeitgeist", size=_PANEL_H["zeitgeist"]),
            Layout(name="memories", size=_PANEL_H["memories"]),
        )

        with Live(layout, console=self._console, refresh_per_second=4, screen=True):
            while not self.signals.terminate:
                try:
                    layout["header"].update(self._render_header())
                    layout["status"].update(self._render_status())
                    layout["prompt"].update(self._render_prompt())
                    layout["conversation"].update(self._render_conversation())
                    layout["trace"].update(self._render_log())
                    layout["online"].update(self._render_online())
                    layout["zeitgeist"].update(self._render_zeitgeist())
                    layout["memories"].update(self._render_memories())
                except Exception as e:
                    self.log(f"Dashboard render error: {e}", source="Interface")
                time.sleep(0.25)
