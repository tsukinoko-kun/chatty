"""Main entry point for the Chatty bot."""

import asyncio
import logging
import os
import signal
import sys

from .scheduler import ProactiveScheduler

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Reduce noise from httpx
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def run_telegram_bot(stop_event: asyncio.Event) -> None:
    """Run the Telegram bot."""
    from .bot import create_bot

    try:
        bot = create_bot()
        logger.info(f"Telegram bot created with character: {bot.character.name}")
    except ValueError as e:
        logger.error(f"Failed to create Telegram bot: {e}")
        return

    # Create Telegram application
    application = bot.create_application()

    # Create and start the proactive scheduler
    scheduler = ProactiveScheduler(bot)

    try:
        # Initialize the application
        await application.initialize()

        # Fetch the user's name to provide context to the LLM
        user_name = await bot.fetch_user_name()
        if user_name:
            logger.info(f"Telegram: LLM will address user as: {user_name}")
        else:
            logger.warning(
                "Telegram: Could not fetch user name, LLM will not have user context"
            )

        # Start the scheduler
        scheduler.start()

        # Start polling for Telegram updates
        await application.start()
        await application.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True,
        )

        logger.info("Telegram bot is running!")

        # Wait for stop signal
        await stop_event.wait()

    except Exception as e:
        logger.error(f"Error running Telegram bot: {e}", exc_info=True)

    finally:
        # Clean shutdown
        logger.info("Shutting down Telegram bot...")

        scheduler.stop()

        if application.updater.running:
            await application.updater.stop()

        await application.stop()
        await application.shutdown()

        logger.info("Telegram bot stopped.")


async def run_discord_bot(stop_event: asyncio.Event) -> None:
    """Run the Discord bot."""
    from .discord_bot import create_discord_bot

    bot = create_discord_bot()
    if bot is None:
        logger.info("Discord bot not configured, skipping")
        return

    logger.info(f"Discord bot created with character: {bot.character.name}")

    # Create and start the proactive scheduler
    scheduler = ProactiveScheduler(bot)

    try:
        # Start the bot in a task so we can cancel it
        bot_task = asyncio.create_task(bot.start())

        # Wait a moment for the bot to connect
        await asyncio.sleep(2)

        # Fetch the user's name to provide context to the LLM
        user_name = await bot.fetch_user_name()
        if user_name:
            logger.info(f"Discord: LLM will address user as: {user_name}")
        else:
            logger.warning(
                "Discord: Could not fetch user name, LLM will not have user context"
            )

        # Start the scheduler
        scheduler.start()

        logger.info("Discord bot is running!")

        # Wait for stop signal
        await stop_event.wait()

        # Cancel the bot task
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass

    except Exception as e:
        logger.error(f"Error running Discord bot: {e}", exc_info=True)

    finally:
        # Clean shutdown
        logger.info("Shutting down Discord bot...")

        scheduler.stop()
        await bot.close()

        logger.info("Discord bot stopped.")


async def main() -> None:
    """Main entry point."""
    logger.info("Starting Chatty bot...")

    # Check which bots are configured
    telegram_configured = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    discord_configured = bool(
        os.getenv("DISCORD_BOT_TOKEN") and os.getenv("DISCORD_USER_ID")
    )

    if not telegram_configured and not discord_configured:
        logger.error(
            "No bots configured. Set TELEGRAM_BOT_TOKEN/TELEGRAM_USER_ID "
            "and/or DISCORD_BOT_TOKEN/DISCORD_USER_ID environment variables."
        )
        sys.exit(1)

    # Set up graceful shutdown
    stop_event = asyncio.Event()

    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Collect tasks for configured bots
    tasks = []

    if telegram_configured:
        logger.info("Telegram bot is configured")
        tasks.append(asyncio.create_task(run_telegram_bot(stop_event)))

    if discord_configured:
        logger.info("Discord bot is configured")
        tasks.append(asyncio.create_task(run_discord_bot(stop_event)))

    # Wait for all bot tasks to complete
    if tasks:
        platforms = []
        if telegram_configured:
            platforms.append("Telegram")
        if discord_configured:
            platforms.append("Discord")
        logger.info(f"Running on: {', '.join(platforms)}. Press Ctrl+C to stop.")

        await asyncio.gather(*tasks)

    logger.info("All bots stopped.")


if __name__ == "__main__":
    asyncio.run(main())
