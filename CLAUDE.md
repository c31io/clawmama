# ClawMama

Telegram bot for Firecracker microVM management with OpenClaw.

## Development

- `uv run python main.py` - Run the bot
- `uv sync` - Sync dependencies from pyproject.toml
- `uvx ty check` - Run type checker
- `ruff format .` - Format code

## Patterns

- Use lazy initialization (get_db()) for global singletons to avoid path errors
- Use UnixConnector from aiohttp for Firecracker API socket communication
- Use absolute imports (from clawmama.x.y) not relative (from x.y) for NixOS portability
- Use `clawmama.logging_.setup_logging()` for logging configuration
- Use zstd (python-zstandard) for backup compression instead of gzip
- Telegram bot handlers: add early return guards for `update.message` None checks
