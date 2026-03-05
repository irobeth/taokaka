# Python Module Imports
import warnings
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")
import signal
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
from comprehensions.memory_extractor import MemoryExtractor
from comprehensions.zeitgeist_extractor import ZeitgeistExtractor
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
    modules['memory_extractor'] = MemoryExtractor(signals, modules['memory'], enabled=True)

    # Create Zeitgeist injector + extractor
    modules['zeitgeist'] = ZeitgeistInjector(signals, enabled=True)
    modules['zeitgeist_extractor'] = ZeitgeistExtractor(signals, modules['zeitgeist'], enabled=True)

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

    while not signals.terminate:
        time.sleep(0.1)
    interface.log("TERMINATING", source="Main")

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
