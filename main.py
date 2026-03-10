#!/usr/bin/env python3
"""ClawMama - Telegram bot for Firecracker microVM management."""

import asyncio
import logging
import os
import sys
from pathlib import Path

from telegram.ext import Application

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


async def main():
    """Main entry point."""
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
        await setup_environment()
    except Exception as e:
        logger.error(f"Environment setup failed: {e}", exc_info=True)

    # Create application
    application = Application.builder().token(token).build()

    # Setup handlers
    setup_handlers(application)

    # Start bot (run_polling is a synchronous method in PTB v21+)
    logger.info("Starting bot...")
    application.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
