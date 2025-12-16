"""Main entry point for the Chatty bot."""

import asyncio
import logging
import signal
import sys

from .bot import create_bot
from .scheduler import ProactiveScheduler

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Reduce noise from httpx
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point."""
    logger.info("Starting Chatty bot...")
    
    # Create bot instance
    try:
        bot = create_bot()
        logger.info(f"Bot created with character: {bot.character.name}")
    except Exception as e:
        logger.error(f"Failed to create bot: {e}")
        sys.exit(1)
    
    # Create Telegram application
    application = bot.create_application()
    
    # Create and start the proactive scheduler
    scheduler = ProactiveScheduler(bot)
    
    # Set up graceful shutdown
    stop_event = asyncio.Event()
    
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        stop_event.set()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Initialize the application
        await application.initialize()
        
        # Start the scheduler
        scheduler.start()
        
        # Start polling for Telegram updates
        await application.start()
        await application.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True,
        )
        
        logger.info("Bot is running! Press Ctrl+C to stop.")
        
        # Wait for stop signal
        await stop_event.wait()
        
    except Exception as e:
        logger.error(f"Error running bot: {e}", exc_info=True)
        
    finally:
        # Clean shutdown
        logger.info("Shutting down...")
        
        scheduler.stop()
        
        if application.updater.running:
            await application.updater.stop()
        
        await application.stop()
        await application.shutdown()
        
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())

