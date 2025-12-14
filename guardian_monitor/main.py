import asyncio
import os
import sys
from dotenv import load_dotenv
from guardian_monitor.graph import create_graph
from guardian_monitor import bot

load_dotenv()



async def main():
    print("Initializing Guardian System...")
    local_mode = os.getenv("LOCAL_MODE", "False").lower() == "true"
    print(f"Mode: {'LOCAL' if local_mode else 'SSH'}")

    # Initialize Bot
    # We do not use app.run_polling() because that blocks.
    # We use updater.start_polling() context or similar approach for async integration
    # python-telegram-bot v20+ recommended way:
    application = bot.create_bot_app()
    
    try:
        if application:
            print("Starting Telegram Bot...")
            await application.initialize()
            await application.start()
            print("Bot is running. Press Ctrl+C to stop.")
            
            # Keep alive
            stop_signal = asyncio.Event()
            # We need polling
            await application.updater.start_polling()
            await stop_signal.wait()

        else:
            print("Telegram Token not found. Set TELEGRAM_TOKEN in .env")
    except KeyboardInterrupt:
        pass
    finally:
        if application:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped.")
