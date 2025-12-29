import os

# 🔒 Security & Identification
TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CLIENT_ID = os.environ.get("CLIENT_ID", "1451230914561577232")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://akazabotmusicdashbord.onrender.com/auth/callback")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# 🎵 Audio Engine Configuration (Senior Level)
BITRATE = 192000 # 192kbps High-Fidelity
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -b:a 192k -af "loudnorm=I=-16:TP=-1.5:LRA=11"'
}

# 🌐 Dashboard Uplink Config
DASHBOARD_PORT = int(os.environ.get("PORT", 8000))
SYNC_INTERVAL = 3 # Real-time sync every 3 seconds
HEARTBEAT_TIMEOUT = 10

# 📋 Performance & Limits
MAX_QUEUE_SIZE = 500
MAX_HISTORY_SIZE = 100
CACHE_CLEAR_INTERVAL = 3600 # 1 hour
