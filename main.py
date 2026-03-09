# Python Module Imports
import warnings
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")
import os
import signal
import subprocess
import sys
import time
import threading
import asyncio

# Class Imports
from signals import Signals
from interface import Interface
from prompter import Prompter
from llmWrappers.llmState import LLMState
from llmWrappers.textLLMWrapper import TextLLMWrapper
from llmWrappers.imageLLMWrapper import ImageLLMWrapper
from stt import STT
from tts import TTS
from modules.twitchClient import TwitchClient
from modules.discordClient import DiscordClient
from modules.audioPlayer import AudioPlayer
from modules.vtubeStudio import VtubeStudio
from modules.multimodal import MultiModal
from modules.customPrompt import CustomPrompt
from modules.memoryInjector import MemoryInjector
from modules.zeitgeistInjector import ZeitgeistInjector
from modules.curiosityInjector import CuriosityInjector
from comprehensions.memory_extractor import MemoryExtractor
from comprehensions.zeitgeist_extractor import ZeitgeistExtractor
from comprehensions.keyword_extractor import KeywordExtractor
from comprehensions.curiosity_extractor import CuriosityExtractor
from comprehensions.definition_extractor import DefinitionExtractor
from comprehensions.mood_extractor import MoodExtractor
from modules.moodInjector import MoodInjector
from socketioServer import SocketIOServer


async def main():
    # CORE FILES
    raw_mode = "--raw" in sys.argv
    signals = Signals()
    interface = Interface(signals, raw_mode=raw_mode)
    interface.start()

    interface.log("Starting Project...", source="Main")

    # Register signal handler so that all threads can be exited.
    def signal_handler(sig, frame):
        interface.log("Received CTRL+C — shutting down.", source="Main")
        signals.terminate = True
        stt.API.shutdown()
        # Restore default handlers so a second Ctrl+C force-exits
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # MODULES
    # Modules that start disabled CANNOT be enabled while the program is running.
    modules = {}
    module_threads = {}

    # Create STT
    stt = STT(signals, interface)
    # Create TTS
    tts = TTS(signals, interface)
    tts.stt = stt
    # Create LLMWrappers
    llmState = LLMState()
    llms = {
        "text": TextLLMWrapper(signals, tts, llmState, modules, interface),
        "image": ImageLLMWrapper(signals, tts, llmState, modules, interface)
    }
    # Create Prompter
    prompter = Prompter(signals, llms, modules, interface)

    # Create Discord bot
    modules['discord'] = DiscordClient(signals, stt, tts, interface, enabled=True)

    # Create Twitch bot
    #modules['twitch'] = TwitchClient(signals, enabled=False)

    # Create audio player
    #modules['audio_player'] = AudioPlayer(signals, enabled=True)

    # Create Vtube Studio plugin
    #modules['vtube_studio'] = VtubeStudio(signals, enabled=True)

    # Create Multimodal module
    modules['multimodal'] = MultiModal(signals, enabled=False)

    # Create Custom Prompt module
    modules['custom_prompt'] = CustomPrompt(signals, enabled=True)

    # Create Memory injector + extractor
    modules['memory'] = MemoryInjector(signals, enabled=True)
    interface._delete_memory_fn = modules['memory'].API.delete_memory
    interface._stt = stt
    def _submit_typed_text(text):
        attributed = f"User: {text}"
        interface.log(attributed, source="Text")
        signals.history.append({"role": "user", "content": attributed, "timestamp": time.time()})
        signals.last_message_time = time.time()
        if not signals.AI_speaking:
            signals.new_message = True
    interface._submit_text_fn = _submit_typed_text
    modules['memory_extractor'] = MemoryExtractor(signals, modules['memory'], enabled=True)

    # Create Zeitgeist injector + extractor
    modules['zeitgeist'] = ZeitgeistInjector(signals, enabled=True)
    modules['zeitgeist_extractor'] = ZeitgeistExtractor(signals, modules['zeitgeist'], enabled=True)

    # Create Keyword extractor (lightweight, no LLM)
    modules['keyword_extractor'] = KeywordExtractor(signals, enabled=True)

    # Create Curiosity injector + extractor
    modules['curiosity'] = CuriosityInjector(signals, enabled=True)
    modules['curiosity_extractor'] = CuriosityExtractor(signals, modules['memory'], interface, enabled=True)

    # Create Definition extractor (defines unknown keywords, links users to topics)
    modules['definition_extractor'] = DefinitionExtractor(signals, modules['memory'], interface, enabled=True)

    # Create Mood injector + extractor
    modules['mood'] = MoodInjector(signals, enabled=True)
    modules['mood_extractor'] = MoodExtractor(signals, modules['memory'], interface, enabled=True)

    # Create Socket.io server
    # The specific llmWrapper it gets doesn't matter since state is shared between all llmWrappers
    sio = SocketIOServer(signals, stt, tts, llms["text"], prompter, modules=modules)

    # Create threads (As daemons, so they exit when the main thread exits)
    prompter_thread = threading.Thread(target=prompter.prompt_loop, daemon=True)
    stt_thread = threading.Thread(target=stt.listen_loop, daemon=True)
    sio_thread = threading.Thread(target=sio.start_server, daemon=True)
    # Start Threads
    sio_thread.start()
    prompter_thread.start()
    stt_thread.start()

    # Create and start threads for modules
    for name, module in modules.items():
        module_thread = threading.Thread(target=module.init_event_loop, daemon=True)
        module_threads[name] = module_thread
        module_thread.start()

    # Frontend process manager
    frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
    frontend_proc = None

    def start_frontend():
        nonlocal frontend_proc
        try:
            frontend_proc = subprocess.Popen(
                ["npm", "run", "dev"],
                cwd=frontend_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            interface.log(f"Frontend started (pid {frontend_proc.pid})", source="Main")
        except Exception as e:
            interface.log(f"Failed to start frontend: {e}", source="Main")
            frontend_proc = None

    def check_ws_alive():
        """Try to connect to the WebSocket and return True if it responds."""
        import socket
        try:
            s = socket.create_connection(("localhost", 3000), timeout=2)
            s.close()
            return True
        except Exception:
            return False

    start_frontend()
    last_frontend_check = time.time()

    while not signals.terminate:
        time.sleep(0.1)

        # Check frontend health every 15 seconds
        if time.time() - last_frontend_check >= 15:
            last_frontend_check = time.time()
            proc_dead = frontend_proc is None or frontend_proc.poll() is not None
            if proc_dead or not check_ws_alive():
                if frontend_proc and frontend_proc.poll() is None:
                    frontend_proc.terminate()
                interface.log("Frontend down, restarting...", source="Main")
                start_frontend()

    interface.log("TERMINATING", source="Main")

    # Kill frontend process
    if frontend_proc and frontend_proc.poll() is None:
        frontend_proc.terminate()
        interface.log("Frontend stopped", source="Main")

    # Wait for child threads to exit before exiting main thread

    # Wait for all modules to finish
    for module_thread in module_threads.values():
        module_thread.join()

    sio_thread.join()
    prompter_thread.join()
    interface.stop()
    print("All threads exited, shutdown complete")
    sys.exit(0)

if __name__ == '__main__':
    asyncio.run(main())
