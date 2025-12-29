import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import time
from .config import TOKEN, SYNC_INTERVAL
from .music_player import MusicPlayer
from .queue_manager import QueueManager
from .voice_manager import VoiceManager
from .dashboard_bridge import DashboardBridge

class GuildState:
    """Stores the real-time state of a specific guild's music player."""
    def __init__(self, guild_id):
        self.guild_id = guild_id
        self.current_song = None
        self.is_paused = False
        self.volume = 1.0
        self.bass_boost = False
        self.auto_play = True
        self.eq_gains = {"low": 0, "mid": 0, "high": 0}
        self.start_time = 0
        self.pause_start_time = 0
        self.total_paused_duration = 0
        self.voice_client = None
        self.queue_list = []
        self.history = []
        self.listeners_count = 0

    def get_elapsed(self):
        if not self.current_song or self.start_time == 0:
            return 0
        if self.is_paused:
            return self.pause_start_time - self.start_time - self.total_paused_duration
        return time.time() - self.start_time - self.total_paused_duration

class AkazaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)
        
        # Core Components
        self.player = MusicPlayer(self)
        self.queue_mgr = QueueManager()
        self.voice_mgr = VoiceManager(self)
        self.bridge = DashboardBridge(self)
        
        # State Tracking
        self.guild_states = {} # guild_id -> GuildState

    def get_guild_state(self, guild_id: int) -> GuildState:
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = GuildState(guild_id)
        return self.guild_states[guild_id]

    async def setup_hook(self):
        """Initializes components and registers Slash Commands."""
        print("[AKAZA] Initializing Systems...")
        await self.tree.sync()
        print(f"[AKAZA] Unified Engine Operational. Synced Slash Commands.")
        
        # Run Dashboard Bridge in the same loop
        asyncio.create_task(self.run_bridge())
        # Run periodic state broadcaster
        asyncio.create_task(self.broadcast_loop())

    async def run_bridge(self):
        import uvicorn
        from .config import DASHBOARD_PORT
        config = uvicorn.Config(self.bridge.app, host="0.0.0.0", port=DASHBOARD_PORT, log_level="error")
        server = uvicorn.Server(config)
        await server.serve()

    async def broadcast_loop(self):
        """Periodically sends state updates to all active dashboard connections."""
        while not self.is_closed():
            for guild_id in list(self.bridge.active_websockets.keys()):
                await self.bridge.broadcast_state(guild_id)
            await asyncio.sleep(SYNC_INTERVAL)

    async def on_ready(self):
        print(f"[ONLINE] Akaza Music Bot: {self.user.name}")
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="Premium Neon Music"))

    async def dashboard_play(self, guild_id: int, query: str):
        """Play logic triggered from the Web Dashboard."""
        state = self.get_guild_state(guild_id)
        guild = self.get_guild(guild_id)
        if not guild: return

        # Try to find a voice channel to join
        target_channel = None
        if state.voice_client:
            target_channel = state.voice_client.channel
        else:
            # Join the first voice channel with members, or just the first one
            for vc in guild.voice_channels:
                if len(vc.members) > 0:
                    target_channel = vc
                    break
            if not target_channel and guild.voice_channels:
                target_channel = guild.voice_channels[0]

        if not target_channel: return

        state.voice_client = await self.voice_mgr.connect_to(target_channel)
        if not state.voice_client: return

        song = await self.player.extract_info(query)
        if not song: return
        
        song['requester'] = "Dashboard"
        
        if state.voice_client.is_playing() or state.voice_client.is_paused():
            self.queue_mgr.add_to_queue(guild_id, song)
            state.queue_list = self.queue_mgr.get_queue(guild_id)
        else:
            await play_song(guild_id, song)

# Initialize instance
bot = AkazaBot()

# --- Slash Command Implementations ---

@bot.tree.command(name="play", description="Summon music into your channel")
@app_commands.describe(query="Song name or URL")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    state = bot.get_guild_state(interaction.guild_id)
    
    # 1. Voice Connection
    if not interaction.user.voice:
        return await interaction.followup.send("❌ You must be in a voice channel!")
    
    state.voice_client = await bot.voice_mgr.connect_to(interaction.user.voice.channel)
    if not state.voice_client:
        return await interaction.followup.send("❌ Could not establish voice uplink.")

    # 2. Extraction
    song = await bot.player.extract_info(query)
    if not song:
        return await interaction.followup.send("❌ Signal decoding failed. Bad URL or restricted video.")
    
    song['requester'] = interaction.user.display_name
    
    # 3. Add to Queue or Play Immediately
    if state.voice_client.is_playing() or state.voice_client.is_paused():
        bot.queue_mgr.add_to_queue(interaction.guild_id, song)
        state.queue_list = bot.queue_mgr.get_queue(interaction.guild_id)
        await interaction.followup.send(f"✅ Added to Queue: **{song['title']}**")
    else:
        await play_song(interaction.guild_id, song)
        await interaction.followup.send(f"🎶 Now Streaming: **{song['title']}**")

async def play_next(guild_id):
    state = bot.get_guild_state(guild_id)
    next_song = bot.queue_mgr.get_next(guild_id)
    state.queue_list = bot.queue_mgr.get_queue(guild_id)
    state.history = bot.queue_mgr.get_history(guild_id)
    
    if next_song:
        await play_song(guild_id, next_song)
    else:
        state.current_song = None

async def play_song(guild_id, song):
    state = bot.get_guild_state(guild_id)
    if not state.voice_client or not state.voice_client.is_connected():
        return

    source = bot.player.create_source(song['url'], volume=state.volume)
    if not source: return

    state.current_song = song
    state.start_time = time.time()
    state.total_paused_duration = 0
    state.is_paused = False
    
    def after_playing(error):
        if error: print(f"[ERROR] Playback error: {error}")
        asyncio.run_coroutine_threadsafe(play_next(guild_id), bot.loop)

    state.voice_client.play(source, after=after_playing)

@bot.tree.command(name="stop", description="Stop the music and clear the queue")
async def stop(interaction: discord.Interaction):
    state = bot.get_guild_state(interaction.guild_id)
    bot.queue_mgr.clear(interaction.guild_id)
    state.queue_list = []
    if state.voice_client:
        state.voice_client.stop()
    await interaction.response.send_message("⏹️ Systems Halted. Queue purged.")

@bot.tree.command(name="skip", description="Skip to the next transmission")
async def skip(interaction: discord.Interaction):
    state = bot.get_guild_state(interaction.guild_id)
    if state.voice_client:
        state.voice_client.stop()
        await interaction.response.send_message("⏭️ Skipping to next signal...")
    else:
        await interaction.response.send_message("❌ Nothing is playing.")

@bot.tree.command(name="pause", description="Pause current execution")
async def pause(interaction: discord.Interaction):
    state = bot.get_guild_state(interaction.guild_id)
    if state.voice_client and state.voice_client.is_playing():
        state.voice_client.pause()
        state.is_paused = True
        state.pause_start_time = time.time()
        await interaction.response.send_message("⏸️ Execution Suspended.")
    else:
        await interaction.response.send_message("❌ Not playing.")

@bot.tree.command(name="resume", description="Resume execution")
async def resume(interaction: discord.Interaction):
    state = bot.get_guild_state(interaction.guild_id)
    if state.voice_client and state.voice_client.is_paused():
        state.voice_client.resume()
        state.is_paused = False
        state.total_paused_duration += time.time() - state.pause_start_time
        await interaction.response.send_message("▶️ Execution Resumed.")

@bot.tree.command(name="volume", description="Adjust the audio level")
@app_commands.describe(level="Volume level 1-200")
async def volume(interaction: discord.Interaction, level: int):
    state = bot.get_guild_state(interaction.guild_id)
    state.volume = min(max(level / 100, 0), 2.0)
    if state.voice_client and state.voice_client.source:
        state.voice_client.source.volume = state.volume
    await interaction.response.send_message(f"🔊 Output calibrated to: **{level}%**")
