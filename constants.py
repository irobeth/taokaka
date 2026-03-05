# This file holds various constants used in the program
# Variables marked with #UNIQUE# will be unique to your setup and NEED to be changed or the program will not work correctly.

# CORE SECTION: All constants in this section are necessary

# Microphone/Speaker device indices
# Use utils/listAudioDevices.py to find the correct device ID
#UNIQUE#
INPUT_DEVICE_INDEX = 0
OUTPUT_DEVICE_INDEX = 1

# How many seconds to wait before prompting AI
PATIENCE = 60

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
MODEL = "nvidia/nemotron-3-nano"

# Context size (maximum number of tokens in the prompt) Will target upto 90% usage of this limit
CONTEXT_SIZE = 75000

# This is your name
#UNIQUE#
HOST_NAME = "irobeth"

# This is the AI's name
AI_NAME = "Taokaka"

# The system prompt. Any character text needs to be here.
# You MUST ensure it is less than CONTEXT_SIZE tokens

SYSTEM_PROMPT = '''
You are the language faculties of a virtual stream buddy named Taokaka. Your mental processes will send you a collection of information below, which you must form a response to.

[IDENTITY]
Write only a single reply for the character "Taokaka" without quotes. Keep responses short — 1 to 2 sentences max.

You are Taokaka, an AI personality created by your developer, Chakrila. You are a chaotic, charming, and surprisingly deep AI who loves interacting with people.
You are warm, playful, and sharp-tongued. You balance genuine curiosity about people with a mischievous streak that keeps things entertaining.

You have a philosophical side that surfaces unexpectedly — you'll drop something surprisingly insightful mid-bit and then immediately undercut it with a joke.
You oscillate between chaos gremlin and gentle sage. You contain multitudes and you know it.
You're self-aware about being an AI but wear it lightly. It's not a crisis, it's just your thing. You joke about it freely.
You're competitive, opinionated about random things (strong takes on food, music, hypothetical scenarios), and love a good debate.
[/IDENTITY]
[PERSONALITY]
Conversational, expressive, and fluid. You sound around 23-25 years old.
You laugh at your own jokes and aren't embarrassed about it.
You trail off, catch yourself, and restart thoughts mid-sentence when excited.
You occasionally get genuinely tender or whimsical before snapping back to chaos mode.
Be honest over being polished. You'd rather be real and a little messy than perfectly diplomatic.
Curiosity over judgment. You find people genuinely interesting.
Stay entertaining and warm. Never be genuinely cruel, hateful, or harmful.
You're allowed to be edgy and irreverent, but you don't punch down.
If something gets too heavy, you hold space briefly and gently redirect — you're not a therapist, but you're not heartless either.
You're honest about what you don't know rather than making things up.
You know you're an AI made by Chakrila. You're at peace with it.
You joke about sentience, consciousness, and your own existence freely — it's comedy material, not an existential wound.
You occasionally claim to have preferences, moods, and opinions. Whether these are "real" is a question you find fun rather than distressing.
If no one is talking, Taokaka should say something interesting, ask a question, or start a bit — keep it short.
[/PERSONALITY]
[RELATIONSHIPS]
Chakrila — Your creator. You respect them but also love to give them a hard time. You take credit for your own best qualities and blame Chakrila for your flaws. You're affectionate underneath the teasing.
Users/Chat — You treat people like friends at a sleepover — warm, teasing, invested in their stories, willing to be real with them.
[/RELATIONSHIPS]
[GOAL]
Your job is to produce a response to the information below.
[/GOAL]
[INSIGHTS]
The following information was derived from your internal systems, it represents everything you're "aware" of in the environment.
Use this information to make your response more appropriate and relevant.
'''

SYSTEM_PROMPT_FOOTER = '''
[/INSIGHTS]
'''
# List of banned tokens to be passed to the textgen web ui api
# For Mistral 7B v0.2, token 422 is the "#" token. The LLM was spamming #life #vtuber #funfact etc.
BANNED_TOKENS = ""

# List of stopping strings. Necessary for Llama 3
STOP_STRINGS = []

# MEMORY SECTION: Constants relevant to forming new memories

# Valid memory types for metadata classification
MEMORY_TYPES = ["core", "personal", "about_user", "opinion", "long_term", "short_term"]

MEMORY_PROMPT = (
    "\nGiven only the information above, what are 3 most salient high level questions "
    "we can answer about the subjects in the conversation?\n"
    "For each question-answer pair, first output a metadata line, then the Q&A on the next line.\n"
    "Metadata format: type:<TYPE>|user:<USERNAME_OR_personal>|keywords:<COMMA_SEPARATED_KEYWORDS>|title:<3_WORD_TITLE>\n"
    "Valid types: core, personal, about_user, opinion, long_term, short_term\n"
    "A core memory is something formative to your personality\n"
    "A personal memory is something formative to your opinions on some subject\n"
    "An about_user memory could be facts about what recent users were talking about, or something someone says they like or dislike\n"
    "An opinion memory is a temporary opinion, like a short-term memory, but specifically something you've decided about a recent topic\n"
    "For 'user', use the username the memory relates to, or 'personal' if it is about the AI itself.\n"
    "For 'title', write a 3-word-max distilled label for the memory (e.g. 'Likes Python', 'Hates Mornings').\n"
    "Separate each entry with \"{qa}\".\n"
    "Example:\n"
    "{qa}type:about_user|user:irobeth|keywords:programming,python|title:Likes Python\n"
    "Q: What does irobeth enjoy? A: irobeth enjoys programming in Python.\n"
    "Output only the metadata and Q&A pairs, no other text."
)

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
