import asyncio
import json
import time

import aiohttp
from aiohttp import web
import socketio


class SocketIOServer:
    def __init__(self, signals, stt, tts, llmWrapper, prompter, modules=None):
        if modules is None:
            modules = {}
        self.signals = signals
        self.stt = stt
        self.tts = tts
        self.llmWrapper = llmWrapper
        self.prompter = prompter
        self.modules = modules
        self._ws_clients = set()

    def start_server(self):
        print("Starting Socket.io server")
        sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
        app = web.Application()
        sio.attach(app)

        @sio.event
        async def get_blacklist(sid):
            await sio.emit('get_blacklist', self.llmWrapper.API.get_blacklist())

        @sio.event
        async def set_blacklist(sid, message):
            self.llmWrapper.API.set_blacklist(message)

        @sio.event
        async def disable_LLM(sid):
            self.llmWrapper.API.set_LLM_status(False)

        @sio.event
        async def enable_LLM(sid):
            self.llmWrapper.API.set_LLM_status(True)

        @sio.event
        async def disable_TTS(sid):
            self.tts.API.set_TTS_status(False)

        @sio.event
        async def enable_TTS(sid):
            self.tts.API.set_TTS_status(True)

        @sio.event
        async def disable_STT(sid):
            self.stt.API.set_STT_status(False)

        @sio.event
        async def enable_STT(sid):
            self.stt.API.set_STT_status(True)

        @sio.event
        async def disable_movement(sid):
            if "vtube_studio" in self.modules:
                self.modules["vtube_studio"].API.set_movement_status(False)

        @sio.event
        async def enable_movement(sid):
            if "vtube_studio" in self.modules:
                self.modules["vtube_studio"].API.set_movement_status(True)

        @sio.event
        async def disable_multimodal(sid):
            if "multimodal" in self.modules:
                self.modules["multimodal"].API.set_multimodal_status(False)

        @sio.event
        async def enable_multimodal(sid):
            if "multimodal" in self.modules:
                self.modules["multimodal"].API.set_multimodal_status(True)

        @sio.event
        async def get_hotkeys(sid):
            if "vtube_studio" in self.modules:
                self.modules["vtube_studio"].API.get_hotkeys()

        @sio.event
        async def send_hotkey(sid, hotkey):
            if "vtube_studio" in self.modules:
                self.modules["vtube_studio"].API.send_hotkey(hotkey)

        @sio.event
        async def trigger_prop(sid, prop_action):
            if "vtube_studio" in self.modules:
                self.modules["vtube_studio"].API.trigger_prop(prop_action)

        @sio.event
        async def move_model(sid, mode):
            if "vtube_studio" in self.modules:
                self.modules["vtube_studio"].API.move_model(mode)

        @sio.event
        async def disable_twitch(sid):
            if "twitch" in self.modules:
                self.modules["twitch"].API.set_twitch_status(False)

        @sio.event
        async def enable_twitch(sid):
            if "twitch" in self.modules:
                self.modules["twitch"].API.set_twitch_status(True)

        @sio.event
        async def cancel_next_message(sid):
            self.llmWrapper.API.cancel_next()

        @sio.event
        async def abort_current_message(sid):
            self.tts.API.abort_current()

        @sio.event
        async def fun_fact(sid):
            self.signals.history.append({"role": "user", "content": "Let's move on. Can we get a fun fact?", "timestamp": time.time()})
            self.signals.new_message = True

        @sio.event
        async def new_topic(sid, message):
            self.signals.history.append({"role": "user", "content": message, "timestamp": time.time()})
            self.signals.new_message = True

        @sio.event
        async def nuke_history(sid):
            self.signals.history = []

        @sio.event
        async def play_audio(sid, file_name):
            if "audio_player" in self.modules:
                self.modules["audio_player"].API.play_audio(file_name)

        @sio.event
        async def pause_audio(sid):
            if "audio_player" in self.modules:
                self.modules["audio_player"].API.pause_audio()

        @sio.event
        async def resume_audio(sid):
            if "audio_player" in self.modules:
                self.modules["audio_player"].API.resume_audio()

        @sio.event
        async def abort_audio(sid):
            if "audio_player" in self.modules:
                self.modules["audio_player"].API.stop_playing()

        @sio.event
        async def set_custom_prompt(sid, data):
            if "custom_prompt" in self.modules:
                self.modules["custom_prompt"].API.set_prompt(data["prompt"], priority=int(data["priority"]))
                await sio.emit("get_custom_prompt", self.modules["custom_prompt"].API.get_prompt())

        @sio.event
        async def clear_short_term(sid):
            if "memory" in self.modules:
                self.modules["memory"].API.clear_short_term()
                await sio.emit("get_memories", self.modules["memory"].API.get_memories())

        @sio.event
        async def import_json(sid):
            if "memory" in self.modules:
                self.modules["memory"].API.import_json()

        @sio.event
        async def export_json(sid):
            if "memory" in self.modules:
                self.modules["memory"].API.export_json()

        @sio.event
        async def delete_memory(sid, data):
            if "memory" in self.modules:
                self.modules["memory"].API.delete_memory(data)
                await sio.emit("get_memories", self.modules["memory"].API.get_memories())

        @sio.event
        async def get_memories(sid, data):
            if "memory" in self.modules:
                await sio.emit("get_memories", self.modules["memory"].API.get_memories(data))

        @sio.event
        async def create_memory(sid, data):
            if "memory" in self.modules:
                self.modules["memory"].API.create_memory(data)
                await sio.emit("get_memories", self.modules["memory"].API.get_memories())

        # When a new client connects, send them the status of everything
        @sio.event
        async def connect(sid, environ):
            # Set signals to themselves to trigger setter function and the sio.emit
            self.signals.AI_thinking = self.signals.AI_thinking
            self.signals.AI_speaking = self.signals.AI_speaking
            self.signals.human_speaking = self.signals.human_speaking
            self.signals.recentTwitchMessages = self.signals.recentTwitchMessages
            await sio.emit("patience_update", {"crr_time": time.time() - self.signals.last_message_time, "total_time": self.signals.patience})
            await sio.emit('get_blacklist', self.llmWrapper.API.get_blacklist())

            if "twitch" in self.modules:
                await sio.emit('twitch_status', self.modules["twitch"].API.get_twitch_status())
            if "audio_player" in self.modules:
                await sio.emit('audio_list', self.modules["audio_player"].API.get_audio_list())
            if "vtube_studio" in self.modules:
                await sio.emit('movement_status', self.modules["vtube_studio"].API.get_movement_status())
                self.modules["vtube_studio"].API.get_hotkeys()
            if "custom_prompt" in self.modules:
                await sio.emit('get_custom_prompt', self.modules["custom_prompt"].API.get_prompt())
            if "multimodal" in self.modules:
                await sio.emit('multimodal_status', self.modules["multimodal"].API.get_multimodal_status())

            # Collect the enabled status of the llm, tts, stt, and movement and send it to the client
            await sio.emit('LLM_status', self.llmWrapper.API.get_LLM_status())
            await sio.emit('TTS_status', self.tts.API.get_TTS_status())
            await sio.emit('STT_status', self.stt.API.get_STT_status())

        @sio.event
        def disconnect(sid):
            print('Client disconnected')

        def _build_state_snapshot():
            s = self.signals
            disc_connected = bool(s.discord_vc and s.discord_vc.is_connected())
            disc_members = []
            if disc_connected:
                disc_members = [
                    {"name": m.display_name, "id": m.id}
                    for m in s.discord_vc.channel.members if not m.bot
                ]

            history_tail = []
            for msg in s.history[-30:]:
                history_tail.append({
                    "role": msg.get("role", ""),
                    "content": msg.get("content", ""),
                    "timestamp": msg.get("timestamp", 0),
                })

            memories_summary = []
            for mem in s.all_memories:
                meta = mem.get("metadata", {})
                memories_summary.append({
                    "id": mem.get("id", ""),
                    "document": mem.get("document", ""),
                    "type": meta.get("type", ""),
                    "related_user": meta.get("related_user", ""),
                    "keywords": meta.get("keywords", ""),
                    "title": meta.get("title", ""),
                })

            return {
                "timestamp": time.time(),
                "pipeline": {
                    "human_speaking": s.human_speaking,
                    "AI_thinking": s.AI_thinking,
                    "AI_speaking": s.AI_speaking,
                    "new_message": s.new_message,
                    "audio_mode": s.audio_mode,
                    "active_voice_user": s.active_voice_user,
                },
                "readiness": {
                    "stt_ready": s.stt_ready,
                    "tts_ready": s.tts_ready,
                    "tts_engine": s.tts_engine,
                },
                "timing": {
                    "last_message_time": s.last_message_time,
                    "patience": s.patience,
                    "seconds_since_last": round(time.time() - s.last_message_time, 1) if s.last_message_time else 0,
                },
                "discord": {
                    "connected": disc_connected,
                    "members": disc_members,
                },
                "history": history_tail,
                "chat_queues": {
                    "twitch": len(s.recentTwitchMessages),
                    "discord": len(s.recentDiscordMessages),
                },
                "extractor_signals": {
                    k: v if isinstance(v, (list, str, int, float, bool)) else str(v)
                    for k, v in s.extractor_signals.items()
                },
                "zeitgeist": s.zeitgeist,
                "memories": {
                    "total": len(s.all_memories),
                    "recalled": s.last_recalled,
                    "forced_ids": list(s.forced_memory_ids),
                    "recent_generated": s.recent_memories[-10:],
                    "all": memories_summary,
                },
                "stt_workers": s.stt_workers,
                "recent_thoughts": s.recent_thoughts[-10:],
            }

        async def ws_handler(request):
            ws = aiohttp.web.WebSocketResponse()
            await ws.prepare(request)
            self._ws_clients.add(ws)
            try:
                async for msg in ws:
                    pass  # read loop keeps connection alive
            finally:
                self._ws_clients.discard(ws)
            return ws

        app.router.add_get("/ws/state", ws_handler)

        async def broadcast_state():
            while not self.signals.terminate:
                if self._ws_clients:
                    try:
                        snapshot = json.dumps(_build_state_snapshot())
                    except Exception:
                        await asyncio.sleep(0.25)
                        continue
                    dead = set()
                    for ws in self._ws_clients:
                        try:
                            await ws.send_str(snapshot)
                        except Exception:
                            dead.add(ws)
                    self._ws_clients -= dead
                await asyncio.sleep(0.25)

        async def send_messages():
            while not self.signals.terminate:
                while not self.signals.sio_queue.empty():
                    event, data = self.signals.sio_queue.get()
                    await sio.emit(event, data)
                await sio.sleep(0.1)

        async def run():
            sio.start_background_task(send_messages)
            sio.start_background_task(broadcast_state)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, 'localhost', 1979)
            await site.start()
            print("Socket.io server started on port 1979")
            print("WebSocket state feed available at ws://localhost:1979/ws/state")
            while not self.signals.terminate:
                await asyncio.sleep(0.1)
            await runner.cleanup()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run())
