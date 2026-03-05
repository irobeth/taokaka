# Taokaka

A local AI companion that listens, thinks, and talks back — through your MacBook or a Discord voice channel.

Forked from [kimjammer/neuro](https://github.com/kimjammer/neuro), which was a 7-day recreation of Neuro-Sama on consumer hardware. This fork has been substantially rewritten with the help of **Claude** (Anthropic's AI assistant). I don't really "know" Python — I know it enough to read it, debug it, and direct an AI to write it. No promises.

## What it does

Taokaka is a real-time conversational AI with voice input/output, long-term memory, and a rich terminal dashboard. You talk, she listens, thinks, and responds — either through your local mic and speakers, or through a Discord voice channel.

### Audio modes (toggle with `m` key)

- **Local mode**: MacBook mic in, MacBook speakers out. The mic is automatically muted during TTS playback to prevent feedback loops.
- **Discord mode**: Discord voice channel in (per-user STT), Discord voice channel out. Text messages from Discord work in both modes.

### Architecture overview

Open `architecture.html` in a browser for an interactive D3 diagram of the full system. Here's the short version:

```
Audio In → STT (whisper turbo) → process_text (gated by mode)
                                        ↓
               Signals (shared state bus) ← Discord text, Twitch
                                        ↓
                                    Prompter (patience timer / new message trigger)
                                        ↓
                          Prompt Injections (Memory, Zeitgeist, CustomPrompt)
                                        ↓
                              LLM (LM Studio, instruct mode)
                                        ↓
                          Response Comprehensions (strip <think> blocks, etc.)
                                        ↓
                              TTS (Kokoro / F5-TTS) → Audio Out
```

### Prompt injections (pre-LLM)

Modules inject context into the system prompt before it reaches the LLM:

- **MemoryInjector** — Queries ChromaDB for relevant memories based on recent conversation. Supports forced/pinned memories from the dashboard.
- **ZeitgeistInjector** — Injects a rolling conversation summary so the AI has a sense of what's been discussed.
- **CustomPrompt** — Static prompt injection for additional context.
- **Discord** — Recent text channel messages.

### Response comprehensions (post-LLM, pre-TTS)

After the LLM responds, the full response is logged and saved to history unmodified. Before it reaches TTS, it passes through a chain of comprehensions:

- **TTSResponseExtractor** — Splits on `</think>` and only sends the spoken portion to TTS. The thinking block stays in the log for debugging.

### Background extractors

These run in their own threads, periodically processing the conversation:

- **MemoryExtractor** — Every 20 new messages, reflects on the conversation and generates Q&A memory pairs via LLM, stored in ChromaDB.
- **ZeitgeistExtractor** — Periodically summarizes the conversation and feeds it back to the ZeitgeistInjector.

## Stack

| Component | Implementation |
|---|---|
| STT | [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) + [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (`large-v3-turbo`) |
| TTS | [Kokoro](https://github.com/remsky/Kokoro-82M) (ONNX, default) or [F5-TTS-MLX](https://github.com/lucasnewman/f5-tts-mlx) |
| LLM | Any OpenAI-compatible endpoint ([LM Studio](https://lmstudio.ai/) tested) |
| Memory | [ChromaDB](https://github.com/chroma-core/chroma) vector store |
| Discord | [discord.py](https://github.com/Rapptz/discord.py) with voice support |
| Dashboard | [Rich](https://github.com/Textualize/rich) terminal UI |
| Frontend | [Socket.IO](https://socket.io/) WebSocket API (compatible with [neurofrontend](https://github.com/kimjammer/neurofrontend)) |

## Dashboard

The terminal dashboard shows everything at a glance:

- **Left column**: System status, online users in Discord VC
- **Center column**: Conversation history, full last prompt sent to LLM, log/trace
- **Right column**: Zeitgeist summary, memory browser (with cursor navigation, delete, force-inject), recalled memories

Hotkeys: `Tab`/`Shift+Tab` cycle panels, `m` toggle audio mode, `r` toggle raw prompt view, arrows to page/navigate, `Enter` to force-inject a memory, `Delete` to remove one.

### Raw mode

Run with `--raw` to skip the dashboard entirely and get line-by-line log output to stdout:

```
python main.py --raw
```

## Setup

### Requirements

- Python 3.11
- macOS (tested on Apple Silicon — `sounddevice` and `f5-tts-mlx` are Mac-oriented)
- An OpenAI-compatible LLM endpoint (LM Studio, etc.)
- Discord bot token (for Discord features)

### Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
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

## Credits

- Original project by [kimjammer](https://github.com/kimjammer/neuro)
- This fork by [irobeth](https://github.com/irobeth) (Chakrila)
- Substantially rewritten with assistance from [Claude](https://claude.ai) (Anthropic)

## Disclaimer

This is an experimental project. The LLM will say whatever it wants. Configure the blacklist in `blacklist.txt`. You assume all risk. See LICENSE for details.
