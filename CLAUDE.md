# ClawMama

Telegram bot for Firecracker microVM management with OpenClaw.

## Development

- `uv run python main.py` - Run the bot
- `uv sync` - Sync dependencies from pyproject.toml

## Patterns

- Use lazy initialization (get_db()) for global singletons to avoid path errors
- Use UnixConnector from aiohttp for Firecracker API socket communication
