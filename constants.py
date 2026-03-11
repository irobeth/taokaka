# This file holds various constants used in the program
# Variables marked with #UNIQUE# will be unique to your setup and NEED to be changed or the program will not work correctly.

# CORE SECTION: All constants in this section are necessary

# Microphone/Speaker device indices
# Use utils/listAudioDevices.py to find the correct device ID
#UNIQUE#
INPUT_DEVICE_INDEX = 0
OUTPUT_DEVICE_INDEX = 1

# Vocabulary hints for STT (Whisper initial_prompt).
# Include names, jargon, or words that get frequently mistranscribed.
# Whisper uses this as context to bias transcription toward these spellings.
STT_VOCABULARY = "Taokaka, Chakrila, irobeth"

# How many seconds to wait before prompting AI
PATIENCE = 15

# URL of LLM API Endpoint
# LLM_ENDPOINT = ""
LLM_ENDPOINT = "http://127.0.0.1:1234"

# Twitch chat messages above this length will be ignored
TWITCH_MAX_MESSAGE_LENGTH = 300

# Twitch channel for bot to join
#UNIQUE#
TWITCH_CHANNEL = ""

# Discord text channel ID for the bot to read messages from (set to 0 to read all channels)
#UNIQUE#
DISCORD_TEXT_CHANNEL_ID = 1474973299757809664

# Discord messages above this length will be ignored
DISCORD_MAX_MESSAGE_LENGTH = 300

# When True, Discord voice is used as the primary audio input instead of the local microphone
DISCORD_PRIMARY_INPUT = False

# Voice reference file for TTS (must be 24kHz mono WAV, 5-30 seconds)
#UNIQUE#
VOICE_REFERENCE = "neuro.wav"

# Exact transcription of what is spoken in the voice reference file (required by F5-TTS)
#UNIQUE#
VOICE_REFERENCE_TEXT = "Hey, no need to overthink it! Just take a breath, let things flow, and trust that it will all work out. You're doing better than you think!"

# MULTIMODAL SPECIFIC SECTION: Not needed when not using multimodal capabilities

MULTIMODAL_ENDPOINT = ""

MULTIMODAL_MODEL = "mistralai/devstral-small-2-2512"

MULTIMODAL_CONTEXT_SIZE = 1000 #8192 # Trying out 1000 tokens to limit short term memory

# This is the multimodal strategy (when to use multimodal/text only llm) that the program will start with.
# Runtime changes will not be saved here.
# Valid values are: "always", "never"
MULTIMODAL_STRATEGY = "never"

# This is the monitor index that screenshots will be taken. THIS IS NOT THE MONITOR NUMBER IN DISPLAY SETTINGS
# Monitor 0 is a "virtual" monitor contains all monitor screens.
PRIMARY_MONITOR = 0

# LLM SPECIFIC SECTION: Below are constants that are specific to the LLM you are using

# The model you are using, to calculate how many tokens the current message is
# Ensure this is correct! Used for token count estimation
MODEL = "qwen/qwen3-vl-8b"

# Context size (maximum number of tokens in the prompt) Will target upto 90% usage of this limit
CONTEXT_SIZE = 32000

# This is your name
#UNIQUE#
HOST_NAME = "irobeth"

# This is the AI's name
AI_NAME = "Taokaka"

# System prompt and footer are loaded from prompts/ directory
from prompts import load_prompt
SYSTEM_PROMPT = load_prompt("system")
SYSTEM_PROMPT_FOOTER = load_prompt("system_footer")
# List of banned tokens to be passed to the textgen web ui api
# For Mistral 7B v0.2, token 422 is the "#" token. The LLM was spamming #life #vtuber #funfact etc.
BANNED_TOKENS = ""

# List of stopping strings. Necessary for Llama 3
STOP_STRINGS = []

# MEMORY SECTION: Constants relevant to forming new memories

# Valid memory types for metadata classification
MEMORY_TYPES = ["core", "personal", "about_user", "opinion", "long_term", "short_term", "definition", "mood"]

MEMORY_PROMPT = load_prompt("memory")
CURIOSITY_PROMPT = load_prompt("curiosity")
CURIOSITY_EVAL_PROMPT = load_prompt("curiosity_eval")

# How many messages in the history to include for querying the database.
MEMORY_QUERY_MESSAGE_COUNT = 10

# How many memories to recall and insert into context
MEMORY_RECALL_COUNT = 10

# VTUBE STUDIO SECTION: Configure & tune model & prop positions here.
# The defaults are for the Hiyori model on a full 16 by 9 aspect ratio screen

VTUBE_MODEL_POSITIONS = {
    "chat": {
        "x": 0.4,
        "y": -1.4,
        "size": -35,
        "rotation": 0,
    },
    "screen": {
        "x": 0.65,
        "y": -1.6,
        "size": -45,
        "rotation": 0,
    },
    "react": {
        "x": 0.7,
        "y": -1.7,
        "size": -48,
        "rotation": 0,
    },
}

VTUBE_MIC_POSITION = {
    "x": 0.52,
    "y": -0.52,
    "size": 0.22,
    "rotation": 0,
}
