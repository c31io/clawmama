#!/usr/bin/env python3
"""ClawMama - Telegram bot for Firecracker microVM management."""

import asyncio
import logging
import os
import sys
from pathlib import Path

from telegram import Update
from telegram.ext import Application, MessageHandler, filters
from telegram.ext import CallbackContext, DictPersistence

from clawmama.config import config
from clawmama.logging_ import setup_logging
from clawmama.bot.handlers import setup_handlers
from clawmama.vm import VMDatabase, VMProvisioner


# Fix SOCKS proxy scheme for httpx (socks:// -> socks5://)
for var in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
    proxy = os.environ.get(var, "")
    if proxy.startswith("socks://"):
        logger = logging.getLogger("clawmama")
        logger.warning(
            f"Converting {var} from socks:// to socks5:// (httpx supports SOCKS5 only)"
        )
        os.environ[var] = proxy.replace("socks://", "socks5://", 1)


class MockContext:
    """Mock context for CLI testing."""
    def __init__(self, args=None):
        self._args = args or []
    
    @property
    def args(self):
        return self._args


async def run_cli_command(cmd: str, args: list[str]):
    """Run a command from CLI, simulating a Telegram message."""
    logger = setup_logging()
    
    # Parse command
    if not cmd:
        print("Usage: clawmama msg <command> [args...]")
        print("Example: clawmama msg /start")
        print("         clawmama msg /msg hello world")
        print("         clawmama msg /list")
        return
    
    # Extract command (with or without /)
    if not cmd.startswith("/"):
        cmd = "/" + cmd
    cmd_name = cmd.lstrip("/")
    cmd_args = args
    
    # Setup environment
    await setup_environment()
    
    # Import handlers
    from clawmama.bot import handlers
    
    # Map commands to handler functions
    command_map = {
        "start": handlers.start_command,
        "help": handlers.help_command,
        "msg": handlers.msg_command,
        "list": handlers.list_command,
        "status": handlers.status_command,
        "run": handlers.start_vm_command,
        "stop": handlers.stop_vm_command,
        "pause": handlers.pause_vm_command,
        "resume": handlers.resume_vm_command,
        "backup": handlers.backup_command,
        "recover": handlers.recover_command,
        "delete": handlers.delete_command,
        "create": handlers.create_command,
        "install": handlers.install_command,
    }
    
    handler = command_map.get(cmd_name)
    if not handler:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(command_map.keys())}")
        return
    
    # Create mock update
    output = []
    
    class MockMessage:
        async def reply_text(self, text, **kwargs):
            output.append(text)
            print(text)
    
    class MockUpdate:
        message = MockMessage()
    
    # Run handler
    context = MockContext(cmd_args)
    try:
        await handler(MockUpdate(), context)
    except Exception as e:
        print(f"Error: {e}")
        logger.exception(f"CLI command failed: {cmd}")


async def setup_environment():
    """Setup the environment for running VMs."""
    # Create required directories
    Path(config.vm_dir).mkdir(parents=True, exist_ok=True)
    Path(config.backup_dir).mkdir(parents=True, exist_ok=True)

    # Prepare VM provisioning
    provisioner = VMProvisioner()
    await provisioner.prepare()

    # Initialize database
    db = VMDatabase()
    await db.init_db()


def main():
    """Main entry point."""
    # Parse CLI arguments - use -- to separate CLI args from bot command args
    # Example: clawmama -- /create vm1 --vcpus 2
    #   CLI: clawmama -- /create vm1
    #   Bot: /create vm1 --vcpus 2
    
    if len(sys.argv) > 1 and sys.argv[1] == "--":
        # CLI mode: remaining args go to bot command
        # sys.argv = ["main.py", "--", "/create", "vm1", "--vcpus", "2"]
        bot_args = sys.argv[2:]
        if bot_args:
            cmd = bot_args[0]
            cmd_args = bot_args[1:]
            asyncio.run(run_cli_command(cmd, cmd_args))
            return
    
    # Check for simple msg subcommand
    if len(sys.argv) > 2 and sys.argv[1] == "msg":
        # sys.argv = ["main.py", "msg", "/create", "vm1"]
        cmd = sys.argv[2]
        cmd_args = sys.argv[3:] if len(sys.argv) > 3 else []
        asyncio.run(run_cli_command(cmd, cmd_args))
        return
    
    # Bot mode: start Telegram bot
    run_bot()
    
    # Bot mode: start Telegram bot
    run_bot()


def run_bot():
    """Run the Telegram bot."""
    # Setup logging
    logger = setup_logging()

    # Check bot token
    token = config.bot_token
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("Please set TELEGRAM_BOT_TOKEN in config.yaml")
        sys.exit(1)

    logger.info("Setting up ClawMama...")

    # Setup environment
    try:
        asyncio.run(setup_environment())
    except Exception as e:
        logger.error(f"Environment setup failed: {e}", exc_info=True)

    # Create application with persistence for ConversationHandler
    application = (
        Application.builder()
        .token(token)
        .persistence(DictPersistence())
        .build()
    )

    # Setup handlers
    setup_handlers(application)

    # Catch-all handler for debugging
    async def catch_all(update, context):
        logger.info("Catch-all received: update=%s, update.message=%s", update, update.message)

    application.add_handler(MessageHandler(filters.ALL, catch_all))

    # Add polling callbacks for debugging
    async def post_init(app):
        logger.info("Bot initialized, polling started")

    application.post_init = post_init

    # Start bot (run_polling manages its own event loop)
    logger.info("Starting bot...")
    application.run_polling()


if __name__ == "__main__":
    main()
