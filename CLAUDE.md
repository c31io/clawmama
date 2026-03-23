# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ClawMama

Telegram bot for Firecracker microVM management with OpenClaw.

## Development

- `uv run python main.py` - Run the bot in Telegram mode
- `uv run python main.py -- /list` - Test bot commands via CLI (uses `--` separator)
- `uv run python main.py msg /list` - Alternative CLI syntax
- `uv sync` - Sync dependencies from pyproject.toml
- `uvx ty check` - Run type checker
- `ruff format .` - Format code

## Architecture

- `clawmama/bot/handlers.py` - Telegram command handlers (/create, /start, /stop, etc.)
- `clawmama/vm/firecracker.py` - Firecracker VM lifecycle (create, start, stop, pause)
- `clawmama/vm/provisioner.py` - VM image provisioning (Ubuntu template)
- `clawmama/vm/backup.py` - Snapshot backup/restore with zstd compression
- `clawmama/vm/database.py` - SQLite database for VM metadata (lazy init via get_db())
- `clawmama/clawkid_host.py` - Host-side communication with VM clawkid daemon via vsock
- `clawmama/config/` - Configuration loading from YAML

## Design Principles

- **Simplicity over compatibility** - Prefer clean, simple code over backward compatibility shims
- Use lazy initialization (get_db()) for global singletons to avoid path errors
- Use UnixConnector from aiohttp for Firecracker API socket communication
- Use absolute imports (from clawmama.x.y) not relative (from x.y) for NixOS portability
- Use `clawmama.logging_.setup_logging()` for logging configuration
- Use zstd (python-zstandard) for backup compression instead of gzip
- Telegram bot handlers: add early return guards for `update.message` None checks
- clawkid daemon runs inside VMs, communicates with host via vsock ports 5000/5001

## Testing

- `uv run pytest tests/ -v` - Run all tests
- `uv run pytest tests/ --cov=clawmama.vm --cov-report=term-missing` - Run with coverage
- `uv sync --all-extras` - Install test dependencies (pytest, pytest-asyncio, pytest-mock, pytest-cov)
- Async fixtures require `@pytest_asyncio.fixture` decorator (not plain `@pytest.fixture`)
- Set `asyncio_mode = "auto"` in `[tool.pytest.ini_options]` for pytest-asyncio auto mode
- aiosqlite `:memory:` creates separate DB per connection - use temp file paths for test databases
