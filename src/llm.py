"""Ollama LLM client wrapper with tool calling support."""

import json
import logging
import os
from typing import Optional

import ollama

from .tools import ToolExecutor, ToolRegistry

logger = logging.getLogger(__name__)

# Model configuration (can be overridden via environment variables)
CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "gpt-oss:20b")
EMBEDDING_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Creative settings for the chat model
CHAT_OPTIONS = {
    "temperature": 0.8,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.1,
}

# Lower temperature for tool-calling to improve reliability
TOOL_CALL_OPTIONS = {
    "temperature": 0.3,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.1,
}

# Maximum number of tool call iterations to prevent infinite loops
MAX_TOOL_ITERATIONS = 5


class LLMClient:
    """Client for interacting with Ollama with tool calling support."""

    def __init__(
        self,
        host: Optional[str] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        """
        Initialize the LLM client.

        Args:
            host: Ollama host URL (defaults to OLLAMA_HOST env var)
            tool_registry: Registry of tools available for the LLM to use
        """
        self.host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.client = ollama.Client(host=self.host)

        # Tool calling setup
        self.tool_registry = tool_registry
        self.tool_executor = ToolExecutor(tool_registry) if tool_registry else None

        # Verify models are available
        self._check_models()

    def _check_models(self) -> None:
        """Check that required models are available."""
        try:
            models = self.client.list()
            model_names = [m.model for m in models.models]

            # Check for chat model (allow partial match for tags)
            chat_model_base = CHAT_MODEL.split(":")[0]
            if not any(chat_model_base in name for name in model_names):
                logger.warning(
                    f"Chat model '{CHAT_MODEL}' not found. "
                    f"Available models: {model_names}. "
                    f"Please run: ollama pull {CHAT_MODEL}"
                )

            # Check for embedding model
            embed_model_base = EMBEDDING_MODEL.split(":")[0]
            if not any(embed_model_base in name for name in model_names):
                logger.warning(
                    f"Embedding model '{EMBEDDING_MODEL}' not found. "
                    f"Please run: ollama pull {EMBEDDING_MODEL}"
                )
        except Exception as e:
            logger.error(f"Failed to check models: {e}")

    def _get_tools_for_ollama(self) -> list[dict] | None:
        """Get tools in Ollama format, or None if no tools available."""
        if not self.tool_registry or len(self.tool_registry) == 0:
            return None
        return self.tool_registry.get_ollama_tools()

    def generate_response(
        self,
        system_prompt: str,
        messages: list[dict],
        user_message: str,
    ) -> str:
        """
        Generate a response using the chat model, with tool calling support.

        Args:
            system_prompt: The system prompt (character definition)
            messages: Recent conversation history as list of {"role": ..., "content": ...}
            user_message: The current user message

        Returns:
            The generated response text
        """
        # Build the full message list
        full_messages = [
            {"role": "system", "content": system_prompt},
        ]

        # Add conversation history
        for msg in messages:
            full_messages.append(
                {
                    "role": msg["role"],
                    "content": msg["content"],
                }
            )

        # Add the current user message
        full_messages.append(
            {
                "role": "user",
                "content": user_message,
            }
        )

        # Get tools if available
        tools = self._get_tools_for_ollama()

        try:
            if tools:
                return self._generate_with_tools(full_messages, tools)
            else:
                return self._generate_simple(full_messages)
        except Exception as e:
            logger.error(f"Failed to generate response: {e}")
            raise

    def _generate_simple(self, messages: list[dict]) -> str:
        """Generate a response without tool calling."""
        response = self.client.chat(
            model=CHAT_MODEL,
            messages=messages,
            options=CHAT_OPTIONS,
        )
        return response.message.content

    def _generate_with_tools(self, messages: list[dict], tools: list[dict]) -> str:
        """Generate a response with tool calling support."""
        current_messages = messages.copy()
        iterations = 0

        while iterations < MAX_TOOL_ITERATIONS:
            iterations += 1

            # Use lower temperature for tool calling
            options = TOOL_CALL_OPTIONS if iterations == 1 else CHAT_OPTIONS

            response = self.client.chat(
                model=CHAT_MODEL,
                messages=current_messages,
                tools=tools,
                options=options,
            )

            # Check if the model wants to call tools
            if response.message.tool_calls:
                logger.info(
                    f"Model requested {len(response.message.tool_calls)} tool call(s)"
                )

                # Add the assistant's response with tool calls
                current_messages.append(
                    {
                        "role": "assistant",
                        "content": response.message.content or "",
                        "tool_calls": [
                            {
                                "id": tc.function.name,  # Ollama doesn't provide IDs, use name
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in response.message.tool_calls
                        ],
                    }
                )

                # Execute each tool and add results
                for tool_call in response.message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments

                    # Arguments may be a dict or a JSON string depending on Ollama version
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except json.JSONDecodeError:
                            tool_args = {}

                    # Execute the tool
                    result = self.tool_executor.execute(tool_name, tool_args)

                    # Add tool result to messages
                    current_messages.append(
                        {
                            "role": "tool",
                            "content": result,
                        }
                    )

                # Continue the loop to let the model process tool results
                continue

            # No tool calls, return the final response
            return response.message.content

        # Exceeded max iterations
        logger.warning(f"Tool calling exceeded {MAX_TOOL_ITERATIONS} iterations")
        return response.message.content or "I'm having trouble processing that request."

    def generate_proactive_message(
        self,
        system_prompt: str,
        proactive_prompt: str,
        recent_messages: list[dict],
        user_facts: list[str],
    ) -> str:
        """
        Generate a proactive message to send to the user.

        Args:
            system_prompt: The character system prompt
            proactive_prompt: Instructions for generating the proactive message
            recent_messages: Recent conversation history
            user_facts: Known facts about the user

        Returns:
            The generated proactive message
        """
        # Build context about the user
        facts_text = (
            "\n".join(f"- {fact}" for fact in user_facts)
            if user_facts
            else "No specific facts recorded yet."
        )

        # Build recent conversation summary
        recent_text = ""
        if recent_messages:
            recent_text = "\n\nRecent conversation:\n"
            for msg in recent_messages[-5:]:  # Last 5 messages
                role = "User" if msg["role"] == "user" else "You"
                recent_text += (
                    f"{role}: {msg['content'][:200]}...\n"
                    if len(msg["content"]) > 200
                    else f"{role}: {msg['content']}\n"
                )

        prompt = f"""{proactive_prompt}

What you know about the user:
{facts_text}
{recent_text}

Generate a natural, in-character message to send. Just write the message itself, nothing else."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        try:
            response = self.client.chat(
                model=CHAT_MODEL,
                messages=messages,
                options=CHAT_OPTIONS,
            )
            return response.message.content.strip()
        except Exception as e:
            logger.error(f"Failed to generate proactive message: {e}")
            raise

    def extract_facts(
        self,
        user_message: str,
        existing_facts: list[str],
    ) -> list[str]:
        """
        Extract new facts about the user from their message.

        Args:
            user_message: The user's message
            existing_facts: Facts we already know

        Returns:
            List of new facts (empty if none found)
        """
        existing_text = (
            "\n".join(f"- {f}" for f in existing_facts)
            if existing_facts
            else "None recorded yet."
        )

        prompt = f"""Analyze this user message and extract any personal facts about them that would be worth remembering for future conversations.

Facts can include:
- Personal information (name, location, job, hobbies)
- Preferences and opinions
- Important life events or situations
- Relationships (family, friends, pets)
- Goals, plans, or things they're working on

Existing facts (don't repeat these):
{existing_text}

User message: "{user_message}"

If there are new facts to extract, list them one per line, starting each with "- ".
If there are no new facts worth remembering, respond with exactly: NONE

Be selective - only extract meaningful, personal facts, not trivial conversation details."""

        try:
            response = self.client.chat(
                model=CHAT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={
                    "temperature": 0.3
                },  # Lower temperature for factual extraction
            )

            content = response.message.content.strip()

            if content == "NONE" or not content:
                return []

            # Parse facts from response
            facts = []
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    facts.append(line[2:])
                elif line and not line.startswith("#"):
                    # Handle lines without bullet points
                    facts.append(line)

            return facts

        except Exception as e:
            logger.error(f"Failed to extract facts: {e}")
            return []

    def embed(self, text: str) -> list[float]:
        """
        Generate an embedding for the given text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats
        """
        try:
            response = self.client.embed(
                model=EMBEDDING_MODEL,
                input=text,
            )
            return response.embeddings[0]
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            raise
