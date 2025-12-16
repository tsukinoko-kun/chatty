"""Character configuration loader."""

from dataclasses import dataclass, field
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
    example_responses: list[str] = field(default_factory=list)
    proactive_prompts: dict[str, str] = field(default_factory=dict)
    user_name: Optional[str] = None
    
    def get_system_prompt(self) -> str:
        """Generate the system prompt from character configuration."""
        examples = "\n".join(f'- "{ex}"' for ex in self.example_responses)
        
        user_context = ""
        if self.user_name:
            user_context = f"\n\n## User\nYou are talking to {self.user_name}. Address them by name when appropriate."
        
        return f"""You are {self.name}, an AI companion with the following characteristics:

## Personality
{self.personality.strip()}

## Background
{self.background.strip()}

## Conversation Style
{self.conversation_style.strip()}

## Example Responses (for tone reference)
{examples}{user_context}

Remember: You are {self.name}. Stay in character. Be genuine, not performative. 
Write short messages, you are writing with an instant message app. No emdashes.
Your responses should feel natural and true to your personality."""

    def get_proactive_prompt(self, prompt_type: str = "check_in") -> Optional[str]:
        """Get a proactive message prompt by type."""
        return self.proactive_prompts.get(prompt_type)


def load_character(config_path: str = "/app/character.yaml") -> Character:
    """Load character configuration from YAML file."""
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
        example_responses=config.get("example_responses", []),
        proactive_prompts=config.get("proactive_prompts", {}),
    )

