import discord
import asyncio

class VoiceManager:
    """Manages resilient voice connections and channel operations."""
    def __init__(self, bot):
        self.bot = bot

    async def connect_to(self, channel: discord.VoiceChannel):
        """Safely connect to a voice channel with retry logic."""
        if not channel: return None
        
        try:
            # Check if someone else is already connected
            vc = channel.guild.voice_client
            if vc:
                if vc.channel.id == channel.id:
                    return vc
                await vc.move_to(channel)
                return vc
            
            # Fresh connection
            return await channel.connect(timeout=20.0, reconnect=True)
        except Exception as e:
            print(f"[ERROR] Voice connection failed in {channel.guild.name}: {e}")
            return None

    async def disconnect_from(self, guild: discord.Guild):
        """Safely disconnect from a voice channel."""
        vc = guild.voice_client
        if vc:
            await vc.disconnect()
            return True
        return False

    def is_connected(self, guild: discord.Guild):
        """Check connection status."""
        return guild.voice_client and guild.voice_client.is_connected()
