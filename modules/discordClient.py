import os
import asyncio
from dotenv import load_dotenv
import discord
from constants import DISCORD_TEXT_CHANNEL_ID, DISCORD_MAX_MESSAGE_LENGTH
from modules.module import Module
from streamingSink import StreamingSink


class DiscordClient(Module):
    def __init__(self, signals, stt, enabled=True):
        super().__init__(signals, enabled)
        self.stt = stt
        self.API = self.API(self)

        # Appears after Twitch chat (150) but before custom prompts (200)
        self.prompt_injection.priority = 160

    # --- Prompt injection (text channel messages) ---

    def get_prompt_injection(self):
        if len(self.signals.recentDiscordMessages) > 0:
            output = "\nThese are recent Discord messages:\n"
            for message in self.signals.recentDiscordMessages:
                output += message + "\n"
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
            print("Discord: DISCORD_TOKEN not set in .env — skipping.")
            return

        intents = discord.Intents.default()
        intents.message_content = True
        bot = discord.Bot(intents=intents)
        connections = {}

        @bot.event
        async def on_ready():
            print(f"Discord: {bot.user} is online.")

        # --- Text channel messages ---

        @bot.event
        async def on_message(message):
            if not self.enabled:
                return
            if message.author == bot.user:
                return
            # Filter by channel if a specific ID is configured
            if DISCORD_TEXT_CHANNEL_ID and message.channel.id != DISCORD_TEXT_CHANNEL_ID:
                return
            if not message.content or len(message.content) > DISCORD_MAX_MESSAGE_LENGTH:
                return

            print(f"Discord [{message.channel.name}] {message.author.display_name}: {message.content}")

            msgs = self.signals.recentDiscordMessages
            if len(msgs) >= 10:
                msgs.pop(0)
            msgs.append(f"{message.author.display_name}: {message.content}")
            # Trigger the setter so the sio_queue gets notified
            self.signals.recentDiscordMessages = msgs

        # --- Voice channel commands ---

        async def finished_callback(sink: StreamingSink, channel: discord.TextChannel, *args):
            sink.cleanup()
            guild_id = sink.vc.guild.id
            await sink.vc.disconnect()
            connections.pop(guild_id, None)
            await channel.send("Left the voice channel.")

        @bot.slash_command(name="ping", description="Check the bot's latency")
        async def ping(ctx):
            await ctx.respond(f"Pong! `{bot.latency * 1000:.1f} ms`")

        @bot.slash_command(name="start", description="Bot joins your voice channel and listens")
        async def start(ctx: discord.ApplicationContext):
            voice = ctx.author.voice
            if not voice:
                return await ctx.respond("You're not in a voice channel.")
            if ctx.guild.id in connections:
                return await ctx.respond("Already recording in this server.")

            vc = await voice.channel.connect()
            connections[ctx.guild.id] = vc
            vc.start_recording(
                StreamingSink(self.signals, self.stt),
                finished_callback,
                ctx.channel,
            )
            await ctx.respond(f"Joined **{voice.channel.name}** and listening.")

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
