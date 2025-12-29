import discord
import yt_dlp
import asyncio
from .config import FFMPEG_OPTIONS
import gc

# Configure yt-dlp for high stability
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

class MusicPlayer:
    """Handles audio extraction and playback logic."""
    def __init__(self, bot):
        self.bot = bot
        self.ydl = yt_dlp.YoutubeDL(YDL_OPTIONS)

    async def extract_info(self, query: str):
        """Extracts song metadata and stream URL without blocking the loop."""
        loop = asyncio.get_event_loop()
        try:
            # Check if it's already a URL
            is_url = query.startswith('http')
            data = await loop.run_in_executor(None, lambda: self.ydl.extract_info(query if is_url else f"ytsearch:{query}", download=False))
            
            if 'entries' in data:
                data = data['entries'][0]

            return {
                'title': data['title'],
                'url': data['url'],
                'thumbnail': data.get('thumbnail'),
                'duration': data.get('duration'),
                'requester': 'Dashboard', # Default, updated by bot.py
                'original_url': data.get('webpage_url')
            }
        except Exception as e:
            print(f"[ERROR] Extraction failed for '{query}': {e}")
            return None
        finally:
            gc.collect()

    def create_source(self, url: str, volume: float = 1.0):
        """Creates a high-quality PCM volume transformer for Discord."""
        try:
            ffmpeg_src = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
            source = discord.PCMVolumeTransformer(ffmpeg_src, volume=volume)
            return source
        except Exception as e:
            print(f"[ERROR] FFmpeg source creation failed: {e}")
            return None
