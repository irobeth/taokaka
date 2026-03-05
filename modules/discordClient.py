import os
import asyncio
import time
from functools import partial
from dotenv import load_dotenv
import discord
from constants import DISCORD_MAX_MESSAGE_LENGTH
from modules.module import Module
from streamingSink import StreamingSink
from discordSTT import DiscordSTT


class DiscordClient(Module):
    def __init__(self, signals, stt, tts, interface, enabled=True):
        super().__init__(signals, enabled)
        self.stt = stt
        self.tts = tts
        self.interface = interface
        self.discord_stt = None
        self.API = self.API(self)

        # Appears after Twitch chat (150) but before custom prompts (200)
        self.prompt_injection.priority = 160

    # --- Prompt injection (text channel messages) ---

    def get_prompt_injection(self):
        if len(self.signals.recentDiscordMessages) > 0:
            output = "\nThese are recent Discord messages:\n"
            for message in self.signals.recentDiscordMessages:
                output += message["text"] + "\n"
            output += "Pick the highest quality message with the most potential for an interesting answer and respond to them.\n"
            self.prompt_injection.text = output
        else:
            self.prompt_injection.text = ""
        return self.prompt_injection

    def cleanup(self):
        self.signals.recentDiscordMessages = []

    # --- Bot logic ---

    async def run(self):
        if not self.enabled:
            return

        load_dotenv()
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            self.interface.log("DISCORD_TOKEN not set in .env — skipping.", source="Discord")
            return

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # requires Server Members Intent in Discord dev portal
        bot = discord.Bot(intents=intents)
        connections = {}
        monitored_channels = {}  # guild_id -> text channel id
        quiet_guilds = set()      # guild_ids running in quiet mode

        @bot.event
        async def on_ready():
            self.interface.log(f"{bot.user} is online.", source="Discord")

        # --- Text channel messages ---

        @bot.event
        async def on_message(message):
            if not self.enabled:
                return
            if message.author == bot.user:
                return
            # Only listen in the channel where /start was invoked for this guild
            if message.guild is None or monitored_channels.get(message.guild.id) != message.channel.id:
                return
            if not message.content or len(message.content) > DISCORD_MAX_MESSAGE_LENGTH:
                return

            self.interface.log(f"[{message.channel.name}] {message.author.display_name}: {message.content}", source="Discord")

            msgs = self.signals.recentDiscordMessages
            if len(msgs) >= 10:
                msgs.pop(0)
            msgs.append({"text": f"{message.author.display_name}: {message.content}", "timestamp": time.time()})
            # Trigger the setter so the sio_queue gets notified
            self.signals.recentDiscordMessages = msgs

        # --- Voice channel commands ---

        async def finished_callback(sink: StreamingSink, channel: discord.TextChannel, *args):
            sink.cleanup()
            guild_id = sink.vc.guild.id
            await sink.vc.disconnect()
            connections.pop(guild_id, None)
            monitored_channels.pop(guild_id, None)
            quiet = guild_id in quiet_guilds
            quiet_guilds.discard(guild_id)
            self.signals.discord_vc = None
            self.interface.log("Left the voice channel.", source="Discord")
            if not quiet:
                await channel.send("Left the voice channel.")

        @bot.slash_command(name="ping", description="Check the bot's latency")
        async def ping(ctx):
            await ctx.respond(f"Pong! `{bot.latency * 1000:.1f} ms`")

        @bot.slash_command(name="patience", description="Set how many seconds Taokaka waits before speaking unprompted")
        async def set_patience(ctx: discord.ApplicationContext, seconds: int):
            if seconds < 1:
                return await ctx.respond("Patience must be at least 1 second.")
            self.signals.patience = seconds
            await ctx.respond(f"Patience set to **{seconds}s**.")

        @bot.slash_command(name="ttsengine", description="Switch TTS engine (f5 = voice clone, kokoro = fast preset)")
        async def ttsengine(ctx: discord.ApplicationContext,
                            engine: discord.Option(str, "Engine to use", choices=["f5", "kokoro"])):
            self.signals.tts_engine = engine
            label = "F5-TTS (voice clone)" if engine == "f5" else "Kokoro ONNX (fast preset)"
            await ctx.respond(f"TTS engine switched to **{label}**.")

        @bot.slash_command(name="echo", description="Make Taokaka say something immediately (TTS test)")
        async def echo(ctx: discord.ApplicationContext, text: str):
            await ctx.respond(f"Playing: *{text}*")
            self.tts.play(text)

        @bot.slash_command(name="speak", description="Make Taokaka speak immediately")
        async def speak(ctx: discord.ApplicationContext):
            self.signals.last_message_time = 0.0
            await ctx.respond("Nudging Taokaka…")

        @bot.slash_command(name="start", description="Bot joins your voice channel and listens")
        async def start(ctx: discord.ApplicationContext,
                        quiet: discord.Option(bool, "Suppress status messages in channel", default=False)):
            voice = ctx.author.voice
            if not voice:
                return await ctx.respond("You're not in a voice channel.", ephemeral=True)
            if ctx.guild.id in connections:
                return await ctx.respond("Already recording in this server.", ephemeral=True)

            # Lazily initialize per-user Discord STT (keeps model across reconnects)
            if self.discord_stt is None:
                self.discord_stt = DiscordSTT(self.signals, self.interface, partial(self.stt.process_text, source="discord"))
                self.discord_stt.init_model()

            vc = await voice.channel.connect()
            connections[ctx.guild.id] = vc
            monitored_channels[ctx.guild.id] = ctx.channel.id
            if quiet:
                quiet_guilds.add(ctx.guild.id)
            self.signals.discord_vc = vc
            vc.start_recording(
                StreamingSink(self.signals, self.discord_stt),
                finished_callback,
                ctx.channel,
            )

            msg = f"Joined **{voice.channel.name}** and monitoring **#{ctx.channel.name}**."
            self.interface.log(msg, source="Discord")
            await ctx.respond(msg, ephemeral=quiet)

        @bot.slash_command(name="sq", description="Alias for /start quiet")
        async def sq(ctx: discord.ApplicationContext):
            await start(ctx, quiet=True)

        @bot.slash_command(name="stop", description="Bot leaves the voice channel")
        async def stop(ctx: discord.ApplicationContext):
            if ctx.guild.id not in connections:
                return await ctx.respond("Not currently in a voice channel.")
            vc = connections[ctx.guild.id]
            vc.stop_recording()  # triggers finished_callback
            await ctx.respond("Stopping recording…")

        try:
            await bot.start(token)
        except asyncio.CancelledError:
            await bot.close()

    # --- API (mirrors TwitchClient.API pattern) ---

    class API:
        def __init__(self, outer):
            self.outer = outer

        def set_discord_status(self, status: bool):
            self.outer.enabled = status
            if not status:
                self.outer.signals.recentDiscordMessages = []

        def get_discord_status(self) -> bool:
            return self.outer.enabled
