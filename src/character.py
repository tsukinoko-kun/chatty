"""Character configuration loader."""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Character:
    """Represents the AI character configuration."""

    name: str
    personality: str
    background: str
    conversation_style: str
    proactive_prompts: dict[str, str] = field(default_factory=dict)
    user_name: Optional[str] = None

    def get_system_prompt(self) -> str:
        """Generate the system prompt from character configuration."""
        # Get current date and time in local timezone
        now = datetime.now()
        current_datetime = now.strftime("%A, %B %d, %Y at %H:%M")
        date_context = f"\n\n## Current Date and Time\nIt is currently {current_datetime}. Use this to interpret relative dates like 'today', 'tomorrow', 'next week', etc."

        user_context = ""
        if self.user_name:
            user_context = f"\n\n## User\nYou are talking to {self.user_name}. Address them by name when appropriate."

        tools_context = """

## Tools
You have access to tools that let you check the user's calendar and reminders. Use these when:
- The user asks about their schedule or upcoming events
- The user asks about their tasks, to-dos, or reminders
- You want to proactively reference something relevant from their calendar
Only use tools when genuinely helpful. Don't force tool usage into every response."""

        return f"""You are {self.name}, an AI companion with the following characteristics:{date_context}

## Personality
{self.personality.strip()}

## Background
{self.background.strip()}

## Conversation Style
{self.conversation_style.strip()}{user_context}{tools_context}

Remember: You are {self.name}. Stay in character. Be genuine, not performative. 
Write short messages, you are writing with an instant message app. No emdashes.
Your responses should feel natural and true to your personality."""

    def get_proactive_prompt(self, prompt_type: str = "check_in") -> Optional[str]:
        """Get a proactive message prompt by type."""
        return self.proactive_prompts.get(prompt_type)


def load_character(config_path: Optional[str] = None) -> Character:
    """Load character configuration from YAML file."""
    if config_path is None:
        # Check env var first, then common locations
        config_path = os.getenv("CHARACTER_CONFIG")
        if config_path is None:
            # Try relative to current working directory
            cwd_path = Path.cwd() / "character.yaml"
            # Try relative to this module's parent (project root)
            module_path = Path(__file__).parent.parent / "character.yaml"

            if cwd_path.exists():
                config_path = str(cwd_path)
            elif module_path.exists():
                config_path = str(module_path)
            else:
                raise FileNotFoundError(
                    f"Character config not found. Checked: {cwd_path}, {module_path}"
                )

    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Character config not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return Character(
        name=config.get("name", "Assistant"),
        personality=config.get("personality", "A helpful AI assistant."),
        background=config.get("background", ""),
        conversation_style=config.get("conversation_style", ""),
        proactive_prompts=config.get("proactive_prompts", {}),
    )
