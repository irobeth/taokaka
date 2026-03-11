# Changelog

## 0.2.4 — 2026-03-11

### New Features
- **React frontend overhaul** — IRC-style 3-column layout (memories/recalled/thoughts/zeitgeist/mood/prompt/pipeline tabs | chat/logs/details tabs | status/online sidebar)
- **Mood panel** — dedicated tab with overall mood emoji + intensity bar, per-subject feelings with emoji indicators
- **Mood emoji mapping** — intensity-variant emojis for all 8 Plutchik emotions (low/mid/high), shown in mood panel, injector, and logs
- **Details panel** — click any memory or thought in the left pane to view full details in the center pane
- **Shutdown button** — graceful backend shutdown from the frontend (next to Live indicator), calls `stt.API.shutdown()` to unblock audio listeners
- **Startup logs in Logs tab** — backend launcher output streams directly to the Logs tab instead of a floating overlay
- **Disconnected mode** — dashboard usable offline with browsable panels; backend launcher inline in header
- **WebSocket command channel** — bidirectional JSON commands over the same WS connection used for state
- **Semi-transparent panels** — backdrop blur over fixed Taokaka background image
- **Backend state extensions** — toggles, alertness, profanity_rating, last_full_prompt, log_entries in WS state snapshot
- **Vite backend launcher API** — `/api/start-backend`, `/api/backend-status`, `/api/stop-backend` endpoints

### Changes
- Mood injector prefixes overall and per-subject lines with emoji
- Log/trace entries piped through `signals.log_entries` to frontend via WebSocket
- Chat input bar nearly opaque (`rgba(10, 10, 15, 0.97)`) for readability

## 0.2.3 — 2026-03-11

### New Features
- **Nickname extraction & storage** — Tao wraps nicknames in `{nick user="name"}Nickname{/nick}` tags; extracted and stored in Elasticsearch as `nickname` type memories (overwrites on reassignment)
- **Emote extraction** — `{me}...{/me}` and `*asterisk*` emotes extracted to `signals.extractor_signals["emotes"]` for vtuber control
- **Alertness state machine** — replaces simple patience timer: awake (15s) → napping (90s) → asleep (never self-prompts); any activity wakes Tao up
- **Superpane** — merged prompt+log panels with P/L pin keys and 15s auto-cycle
- **Raw view mode** — press `V` to toggle between dashboard and full-screen scrolling log with streaming tokens
- **Audio volume gate** — rejects recordings below RMS threshold to filter ambient noise
- **Audio debounce** — increased silence duration (1.0s), min recording length (0.5s), min gap (0.5s)
- **LLM token streaming** — tokens stream to interface in real-time via `stream_token()`

### Changes
- **Alertness display** in header (AWAKE / napping zzz / asleep)
- **Context size** corrected from 75000 to 32000 (matching model capability)
- **max_tokens reduced** to 200 for shorter 1-2 sentence responses
- **Speaker attribution** uses HOST_NAME instead of "User" for local STT
- **Kokoro voice** changed to `af_bella`
- **SentenceTransformer offline** — `HF_HUB_OFFLINE=1` prevents network calls on cached models
- **SSE stream cleanup** — `stream_response.close()` in finally block prevents response bleeding
- **STT mic fix** — mute/unmute changed to no-ops (set_microphone kills multiprocessing pipes); AI_speaking gate handles filtering instead
- **Self-hearing prevention** — flush audio queue, reset Silero VAD states, clear frames after TTS playback
- **Idle timer freeze** — timer pauses while AI is thinking or speaking
- **System prompt** — 1-2 sentence max, `{me}` emote tags, `{nick}` nickname tags, `<think>` response format section

## 0.2.2 — 2026-03-10

### New Features
- **VoiceFX pipeline** — post-TTS audio effects: pitch shift, speed, high/low-pass filters, gain
  - Taokaka pitched up +3 semitones for anime voice
- **Startup sound** — TTS plays "TAOKAKA ZOOM!!" on boot to prime speech models; SYSTEM READY waits for playback to finish
- **Factory reset (F12)** — wipes all memories, curiosities, zeitgeist, mood, and conversation history with scary confirmation prompt
- **`--local` / `--discord` CLI flags** — set audio mode at startup
- **Elasticsearch migration** — replaced ChromaDB with Elasticsearch hybrid search (BM25 + kNN vectors)
  - Drop-in `ElasticCollection` wrapper, migration script, docker-compose
- **Universal startup script** (`start.sh`) — auto-starts Docker/ES, checks LLM, installs frontend deps
- **Discord voice retry** — handles 4017 close code with force-disconnect and backoff (3s, 6s, 9s)

### Changes
- **60fps dashboard** — render loop bumped from 4fps to 60fps for responsive typing and UI
- **Lock-free typing** — removed lock contention from text input; single-writer pattern with faster polling (10ms)
- **Username keyword filtering** — `strip_attributions()` removes `"Username: "` prefixes before keyword extraction; added chat labels (user, assistant, taokaka, irobeth) to stopwords
- **Increased extractor max_tokens** — all comprehension extractors bumped to accommodate longer think blocks

## 0.2.0 — 2026-03-09

### New Features
- **Mood system** — 3D emotional state using Plutchik's emotion wheel
  - Three axes: emotion (8 primary emotions), intensity (0–1), inertia (resistance to change, 0–1)
  - Global mood evaluates after each prompt cycle via LLM
  - Per-subject moods (users, topics, keywords) stored in ChromaDB as `mood` type memories
  - Inertia-weighted blending: moods transition smoothly using cartesian vector math on the emotion wheel
  - MoodInjector (priority 158) injects current feelings + notable subject moods into prompt
- **Prompts directory** — all LLM prompts moved from inline Python strings to editable `prompts/*.txt` files
  - `prompts/__init__.py` provides `load_prompt(name)` and `strip_think(text)` utilities
  - System, memory, curiosity, curiosity_eval, zeitgeist, definition, mood prompts

### Changes
- **XML injection tags** — all prompt injections now use `<XML>` tags instead of `[Bracket]` style
  - `<SYSTEM>`, `<CONTEXT>`, `<MEMORIES>`, `<CURIOSITIES>`, `<ZEITGEIST>`, `<MOOD>`, `<DISCORD>`, `<TWITCH>`
- **Think-block stripping** — all extractors that call the LLM directly now strip `<think>` blocks before parsing
  - Fixed: curiosity, memory, zeitgeist, and definition extractors
- **Curiosity parser** — updated to handle `{qa}...{/qa}` block delimiters
- **System prompt rewrite** — new Taokaka character prompt (BlazBlue catgirl personality)
- **Memory types** expanded: added `mood`

## 0.1.9 — 2026-03-05

### New Features
- **Profanity filter with severity ratings** — uses dsojevic/profanity-list (434 words, severity 1-4)
  - Severity labels: PG-13, R, NC-17, 4chan
  - Default max severity: R (level 2)
  - Severity overrides for specific words (e.g. "fuck" → R instead of 4chan)
  - Violations trigger automatic LLM re-prompt asking to rephrase (up to 2 retries)
  - Hard blacklist filter still works as final fallback
- **STT vocabulary hints** — Whisper `initial_prompt` for custom names (Taokaka, Chakrila, irobeth)
- **Rating display** in header bar showing current profanity rating

### Changes
- Audio mode toggle moved from `m` to `a`
- Panel keybinds: direct selection via o/i/c/b/e/l/z/h/p with underlined hints
- Text input mode changed from `t` to backtick (`` ` ``)
- Default attention span reduced to 15s
- Memories panel now shows active curiosities

## 0.1.8 — 2026-03-05

### New Features
- **Text input mode** (`\`` key) — type messages directly to Tao without STT
- **Curiosity system** — Tao generates short-term curiosity memories after each prompt cycle, evaluates and promotes them to long-term on patience expiry
- **Curiosity injector** — active curiosities are injected into the prompt so Tao can follow up naturally
- **Definition extractor** — unknown zeitgeist keywords get auto-defined via LLM, stored as `definition` memories with 7-day TTL
- **Keyword attribution** — zeitgeist tracks which user introduced which topic, creates `about_user` memories linking users to their topics
- **Keyword extractor** — lightweight stopword-filtered keyword extraction from conversation, no LLM needed
- **Extractor signal bus** (`signals.extractor_signals`) — decoupled pub/sub for extractor-to-injector communication outside the main prompt loop
- **Pipeline panel** — left-column panel showing real-time pipeline state, queues, and extractor signals
- **Thoughts panel** — displays Tao's `<think>` blocks separately from conversation history
- **Attention span bar** — animated countdown bar in header showing time until patience expiry (green/yellow/red)
- **WebSocket state feed** — full engine state broadcast at `ws://localhost:1979/ws/state` (250ms interval)
- **React frontend** — Vite + React dashboard at port 3000, auto-started and health-checked by main process
- **F5 toggle** — toggle local STT on/off (starts disabled by default)
- **Ship script** (`./ship.sh`) — one-command git add/commit/push

### Changes
- **Thinking separation** — `<think>` blocks are stripped from history before storage; only spoken text enters conversation history, zeitgeist, and keyword extraction
- **Emoji stripping** — TTS comprehension layer strips emojis/unicode symbols before speech synthesis
- **Panel keybinds** — direct panel selection via shortcut keys (o/i/c/b/e/l/z/h/p) with underlined hints in titles
- **Audio mode toggle** moved from `m` to `a`
- **Default patience** reduced from 60s to 15s
- **Stopwords module** — static English stopwords list with `extract_keywords()` helper
- **Memory types** expanded: added `definition` type
- **Server port** changed from 8080 to 1979

## 0.1.7 — 2026-03-05

- Initial tagged version (see git history for prior changes)
- Rewrite README for Taokaka fork
- Local/Discord audio mode toggle
- Comprehensions pipeline, injector/extractor split
- Interactive memory browser with cursor navigation, delete, force injection
- Per-user Discord STT recorders
