from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import httpx
import asyncio
import json
import time
from typing import Dict, List
from .config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI

class DashboardBridge:
    def __init__(self, bot):
        self.bot = bot
        self.app = FastAPI(title="Akaza Dashboard Uplink")
        self.active_websockets: Dict[int, List[WebSocket]] = {}
        self.http_client = httpx.AsyncClient()
        
        # Security: In-memory token store (Simplified for rebuild)
        self.tokens = {} # token -> user_data
        
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        self.setup_routes()
        
        # Serve static files for the dashboard
        # This must be mounted AFTER routes or using a specific order
        self.app.mount("/", StaticFiles(directory="dashboard/frontend", html=True), name="frontend")

    def setup_routes(self):
        @self.app.get("/auth/login")
        async def login():
            auth_url = (
                f"https://discord.com/api/oauth2/authorize"
                f"?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
                f"&response_type=code&scope=identify%20guilds"
            )
            return RedirectResponse(url=auth_url)

        @self.app.get("/auth/callback")
        async def callback(code: str):
            # 1. Exchange code for token
            data = {
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': REDIRECT_URI
            }
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            r = await self.http_client.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
            if r.status_code != 200: return {"error": "Failed to exchange token"}
            
            token_data = r.json()
            access_token = token_data['access_token']
            
            # 2. Get User Info
            headers = {'Authorization': f'Bearer {access_token}'}
            user_r = await self.http_client.get("https://discord.com/api/users/@me", headers=headers)
            user = user_r.json()
            
            # 3. Store locally (In-proc)
            self.tokens[access_token] = user
            
            # Redirect back to frontend with token
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=f"/?token={access_token}")

        @self.app.get("/api/user")
        async def get_user(token: str):
            if token not in self.tokens:
                raise HTTPException(401, "Invalid session")
            return self.tokens[token]

        @self.app.get("/api/servers")
        async def get_servers(token: str):
            if not token or token not in self.tokens:
                print(f"[AUTH] ❌ Invalid or missing token")
                raise HTTPException(401, "Session expired or invalid")
            
            print(f"[SERVERS] 🔍 Fetching guilds from Discord...")
            
            # Retry mechanism with exponential backoff
            max_retries = 3
            base_delay = 1
            
            for attempt in range(max_retries):
                try:
                    headers = {'Authorization': f'Bearer {token}'}
                    
                    # Add timeout to prevent hanging
                    r = await asyncio.wait_for(
                        self.http_client.get("https://discord.com/api/users/@me/guilds", headers=headers),
                        timeout=10.0
                    )
                    
                    print(f"[DISCORD API] Response status: {r.status_code}")
                    
                    # Handle specific error cases
                    if r.status_code == 401:
                        print(f"[DISCORD API] ❌ Token expired or invalid")
                        raise HTTPException(401, "Discord session expired. Please login again.")
                    
                    elif r.status_code == 429:
                        # Rate limited
                        retry_after = int(r.headers.get('Retry-After', base_delay * (2 ** attempt)))
                        print(f"[DISCORD API] ⏳ Rate limited. Retry after {retry_after}s...")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_after)
                            continue
                        raise HTTPException(429, "Discord API rate limit. Please try again later.")
                    
                    elif r.status_code != 200:
                        error_text = r.text[:200] if r.text else "Unknown error"
                        print(f"[DISCORD API] ❌ Status {r.status_code}: {error_text}")
                        if attempt < max_retries - 1:
                            delay = base_delay * (2 ** attempt)
                            print(f"[RETRY] Attempt {attempt + 1}/{max_retries}, waiting {delay}s...")
                            await asyncio.sleep(delay)
                            continue
                        raise HTTPException(r.status_code, f"Discord API error: {error_text}")
                    
                    # Success - parse response
                    user_guilds = r.json()
                    
                    if not isinstance(user_guilds, list):
                        print(f"[DISCORD API] ⚠️ Unexpected response format: {type(user_guilds)}")
                        # Try to extract error message if it's a dict
                        if isinstance(user_guilds, dict):
                            error_msg = user_guilds.get('message', 'Unknown format')
                            raise HTTPException(500, f"Discord returned error: {error_msg}")
                        return []
                    
                    print(f"[SERVERS] ✅ Found {len(user_guilds)} guilds")
                    
                    servers = []
                    for g in user_guilds:
                        try:
                            guild_id = int(g['id'])
                            discord_guild = self.bot.get_guild(guild_id)
                            
                            perms = int(g.get('permissions', 0))
                            has_manage = (perms & 0x20) == 0x20 or (perms & 0x8) == 0x8
                            
                            servers.append({
                                "id": g['id'],
                                "name": g.get('name', 'Unknown Server'),
                                "icon": g.get('icon'),
                                "bot_in": discord_guild is not None,
                                "has_access": has_manage,
                                "permissions": perms
                            })
                        except (KeyError, ValueError) as entry_err:
                            print(f"[SKIP] ⚠️ Bad guild entry: {entry_err}")
                            continue
                    
                    print(f"[SERVERS] ✅ Returning {len(servers)} processed servers")
                    return servers
                    
                except asyncio.TimeoutError:
                    print(f"[DISCORD API] ⏱️ Request timeout (attempt {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        print(f"[RETRY] Waiting {delay}s before retry...")
                        await asyncio.sleep(delay)
                        continue
                    raise HTTPException(504, "Discord API timeout. Please try again.")
                    
                except HTTPException:
                    # Re-raise HTTP exceptions as-is
                    raise
                    
                except Exception as e:
                    print(f"[SYSTEM ERROR] ❌ Unexpected error: {type(e).__name__}: {str(e)}")
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        print(f"[RETRY] Attempt {attempt + 1}/{max_retries}, waiting {delay}s...")
                        await asyncio.sleep(delay)
                        continue
                    raise HTTPException(500, f"Internal error: {str(e)}")
            
            # Should never reach here, but just in case
            raise HTTPException(500, "Failed after all retry attempts")

        @self.app.get("/health")
        async def health_check():
            return {"status": "operational", "bot_ready": self.bot.is_ready()}

        @self.app.websocket("/ws/{guild_id}")
        async def websocket_endpoint(websocket: WebSocket, guild_id: int):
            await websocket.accept()
            if guild_id not in self.active_websockets:
                self.active_websockets[guild_id] = []
            self.active_websockets[guild_id].append(websocket)
            
            try:
                # Send initial state immediately on connect
                await self.broadcast_state(guild_id, [websocket])
                while True:
                    await websocket.receive_text() # Keep-alive
            except WebSocketDisconnect:
                if guild_id in self.active_websockets:
                    self.active_websockets[guild_id].remove(websocket)

        @self.app.get("/api/bot/status")
        async def get_bot_global_status():
            """Returns the overall health of the bot process."""
            return {
                "is_running": True,
                "bot_ready": self.bot.is_ready(),
                "latency": round(self.bot.latency * 1000, 2) if self.bot.is_ready() else 0,
                "engine": "Akaza Senior V3 (Unified Process)"
            }

        @self.app.post("/api/server/{guild_id}/control")
        async def control_bot(guild_id: int, action: str, params: dict = None):
            if not self.bot.is_ready():
                raise HTTPException(status_code=503, detail="Bot engine not ready")
            
            guild = self.bot.get_guild(guild_id)
            if not guild:
                raise HTTPException(status_code=404, detail="Guild not found")
            
            state = self.bot.get_guild_state(guild_id)
            params = params or {}
            
            try:
                if action == "play":
                    query = params.get("query")
                    if not query: raise HTTPException(400, "Missing query")
                    asyncio.create_task(self.bot.dashboard_play(guild_id, query))
                
                elif action == "pause":
                    if state.voice_client:
                        state.voice_client.pause()
                        state.is_paused = True
                        state.pause_start_time = time.time()
                
                elif action == "resume":
                    if state.voice_client:
                        state.voice_client.resume()
                        state.is_paused = False
                        state.total_paused_duration += time.time() - state.pause_start_time
                
                elif action == "skip":
                    if state.voice_client: state.voice_client.stop()
                
                elif action == "stop":
                    self.bot.queue_mgr.clear(guild_id)
                    state.queue_list = []
                    if state.voice_client: state.voice_client.stop()

                elif action == "volume":
                    level = params.get("level", 100)
                    state.volume = min(max(level / 100, 0), 2.0)
                    if state.voice_client and state.voice_client.source:
                        state.voice_client.source.volume = state.volume

                await self.broadcast_state(guild_id)
                return {"status": "dispatched", "action": action}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/server/{guild_id}/status")
        async def get_status(guild_id: int):
            state = self.bot.get_guild_state(guild_id)
            return {"online": True, "connected": state.voice_client is not None}

    async def broadcast_state(self, guild_id: int, target_websockets: List[WebSocket] = None):
        """Broadcasts the current bot state to the dashboard via WebSockets."""
        state = self.bot.get_guild_state(guild_id)
        if not state: return

        payload = {
            "online": True,
            "connected": state.voice_client is not None,
            "channel": state.voice_client.channel.name if state.voice_client else None,
            "current_song": state.current_song,
            "is_paused": state.is_paused,
            "volume": int(state.volume * 100),
            "queue": state.queue_list,
            "bass_boost": state.bass_boost,
            "auto_play": state.auto_play,
            "listeners": state.listeners_count,
            "elapsed": int(state.get_elapsed()),
            "history": state.history,
            "eq_gains": state.eq_gains
        }

        websockets = target_websockets if target_websockets is not None else self.active_websockets.get(guild_id, [])
        dead_ws = []
        
        for ws in websockets:
            try:
                await ws.send_json(payload)
            except:
                dead_ws.append(ws)
        
        for dw in dead_ws:
            if guild_id in self.active_websockets:
                self.active_websockets[guild_id].remove(dw)
