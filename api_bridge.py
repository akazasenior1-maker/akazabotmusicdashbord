from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import httpx
import uvicorn
import asyncio
import os
import config
from typing import Optional, List, Dict
import subprocess
import psutil
import signal
import sys
import gc

app = FastAPI()

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Reference to the bot instance and process
bot_instance = None
bot_process: Optional[subprocess.Popen] = None
active_websockets: Dict[int, List[WebSocket]] = {} # guild_id -> list of websockets
cache_data = {} # In-memory cache for Discord API
last_broadcasted_state = {} # guild_id -> last status dict
LISTENING_PORT = 8000 # Default to manager port

# Frontend path configuration
frontend_path = os.path.join(os.path.dirname(__file__), "dashboard", "frontend")

@app.on_event("startup")
async def startup_event():
    print("[INFO] Server starting up...")
    # Auto-start bot if token is available (Production/Render mode)
    # Auto-start bot if token is available (Production/Render mode)
    token = config.TOKEN
    if token and token != "YOUR_BOT_TOKEN_HERE":
        print("[INFO] Starting Bot Watchdog...")
        asyncio.create_task(bot_watchdog())

async def bot_watchdog():
    print("[INFO] Bot Watchdog Active.")
    while True:
        try:
            global bot_process
            
            if bot_process:
                if bot_process.poll() is not None:
                    print(f"[WARN] Bot process ended (Code: {bot_process.returncode}). Restarting...")
                    bot_process = None
                    await start_bot_internal()
            else:
                # Check via API if instance is missing
                status = await get_bot_status()
                if not status["is_running"]:
                    print("[INFO] Bot process not found. Starting core...")
                    await start_bot_internal()

            await asyncio.sleep(15) 
                
        except Exception as e:
            print(f"[ERROR] Watchdog error: {e}")
            await asyncio.sleep(10)

async def cleanup_bot_processes():
    """Aggressive cleanup of any hanging bot/ffmpeg processes."""
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            cmd = " ".join(proc.info.get('cmdline') or [])
            name = proc.info.get('name', '').lower()
            if ('bot.py' in cmd and 'python' in name) or ('ffmpeg' in name):
                print(f"[CLEANUP] Terminating {name} (PID: {proc.pid})")
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    gc.collect()

async def start_bot_internal():
    global bot_process
    if bot_process: return

    python_exe = os.path.join(os.path.dirname(__file__), "venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = sys.executable 

    try:
        # On Render (Linux), we don't need CREATE_NEW_PROCESS_GROUP usually, 
        # but let's keep it compatible.
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        bot_process = subprocess.Popen(
            [python_exe, "bot.py"],
            cwd=os.path.dirname(__file__),
            creationflags=creationflags
        )
        print("[INFO] Bot process launched successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to auto-start bot: {e}")

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(frontend_path, "index.html"))

@app.get("/style.css")
async def read_css():
    return FileResponse(os.path.join(frontend_path, "style.css"))

@app.get("/app.js")
async def read_js():
    return FileResponse(os.path.join(frontend_path, "app.js"))

def get_bot():
    if bot_instance is None:
        raise HTTPException(status_code=503, detail="Bot not ready")
    return bot_instance

async def verify_token(token: str):
    now = asyncio.get_event_loop().time()
    if token in cache_data and now - cache_data[token]["time"] < 300:
        return cache_data[token]["user"]
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            r = await client.get("https://discord.com/api/users/@me", headers=headers)
            if r.status_code == 200:
                user = r.json()
                
                # Capping cache size to prevent OOM
                if len(cache_data) > 50:
                    cache_data.clear() # Simple flush if too large
                
                cache_data[token] = {"user": user, "time": now}
                return user
            elif r.status_code == 401:
                # Token expired or revoked
                if token in cache_data: del cache_data[token]
                raise HTTPException(status_code=401, detail="Session expired. Please re-authenticate.")
            else:
                print(f"[DEBUG] verify_token failed for token ...{token[-5:]}: {r.status_code} - {r.text}")
                # If we have a cached version and it's not TOO old, allow grace period on API failure
                if token in cache_data and now - cache_data[token]["time"] < 1800:
                    return cache_data[token]["user"]
                raise HTTPException(status_code=r.status_code, detail="Discord API unreachable")
        except Exception as e:
            if isinstance(e, HTTPException): raise e
            print(f"[ERROR] verify_token failed: {e}")
            # Cache fallback logic (grace period for Discord API lag)
            if token in cache_data and now - cache_data[token]["time"] < 3600:
                return cache_data[token]["user"]
            raise HTTPException(status_code=500, detail="Identity verification failed")

@app.websocket("/ws/{guild_id}")
async def websocket_endpoint(websocket: WebSocket, guild_id: int):
    print(f"[WS] New connection request for guild {guild_id}")
    await websocket.accept()
    if guild_id not in active_websockets:
        active_websockets[guild_id] = []
    active_websockets[guild_id].append(websocket)
    print(f"[WS] Connection accepted for guild {guild_id}")
    try:
        while True:
            await websocket.receive_text() # Keep alive
    except WebSocketDisconnect:
        active_websockets[guild_id].remove(websocket)

async def broadcast_update(guild_id: int):
    if guild_id in active_websockets:
        bot = get_bot()
        guild = bot.get_guild(guild_id)
        music_cog = bot.get_cog("Music")
        state = music_cog.get_state(guild_id)
        
        vc = state.voice_client or (guild.voice_client if guild else None)
        
        # Get bot's highest role in the guild for display
        dj_role = "Bot"
        if guild:
            bot_member = guild.me
            if bot_member:
                # Filter for roles that look like DJ roles or just the highest
                dj_roles = [r.name for r in bot_member.roles if "DJ" in r.name.upper() or "MUSIC" in r.name.upper()]
                if dj_roles:
                    dj_role = dj_roles[-1] # Take the most specific one
                elif len(bot_member.roles) > 1:
                    dj_role = bot_member.top_role.name

        # Calculate current elapsed time
        current_elapsed = state.elapsed_before_pause
        if not state.is_paused and state.current_song:
            current_elapsed += asyncio.get_event_loop().time() - state.start_time

        # Prepare status payload
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
            "history": state.history,
            "eq_gains": state.eq_gains
        }
        
        disconnected = []
        for ws in active_websockets[guild_id]:
            try:
                await ws.send_json(status)
            except:
                disconnected.append(ws)
        
        for ws in disconnected:
            active_websockets[guild_id].remove(ws)

@app.get("/auth/login")
async def login():
    url = f"https://discord.com/api/oauth2/authorize?client_id={config.CLIENT_ID}&redirect_uri={config.REDIRECT_URI}&response_type=code&scope=identify%20guilds"
    return RedirectResponse(url)

@app.get("/auth/callback")
async def callback(code: str):
    async with httpx.AsyncClient() as client:
        data = {
            "client_id": config.CLIENT_ID,
            "client_secret": config.CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.REDIRECT_URI,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        r = await client.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
        if r.status_code != 200:
            print(f"[DEBUG] Auth callback failed: {r.status_code} - {r.text}")
            return JSONResponse(status_code=r.status_code, content=r.json())
        
        token_data = r.json()
        access_token = token_data["access_token"]
        return RedirectResponse(f"/?token={access_token}")

@app.get("/api/user")
async def get_user(token: str):
    return await verify_token(token)

@app.get("/api/servers")
async def get_servers(token: str):
    try:
        user = await verify_token(token)
        
        # If we are the manager, try to get info from the bot if possible
        # but for server list, we can just use the token to get guilds from Discord
        
        cache_key = f"guilds_{token}"
        if cache_key in cache_data and asyncio.get_event_loop().time() - cache_data[cache_key]["time"] < 5:
            return cache_data[cache_key]["guilds"]

        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {token}"}
            r = await client.get("https://discord.com/api/users/@me/guilds", headers=headers)
            if r.status_code != 200:
                print(f"[DEBUG] get_servers failed: {r.status_code} - {r.text}")
                return []
            
            guilds = r.json()
            managed_guilds = []

        # If we are the manager, we don't have bot_instance, so we proxy the "bot_in" check
        # Actually, for simplicity, we'll just check if the bot process is running 
        # and then let the frontend handle the "bot not connected" states.
        # But for the "bot_in" flag, let's keep it simple: if manager, we might not know.
        
        # Manager Proxy Logic: If we are manager (no bot instance), proxy to bot for accurate role checks
        if bot_instance is None:
             async with httpx.AsyncClient() as client:
                try:
                    # Proxy the request to the Bot process
                    r = await client.get(f"http://127.0.0.1:8001/api/servers?token={token}", timeout=10.0)
                    if r.status_code == 200:
                        return r.json()
                except Exception as e:
                    print(f"[WARN] Failed to proxy get_servers to bot: {e}")
                    # Fallback to local admin check if bot is down
        
        # Fallback / Local Manager Logic (if proxy failed or we just want basic admin check)
        if LISTENING_PORT == 8000 or bot_instance is None:
            # Manager logic: assume bot is in if user is admin for now, 
            # or try to probe the bot API
            for guild in guilds:
                permissions = int(guild.get("permissions", 0))
                is_admin = (permissions & 0x8) or (permissions & 0x20)
                if is_admin:
                    guild["bot_in"] = True # Assume for list display
                    guild["has_access"] = True
                    managed_guilds.append(guild)
            return managed_guilds

        # Bot logic (8001)
        bot = get_bot()
        user_id = int(user["id"])
        
        for guild in guilds:
            guild_id = int(guild["id"])
            permissions = int(guild.get("permissions", 0))
            is_admin = (permissions & 0x8) or (permissions & 0x20)
            
            discord_guild = bot.get_guild(guild_id)
            if discord_guild:
                member = discord_guild.get_member(user_id)
                if not member:
                    try:
                        print(f"[DEBUG] Member {user_id} not in cache for guild {guild_id}, fetching...")
                        member = await discord_guild.fetch_member(user_id)
                    except Exception as e:
                        print(f"[ERROR] Failed to fetch member: {e}")
                
                has_dj_role = False
                if member:
                    # Relaxed check: Accept exact match OR any role with "DJ" or "Music" in name (case-insensitive)
                    has_dj_role = any("DJ" in r.name.upper() or "MUSIC" in r.name.upper() or r.name == "⚛ | 𝐃𝐉𝐌𝐀𝐒𝐓𝐄𝐑" for r in member.roles)
                    print(f"[DEBUG] User {user['username']} in {discord_guild.name}: Roles={[r.name for r in member.roles]}, HasDJ={has_dj_role}")
                else:
                    print(f"[DEBUG] Member {user_id} found in neither cache nor API for guild {guild_id}")
                
                # Check if role exists in guild (regardless of whether user has it)
                role_exists = any(r.name == "⚛ | 𝐃𝐉𝐌𝐀𝐒𝐓𝐄𝐑" for r in discord_guild.roles)
                
                # Include guild in list but mark access
                guild["bot_in"] = True
                guild["has_access"] = has_dj_role or is_admin
                guild["role_missing"] = not role_exists
                managed_guilds.append(guild)
                
            elif is_admin:
                # If bot not in, but user is admin, they might want to invite it
                guild["bot_in"] = False
                guild["has_access"] = True
                managed_guilds.append(guild)
            
        cache_data[cache_key] = {"guilds": managed_guilds, "time": asyncio.get_event_loop().time()}
        return managed_guilds
    except Exception as e:
        print(f"[ERROR] Exception in get_servers: {e}")
        return []

@app.get("/api/server/{guild_id}/status")
async def get_server_status(guild_id: int, token: str):
    await verify_token(token)
    
    if bot_instance is None:
        # Proxy to Bot
        async with httpx.AsyncClient() as client:
            try:
                r = await client.get(f"http://127.0.0.1:8001/api/server/{guild_id}/status?token={token}", timeout=10.0)
                return JSONResponse(status_code=r.status_code, content=r.json())
            except Exception as e:
                return JSONResponse(status_code=503, content={"detail": "Bot unreachable"})

    # Bot implementation
    try:
        bot = get_bot()
        guild = bot.get_guild(guild_id)
        if not guild:
            raise HTTPException(status_code=404, detail="Guild not found")
        
        music_cog = bot.get_cog("Music")
        state = music_cog.get_state(guild_id)
        
        vc = guild.voice_client
    
        # Get bot's highest role for display
        dj_role = "Bot"
        bot_member = guild.me
        if bot_member:
            dj_roles = [r.name for r in bot_member.roles if "DJ" in r.name.upper() or "MUSIC" in r.name.upper()]
            if dj_roles:
                dj_role = dj_roles[-1]
            elif len(bot_member.roles) > 1:
                dj_role = bot_member.top_role.name

        # Calculate current elapsed time
        current_elapsed = state.elapsed_before_pause
        if not state.is_paused and state.current_song:
            current_elapsed += asyncio.get_event_loop().time() - state.start_time

        return {
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
            "history": state.history,
            "eq_gains": state.eq_gains
        }
    except Exception as e:
        print(f"[ERROR] Exception in get_server_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/server/{guild_id}/settings")
async def update_settings(guild_id: int, params: Dict, token: str):
    await verify_token(token)
    
    if bot_instance is None:
        # Proxy to Bot
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(f"http://127.0.0.1:8001/api/server/{guild_id}/settings?token={token}", json=params, timeout=10.0)
                return JSONResponse(status_code=r.status_code, content=r.json())
            except Exception as e:
                return JSONResponse(status_code=503, content={"detail": "Bot unreachable"})

    # Bot implementation
    bot = get_bot()
    music_cog = bot.get_cog("Music")
    state = music_cog.get_state(guild_id)
    
    if "volume" in params:
        state.volume = params["volume"] / 100
    if "bass_boost" in params:
        state.bass_boost = params["bass_boost"]
        await music_cog.refresh_playback(guild_id)
    if "auto_play" in params:
        state.auto_play = params["auto_play"]
    if "eq_gains" in params:
        state.eq_gains = params["eq_gains"]
        await music_cog.refresh_playback(guild_id)
        
    state.save_settings()
    await broadcast_update(guild_id)
    return {"status": "ok"}

class ControlParams(BaseModel):
    level: Optional[int] = None
    enabled: Optional[bool] = None
    index: Optional[int] = None
    from_index: Optional[int] = None
    to_index: Optional[int] = None
    band: Optional[str] = None
    gain: Optional[int] = None
    query: Optional[str] = None
    token: str

@app.post("/api/server/{guild_id}/control")
async def control_bot(guild_id: int, action: str, params: ControlParams):
    try:
        user = await verify_token(params.token)
        
        if bot_instance is None:
            # Proxy to Bot
            async with httpx.AsyncClient() as client:
                try:
                    r = await client.post(f"http://127.0.0.1:8001/api/server/{guild_id}/control?action={action}", json=params.dict(), timeout=60.0)
                    return JSONResponse(status_code=r.status_code, content=r.json())
                except Exception as e:
                    return JSONResponse(status_code=503, content={"detail": "Bot unreachable"})

        # Bot implementation
        bot = get_bot()
        music_cog = bot.get_cog("Music")
        state = music_cog.get_state(guild_id)
        guild = bot.get_guild(guild_id)
        
        vc = guild.voice_client if guild else None
        
        # Access control check
        user_id = int(user["id"])
        member = guild.get_member(user_id)
        is_admin = member.guild_permissions.administrator or member.guild_permissions.manage_guild if member else False
        # Relaxed check for control endpoint as well
        has_dj_role = any("DJ" in r.name.upper() or "MUSIC" in r.name.upper() or r.name == "⚛ | 𝐃𝐉𝐌𝐀𝐒𝐓𝐄𝐑" for r in member.roles) if member else False
        
        if not (has_dj_role or is_admin):
            raise HTTPException(status_code=403, detail="You do not have the ⚛ | 𝐃𝐉𝐌𝐀𝐒𝐓𝐄𝐑 role required to use this dashboard.")
        
        if action == "play":
            if not params.query:
                raise HTTPException(status_code=400, detail="Query is required")
            res = await music_cog.api_play(guild_id, params.query, user.get("username", "Dashboard"))
            if "error" in res:
                raise HTTPException(status_code=400, detail=res["error"])
            await broadcast_update(guild_id)
            return {"status": "ok"}

        if not vc:
            raise HTTPException(status_code=400, detail="Bot not in voice channel")

        if action == "pause":
            if vc.is_playing():
                vc.pause()
                state.is_paused = True
        elif action == "resume":
            if vc.is_paused():
                vc.resume()
                state.is_paused = False
        elif action == "skip":
            vc.stop()
        elif action == "stop":
            state.queue.clear()
            state.current_song = None
            vc.stop()
        elif action == "volume":
            lvl = params.level if params.level is not None else 100
            state.volume = lvl / 100
            state.save_settings()
            if vc and vc.source:
                vc.source.volume = state.volume
        elif action == "bass_boost":
            state.bass_boost = params.enabled if params.enabled is not None else False
            state.save_settings()
            await music_cog.refresh_playback(guild_id)
        elif action == "auto_play":
            state.auto_play = params.enabled if params.enabled is not None else False
            state.save_settings()
        elif action == "leave":
            if vc:
                await vc.disconnect()
                state.voice_client = None
                state.queue.clear()
                state.current_song = None
        elif action == "delete_queue":
            idx = params.index
            if idx is not None:
                music_cog.delete_queue_item(guild_id, idx)
        elif action == "move_queue":
            f = params.from_index
            t = params.to_index
            if f is not None and t is not None:
                music_cog.move_queue_item(guild_id, f, t)
        elif action == "equalizer":
                state.eq_gains[params.band] = params.gain
                state.save_settings()
                await music_cog.refresh_playback(guild_id)
        elif action == "create_role":
            if not is_admin:
                raise HTTPException(status_code=403, detail="Only admins can create roles.")
            if any(r.name == "⚛ | 𝐃𝐉𝐌𝐀𝐒𝐓𝐄𝐑" for r in guild.roles):
                return {"status": "exists", "message": "Role already exists"}
            try:
                await guild.create_role(name="⚛ | 𝐃𝐉𝐌𝐀𝐒𝐓𝐄𝐑", color=discord.Color.from_rgb(0, 242, 255), reason="Dashboard One-Click Setup")
                return {"status": "created"}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to create role: {e}")
        
        await broadcast_update(guild_id)
        return {"status": "ok"}
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        print(f"[ERROR] Exception in control_bot: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bot/status")
async def get_bot_status():
    global bot_process
    is_running = False
    
    if bot_process:
        if bot_process.poll() is None:
            is_running = True
        else:
            bot_process = None # Process ended

    # Fallback check via psutil in case it was started manually or elsewhere
    if not is_running:
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                if proc.info['name'] == 'python.exe' and 'bot.py' in str(proc.info['cmdline']):
                    is_running = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    # If we are the manager (no bot_instance), we need to ask the bot if IT is ready
    bot_ready = bot_instance is not None and bot_instance.is_ready()
    if not bot_ready and is_running:
        try:
            # Ping the bot's internal API to see if it's fully loaded
            async with httpx.AsyncClient() as client:
                r = await client.get("http://127.0.0.1:8001/api/bot/status", timeout=2.0)
                if r.status_code == 200:
                    data = r.json()
                    # If the bot answers, it means the API is up. 
                    # The bot's OWN /api/bot/status will say bot_ready=True because it has bot_instance set.
                    bot_ready = data.get("bot_ready", False)
        except Exception:
            # Bot might be starting up and API not ready yet
            bot_ready = False

    return {
        "is_running": is_running,
        "bot_ready": bot_ready
    }

@app.post("/api/bot/start")
async def start_bot(token: str):
    user = await verify_token(token)
    
    # If OWNER_ID is set, strict check
    if config.OWNER_ID:
        if str(user["id"]) != str(config.OWNER_ID):
             raise HTTPException(status_code=403, detail="Security Restrictions: Only the Bot Owner can start the system.")
    else:
        # Fallback to Admin check if owner not configured
        managed_guilds = await get_servers(token)
        is_admin = any(g.get("permissions", 0) & 0x8 for g in managed_guilds)
        if not is_admin:
            raise HTTPException(status_code=403, detail="Only server administrators can start the bot.")
    global bot_process
    
    status = await get_bot_status()
    if status["is_running"]:
        return {"status": "already_running"}

    python_exe = os.path.join(os.path.dirname(__file__), "venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = sys.executable # Fallback to current python

    try:
        # Start bot in a new process group so it doesn't die with the manager
        # Using shell=False for safety
        bot_process = subprocess.Popen(
            [python_exe, "bot.py"],
            cwd=os.path.dirname(__file__),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        )
        return {"status": "starting"}
    except Exception as e:
        print(f"[ERROR] Failed to start bot: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bot/stop")
async def stop_bot(token: str):
    user = await verify_token(token)
    
    # If OWNER_ID is set, strict check
    if config.OWNER_ID:
        if str(user["id"]) != str(config.OWNER_ID):
             raise HTTPException(status_code=403, detail="Security Restrictions: Only the Bot Owner can restart the system.")
    else:
        # Fallback to Admin check if owner not configured
        managed_guilds = await get_servers(token)
        is_admin = any(g.get("permissions", 0) & 0x8 for g in managed_guilds)
        if not is_admin:
            raise HTTPException(status_code=403, detail="Only server administrators can stop the bot.")
    global bot_process, bot_instance
    
    stopped = False
    # Try to stop via psutil for more reliability
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            if proc.info['name'] == 'python.exe' and 'bot.py' in str(proc.info['cmdline']):
                proc.terminate()
                stopped = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
            
    if bot_process:
        bot_process.terminate()
        bot_process = None
        stopped = True
    
    bot_instance = None # Reset instance
    return {"status": "stopped" if stopped else "not_found"}

@app.post("/api/internal/broadcast/{guild_id}")
async def internal_broadcast(guild_id: int, status: Dict):
    """Internal endpoint for the bot to push status updates to the manager's WebSockets."""
    if LISTENING_PORT != 8000:
        return {"error": "Only manager can broadcast"}
        
    # Optimization: Only broadcast if state changed meaningfully
    global last_broadcasted_state
    prev = last_broadcasted_state.get(guild_id)
    
    # Filter out elapsed time changes if they are small (e.g. < 2 seconds) 
    # and nothing else changed, to reduce noise.
    # But for "100% real-time", we might want to keep it.
    # Let's check for "Structural" changes.
    structural_keys = ["current_song", "is_paused", "volume", "queue", "bass_boost", "auto_play", "history", "eq_gains"]
    changed = False
    if not prev:
        changed = True
    else:
        for k in structural_keys:
            if status.get(k) != prev.get(k):
                changed = True
                break
        
        # Also check elapsed if it jumped significantly (e.g. seek or major lag)
        if not changed:
            prev_elapsed = prev.get("elapsed", 0)
            curr_elapsed = status.get("elapsed", 0)
            if abs(curr_elapsed - prev_elapsed) > 2:
                changed = True

    if not changed:
        return {"status": "skipped"}

    # Limit state cache
    if len(last_broadcasted_state) > 100:
        last_broadcasted_state.clear()
        
    last_broadcasted_state[guild_id] = status

    if guild_id in active_websockets:
        disconnected = []
        for ws in active_websockets[guild_id]:
            try:
                await ws.send_json(status)
            except:
                disconnected.append(ws)
        
        for ws in disconnected:
            active_websockets[guild_id].remove(ws)
    return {"status": "ok"}

# Static Files Mount (at the end to avoid intercepting specialized routes)
app.mount("/static", StaticFiles(directory=frontend_path), name="static")

async def run_server(port=8000):
    global LISTENING_PORT
    LISTENING_PORT = port
    print(f"[OK] Dashboard API starting on port {port} with WebSocket support")
    config_uvicorn = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config_uvicorn)
    await server.serve()
