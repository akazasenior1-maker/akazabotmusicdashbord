import os

# BOT_TOKEN should be set in environment variables for security
TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Discord OAuth2 Credentials
CLIENT_ID = os.environ.get("CLIENT_ID", "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
# For production (Render), set REDIRECT_URI in environment variables.
# Example: https://your-site.onrender.com/auth/callback
REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://localhost:8000/auth/callback")
