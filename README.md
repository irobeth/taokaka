# Taokaka

A local AI companion that listens, thinks, and talks back — through your MacBook or a Discord voice channel.

Forked from [kimjammer/neuro](https://github.com/kimjammer/neuro), which was a 7-day recreation of Neuro-Sama on consumer hardware. This fork has been substantially rewritten with the help of **Claude** (Anthropic's AI assistant). I don't really "know" Python — I know it enough to read it, debug it, and direct an AI to write it. No promises.

## What it does

Taokaka is a real-time conversational AI with voice input/output, long-term memory, a curiosity system, and a rich terminal dashboard. You talk, she listens, thinks, and responds — either through your local mic and speakers, or through a Discord voice channel.

### Audio modes (toggle with `a` key)

- **Local mode**: MacBook mic in, MacBook speakers out. The mic is automatically muted during TTS playback to prevent feedback loops. Local STT starts disabled — press `F5` to enable.
- **Discord mode**: Discord voice channel in (per-user STT), Discord voice channel out. Text messages from Discord work in both modes.

### Text input

Press `` ` `` (backtick) to type a message directly to Tao. Press `Enter` to send, `Esc` to cancel. Works regardless of audio mode or STT state.

### Architecture overview

Open `architecture.html` in a browser for an interactive D3 diagram of the full system. Here's the short version:

```
Audio In → STT (whisper turbo) → process_text (gated by mode)
                                        ↓
               Signals (shared state bus) ← Discord text, Twitch, Text input
                                        ↓
                                    Prompter (attention span timer / new message trigger)
                                        ↓
                          Prompt Injections (Memory, Zeitgeist, Curiosity, CustomPrompt)
                                        ↓
                              LLM (LM Studio, instruct mode)
                                        ↓
                    Thinking separation (<think> blocks → Thoughts panel)
                                        ↓
                          Response Comprehensions (emoji strip, etc.)
                                        ↓
                              TTS (Kokoro / F5-TTS) → Audio Out
                                        ↓
                    Background Extractors (curiosity, memory, zeitgeist, keywords, definitions)
                                        ↓
                              extractor_signals → fed back into next prompt cycle
```

### Prompt injections (pre-LLM)

Modules inject context into the system prompt before it reaches the LLM, sorted by priority:

- **MemoryInjector** (60) — Queries ChromaDB for relevant memories, enriched by zeitgeist keywords. Supports forced/pinned memories.
- **CuriosityInjector** (65) — Injects Tao's active curiosities so she can naturally follow up on things she finds interesting.
- **CustomPrompt** — Static prompt injection for additional context.
- **Discord** — Recent text channel messages.
- **ZeitgeistInjector** (155) — Rolling conversation summary with topic/mood context.

### Response comprehensions (post-LLM, pre-TTS)

After the LLM responds, thinking blocks are separated and stored in `signals.recent_thoughts`. Only the spoken portion enters conversation history. Before TTS:

- **TTSResponseExtractor** — Strips any remaining `</think>` tags and removes emojis/non-speakable unicode.

### Background extractors

These run in their own threads on independent schedules, publishing to `signals.extractor_signals`:

- **CuriosityExtractor** — After each prompt cycle, asks "what's interesting here?" and stores short-term curiosity memories. On patience expiry, evaluates curiosities: answered ones get promoted to long-term, stale ones get dropped.
- **MemoryExtractor** — Every 20 new messages, reflects on the conversation and generates Q&A memory pairs via LLM, stored in ChromaDB.
- **ZeitgeistExtractor** — Periodically summarizes conversation, extracts keywords, and attributes keywords to users who brought them up.
- **KeywordExtractor** — Lightweight (no LLM), scans recent conversation for high-frequency non-stopword terms every 15s.
- **DefinitionExtractor** — When zeitgeist produces unknown keywords, asks the LLM for a one-sentence definition and stores it. Definitions expire after 7 days and get refreshed. Also creates `about_user` memories linking users to topics they discussed.

### Memory types

| Type | Description |
|---|---|
| `core` | Formative to Tao's personality |
| `personal` | Formative to opinions on a subject |
| `about_user` | Facts about users, what they like/dislike, topics they discussed |
| `opinion` | Temporary opinion about a recent topic |
| `definition` | LLM-generated definition of a keyword (7-day TTL) |
| `long_term` | Promoted from short-term or resolved curiosities |
| `short_term` | Recent observations, active curiosities |

## Stack

| Component | Implementation |
|---|---|
| STT | [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) + [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (`large-v3-turbo`) |
| TTS | [Kokoro](https://github.com/remsky/Kokoro-82M) (ONNX, default) or [F5-TTS-MLX](https://github.com/lucasnewman/f5-tts-mlx) |
| LLM | Any OpenAI-compatible endpoint ([LM Studio](https://lmstudio.ai/) tested) |
| Memory | [ChromaDB](https://github.com/chroma-core/chroma) vector store |
| Discord | [discord.py](https://github.com/Rapptz/discord.py) with voice support |
| Dashboard | [Rich](https://github.com/Textualize/rich) terminal UI |
| Frontend | [React](https://react.dev/) + [Vite](https://vite.dev/) dashboard (auto-started, port 3000) |
| WebSocket | Full engine state feed at `ws://localhost:1979/ws/state` |

## Dashboard

The terminal dashboard shows everything at a glance:

- **Left column**: System status, online users in Discord VC, pipeline state with extractor signals
- **Center column**: Conversation history, full last prompt sent to LLM, log/trace
- **Right column**: Zeitgeist summary + keywords, recent thoughts, memory browser, recalled/forced/curious memories

### Hotkeys

| Key | Action |
|---|---|
| `` ` `` | Text input mode |
| `o` | Select **O**nline panel |
| `i` | Select P**i**peline panel |
| `c` | Select **C**onversation panel |
| `b` | Select Memory **B**rowser panel |
| `e` | Select M**e**mory panel |
| `l` | Select **L**og panel |
| `z` | Select **Z**eitgeist panel |
| `h` | Select T**h**oughts panel |
| `p` | Select **P**rompt panel |
| `a` | Toggle audio mode (local/discord) |
| `r` | Toggle raw prompt view |
| `F5` | Toggle local STT on/off |
| `Tab` / `Shift+Tab` | Cycle panels |
| Arrows | Page through panel content / navigate memory browser |
| `Enter` | Force-inject selected memory |
| `Delete` | Delete selected memory |

### Raw mode

Run with `--raw` to skip the dashboard entirely and get line-by-line log output to stdout:

```
python main.py --raw
```

## Setup

### Requirements

- Python 3.11
- Node.js (for React frontend)
- macOS (tested on Apple Silicon — `sounddevice` and `f5-tts-mlx` are Mac-oriented)
- An OpenAI-compatible LLM endpoint (LM Studio, etc.)
- Discord bot token (for Discord features)

### Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

Create a `.env` file with your tokens (see `.env.example`).

Find your audio device indices:
```bash
python utils/listAudioDevices.py
```

Configure `constants.py` — check everything marked `#UNIQUE#`.

### Running

1. Start your LLM server (e.g. LM Studio on `http://127.0.0.1:1234`)
2. `python main.py` (or `python main.py --raw` for raw output)
3. Wait for "SYSTEM READY" in the dashboard
4. The React frontend auto-starts at `http://localhost:3000`

## Credits

- Original project by [kimjammer](https://github.com/kimjammer/neuro)
- This fork by [irobeth](https://github.com/irobeth) (Chakrila)
- Substantially rewritten with assistance from [Claude](https://claude.ai) (Anthropic)

## Disclaimer

This is an experimental project. The LLM will say whatever it wants. Configure the blacklist in `blacklist.txt`. You assume all risk. See LICENSE for details.
