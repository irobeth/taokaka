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
from profanity import SEVERITY_LABELS

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

_WIDTH = 250
_HEIGHT = 75
_BODY_H = _HEIGHT - 3  # header takes 3 rows

_PANELS = ["online", "pipeline", "conversation", "memory_tree", "memories", "trace", "zeitgeist", "thoughts", "prompt"]

# Explicit heights for every panel (including border).
# Inner content lines = height - 2.
_LEFT_ONLINE_H = 20
_LEFT_STATUS_H = 16
_LEFT_PIPELINE_H = _BODY_H - _LEFT_STATUS_H - _LEFT_ONLINE_H  # fills left remainder

_PANEL_H = {
    "conversation": 16,
    "trace":        14,
    "prompt":       _BODY_H - 16 - 14,          # fills center remainder
    "status":       _LEFT_STATUS_H,
    "online":       _LEFT_ONLINE_H,
    "pipeline":     _LEFT_PIPELINE_H,
    "zeitgeist":    10,
    "thoughts":     12,
    "memory_tree":  (_BODY_H - 10 - 12) // 2,
    "memories":     _BODY_H - 10 - 12 - (_BODY_H - 10 - 12) // 2,
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
    def __init__(self, signals, raw_mode=False):
        self.signals = signals
        self._entries = deque(maxlen=500)  # unified log + trace
        self._lock = threading.Lock()
        self._started = False
        self._raw_mode = raw_mode
        self._real_stdout = sys.stdout
        self._console = Console(width=_WIDTH, highlight=False, file=sys.__stdout__)

        self._active_panel_idx = 0
        self._include_raw = False
        # pages_back: 0 = last page (tail / most recent), higher = further back
        self._pages = {p: 0 for p in _PANELS}

        self._tree_cursor = 0           # index into self._tree_selectable
        self._tree_selectable = []      # list of (all_lines_index, memory_id) built during render
        self._tree_total_lines = 0      # total line count, set during render
        self._delete_confirm_id = None  # memory ID pending delete confirmation
        self._delete_memory_fn = None   # callback wired from main.py
        self._stt = None                # STT reference wired from main.py
        self._factory_reset_fn = None   # callback wired from main.py
        self._factory_reset_pending = False

        # Text input mode
        self._typing_mode = False
        self._typing_buffer = ""
        self._submit_text_fn = None     # callback wired from main.py

    # ── Public API ────────────────────────────────────────────────────────

    def log(self, message: str, source: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._entries.append((ts, source, str(message), None))
        if self._raw_mode or not self._started:
            prefix = f"[{source}] " if source else ""
            self._real_stdout.write(f"{ts} {prefix}{message}\n")
            self._real_stdout.flush()

    def trace(self, message: str, source: str = "", level: str = "debug"):
        ts = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._entries.append((ts, source, str(message), level.lower()))
        if self._raw_mode:
            prefix = f"[{source}] " if source else ""
            lvl = level.upper()
            self._real_stdout.write(f"{ts} {lvl} {prefix}{message}\n")
            self._real_stdout.flush()

    def start(self):
        if self._raw_mode:
            self._real_stdout = sys.stdout
            sys.stdout = _StdoutCapture(self.log)
            self._started = True
            self._real_stdout.write("Raw output mode — dashboard disabled\n")
            self._real_stdout.flush()
            return

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

    # Panel name -> shortcut key
    _PANEL_KEYS = {
        b"o": "online",
        b"i": "pipeline",
        b"c": "conversation",
        b"b": "memory_tree",
        b"e": "memories",
        b"l": "trace",
        b"z": "zeitgeist",
        b"h": "thoughts",
        b"p": "prompt",
    }

    def _select_panel(self, name):
        with self._lock:
            if name in _PANELS:
                self._active_panel_idx = _PANELS.index(name)

    def _cycle_panel(self):
        with self._lock:
            self._active_panel_idx = (self._active_panel_idx + 1) % len(_PANELS)

    def _cycle_panel_back(self):
        with self._lock:
            self._active_panel_idx = (self._active_panel_idx - 1) % len(_PANELS)

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

    def _cursor_up(self):
        if _PANELS[self._active_panel_idx] != "memory_tree":
            return
        with self._lock:
            if self._tree_selectable and self._tree_cursor > 0:
                self._tree_cursor -= 1
                self._auto_scroll_to_cursor()

    def _cursor_down(self):
        if _PANELS[self._active_panel_idx] != "memory_tree":
            return
        with self._lock:
            if self._tree_selectable and self._tree_cursor < len(self._tree_selectable) - 1:
                self._tree_cursor += 1
                self._auto_scroll_to_cursor()

    def _auto_scroll_to_cursor(self):
        """Adjust pagination so cursor row is visible. Called under self._lock."""
        if not self._tree_selectable:
            return
        cursor_line_idx = self._tree_selectable[self._tree_cursor][0]
        page_size = _INNER["memory_tree"]
        total_pages = max(1, math.ceil(self._tree_total_lines / page_size))
        cursor_page = (cursor_line_idx // page_size) + 1
        self._pages["memory_tree"] = total_pages - cursor_page

    def _request_delete(self):
        if _PANELS[self._active_panel_idx] != "memory_tree":
            return
        with self._lock:
            if not self._tree_selectable:
                return
            _, mem_id = self._tree_selectable[self._tree_cursor]
            self._delete_confirm_id = mem_id

    def _do_delete_confirmed(self):
        """Actually delete. Called under self._lock."""
        mem_id = self._delete_confirm_id
        if not mem_id:
            return
        self.signals.forced_memory_ids.discard(mem_id)
        if self._delete_memory_fn:
            try:
                self._delete_memory_fn(mem_id)
            except Exception:
                pass
        # Clamp cursor after deletion
        if self._tree_cursor >= len(self._tree_selectable) - 1:
            self._tree_cursor = max(0, self._tree_cursor - 1)

    def _toggle_local_stt(self):
        if self._stt:
            self._stt.enabled = not self._stt.enabled
            state = "ON" if self._stt.enabled else "OFF"
            self.log(f"Local STT: {state}", source="Interface")

    def _toggle_forced(self):
        if _PANELS[self._active_panel_idx] != "memory_tree":
            return
        with self._lock:
            if not self._tree_selectable:
                return
            _, mem_id = self._tree_selectable[self._tree_cursor]
            if mem_id in self.signals.forced_memory_ids:
                self.signals.forced_memory_ids.discard(mem_id)
            else:
                self.signals.forced_memory_ids.add(mem_id)

    def _read_input(self):
        fd = sys.__stdin__.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not self.signals.terminate:
                # Poll faster in typing mode so keystrokes aren't dropped
                timeout = 0.01 if self._typing_mode else 0.05
                if not select.select([sys.__stdin__], [], [], timeout)[0]:
                    continue
                ch = os.read(fd, 1)

                # Typing mode: capture all input into buffer (no lock needed —
                # single writer thread, render only reads for display)
                if self._typing_mode:
                    if ch == b"\x1b":
                        self._typing_buffer = ""
                        self._typing_mode = False
                        continue
                    elif ch in (b"\r", b"\n"):
                        text = self._typing_buffer.strip()
                        self._typing_buffer = ""
                        self._typing_mode = False
                        if text and self._submit_text_fn:
                            self._submit_text_fn(text)
                        continue
                    elif ch in (b"\x7f", b"\x08"):
                        self._typing_buffer = self._typing_buffer[:-1]
                        continue
                    else:
                        try:
                            c = ch.decode("utf-8", errors="ignore")
                            if c and c.isprintable():
                                self._typing_buffer += c
                        except Exception:
                            pass
                        continue

                # Factory reset confirmation intercept
                if self._factory_reset_pending:
                    if ch in (b"y", b"Y"):
                        self._factory_reset_pending = False
                        if self._factory_reset_fn:
                            self._factory_reset_fn()
                            self.log("FACTORY RESET COMPLETE — all memories and curiosities wiped.", source="Interface")
                    else:
                        self._factory_reset_pending = False
                    continue

                # Delete confirmation intercept: next key is Y/N answer
                if self._delete_confirm_id is not None:
                    with self._lock:
                        if ch in (b"y", b"Y"):
                            self._do_delete_confirmed()
                        self._delete_confirm_id = None
                    continue

                if ch == b"\t":
                    self._cycle_panel()
                elif ch == b"`":
                    self._typing_buffer = ""
                    self._typing_mode = True
                elif ch == b"a":
                    cur = self.signals.audio_mode
                    self.signals.audio_mode = "discord" if cur == "local" else "local"
                elif ch == b"r":
                    with self._lock:
                        self._include_raw = not self._include_raw
                elif ch in self._PANEL_KEYS:
                    self._select_panel(self._PANEL_KEYS[ch])
                elif ch in (b"\r", b"\n"):
                    self._toggle_forced()
                elif ch == b"\x1b":
                    if select.select([sys.__stdin__], [], [], 0.05)[0]:
                        seq = os.read(fd, 2)
                        if seq == b"[Z":      # shift+tab
                            self._cycle_panel_back()
                        elif seq == b"[D":      # left arrow
                            self._page_back()
                        elif seq == b"[C":    # right arrow
                            self._page_forward()
                        elif seq == b"[A":    # up arrow
                            self._cursor_up()
                        elif seq == b"[B":    # down arrow
                            self._cursor_down()
                        elif seq == b"[1":    # function keys (\x1b[1X~)
                            if select.select([sys.__stdin__], [], [], 0.05)[0]:
                                tail = os.read(fd, 2)
                                if tail == b"5~":   # F5
                                    self._toggle_local_stt()
                        elif seq == b"[2":    # F9-F12 (\x1b[2X~)
                            if select.select([sys.__stdin__], [], [], 0.05)[0]:
                                tail = os.read(fd, 2)
                                if tail == b"4~":   # F12
                                    self._factory_reset_pending = True
                        elif seq == b"[3":    # Delete key (\x1b[3~)
                            if select.select([sys.__stdin__], [], [], 0.05)[0]:
                                tail = os.read(fd, 1)
                                if tail == b"~":
                                    self._request_delete()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    # ── Pagination helpers ────────────────────────────────────────────────

    def _border(self, name: str) -> str:
        return "cyan" if _PANELS[self._active_panel_idx] == name else "#BF00FF"

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
        raw_label = (
            "[bold green]Include Raw: ON[/bold green]"
            if self._include_raw
            else "[dim]Include Raw: OFF[/dim]"
        )

        mode_color = "green" if s.audio_mode == "local" else "yellow"
        mode_label = f"[{mode_color}]{s.audio_mode}[/{mode_color}]"

        # Attention span bar
        elapsed = time.time() - s.last_message_time if s.last_message_time else 0
        remaining = max(0, s.patience - elapsed)
        ratio = min(1.0, elapsed / s.patience) if s.patience > 0 else 0
        bar_width = 12
        filled = int(bar_width * (1 - ratio))
        empty = bar_width - filled
        if ratio >= 1.0:
            bar_color = "red"
        elif ratio >= 0.7:
            bar_color = "yellow"
        else:
            bar_color = "green"
        bar = f"[{bar_color}]{'█' * filled}{'░' * empty}[/{bar_color}] [dim]{int(remaining)}s[/dim]"

        rating = SEVERITY_LABELS.get(s.max_profanity_severity, "?")

        left = Text.from_markup(
            f" {dot(s.stt_ready)} STT {'[green]ON[/green]' if self._stt and self._stt.enabled else '[red]OFF[/red]'}  "
            f"{dot(s.tts_ready)} TTS  "
            f"{dot(disc_up)} Discord  "
            f"[dim]│[/dim]  Mode: {mode_label}  "
            f"[dim]│[/dim]  Engine: [cyan]{s.tts_engine}[/cyan]  "
            f"[dim]│[/dim]  Rating: [yellow]{rating}[/yellow]  "
            f"[dim]│[/dim]  Attention Span: {bar}  "
            f"[dim]│[/dim]  {system_label}"
            f"  [dim]│[/dim]  [cyan]{active_name}[/cyan]"
        )
        right = Text.from_markup(raw_label)

        # Pad between left and right so the raw toggle is right-aligned
        gap = max(1, _WIDTH - 4 - left.cell_len - right.cell_len)  # -4 for panel border/padding
        text = Text()
        text.append_text(left)
        text.append(" " * gap)
        text.append_text(right)

        # Factory reset confirmation overlay
        if self._factory_reset_pending:
            text.append_text(Text.from_markup(
                "\n [bold red blink]!! FACTORY RESET — ERASE ALL MEMORIES AND CURIOSITIES? !![/bold red blink]"
                "\n [bold red]This cannot be undone. Press Y to confirm, any other key to cancel.[/bold red]"
            ))
        # Typing mode overlay (no lock — single writer, render only reads)
        elif self._typing_mode:
            buf = self._typing_buffer
            typing_text = Text.from_markup(
                f"\n [bold yellow]> [/bold yellow][white]{buf}[/white][blink]▌[/blink]"
                f"  [dim](Enter to send, Esc to cancel)[/dim]"
            )
            text.append_text(typing_text)

        return Panel(
            text,
            title="[bold white]✦ TAOKAKA ✦[/bold white]",
            box=box.HEAVY,
            padding=(0, 1),
            height=5 if (self._typing_mode or self._factory_reset_pending) else None,
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
        if prompt and not self._include_raw:
            # Strip the raw response section appended by the LLM wrapper
            marker = "\n\n═══ RAW RESPONSE ═══\n"
            idx = prompt.find(marker)
            if idx != -1:
                prompt = prompt[:idx]
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
            title="[bold dim]Last [u]P[/u]rompt Details[/bold dim]",
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
            title="[bold][u]C[/u]onversation[/bold]",
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
            title="[bold][u]L[/u]og[/bold]",
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
            title="[bold][u]O[/u]nline[/bold]",
            subtitle=self._subtitle(pg, total),
            subtitle_align="right",
            box=box.ROUNDED,
            padding=(0, 1),
            border_style=self._border("online"),
        )

    def _render_pipeline(self):
        s = self.signals
        text = Text(overflow="fold")
        text.append("\n")

        # Core prompt-loop signals
        new_msg = "[green]YES[/green]" if s.new_message else "[dim]no[/dim]"
        text.append_text(Text.from_markup(f"  new_message: {new_msg}\n"))

        thinking = "[yellow]YES[/yellow]" if s.AI_thinking else "[dim]no[/dim]"
        text.append_text(Text.from_markup(f"  AI_thinking: {thinking}\n"))

        speaking = "[yellow]YES[/yellow]" if s.AI_speaking else "[dim]no[/dim]"
        text.append_text(Text.from_markup(f"  AI_speaking: {speaking}\n"))

        human = "[cyan]YES[/cyan]" if s.human_speaking else "[dim]no[/dim]"
        text.append_text(Text.from_markup(f"  human_speaking: {human}\n"))

        # Pending queues
        twitch_n = len(s.recentTwitchMessages)
        discord_n = len(s.recentDiscordMessages)
        history_n = len(s.history)
        text.append_text(Text.from_markup(f"  [dim]local queue:[/dim]   {history_n} msgs\n"))
        text.append_text(Text.from_markup(f"  [dim]discord queue:[/dim] {discord_n}\n"))
        text.append_text(Text.from_markup(f"  [dim]twitch queue:[/dim]  {twitch_n}\n"))

        try:
            sio_depth = s.sio_queue.qsize()
        except Exception:
            sio_depth = "?"
        text.append_text(Text.from_markup(f"  [dim]sio_queue:[/dim]    {sio_depth}\n"))

        # Extractor signals
        ext = s.extractor_signals
        text.append("\n")
        text.append_text(Text.from_markup("  [bold dim]Extractor Signals[/bold dim]\n"))
        if ext:
            for key, val in ext.items():
                if isinstance(val, list):
                    display = ", ".join(str(v) for v in val[:8])
                    if len(val) > 8:
                        display += f" (+{len(val) - 8})"
                else:
                    display = str(val)[:60]
                text.append(f"  {key}: ", style="dim cyan")
                text.append(f"{display}\n", style="dim")
        else:
            text.append("  [none]\n", style="dim")

        all_lines = text.plain.splitlines()
        pg = 1
        total = 1

        return Panel(
            text,
            title="[bold]P[u]i[/u]peline[/bold]",
            subtitle=self._subtitle(pg, total),
            subtitle_align="right",
            box=box.ROUNDED,
            padding=(0, 1),
            border_style=self._border("pipeline"),
        )

    def _render_zeitgeist(self):
        z = self.signals.zeitgeist
        text = Text(overflow="fold")
        keywords = self.signals.extractor_signals.get("keywords", [])
        if z:
            full = z
            if keywords:
                full += "\n[keywords] " + ", ".join(keywords[:12])
            lines = full.splitlines()
            visible, pg, total = self._paginate(lines, "zeitgeist")
            text.append("\n".join(visible), style="italic dim white")
        else:
            pg, total = 1, 1
            text.append("Waiting for enough conversation…", style="dim")
        return Panel(
            text,
            title="[bold][u]Z[/u]eitgeist[/bold]",
            subtitle=self._subtitle(pg, total),
            subtitle_align="right",
            box=box.ROUNDED,
            padding=(0, 1),
            border_style=self._border("zeitgeist"),
        )

    def _render_thoughts(self):
        thoughts = self.signals.recent_thoughts
        text = Text(overflow="fold")
        if thoughts:
            all_lines = []
            for entry in thoughts:
                ts = datetime.fromtimestamp(entry["timestamp"]).strftime("%H:%M:%S")
                for line in entry["thought"].splitlines():
                    if line.strip():
                        all_lines.append((ts, line.strip()))
                        ts = ""  # only show timestamp on first line
            visible, pg, total = self._paginate(all_lines, "thoughts")
            for ts, line in visible:
                if ts:
                    text.append(f"{ts} ", style="dim")
                text.append(f"{line}\n", style="dim magenta")
        else:
            pg, total = 1, 1
            text.append("No thoughts yet", style="dim")
        return Panel(
            text,
            title="[bold]T[u]h[/u]oughts[/bold]",
            subtitle=self._subtitle(pg, total),
            subtitle_align="right",
            box=box.ROUNDED,
            padding=(0, 1),
            border_style=self._border("thoughts"),
        )

    def _render_memory_tree(self):
        all_mems = self.signals.all_memories
        forced_ids = self.signals.forced_memory_ids

        # Group memories by type
        from collections import defaultdict
        grouped = defaultdict(list)
        for mem in all_mems:
            meta = mem.get("metadata", {})
            mem_type = meta.get("type", "unknown")
            grouped[mem_type].append(mem)

        # Build lines for pagination: we flatten the tree into styled text lines
        # because Rich Tree cannot be sliced for pagination directly.
        # Each line is (content, style, mem_id_or_None)
        all_lines = []
        selectable = []  # list of (line_index, memory_id)
        all_lines.append((f"Memories ({len(all_mems)} total)", "bold", None))

        # Display types in a fixed order, skip empty ones
        type_order = ["core", "personal", "about_user", "opinion", "definition",
                      "long_term", "short_term", "long-term", "short-term", "unknown"]
        for mem_type in type_order:
            entries = grouped.get(mem_type, [])
            if not entries:
                continue
            all_lines.append((f"  {mem_type} ({len(entries)})", "bold yellow", None))
            for entry in entries:
                meta = entry.get("metadata", {})
                title = meta.get("title", "")
                doc = entry.get("document", "")
                mem_id = entry.get("id", "")
                # Truncate long documents
                display = doc[:55] + "..." if len(doc) > 55 else doc
                # Show related_user if present
                user = meta.get("related_user", "")
                if user and user != "personal":
                    display = f"[{user}] {display}"
                line_idx = len(all_lines)
                selectable.append((line_idx, mem_id))
                if title:
                    all_lines.append(("title_line", ("    ", title, display), mem_id))
                else:
                    all_lines.append((f"    {display}", "dim", mem_id))

        if len(all_mems) == 0:
            all_lines.append(("  No memories stored", "dim", None))

        # Store selectable list and total lines for cursor navigation
        with self._lock:
            self._tree_selectable = selectable
            self._tree_total_lines = len(all_lines)
            # Clamp cursor
            if selectable:
                self._tree_cursor = min(self._tree_cursor, len(selectable) - 1)
            else:
                self._tree_cursor = 0
            current_cursor = self._tree_cursor
            confirm_id = self._delete_confirm_id

        visible, pg, total = self._paginate(all_lines, "memory_tree")

        # Determine the absolute start index of visible lines
        page_size = _INNER["memory_tree"]
        total_pages = max(1, math.ceil(len(all_lines) / page_size))
        pages_back = self._pages.get("memory_tree", 0)
        current_page = total_pages - pages_back
        abs_start = (current_page - 1) * page_size

        # Build the cursor line index (absolute) from selectable
        cursor_abs_idx = None
        cursor_mem_id = None
        if selectable and current_cursor < len(selectable):
            cursor_abs_idx = selectable[current_cursor][0]
            cursor_mem_id = selectable[current_cursor][1]

        text = Text(overflow="fold")
        for i, (content, style, mem_id) in enumerate(visible):
            abs_idx = abs_start + i
            is_cursor = (abs_idx == cursor_abs_idx)

            # Delete confirmation overlay
            if is_cursor and confirm_id is not None and confirm_id == mem_id:
                text.append(">> Delete? [Y/N] <<\n", style="bold red")
                continue

            # Forced prefix
            forced_prefix = "[F] " if mem_id and mem_id in forced_ids else ""

            if is_cursor:
                # Cursor row: bold cyan with >> prefix
                if content == "title_line":
                    indent, title, doc = style
                    text.append(f">> {forced_prefix}", style="bold cyan")
                    text.append(title, style="bold cyan")
                    text.append(f" {doc}\n", style="bold cyan")
                else:
                    text.append(f">> {forced_prefix}{content}\n", style="bold cyan")
            elif content == "title_line":
                indent, title, doc = style
                text.append(f"{indent}{forced_prefix}")
                text.append(title, style="bold bright_white")
                text.append(f" {doc}\n", style="dim")
            else:
                if forced_prefix and mem_id:
                    text.append(f"    {forced_prefix}{content.lstrip()}\n", style=style)
                else:
                    text.append(f"{content}\n", style=style)

        return Panel(
            text,
            title="[bold]Memory [u]B[/u]rowser[/bold]",
            subtitle=self._subtitle(pg, total),
            subtitle_align="right",
            box=box.ROUNDED,
            padding=(0, 1),
            border_style=self._border("memory_tree"),
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
        # Forced section
        forced_ids = self.signals.forced_memory_ids
        all_lines.append(("", ""))
        all_lines.append(("Forced", "bold dim"))
        if forced_ids:
            id_to_doc = {m["id"]: m["document"] for m in self.signals.all_memories}
            for fid in forced_ids:
                doc = id_to_doc.get(fid, "(deleted)")
                all_lines.append((f"  * {doc}", "dim magenta"))
        else:
            all_lines.append(("  none", "dim"))

        # Curiosities section
        curiosities = self.signals.extractor_signals.get("curiosities", [])
        all_lines.append(("", ""))
        all_lines.append(("Curious About", "bold dim"))
        if curiosities:
            for c in curiosities[:5]:
                all_lines.append((f"  ? {c}", "dim yellow"))
        else:
            all_lines.append(("  nothing yet", "dim"))

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
            title="[bold]M[u]e[/u]mory[/bold]",
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
            Layout(name="left", ratio=2),
            Layout(name="center", ratio=7),
            Layout(name="right", ratio=3),
        )
        layout["left"].split_column(
            Layout(name="status", size=_PANEL_H["status"]),
            Layout(name="online", size=_PANEL_H["online"]),
            Layout(name="pipeline"),
        )
        layout["center"].split_column(
            Layout(name="conversation", size=_PANEL_H["conversation"]),
            Layout(name="prompt"),
            Layout(name="trace", size=_PANEL_H["trace"]),
        )
        layout["right"].split_column(
            Layout(name="zeitgeist", size=_PANEL_H["zeitgeist"]),
            Layout(name="thoughts", size=_PANEL_H["thoughts"]),
            Layout(name="memory_tree", size=_PANEL_H["memory_tree"]),
            Layout(name="memories"),
        )

        with Live(layout, console=self._console, refresh_per_second=60, screen=True):
            while not self.signals.terminate:
                try:
                    layout["header"].update(self._render_header())
                    layout["status"].update(self._render_status())
                    layout["prompt"].update(self._render_prompt())
                    layout["conversation"].update(self._render_conversation())
                    layout["trace"].update(self._render_log())
                    layout["online"].update(self._render_online())
                    layout["pipeline"].update(self._render_pipeline())
                    layout["zeitgeist"].update(self._render_zeitgeist())
                    layout["thoughts"].update(self._render_thoughts())
                    layout["memory_tree"].update(self._render_memory_tree())
                    layout["memories"].update(self._render_memories())
                except Exception as e:
                    self.log(f"Dashboard render error: {e}", source="Interface")
                time.sleep(1 / 60)
