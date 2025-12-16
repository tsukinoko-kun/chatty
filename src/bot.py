"""Telegram bot handler."""

import logging
import os
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .character import Character
from .llm import LLMClient
from .memory import MemoryManager

logger = logging.getLogger(__name__)


class ChattyBot:
    """Telegram bot that uses LLM for conversations with memory."""

    def __init__(
        self,
        token: str,
        allowed_user_id: int,
        character: Character,
        llm: LLMClient,
        memory: MemoryManager,
    ):
        """
        Initialize the bot.

        Args:
            token: Telegram bot token
            allowed_user_id: Only respond to this user ID
            character: Character configuration
            llm: LLM client for generating responses
            memory: Memory manager for storing/retrieving context
        """
        self.token = token
        self.allowed_user_id = allowed_user_id
        self.character = character
        self.llm = llm
        self.memory = memory

        # Store application reference for sending proactive messages
        self.application: Optional[Application] = None

    def _is_allowed_user(self, user_id: int) -> bool:
        """Check if the user is allowed to interact with the bot."""
        return user_id == self.allowed_user_id

    async def start_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        if not update.effective_user or not self._is_allowed_user(
            update.effective_user.id
        ):
            logger.info(
                f"Ignoring /start from unauthorized user: {update.effective_user.id if update.effective_user else 'unknown'}"
            )
            return

        await update.message.reply_text(
            f"Hey! I'm {self.character.name}. Nice to meet you! "
            f"Feel free to chat with me anytime. 💬"
        )

    async def help_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command."""
        if not update.effective_user or not self._is_allowed_user(
            update.effective_user.id
        ):
            return

        await update.message.reply_text(
            f"I'm {self.character.name}, your AI companion!\n\n"
            "Just send me a message and I'll respond. "
            "I remember our conversations and learn about you over time.\n\n"
            "Commands:\n"
            "/start - Start a conversation\n"
            "/help - Show this help message\n"
            "/facts - See what I remember about you\n"
            "/forget - Clear my memory of our conversations"
        )

    async def facts_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /facts command - show stored facts about user."""
        if not update.effective_user or not self._is_allowed_user(
            update.effective_user.id
        ):
            return

        facts = self.memory.get_all_facts()

        if not facts:
            await update.message.reply_text(
                "I haven't learned any specific facts about you yet. "
                "We'll get to know each other as we chat!"
            )
        else:
            facts_text = "\n".join(f"• {fact}" for fact in facts)
            await update.message.reply_text(
                f"Here's what I remember about you:\n\n{facts_text}"
            )

    async def forget_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /forget command - placeholder for clearing memory."""
        if not update.effective_user or not self._is_allowed_user(
            update.effective_user.id
        ):
            return

        await update.message.reply_text(
            "Memory clearing is not implemented yet. "
            "If you need to reset, you can delete the Qdrant data volume."
        )

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle incoming text messages."""
        if not update.effective_user or not update.message or not update.message.text:
            return

        user_id = update.effective_user.id

        # Ignore messages from unauthorized users
        if not self._is_allowed_user(user_id):
            logger.info(f"Ignoring message from unauthorized user: {user_id}")
            return

        user_message = update.message.text
        logger.info(f"Received message from user {user_id}: {user_message[:50]}...")

        # Show typing indicator
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )

        try:
            # Get relevant context from memory
            relevant_history = self.memory.get_relevant_history(user_message, limit=5)
            recent_history = self.memory.get_recent_history(limit=10)
            relevant_facts = self.memory.get_relevant_facts(user_message, limit=5)

            # Combine histories, preferring recent but including relevant
            history_ids = set()
            combined_history = []

            for msg in recent_history:
                msg_key = f"{msg['role']}:{msg['timestamp']}"
                if msg_key not in history_ids:
                    history_ids.add(msg_key)
                    combined_history.append(msg)

            for msg in relevant_history:
                msg_key = f"{msg['role']}:{msg['timestamp']}"
                if msg_key not in history_ids:
                    history_ids.add(msg_key)
                    combined_history.append(msg)

            # Sort by timestamp
            combined_history.sort(key=lambda m: m["timestamp"])

            # Build system prompt with facts
            system_prompt = self.character.get_system_prompt()
            if relevant_facts:
                facts_text = "\n".join(f"- {f}" for f in relevant_facts)
                system_prompt += f"\n\n## What you know about the user:\n{facts_text}"

            # Generate response
            response = self.llm.generate_response(
                system_prompt=system_prompt,
                messages=combined_history,
                user_message=user_message,
            )

            # Store the conversation
            self.memory.add_message("user", user_message)
            self.memory.add_message("assistant", response)

            # Extract and store new facts (don't wait for this)
            self._extract_and_store_facts(user_message)

            # Send response
            await update.message.reply_text(response)
            logger.info(f"Sent response: {response[:50]}...")

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            await update.message.reply_text(
                "Sorry, I had trouble processing that. Could you try again?"
            )

    def _extract_and_store_facts(self, user_message: str) -> None:
        """Extract facts from user message and store them."""
        try:
            existing_facts = self.memory.get_all_facts()
            new_facts = self.llm.extract_facts(user_message, existing_facts)

            for fact in new_facts:
                self.memory.add_fact(fact)
                logger.info(f"Stored new fact: {fact}")

        except Exception as e:
            logger.error(f"Error extracting facts: {e}")

    async def send_proactive_message(self, message: str) -> bool:
        """
        Send a proactive message to the user.

        Args:
            message: Message to send

        Returns:
            True if message was sent successfully
        """
        if not self.application:
            logger.error("Cannot send proactive message: application not initialized")
            return False

        try:
            await self.application.bot.send_message(
                chat_id=self.allowed_user_id,
                text=message,
            )

            # Store the proactive message in memory
            self.memory.add_message("assistant", message)

            logger.info(f"Sent proactive message: {message[:50]}...")
            return True

        except Exception as e:
            logger.error(f"Failed to send proactive message: {e}")
            return False

    async def fetch_user_name(self) -> str | None:
        """
        Fetch the user's name from Telegram using their user ID.

        Returns:
            The user's first name, or None if it couldn't be fetched
        """
        if not self.application:
            logger.error("Cannot fetch user name: application not initialized")
            return None

        try:
            chat = await self.application.bot.get_chat(self.allowed_user_id)
            # Prefer first_name, fall back to username
            user_name = chat.first_name or chat.username
            if user_name:
                logger.info(f"Fetched user name: {user_name}")
                self.character.user_name = user_name
            return user_name
        except Exception as e:
            logger.warning(
                f"Could not fetch user name for ID {self.allowed_user_id}: {e}"
            )
            return None

    def create_application(self) -> Application:
        """Create and configure the Telegram application."""
        self.application = Application.builder().token(self.token).build()

        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("facts", self.facts_command))
        self.application.add_handler(CommandHandler("forget", self.forget_command))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        return self.application


def create_bot() -> ChattyBot:
    """Create a ChattyBot instance from environment variables."""
    from .character import load_character
    from .tools import create_default_registry

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

    user_id_str = os.getenv("TELEGRAM_USER_ID")
    if not user_id_str:
        raise ValueError("TELEGRAM_USER_ID environment variable is required")

    try:
        allowed_user_id = int(user_id_str)
    except ValueError:
        raise ValueError(f"TELEGRAM_USER_ID must be an integer, got: {user_id_str}")

    # Load character
    character = load_character()

    # Create tool registry with default tools (calendar, reminders)
    tool_registry = create_default_registry()

    # Create LLM client with tools
    llm = LLMClient(tool_registry=tool_registry)

    # Create memory manager with embedding function
    memory = MemoryManager(embed_func=llm.embed)

    return ChattyBot(
        token=token,
        allowed_user_id=allowed_user_id,
        character=character,
        llm=llm,
        memory=memory,
    )
