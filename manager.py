import asyncio
import api_bridge
import os

async def main():
    print("="*40)
    print(" AKAZA MUSIC MANAGEMENT SYSTEM ")
    print("="*40)
    print(f"Working Directory: {os.getcwd()}")
    
    # Start the API bridge server
    # This server will stay alive to manage the bot process
    port = int(os.environ.get("PORT", 8000))
    try:
        await api_bridge.run_server(port=port)
    except KeyboardInterrupt:
        print("\n[INFO] Manager shutting down...")
    except Exception as e:
        print(f"[ERROR] Manager failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
