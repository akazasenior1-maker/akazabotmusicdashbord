import discord
from discord.ext import commands
from music import Music
import config
import api_bridge
import asyncio
import httpx

intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True
intents.guilds = True
intents.members = True # Required to check roles/permissions


class MusicBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.add_cog(Music(self))
        # Sync all commands
        await self.tree.sync()
        print("[OK] Commands synced")
        
        # Connect bot to API bridge on port 8001
        api_bridge.bot_instance = self
        
        # Overwrite the broadcast_update function locally to use IPC
        # This ensures all calls inside cogs go to the manager
        original_broadcast = api_bridge.broadcast_update
        async def ipc_broadcast(guild_id: int):
            # We call the original bot-side logic to get the status dict
            # but then we send it to the manager via HTTP
            try:
                # We need to reach into the internal bot logic to get the status
                music_cog = self.get_cog("Music")
                state = music_cog.get_state(guild_id)
                guild = self.get_guild(guild_id)
                vc = state.voice_client or (guild.voice_client if guild else None)
                
                dj_role = "Bot"
                if guild:
                    bot_member = guild.me
                    if bot_member:
                        dj_roles = [r.name for r in bot_member.roles if "DJ" in r.name.upper() or "MUSIC" in r.name.upper()]
                        dj_role = dj_roles[-1] if dj_roles else (bot_member.top_role.name if len(bot_member.roles) > 1 else "Bot")

                current_elapsed = state.elapsed_before_pause
                if not state.is_paused and state.current_song:
                    current_elapsed += asyncio.get_event_loop().time() - state.start_time

                status = {
                    "online": True,
                    "connected": vc is not None,
                    "channel": vc.channel.name if vc and vc.channel else None,
                    "current_song": state.current_song,
                    "is_paused": state.is_paused,
                    "volume": int(state.volume * 100),
                    "queue": state.queue,
                    "bass_boost": state.bass_boost,
                    "auto_play": state.auto_play,
                    "listeners": len(vc.channel.members) - 1 if vc and vc.channel else 0,
                    "dj_role": dj_role,
                    "start_time": state.start_time,
                    "elapsed": int(current_elapsed),
                    "stats": state.stats,
                    "eq_gains": state.eq_gains
                }
                
                async with httpx.AsyncClient() as client:
                    await client.post(f"http://localhost:8000/api/internal/broadcast/{guild_id}", json=status)
            except Exception as e:
                print(f"[ERROR] IPC Broadcast failed: {e}")

        api_bridge.broadcast_update = ipc_broadcast
        
        # Start Internal API for Manager to control us
        self.loop.create_task(api_bridge.run_server(port=8001))
        print("[OK] Internal Bot API started on port 8001")

    def dispatch_dashboard_update(self, guild_id: int):
        self.loop.create_task(api_bridge.broadcast_update(guild_id))

bot = MusicBot()

@bot.event
async def on_ready():
    print(f"[OK] Bot logged in as {bot.user}")

if __name__ == "__main__":
    bot.run(config.TOKEN)
