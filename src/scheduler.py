"""Scheduler for proactive messaging."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from .bot import ChattyBot

logger = logging.getLogger(__name__)

# How long without a message before sending a proactive message
INACTIVITY_THRESHOLD_HOURS = 24

# How often to check for inactivity
CHECK_INTERVAL_HOURS = 1


class ProactiveScheduler:
    """Schedules proactive messages based on user inactivity."""
    
    def __init__(self, bot: "ChattyBot"):
        """
        Initialize the scheduler.
        
        Args:
            bot: The ChattyBot instance to use for sending messages
        """
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self._last_proactive_message: datetime | None = None
    
    def start(self) -> None:
        """Start the scheduler."""
        self.scheduler.add_job(
            self._check_and_send_proactive,
            trigger=IntervalTrigger(hours=CHECK_INTERVAL_HOURS),
            id="proactive_check",
            name="Check for inactivity and send proactive message",
            replace_existing=True,
        )
        
        self.scheduler.start()
        logger.info(
            f"Proactive scheduler started. "
            f"Checking every {CHECK_INTERVAL_HOURS} hour(s) for {INACTIVITY_THRESHOLD_HOURS}+ hours of inactivity."
        )
    
    def stop(self) -> None:
        """Stop the scheduler."""
        self.scheduler.shutdown(wait=False)
        logger.info("Proactive scheduler stopped.")
    
    async def _check_and_send_proactive(self) -> None:
        """Check if we should send a proactive message and send one if needed."""
        try:
            last_user_message = self.bot.memory.get_last_user_message_time()
            
            if last_user_message is None:
                logger.debug("No messages in history, skipping proactive check")
                return
            
            now = datetime.utcnow()
            time_since_last = now - last_user_message
            threshold = timedelta(hours=INACTIVITY_THRESHOLD_HOURS)
            
            logger.debug(
                f"Time since last user message: {time_since_last}, "
                f"threshold: {threshold}"
            )
            
            if time_since_last < threshold:
                logger.debug("User active recently, no proactive message needed")
                return
            
            # Check if we already sent a proactive message recently
            if self._last_proactive_message:
                time_since_proactive = now - self._last_proactive_message
                # Don't send more than one proactive message per inactivity period
                if time_since_proactive < threshold:
                    logger.debug("Already sent proactive message recently, skipping")
                    return
            
            # Generate and send proactive message
            await self._send_proactive_message()
            
        except Exception as e:
            logger.error(f"Error in proactive check: {e}", exc_info=True)
    
    async def _send_proactive_message(self) -> None:
        """Generate and send a proactive message."""
        try:
            # Get context for generating the message
            recent_messages = self.bot.memory.get_recent_history(limit=10)
            user_facts = self.bot.memory.get_all_facts()
            
            # Get the proactive prompt from character config
            proactive_prompt = self.bot.character.get_proactive_prompt("check_in")
            
            if not proactive_prompt:
                proactive_prompt = (
                    "It's been a while since we last talked. "
                    "Generate a natural, casual message to check in with the user."
                )
            
            # Generate the message
            message = self.bot.llm.generate_proactive_message(
                system_prompt=self.bot.character.get_system_prompt(),
                proactive_prompt=proactive_prompt,
                recent_messages=recent_messages,
                user_facts=user_facts,
            )
            
            # Send it
            success = await self.bot.send_proactive_message(message)
            
            if success:
                self._last_proactive_message = datetime.utcnow()
                logger.info("Proactive message sent successfully")
            
        except Exception as e:
            logger.error(f"Error sending proactive message: {e}", exc_info=True)



