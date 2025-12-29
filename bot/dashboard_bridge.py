import httpx
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

    def setup_routes(self):
        @self.app.get("/auth/login")
        async def login():
            auth_url = (
                f"https://discord.com/api/oauth2/authorize"
                f"?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
                f"&response_type=code&scope=identify%20guilds"
            )
            return {"url": auth_url}

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
            if token not in self.tokens: raise HTTPException(401)
            
            # Get User Guilds
            headers = {'Authorization': f'Bearer {token}'}
            r = await self.http_client.get("https://discord.com/api/users/@me/guilds", headers=headers)
            user_guilds = r.json()
            
            servers = []
            for g in user_guilds:
                # Check if bot is in this guild and user has MANAGE_GUILD (0x20) or ADMIN (0x8)
                guild_id = int(g['id'])
                discord_guild = self.bot.get_guild(guild_id)
                
                perms = int(g['permissions'])
                has_manage = (perms & 0x20) == 0x20 or (perms & 0x8) == 0x8
                
                servers.append({
                    "id": g['id'],
                    "name": g['name'],
                    "icon": g['icon'],
                    "bot_in": discord_guild is not None,
                    "has_access": has_manage,
                    "permissions": perms
                })
            return servers

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
