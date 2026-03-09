#!/usr/bin/env python3
"""ClawMama - Telegram bot for Firecracker microVM management."""

import asyncio
import logging
import sys
from pathlib import Path

from telegram.ext import Application

from clawmama.config import config
from clawmama.bot.handlers import setup_handlers
from clawmama.vm import VMDatabase, SecurityManager, VMProvisioner


async def setup_environment():
    """Setup the environment for running VMs."""
    # Create required directories
    Path(config.vm_dir).mkdir(parents=True, exist_ok=True)
    Path(config.backup_dir).mkdir(parents=True, exist_ok=True)

    # Setup security
    security = SecurityManager()
    security.setup_host_protection()

    # Prepare VM provisioning
    provisioner = VMProvisioner()
    await provisioner.prepare()

    # Initialize database
    db = VMDatabase()
    await db.init_db()


async def main():
    """Main entry point."""
    # Setup logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    logger = logging.getLogger(__name__)

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
        logger.warning(f"Environment setup warning: {e}")

    # Create application
    application = Application.builder().token(token).build()

    # Setup handlers
    setup_handlers(application)

    # Start bot
    logger.info("Starting bot...")
    application.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
