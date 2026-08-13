# TeleBaseBot

> **⚠️ Work in Progress — This project is in development. Not for use in any hobby setting, much less production**

TeleBaseBot is a self-evolving Telegram bot that can modify its own code at runtime.
It includes a three-agent system (StandardAgent for chat, PlanAgent for requirements, CodeAgent for code generation), hot-reloading of handlers and tools, and a backup/restore mechanism for safe code mutations.

It is designed for a single user. You talk to it, describe what you want it to do, and it writes the code into `working/` and activates it without restarting.

## Requirements

- Python 3.12 or newer
- `uv` for dependency management and running the project
- a Telegram bot token from BotFather
- an OpenAI-compatible model endpoint, or another compatible chat backend

## Install `uv`

### macOS and Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your shell after installation if `uv` is not immediately available.

### Windows

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Verify installation

```bash
uv --version
```

## Project Setup

Clone the repository and install dependencies:

```bash
git clone <your-repo-url>
cd TeleBaseBot
uv sync
```

If you prefer to run it without creating a separate virtual environment manually, `uv` will manage the environment for you.

## Configuration

Create a `.env` file in the project root. Use `.env.example` as the template.

Minimum required values:

```dotenv
TELEGRAM_TOKEN=your-telegram-bot-token
AUTHORIZED_USER=123456789
OPENAI_BASE_URL=http://localhost:11434
OPENAI_API_KEY=
DEFAULT_MODEL=
```

Notes:

- `OPENAI_BASE_URL` should point to the host of your OpenAI-compatible server.
- The application normalizes this to the client API path when needed.
- `AUTHORIZED_USER` is a single Telegram user ID that is allowed to interact with the bot (for whitelist management, use a single ID).

## Run the Bot

Start the bot with:

```bash
uv run python main.py
```

If you want to run the agent module directly during development, you can also import and instantiate it in Python to verify the model connection.

## Project Structure

```text
TeleBaseBot/
├── main.py                     # Entry point
├── core/                       # Core bot infrastructure (immutable)
│   ├── config.py               # Application settings (env-based)
│   ├── core_agent.py           # Agent orchestrator
│   ├── session_manager.py      # Per-chat session memory and edit state
│   ├── main_telegram_bot.py    # Telegram bot entry point
│   ├── agents/
│   │   ├── tools.py            # Shared tools (file read, web search, site fetch)
│   │   ├── logging_handler.py  # Agent callback logger
│   │   ├── standard_agent/     # Standard chat agent (uses working/tools)
│   │   ├── plan_agent/         # Requirements planner agent
│   │   ├── code_agent/         # Code generation agent (writes to working/)
│   │   │   ├── prompts.py      # System prompt + environment block
│   │   │   └── tools.py        # Coding tool harness (read/edit/write/glob/grep/bash)
│   └── telegram_worker/
│       ├── bot.py              # TeleBaseBot class, command registration, hot-reload
│       ├── handlers.py         # Message and command handlers
│       └── auth.py             # Single-user authorization
├── working/                    # User-extensible workspace (writable by CodeAgent)
│   ├── handlers/               # Pluggable Telegram handlers
│   ├── tools/                  # Pluggable agent tools
│   └── subagents/              # Pluggable subagent tools
├── backup/                     # Auto-backup of working/ during code mutations
```

## How It Works

### Standard Chat
1. Telegram updates come into the bot via handlers.
2. Middleware logs the incoming message and applies role checks.
3. Text messages are appended to a per-chat session history.
4. The StandardAgent receives the conversation history and any loaded tools from `working/tools/`.
5. The bot sends the reply back to Telegram.

### Code Editing (`/edit`)
1. User sends `/edit <description>` with a feature request.
2. The PlanAgent refines the requirements through a brief conversation.
3. Once confirmed (user replies "go"), the PlanAgent finalizes a canonical spec, and the CodeAgent writes the code into `working/` using its file-edit/search tools.
4. The code is verified; if invalid, the previous state is restored from `backup/`.
5. The bot performs an in-process hot-reload — new handlers and tools are activated without restarting.

### Hot Reload
The bot watches `working/handlers/`, `working/tools/`, and `working/subagents/`. When code is written there (either manually or by the CodeAgent), calling `reload()` reimports all modules in-process, updates the StandardAgent's toolset, and re-registers Telegram bot commands.

---

<small>Originally written by [github.com/Yushenggg](https://github.com/Yushenggg)</small>

