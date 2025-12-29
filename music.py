import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import asyncio
import os
import json
import gc
import random
import logging

# Configure Advanced Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AkazaMusic")

# FFmpeg path
FFMPEG_PATH = "ffmpeg" # Default to system path (Linux/Render)
LOCAL_FFMPEG = os.path.join(os.path.dirname(__file__), "ffmpeg-8.0.1-essentials_build", "bin", "ffmpeg.exe")

if os.path.exists(LOCAL_FFMPEG):
    FFMPEG_PATH = LOCAL_FFMPEG

ydl_opts_base = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "source_address": "0.0.0.0",
    "extract_flat": "in_playlist",
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "logtostderr": False,
    "no_color": True,
    "no_playlist": True,
    "default_search": "ytsearch",
    "socket_timeout": 15,
    "cachedir": False,
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Mode": "navigate",
    },
    "visitor_data": "CgtqbkZNQVdRUEZ6cyj5hMjKBjIKCgJUThIEGgAgWmLfAgrcAjE0LllUPVJCUUV5Y0lzT2VGb01vT29rOFd2NDBTX2Nld1RJVkNjT1A4VVRWSXk4OGxmRy1nZGxWZFVWd2x4dER1cEZfUEJReU5WajVEbXBaajhLcGxqaExKM3lIWl9ySGNXalhSSEd2ZVJ6elVHVDFIdGlmYzJGcXk5OG9vUlQ2LWxXMnlvSmNrY0tWTmtwamdLcF92RlVySWY4YXo3TjB6R2k3WF9KM2FpVHpCdW5RdTEyUlJIWGwySVh5cUkzQ0NnczIwSE9NM0NNRldRVGgwSS0xQ2owUXR5ZDY2RlZHV3cxLVI1bkFlTzF4MXBMRkFCVTViYjhwNnNHYTQ1N2pNMUIzSlRzYUI1aEhSdnVXZ2V0V0tPaXFaREJZWGQ1UUp5WVVXSGlkaWlUUFFyNmllSS13ekdvRWFjMzVkd0x3dDNGMzQzbTNqeTJNWnktSlU0R3ZvczBFeHBPdw=="
}

# Optimized Extraction Clients
extraction_clients = [
    {"extractor_args": {"youtube": {"client": ["android", "ios", "tvhtml5"]}}}, 
    {"extractor_args": {"youtube": {"client": ["web_creator", "web"]}}},
]

# Check for cookies.txt to bypass "bot detection" on Render
COOKIES_PATH = "cookies.txt"
if os.path.exists(COOKIES_PATH):
    ydl_opts_base["cookiefile"] = COOKIES_PATH
    print("[INFO] YouTube cookies detected.")
ffmpeg_opts = {
    "executable": FFMPEG_PATH,
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 10M -analyzeduration 10M",
    "options": "-vn -b:a 128k -ar 48000 -ac 2" 
}
# Quality Note: 128k is optimal for Discord streaming balance. 
# probesize/analyzeduration helps with fast stream start without stutters.

class GuildState:
    def __init__(self, guild_id, cog):
        self.guild_id = guild_id
        self.cog = cog
        self.queue = []
        self.current_song = None
        self.volume = 1.0
        self.is_paused = False
        self.voice_client = None
        self.bass_boost = False
        self.auto_play = False
        self.loop = False
        self.start_time = 0
        self.elapsed_before_pause = 0
        self.stats = {"total_played": 0, "tracks": {}}
        self.eq_gains = {"low": 0, "mid": 0, "high": 0}
        self.history = []
        
        # Concurrency Lock
        self.lock = asyncio.Lock()
        
        self.load_settings()
        self.load_stats()

    def load_stats(self):
        try:
            if os.path.exists("music_stats.json"):
                with open("music_stats.json", "r") as f:
                    data = json.load(f)
                    guild_stats = data.get(str(self.guild_id), {})
                    self.stats = guild_stats.get("stats", {"total_played": 0, "tracks": {}})
                    self.history = guild_stats.get("history", [])
        except Exception as e:
            print(f"Error loading stats: {e}")

    def save_stats(self):
        """Atomic save for music statistics to prevent corruption."""
        try:
            data = {}
            if os.path.exists("music_stats.json"):
                with open("music_stats.json", "r") as f:
                    data = json.load(f)
            
            data[str(self.guild_id)] = {
                "stats": self.stats,
                "history": self.history
            }
            
            # Temporary file used for atomic write
            with open("music_stats.json.tmp", "w") as f:
                json.dump(data, f, indent=4)
            os.replace("music_stats.json.tmp", "music_stats.json")
        except Exception as e:
            logger.error(f"Failed to save stats for guild {self.guild_id}: {e}")

    def load_settings(self):
        try:
            if os.path.exists("settings.json"):
                with open("settings.json", "r") as f:
                    data = json.load(f)
                    guild_data = data.get(str(self.guild_id), {})
                    self.volume = guild_data.get("volume", 1.0)
                    self.bass_boost = guild_data.get("bass_boost", False)
                    self.auto_play = guild_data.get("auto_play", False)
                    self.eq_gains = guild_data.get("eq_gains", {"low": 0, "mid": 0, "high": 0})
        except Exception as e:
            print(f"Error loading settings: {e}")

    def save_settings(self):
        try:
            data = {}
            if os.path.exists("settings.json"):
                with open("settings.json", "r") as f:
                    data = json.load(f)
            
            data[str(self.guild_id)] = {
                "volume": self.volume,
                "bass_boost": self.bass_boost,
                "auto_play": self.auto_play,
                "eq_gains": self.eq_gains
            }
            
            with open("settings.json", "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_states = {}

    def get_state(self, guild_id):
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = GuildState(guild_id, self)
        return self.guild_states[guild_id]

    async def api_play(self, guild_id, query, requester="Dashboard"):
        state = self.get_state(guild_id)
        guild = self.bot.get_guild(guild_id)
        if not guild: return {"error": "Guild not found"}

        vc = guild.voice_client
        if not vc:
            # Senior logic: check if requester is in a voice channel first
            # Since we don't always know requester's member object in API call, 
            # we fallback to finding ANY populated channel.
            target_channel = None
            for channel in guild.voice_channels:
                if len(channel.members) > 0:
                    target_channel = channel
                    break
            
            if not target_channel and len(guild.voice_channels) > 0:
                target_channel = guild.voice_channels[0]
            
            if target_channel:
                try:
                    vc = await target_channel.connect(timeout=20.0, reconnect=True)
                    state.voice_client = vc
                except Exception as e:
                    return {"error": f"Failed to connect to voice: {e}"}
            else:
                return {"error": "No voice channels available in this server."}

        try:
            loop = asyncio.get_event_loop()
            
            # ydl_opts passed to constructor, but we need to create ydl instance inside executor? 
            # No, ydl instance is not thread-safe if reused, but here we create one.
            # It's safer to wrap the entire extraction function.
            
            def extract(q):
                last_err = None
                for client_config in extraction_clients:
                    # Logic: Each client has 2 retries on network transient errors
                    for attempt in range(2):
                        time_to_wait = random.uniform(1.0, 2.5)
                        asyncio.run_coroutine_threadsafe(asyncio.sleep(time_to_wait), loop)
                        
                        opts = ydl_opts_base.copy()
                        opts.update(client_config)
                        try:
                            with yt_dlp.YoutubeDL(opts) as ydl:
                                return ydl.extract_info(f"ytsearch:{q}" if not q.startswith("http") else q, download=False)
                        except Exception as e:
                            last_err = e
                            err_str = str(e).lower()
                            # If it's a "Blocked" or "Private" or "Sign in" error, try next client immediately
                            if any(x in err_str for x in ["blocked", "private", "sign in", "confirm you're not a bot"]):
                                print(f"[WARN] Client {client_config} blocked. Switching...")
                                break 
                            print(f"[WARN] Extraction attempt {attempt+1} failed: {e}")
                            continue # Retry current client
                raise last_err 
            
            # Run blocking extraction in executor
            info = await loop.run_in_executor(None, extract, query)

            if not info:
                return {"error": "Could not extract song info."}

            if 'entries' in info:
                # Filter out None entries if it's a list
                valid_entries = [e for e in info['entries'] if e]
                if not valid_entries:
                    return {"error": "No playable entries found."}
                info = valid_entries[0]
            
            song_info = {
                "url": info["url"],
                "title": info.get("title", "Unknown"),
                "duration": info.get("duration", 0),
                "thumbnail": info.get("thumbnail"),
                "requester": requester,
                "original_url": info.get("webpage_url", query)
            }

            # Memory Safety: Limit queue size to 100
            if len(state.queue) >= 100:
                return {"error": "Queue limit exceeded (100 tracks)."}

            state.queue.append(song_info)
            
            # Explicitly clear 'info' and trigger GC
            info = None
            gc.collect()

            async with state.lock:
                if not vc.is_playing() and not vc.is_paused():
                    await self.play_next(guild_id)
            
            if hasattr(self.bot, 'dispatch_dashboard_update'):
                self.bot.dispatch_dashboard_update(guild_id)
            return {"status": "ok", "song": song_info}
        except Exception as e:
            print(f"[ERROR] API Play Exception: {e}")
            gc.collect()
            return {"error": "Extraction failed. Try a different link or title."}

    def get_filters(self, state):
        filters = []
        if state.bass_boost:
            filters.append("equalizer=f=40:width_type=h:width=50:g=10")
        
        if state.eq_gains["low"] != 0:
            filters.append(f"equalizer=f=100:width_type=h:width=200:g={state.eq_gains['low']}")
        if state.eq_gains["mid"] != 0:
            filters.append(f"equalizer=f=1000:width_type=h:width=1500:g={state.eq_gains['mid']}")
        if state.eq_gains["high"] != 0:
            filters.append(f"equalizer=f=8000:width_type=h:width=3000:g={state.eq_gains['high']}")
        return filters

    async def refresh_playback(self, guild_id):
        """
        Hot-restarts the audio stream with updated filters (Equalizer/Bass Boost)
        without skipping the song. Calculates elapsed time for perfect resume.
        """
        state = self.get_state(guild_id)
        guild = self.bot.get_guild(guild_id)
        if not guild or not guild.voice_client: return
        
        vc = guild.voice_client
        if not state.current_song: return

        # Calculate current elapsed time
        elapsed = state.elapsed_before_pause
        if not state.is_paused:
            elapsed += asyncio.get_event_loop().time() - state.start_time

        # Stop current source
        if vc.is_playing() or vc.is_paused():
            # Temporarily remove after callback to prevent play_next from triggering
            vc._after = None 
            vc.stop()

        # Restart with new filters and offset
        filters = self.get_filters(state)
        options = ffmpeg_opts.copy()
        options["options"] += f" -ss {elapsed}" # Seek to current position
        if filters:
            options["options"] += f" -af \"{','.join(filters)}\""

        try:
            source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(state.current_song["url"], **options))
            source.volume = state.volume
            
            state.start_time = asyncio.get_event_loop().time()
            state.elapsed_before_pause = elapsed

            def after_playing(error):
                if error:
                    print(f"[ERROR] Playback error in refresh_playback: {error}")
                coro = self.play_next(guild_id)
                asyncio.run_coroutine_threadsafe(coro, self.bot.loop)

            vc.play(source, after=after_playing)
            if state.is_paused:
                vc.pause()
        except Exception as e:
            print(f"[CRITICAL] Failed to refresh playback: {e}")
        
        if hasattr(self.bot, 'dispatch_dashboard_update'):
            self.bot.dispatch_dashboard_update(guild_id)

    @app_commands.command(name="join", description="دخول الروم الصوتي")
    async def join(self, interaction: discord.Interaction):
        if interaction.user.voice:
            channel = interaction.user.voice.channel
            state = self.get_state(interaction.guild_id)
            if interaction.guild.voice_client:
                await interaction.guild.voice_client.move_to(channel)
            else:
                state.voice_client = await channel.connect()
            
            if hasattr(self.bot, 'dispatch_dashboard_update'):
                self.bot.dispatch_dashboard_update(interaction.guild_id)
            await interaction.response.send_message("🎧 دخلت الروم الصوتي")
        else:
            await interaction.response.send_message("❌ يجب أن تكون في روم صوتي", ephemeral=True)

    @app_commands.command(name="play", description="تشغيل أو إضافة إلى القائمة")
    async def play(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()
        res = await self.api_play(interaction.guild_id, url, interaction.user.display_name)
        if "error" in res:
            await interaction.followup.send(f"❌ خطأ: {res['error']}")
        else:
            await interaction.followup.send(f"➕ أضيف إلى القائمة: **{res['song']['title']}**")

    async def play_next(self, guild_id, channel=None):
        state = self.get_state(guild_id)
        async with state.lock:
            guild = self.bot.get_guild(guild_id)
            if not guild: return
            vc = state.voice_client or guild.voice_client
            
            if not vc: return

            if not state.queue:
                state.current_song = None
                if hasattr(self.bot, 'dispatch_dashboard_update'):
                    self.bot.dispatch_dashboard_update(guild_id)
                return

            song = state.queue.pop(0)
            state.current_song = song
            state.start_time = asyncio.get_event_loop().time()
            state.elapsed_before_pause = 0
            
            # Update Stats
            state.stats["total_played"] += 1
            title = song.get("title", "Unknown")
            state.stats["tracks"][title] = state.stats["tracks"].get(title, 0) + 1
            
            # Update History
            history_item = {
                "title": song.get("title", "Unknown"),
                "thumbnail": song.get("thumbnail"),
                "requester": song.get("requester"),
                "timestamp": asyncio.get_event_loop().time()
            }
            state.history.insert(0, history_item)
            if len(state.history) > 20:
                state.history.pop()
                
            state.save_stats()
            state.elapsed_before_pause = 0
            
            # Build Filter Chain
            filters = self.get_filters(state)
            options = ffmpeg_opts.copy()
            if filters:
                options["options"] += f" -af \"{','.join(filters)}\""

            try:
                source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(song["url"], **options))
                source.volume = state.volume
                
                def after_playing(error):
                    if error:
                        print(f"[ERROR] Player Error: {error}")
                    self.bot.loop.create_task(self._delayed_next(guild_id, channel))

                if vc.is_playing() or vc.is_paused():
                    vc.stop()

                vc.play(source, after=after_playing)
                state.is_paused = False
            except Exception as e:
                print(f"[ERROR] Failed to play track {song.get('title')}: {e}")
                self.bot.loop.create_task(self.play_next(guild_id, channel))
            
            if hasattr(self.bot, 'dispatch_dashboard_update'):
                self.bot.dispatch_dashboard_update(guild_id)

    async def _delayed_next(self, guild_id, channel):
        await asyncio.sleep(1) # Gap between songs for stability
        await self.play_next(guild_id, channel)
        
        # Notify API via WebSocket (we'll implement this bridge soon)
        if hasattr(self.bot, 'dispatch_dashboard_update'):
            self.bot.dispatch_dashboard_update(guild_id)

    @app_commands.command(name="pause", description="إيقاف مؤقت")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        state = self.get_state(interaction.guild_id)
        if vc and vc.is_playing():
            vc.pause()
            state.is_paused = True
            state.elapsed_before_pause += asyncio.get_event_loop().time() - state.start_time
            if hasattr(self.bot, 'dispatch_dashboard_update'):
                self.bot.dispatch_dashboard_update(interaction.guild_id)
            await interaction.response.send_message("⏸️ تم الإيقاف المؤقت")
        else:
            await interaction.response.send_message("❌ لا يوجد تشغيل حالياً", ephemeral=True)

    @app_commands.command(name="resume", description="استئناف التشغيل")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        state = self.get_state(interaction.guild_id)
        if vc and vc.is_paused():
            vc.resume()
            state.is_paused = False
            state.start_time = asyncio.get_event_loop().time() # Reset start time for the resume period
            if hasattr(self.bot, 'dispatch_dashboard_update'):
                self.bot.dispatch_dashboard_update(interaction.guild_id)
            await interaction.response.send_message("▶️ تم الاستئناف")
        else:
            await interaction.response.send_message("❌ البوت غير متوقف مؤقتاً", ephemeral=True)

    @app_commands.command(name="skip", description="تخطي الأغنية")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            if hasattr(self.bot, 'dispatch_dashboard_update'):
                self.bot.dispatch_dashboard_update(interaction.guild_id)
            await interaction.response.send_message("⏭️ تم التخطي")
        else:
            await interaction.response.send_message("❌ لا يوجد تشغيل", ephemeral=True)

    @app_commands.command(name="volume", description="تغيير مستوى الصوت")
    async def volume(self, interaction: discord.Interaction, level: int):
        if not 0 <= level <= 100:
            return await interaction.response.send_message("❌ مستوى الصوت يجب أن يكون بين 0 و 100", ephemeral=True)
        
        state = self.get_state(interaction.guild_id)
        state.volume = level / 100
        state.save_settings()
        vc = interaction.guild.voice_client
        if vc and vc.source:
            vc.source.volume = state.volume
        
        if hasattr(self.bot, 'dispatch_dashboard_update'):
          if vc and vc.source:
            vc.source.volume = state.volume
        
        if hasattr(self.bot, 'dispatch_dashboard_update'):
            self.bot.dispatch_dashboard_update(interaction.guild_id)
        await interaction.response.send_message(f"🔊 مستوى الصوت الآن: **{level}%**")

    @app_commands.command(name="stop", description="إيقاف ومسح القائمة")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        state = self.get_state(interaction.guild_id)
        state.queue.clear()
        state.current_song = None
        if vc:
            vc.stop()
            if hasattr(self.bot, 'dispatch_dashboard_update'):
                self.bot.dispatch_dashboard_update(interaction.guild_id)
            await interaction.response.send_message("⏹️ تم الإيقاف ومسح القائمة")
        else:
            await interaction.response.send_message("❌ غير متصل", ephemeral=True)

    @app_commands.command(name="leave", description="الخروج من الروم")
    async def leave(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        state = self.get_state(interaction.guild_id)
        state.queue.clear()
        state.current_song = None
        if vc:
            await vc.disconnect()
            state.voice_client = None
            if hasattr(self.bot, 'dispatch_dashboard_update'):
                self.bot.dispatch_dashboard_update(interaction.guild_id)
            await interaction.response.send_message("👋 خرجت من الروم")
        else:
            await interaction.response.send_message("❌ غير متصل", ephemeral=True)

    def move_queue_item(self, guild_id, from_index, to_index):
        state = self.get_state(guild_id)
        if 0 <= from_index < len(state.queue) and 0 <= to_index <= len(state.queue):
            item = state.queue.pop(from_index)
            state.queue.insert(to_index, item)
            if hasattr(self.bot, 'dispatch_dashboard_update'):
                self.bot.dispatch_dashboard_update(guild_id)
            return True
        return False

    def delete_queue_item(self, guild_id, index):
        state = self.get_state(guild_id)
        if 0 <= index < len(state.queue):
            state.queue.pop(index)
            if hasattr(self.bot, 'dispatch_dashboard_update'):
                self.bot.dispatch_dashboard_update(guild_id)
            return True
        return False
