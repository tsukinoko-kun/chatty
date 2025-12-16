"""Discord bot handler."""

import logging
import os
from typing import Optional

import discord
from discord import app_commands

from .character import Character
from .llm import LLMClient
from .memory import MemoryManager

logger = logging.getLogger(__name__)


class DiscordBot:
    """Discord bot that uses LLM for conversations with memory."""

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
            token: Discord bot token
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

        # Discord client setup
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True

        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)

        # Cache the user object for proactive messaging
        self._allowed_user: Optional[discord.User] = None

        # Set up event handlers
        self._setup_handlers()

    def _is_allowed_user(self, user_id: int) -> bool:
        """Check if the user is allowed to interact with the bot."""
        return user_id == self.allowed_user_id

    def _setup_handlers(self) -> None:
        """Set up Discord event handlers and commands."""

        @self.client.event
        async def on_ready():
            """Called when the bot is ready."""
            logger.info(f"Discord bot logged in as {self.client.user}")

            # Sync slash commands
            try:
                synced = await self.tree.sync()
                logger.info(f"Synced {len(synced)} slash commands")
            except Exception as e:
                logger.error(f"Failed to sync commands: {e}")

            # Cache the allowed user
            try:
                self._allowed_user = await self.client.fetch_user(self.allowed_user_id)
                logger.info(f"Cached allowed user: {self._allowed_user.name}")
            except Exception as e:
                logger.warning(f"Could not fetch allowed user: {e}")

        @self.client.event
        async def on_message(message: discord.Message):
            """Handle incoming messages."""
            # Ignore messages from the bot itself
            if message.author == self.client.user:
                return

            # Only respond to DMs from the allowed user
            if not isinstance(message.channel, discord.DMChannel):
                return

            if not self._is_allowed_user(message.author.id):
                logger.info(f"Ignoring DM from unauthorized user: {message.author.id}")
                return

            # Ignore empty messages or messages that are just attachments
            if not message.content:
                return

            await self._handle_message(message)

        # Slash commands
        @self.tree.command(name="help", description="Show help message")
        async def help_command(interaction: discord.Interaction):
            if not self._is_allowed_user(interaction.user.id):
                await interaction.response.send_message(
                    "You are not authorized to use this bot.", ephemeral=True
                )
                return

            await interaction.response.send_message(
                f"I'm {self.character.name}, your AI companion!\n\n"
                "Just send me a DM and I'll respond. "
                "I remember our conversations and learn about you over time.\n\n"
                "**Commands:**\n"
                "`/help` - Show this help message\n"
                "`/facts` - See what I remember about you\n"
                "`/forget` - Clear my memory of our conversations"
            )

        @self.tree.command(name="facts", description="See what I remember about you")
        async def facts_command(interaction: discord.Interaction):
            if not self._is_allowed_user(interaction.user.id):
                await interaction.response.send_message(
                    "You are not authorized to use this bot.", ephemeral=True
                )
                return

            facts = self.memory.get_all_facts()

            if not facts:
                await interaction.response.send_message(
                    "I haven't learned any specific facts about you yet. "
                    "We'll get to know each other as we chat!"
                )
            else:
                facts_text = "\n".join(f"• {fact}" for fact in facts)
                await interaction.response.send_message(
                    f"Here's what I remember about you:\n\n{facts_text}"
                )

        @self.tree.command(
            name="forget", description="Clear my memory of our conversations"
        )
        async def forget_command(interaction: discord.Interaction):
            if not self._is_allowed_user(interaction.user.id):
                await interaction.response.send_message(
                    "You are not authorized to use this bot.", ephemeral=True
                )
                return

            await interaction.response.send_message(
                "Memory clearing is not implemented yet. "
                "If you need to reset, you can delete the Qdrant data volume."
            )

    async def _handle_message(self, message: discord.Message) -> None:
        """Handle an incoming DM from the allowed user."""
        user_message = message.content
        logger.info(f"Received Discord DM: {user_message[:50]}...")

        # Show typing indicator
        async with message.channel.typing():
            try:
                # Get relevant context from memory
                relevant_history = self.memory.get_relevant_history(
                    user_message, limit=5
                )
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
                    system_prompt += (
                        f"\n\n## What you know about the user:\n{facts_text}"
                    )

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
                await message.reply(response)
                logger.info(f"Sent Discord response: {response[:50]}...")

            except Exception as e:
                logger.error(f"Error handling Discord message: {e}", exc_info=True)
                await message.reply(
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
        Send a proactive message to the user via DM.

        Args:
            message: Message to send

        Returns:
            True if message was sent successfully
        """
        if not self._allowed_user:
            # Try to fetch the user if we don't have them cached
            try:
                self._allowed_user = await self.client.fetch_user(self.allowed_user_id)
            except Exception as e:
                logger.error(
                    f"Cannot send proactive message: failed to fetch user: {e}"
                )
                return False

        try:
            await self._allowed_user.send(message)

            # Store the proactive message in memory
            self.memory.add_message("assistant", message)

            logger.info(f"Sent proactive Discord DM: {message[:50]}...")
            return True

        except Exception as e:
            logger.error(f"Failed to send proactive Discord message: {e}")
            return False

    async def fetch_user_name(self) -> str | None:
        """
        Fetch the user's name from Discord using their user ID.

        Returns:
            The user's display name, or None if it couldn't be fetched
        """
        try:
            if not self._allowed_user:
                self._allowed_user = await self.client.fetch_user(self.allowed_user_id)

            # Use display_name (which includes global nickname) or fall back to name
            user_name = self._allowed_user.display_name or self._allowed_user.name
            if user_name:
                logger.info(f"Fetched Discord user name: {user_name}")
                self.character.user_name = user_name
            return user_name
        except Exception as e:
            logger.warning(
                f"Could not fetch Discord user name for ID {self.allowed_user_id}: {e}"
            )
            return None

    async def start(self) -> None:
        """Start the Discord bot."""
        await self.client.start(self.token)

    async def close(self) -> None:
        """Close the Discord bot connection."""
        await self.client.close()


def create_discord_bot() -> DiscordBot | None:
    """Create a DiscordBot instance from environment variables.

    Returns:
        DiscordBot instance if Discord is configured, None otherwise
    """
    from .character import load_character
    from .tools import create_default_registry

    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        return None

    user_id_str = os.getenv("DISCORD_USER_ID")
    if not user_id_str:
        logger.warning(
            "DISCORD_BOT_TOKEN is set but DISCORD_USER_ID is missing. "
            "Discord bot will not start."
        )
        return None

    try:
        allowed_user_id = int(user_id_str)
    except ValueError as exc:
        raise ValueError(
            f"DISCORD_USER_ID must be an integer, got: {user_id_str}"
        ) from exc

    # Load character
    character = load_character()

    # Create tool registry with default tools (calendar, reminders)
    tool_registry = create_default_registry()

    # Create LLM client with tools
    llm = LLMClient(tool_registry=tool_registry)

    # Create memory manager with embedding function
    memory = MemoryManager(embed_func=llm.embed)

    return DiscordBot(
        token=token,
        allowed_user_id=allowed_user_id,
        character=character,
        llm=llm,
        memory=memory,
    )
