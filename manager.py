from bot.bot import bot
import asyncio

async def main():
    # Entry point for Render
    try:
        await bot.start("") # Token will be read from os.environ in bot.py logic if updated, or pass it here. 
        # Actually bot.py class doesn't read token automatically in constructor. 
    except Exception as e:
        print(f"FAILED TO START: {e}")

if __name__ == "__main__":
    from bot.config import TOKEN
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("FATAL ERROR: BOT_TOKEN not set in Environment Variables!")
    else:
        asyncio.run(bot.start(TOKEN))
