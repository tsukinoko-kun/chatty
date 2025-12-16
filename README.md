# Chatty

A personal AI companion bot for Telegram and Discord with long-term memory. Uses local LLMs via Ollama and stores conversation history in Qdrant vector database for semantic recall.

## Features

- 🤖 Customizable AI personality via YAML character files
- 🧠 Long-term memory with semantic search (remembers relevant past conversations)
- 📝 Automatic fact extraction (learns things about you over time)
- 💬 Proactive messaging (reaches out if you've been quiet)
- 🔒 Single-user mode (responds only to your account)
- 🏠 Fully local/self-hosted (no data sent to cloud AI services)
- 📱 Multi-platform support (Telegram and/or Discord)

## Prerequisites

### 1. Install Ollama

Download and install Ollama from [ollama.com/download](https://ollama.com/download).

**macOS:**
```bash
brew install ollama
```

**Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Start the Ollama service:
```bash
ollama serve
```

### 2. Pull Required Models

You need two models - a chat model and an embedding model:

```bash
# Chat model (20B parameter model - adjust based on your hardware)
ollama pull gpt-oss:20b

# Embedding model (required for memory/semantic search)
ollama pull nomic-embed-text
```

> **Note:** The chat model can be changed via environment variable. See [Model Configuration](#model-configuration) below.
>
> Browse available models at [ollama.com/library](https://ollama.com/library)

### 3. Install Docker

Docker is required for running the bot and Qdrant database.

- **macOS/Windows:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- **Linux:** [Docker Engine](https://docs.docker.com/engine/install/)

### 4. Set Up a Bot Platform

You can use Telegram, Discord, or both.

#### Option A: Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Choose a name and username for your bot
4. Save the **bot token** (looks like `4839574812:AAFD39kkdpWt3ywyRZergyOLMaJhac60qc`)

For more details, see the [official Telegram Bot tutorial](https://core.telegram.org/bots/tutorial).

**Get Your Telegram User ID:**

1. Search for [@userinfobot](https://t.me/userinfobot) on Telegram
2. Send `/start` - it will reply with your user ID
3. Save this numeric ID

#### Option B: Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" section in the left sidebar
4. Click "Reset Token" and save the **bot token**
5. Enable these Privileged Gateway Intents:
   - Message Content Intent
6. Go to "OAuth2" > "URL Generator"
7. Select scopes: `bot`, `applications.commands`
8. Select bot permissions: `Send Messages`, `Read Message History`
9. Copy the generated URL (User Install) and open it to invite the bot to a server (required for the bot to work, even for DMs)

**Get Your Discord User ID:**

1. Enable Developer Mode in Discord (User Settings > App Settings > Advanced > Developer Mode)
2. Right-click on your username and select "Copy User ID"
3. Save this numeric ID

**DM the bot:** Open `https://discord.com/users/` + the bots Application ID in your browser.

## Setup

### 1. Clone and Configure

```bash
git clone <your-repo-url>
cd chatty
```

### 2. Create Environment File

Create a `.env` file in the project root:

```bash
# Telegram (optional - set if using Telegram)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_USER_ID=your_telegram_numeric_user_id

# Discord (optional - set if using Discord)
DISCORD_BOT_TOKEN=your_discord_bot_token_here
DISCORD_USER_ID=your_discord_numeric_user_id

# Optional - uncomment to override defaults
# OLLAMA_HOST=http://localhost:11434
# OLLAMA_CHAT_MODEL=gpt-oss:20b
# OLLAMA_EMBED_MODEL=nomic-embed-text
```

> **Note:** You must configure at least one platform (Telegram or Discord). You can use both simultaneously.

### 3. Customize Character (Optional)

Edit `character.yaml` to customize your bot's personality:

```yaml
name: YourBotName
personality: >
  Description of your bot's personality traits...
background: >
  Your bot's backstory...
conversation_style: >
  How your bot communicates...
example_responses:
  - "Example message 1"
  - "Example message 2"
proactive_prompts:
  check_in: >
    What your bot says when reaching out proactively...
```

## Running

### Start the Bot

```bash
docker compose up -d
```

This starts:
- **chatty-bot** - The bot (Telegram and/or Discord based on config)
- **chatty-qdrant** - Vector database for memory storage

### View Logs

```bash
docker compose logs -f bot
```

### Stop the Bot

```bash
docker compose down
```

### Reset Memory

To clear all conversation history and learned facts:

```bash
docker compose down -v
```

## Bot Commands

### Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Start a conversation |
| `/help` | Show help message |
| `/facts` | See what the bot remembers about you |
| `/forget` | Clear memory (not yet implemented) |

### Discord Commands

Discord uses slash commands. Type `/` in a DM with the bot to see available commands:

| Command | Description |
|---------|-------------|
| `/help` | Show help message |
| `/facts` | See what the bot remembers about you |
| `/forget` | Clear memory (not yet implemented) |

> **Note:** The Discord bot only responds to direct messages (DMs) from the configured user.

## Model Configuration

You can use different Ollama models by setting environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_CHAT_MODEL` | `gpt-oss:20b` | Model for generating responses |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Model for embeddings (memory search) |

**Example with a smaller model:**

```bash
# In .env file
OLLAMA_CHAT_MODEL=llama3.2:3b
```

> **Hardware Note:** Larger models require more VRAM/RAM. The default `gpt-oss:20b` needs ~16GB+ VRAM. For lower-end hardware, try `llama3.2:3b` or `mistral:7b`.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Telegram      │◄────│                 │────►│    Discord      │
│   (User)        │     │   Chatty Bot    │     │    (User)       │
└─────────────────┘     │   (Docker)      │     └─────────────────┘
                        └────────┬────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
           ┌────────▼────────┐    ┌──────────▼──────────┐
           │     Ollama      │    │       Qdrant        │
           │   (Host/LLM)    │    │   (Vector DB)       │
           └─────────────────┘    └─────────────────────┘
```

Both platforms share the same:
- **Memory** - Conversations from either platform are stored together
- **Character** - Same personality across platforms
- **LLM** - Same model generates responses

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | If using Telegram | Telegram bot token from BotFather |
| `TELEGRAM_USER_ID` | If using Telegram | Your Telegram numeric user ID |
| `DISCORD_BOT_TOKEN` | If using Discord | Discord bot token from Developer Portal |
| `DISCORD_USER_ID` | If using Discord | Your Discord numeric user ID |
| `OLLAMA_HOST` | No | Ollama API endpoint (default: `http://localhost:11434`) |
| `OLLAMA_CHAT_MODEL` | No | Chat model name (default: `gpt-oss:20b`) |
| `OLLAMA_EMBED_MODEL` | No | Embedding model name (default: `nomic-embed-text`) |

## Troubleshooting

### "model not found" error

Make sure you've pulled both required models:

```bash
ollama pull gpt-oss:20b
ollama pull nomic-embed-text
```

### Bot not responding

1. Check that Ollama is running: `ollama list`
2. Verify your user ID is correct for the platform you're using
3. Check logs: `docker compose logs -f bot`

### Connection refused to Ollama

On Linux, you may need to configure Ollama to listen on all interfaces:

```bash
# Edit /etc/systemd/system/ollama.service
# Add to [Service] section:
Environment="OLLAMA_HOST=0.0.0.0"

# Then restart
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

### Discord bot not responding to DMs

1. Make sure the bot is invited to at least one server (required for Discord to route DMs)
2. Verify Message Content Intent is enabled in the Discord Developer Portal
3. Check that your `DISCORD_USER_ID` is correct
4. The bot only responds to DMs, not messages in servers

### Discord slash commands not showing

Slash commands may take up to an hour to sync globally. Try:
1. Restart the bot
2. Wait a few minutes
3. If still not working, check logs for sync errors

## Development

Run locally without Docker:

```bash
# Install dependencies
pip install -r requirements.txt

# Run Qdrant separately
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant

# Run the bot
python -m src.main
```

## License

MIT
