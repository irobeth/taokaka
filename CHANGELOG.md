# Changelog

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
