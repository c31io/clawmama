"""Telegram bot handlers."""

import logging
from typing import TYPE_CHECKING, Any, Callable

from telegram import Update

logger = logging.getLogger("clawmama.handlers")
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
)

from clawmama.config import config
from clawmama.vm import VMDatabase, FirecrackerManager, VMProvisioner, BackupManager


def _check_authorized(update: Update) -> bool:
    """Check if user is authorized to use the bot."""
    if not update.message:
        return False
    if not update.message.from_user:
        return False

    allowed_user_id = config.bot_user_id
    if allowed_user_id is None:
        return True  # No restriction configured

    return update.message.from_user.id == allowed_user_id


# Context type for handlers - use Any to satisfy ConversationHandler generic type
# Defined early to avoid forward reference issues with _auth_guard
if TYPE_CHECKING:
    BotContext = CallbackContext[Any, dict[str, Any], Any, Any]
else:
    BotContext = ContextTypes.DEFAULT_TYPE


def _auth_guard(
    handler: Callable[[Update, BotContext], Any],
) -> Callable[[Update, BotContext], Any]:
    """Decorator to wrap handlers with authorization check."""

    async def wrapper(update: Update, context: BotContext):
        if not _check_authorized(update):
            if update.message:
                await update.message.reply_text(
                    "⛔ Unauthorized: you are not allowed to use this bot."
                )
            return
        return await handler(update, context)

    return wrapper


# Type alias for ConversationHandler to avoid generic issues
ConversationHandlerAny = ConversationHandler[Any]


# Conversation states
(
    CREATE_NAME,
    CREATE_VCPUS,
    CREATE_MEMORY,
    CREATE_DISK,
) = range(4)

# Global database instance (initialized lazily)
db: VMDatabase | None = None
backup_manager: BackupManager | None = None
provisioner: VMProvisioner | None = None


def get_db() -> VMDatabase:
    """Get or create database instance."""
    global db
    if db is None:
        db = VMDatabase()
    return db


def get_backup_manager() -> BackupManager:
    """Get or create backup manager instance."""
    global backup_manager
    if backup_manager is None:
        backup_manager = BackupManager(get_db())
    return backup_manager


def get_provisioner() -> VMProvisioner:
    """Get or create provisioner instance."""
    global provisioner
    if provisioner is None:
        provisioner = VMProvisioner()
    return provisioner


async def start_command(update: Update, context: BotContext):
    """Handle /start command."""
    if not update.message:
        return
    welcome_text = """
Welcome to ClawMama! 🐾

I manage Firecracker microVMs with OpenClaw for you.

Available commands:
/help - Show this help message
/list - List all VMs
/create - Create a new VM
/status <name> - Check VM status
/run <name> - Start a VM
/stop <name> - Stop a VM
/pause <name> - Pause a VM
/resume <name> - Resume a VM
/backup <name> - Create backup
/recover <name> - Recover from backup
/delete <name> - Delete a VM

Note: VMs are isolated and cannot attack the host.
"""
    await update.message.reply_text(welcome_text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    await start_command(update, context)


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /list command - show all VMs."""
    if not update.message:
        return
    logger.info("Listing all VMs")
    vms = await get_db().list_vms()

    if not vms:
        await update.message.reply_text("No VMs found. Create one with /create")
        return

    text = "📋 Your VMs:\n\n"
    for vm in vms:
        state_emoji = {
            "running": "🟢",
            "paused": "⏸️",
            "stopped": "🔴",
        }.get(vm["state"], "❓")

        text += (
            f"{state_emoji} <b>{vm['name']}</b>\n"
            f"   State: {vm['state']}\n"
            f"   Resources: {vm['vcpus']} vCPU, {vm['memory_mib']} MB\n"
            f"   IP: {vm.get('ip_address', 'N/A')}\n\n"
        )

    await update.message.reply_text(text, parse_mode="HTML")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Usage: /status <vm_name>")
        return

    vm_name = context.args[0]
    logger.info(f"Getting status for VM: {vm_name}")
    vm = await get_db().get_vm(vm_name)

    if not vm:
        await update.message.reply_text(f"VM '{vm_name}' not found")
        return

    state_emoji = {
        "running": "🟢 Running",
        "paused": "⏸️ Paused",
        "stopped": "🔴 Stopped",
    }.get(vm["state"], f"❓ {vm['state']}")

    text = f"""
<b>VM: {vm["name"]}</b>

{state_emoji}

<b>Resources:</b>
- vCPUs: {vm["vcpus"]}
- Memory: {vm["memory_mib"]} MB
- Disk: {vm["disk_gb"]} GB

<b>Network:</b>
- IP: {vm.get("ip_address", "N/A")}

<b>Created:</b> {vm["created_at"]}
"""
    await update.message.reply_text(text, parse_mode="HTML")


async def start_vm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /run command - start a VM."""
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Usage: /run <vm_name>")
        return

    vm_name = context.args[0]
    logger.info(f"Starting VM: {vm_name}")
    vm = await get_db().get_vm(vm_name)

    if not vm:
        await update.message.reply_text(f"VM '{vm_name}' not found")
        return

    if vm["state"] == "running":
        await update.message.reply_text(f"VM '{vm_name}' is already running")
        return

    await update.message.reply_text(f"Starting VM '{vm_name}'...")

    try:
        fc = FirecrackerManager(vm_name)

        # Start the VM
        ip_address = await fc.start_vm()
        assert ip_address is not None

        await get_db().update_vm_state(vm_name, "running")
        await get_db().update_vm_ip(vm_name, ip_address)

        logger.info(f"VM {vm_name} started with IP {ip_address}")
        await update.message.reply_text(
            f"✅ VM '{vm_name}' started!\n"
            f"IP: {ip_address}\n"
            "OpenClaw should be accessible via the configured port."
        )
    except Exception as e:
        logger.exception(f"[{vm_name}] Failed to start VM")
        await update.message.reply_text(f"❌ Failed to start VM: {e}")


async def stop_vm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop command - stop a VM."""
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Usage: /stop <vm_name>")
        return

    vm_name = context.args[0]
    logger.info(f"Stopping VM: {vm_name}")
    vm = await get_db().get_vm(vm_name)

    if not vm:
        await update.message.reply_text(f"VM '{vm_name}' not found")
        return

    if vm["state"] == "stopped":
        await update.message.reply_text(f"VM '{vm_name}' is already stopped")
        return

    await update.message.reply_text(f"Stopping VM '{vm_name}'...")

    try:
        fc = FirecrackerManager(vm_name)
        await fc.stop_vm()

        await get_db().update_vm_state(vm_name, "stopped")

        logger.info(f"VM {vm_name} stopped")
        await update.message.reply_text(f"✅ VM '{vm_name}' stopped!")
    except Exception as e:
        logger.exception(f"[{vm_name}] Failed to stop VM")
        await update.message.reply_text(f"❌ Failed to stop VM: {e}")


async def pause_vm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pause command - pause a VM."""
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Usage: /pause <vm_name>")
        return

    vm_name = context.args[0]
    logger.info(f"Pausing VM: {vm_name}")
    vm = await get_db().get_vm(vm_name)

    if not vm:
        await update.message.reply_text(f"VM '{vm_name}' not found")
        return

    if vm["state"] != "running":
        await update.message.reply_text(f"VM '{vm_name}' must be running to pause")
        return

    try:
        fc = FirecrackerManager(vm_name)
        await fc.pause_vm()

        await get_db().update_vm_state(vm_name, "paused")

        logger.info(f"VM {vm_name} paused")
        await update.message.reply_text(f"⏸️ VM '{vm_name}' paused!")
    except Exception as e:
        logger.exception(f"[{vm_name}] Failed to pause VM")
        await update.message.reply_text(f"❌ Failed to pause VM: {e}")


async def resume_vm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resume command - resume a VM."""
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Usage: /resume <vm_name>")
        return

    vm_name = context.args[0]
    logger.info(f"Resuming VM: {vm_name}")
    vm = await get_db().get_vm(vm_name)

    if not vm:
        await update.message.reply_text(f"VM '{vm_name}' not found")
        return

    if vm["state"] != "paused":
        await update.message.reply_text(f"VM '{vm_name}' must be paused to resume")
        return

    try:
        fc = FirecrackerManager(vm_name)
        await fc.resume_vm()

        await get_db().update_vm_state(vm_name, "running")

        logger.info(f"VM {vm_name} resumed")
        await update.message.reply_text(f"▶️ VM '{vm_name}' resumed!")
    except Exception as e:
        logger.exception(f"[{vm_name}] Failed to resume VM")
        await update.message.reply_text(f"❌ Failed to resume VM: {e}")


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /backup command - create VM backup."""
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Usage: /backup <vm_name>")
        return

    vm_name = context.args[0]
    logger.info(f"Creating backup for VM: {vm_name}")
    vm = await get_db().get_vm(vm_name)

    if not vm:
        await update.message.reply_text(f"VM '{vm_name}' not found")
        return

    await update.message.reply_text(f"Creating backup of '{vm_name}'...")

    try:
        backup = await get_backup_manager().create_backup(vm_name)

        if backup:
            size_mb = backup["size_bytes"] / (1024 * 1024)
            logger.info(f"Backup created for {vm_name}: {backup['path']}")
            await update.message.reply_text(
                f"✅ Backup created!\nFile: {backup['path']}\nSize: {size_mb:.2f} MB"
            )
        else:
            await update.message.reply_text("❌ Backup failed")
    except Exception as e:
        logger.exception(f"[{vm_name}] Failed to create backup")
        await update.message.reply_text(f"❌ Backup failed: {e}")


async def recover_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /recover command - recover from backup."""
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Usage: /recover <vm_name> [backup_id]")
        return

    vm_name = context.args[0]
    backup_id = int(context.args[1]) if len(context.args) > 1 else None

    logger.info(f"Recovering VM: {vm_name}, backup_id: {backup_id}")
    vm = await get_db().get_vm(vm_name)
    if not vm:
        await update.message.reply_text(f"VM '{vm_name}' not found")
        return

    # List available backups if no ID provided
    if not backup_id:
        backups = await get_backup_manager().list_backups(vm_name)
        if not backups:
            await update.message.reply_text(f"No backups found for '{vm_name}'")
            return

        text = "Available backups:\n\n"
        for b in backups:
            text += f"ID: {b['id']} - {b['created_at']}\n"

        await update.message.reply_text(text)
        return

    await update.message.reply_text("Recovering VM from backup...")

    try:
        result = await get_backup_manager().restore_backup(vm_name, backup_id=backup_id)

        if result:
            logger.info(f"VM {vm_name} recovered from backup {backup_id}")
            await update.message.reply_text(
                "✅ VM recovered from backup!\nNote: You may need to restart the VM."
            )
        else:
            await update.message.reply_text("❌ Recovery failed")
    except Exception as e:
        logger.exception(f"[{vm_name}] Failed to recover from backup")
        await update.message.reply_text(f"❌ Recovery failed: {e}")


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /delete command - delete a VM."""
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Usage: /delete <vm_name>")
        return

    vm_name = context.args[0]
    logger.info(f"Deleting VM: {vm_name}")
    vm = await get_db().get_vm(vm_name)

    if not vm:
        await update.message.reply_text(f"VM '{vm_name}' not found")
        return

    # Warn user
    if vm["state"] == "running":
        await update.message.reply_text(
            f"⚠️ VM '{vm_name}' is running. Stop it first with /stop {vm_name}"
        )
        return

    try:
        fc = FirecrackerManager(vm_name)
        await fc.delete_vm()

        await get_db().delete_vm(vm_name)

        logger.info(f"VM {vm_name} deleted")
        await update.message.reply_text(f"🗑️ VM '{vm_name}' deleted!")
    except Exception as e:
        logger.exception(f"[{vm_name}] Failed to delete VM")
        await update.message.reply_text(f"❌ Delete failed: {e}")


# Create conversation handler for VM creation
async def create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the VM creation conversation."""
    if not update.message:
        return
    logger.info("Starting VM creation conversation")
    await update.message.reply_text(
        "Creating a new VM...\n\nPlease enter a name for your VM:"
    )
    return CREATE_NAME


async def create_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get VM name."""
    if not update.message:
        return
    if not update.message.text:
        return
    if not context.user_data:
        return
    vm_name = update.message.text.strip()

    # Validate name
    if not vm_name.replace("-", "").replace("_", "").isalnum():
        await update.message.reply_text(
            "Invalid name. Use only letters, numbers, hyphens, and underscores."
        )
        return CREATE_NAME

    # Check if VM already exists
    existing = await get_db().get_vm(vm_name)
    if existing:
        await update.message.reply_text(f"VM '{vm_name}' already exists.")
        return ConversationHandler.END

    context.user_data["vm_name"] = vm_name

    await update.message.reply_text(
        f"Name: {vm_name}\n\n"
        f"How many vCPUs? (1-{config.max_vcpus}, default: {config.default_vcpus}):"
    )
    return CREATE_VCPUS


async def create_vcpus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get vCPU count."""
    if not update.message:
        return
    if not update.message.text:
        return
    if not context.user_data:
        return
    try:
        vcpus = int(update.message.text.strip())
        if vcpus < 1 or vcpus > config.max_vcpus:
            await update.message.reply_text(
                f"Invalid vCPU count. Must be between 1 and {config.max_vcpus}."
            )
            return CREATE_VCPUS
    except ValueError:
        vcpus = config.default_vcpus

    context.user_data["vcpus"] = vcpus

    await update.message.reply_text(
        f"vCPUs: {vcpus}\n\n"
        f"How much memory in MB? (512-{config.max_memory_mib}, "
        f"default: {config.default_memory_mib}):"
    )
    return CREATE_MEMORY


async def create_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get memory size."""
    if not update.message:
        return
    if not update.message.text:
        return
    if not context.user_data:
        return
    try:
        memory = int(update.message.text.strip())
        if memory < 512 or memory > config.max_memory_mib:
            await update.message.reply_text(
                f"Invalid memory. Must be between 512 and {config.max_memory_mib} MB."
            )
            return CREATE_MEMORY
    except ValueError:
        memory = config.default_memory_mib

    context.user_data["memory_mib"] = memory

    await update.message.reply_text(
        f"Memory: {memory} MB\n\n"
        f"How much disk in GB? (1-{config.max_disk_gb}, "
        f"default: {config.default_disk_gb}):"
    )
    return CREATE_DISK


async def create_disk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get disk size and create VM."""
    if not update.message:
        return
    if not update.message.text:
        return
    if not context.user_data:
        return
    try:
        disk = int(update.message.text.strip())
        if disk < 1 or disk > config.max_disk_gb:
            await update.message.reply_text(
                f"Invalid disk size. Must be between 1 and {config.max_disk_gb} GB."
            )
            return CREATE_DISK
    except ValueError:
        disk = config.default_disk_gb

    vm_name = context.user_data["vm_name"]
    vcpus = context.user_data["vcpus"]
    memory = context.user_data["memory_mib"]

    # Create VM record
    await get_db().create_vm(vm_name, vcpus, memory, disk)

    logger.info(f"VM {vm_name} created: {vcpus} vCPU, {memory} MB RAM, {disk} GB disk")
    await update.message.reply_text(
        f"✅ VM '{vm_name}' created!\n\n"
        f"Resources: {vcpus} vCPU, {memory} MB RAM, {disk} GB disk\n\n"
        f"Start it with: /run {vm_name}"
    )

    return ConversationHandler.END


async def create_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel VM creation."""
    if not update.message:
        return
    logger.info("VM creation cancelled")
    await update.message.reply_text("VM creation cancelled.")
    return ConversationHandler.END


def setup_handlers(application: Application):
    """Setup all bot handlers."""
    # Basic commands (start and help are public)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    # Protected commands - wrap with auth guard
    protected_commands = [
        ("list", list_command),
        ("status", status_command),
        ("run", start_vm_command),
        ("stop", stop_vm_command),
        ("pause", pause_vm_command),
        ("resume", resume_vm_command),
        ("backup", backup_command),
        ("recover", recover_command),
        ("delete", delete_command),
    ]

    for cmd, handler in protected_commands:
        application.add_handler(CommandHandler(cmd, _auth_guard(handler)))

    # Create VM conversation (protected)
    create_handler = ConversationHandlerAny(
        entry_points=[CommandHandler("create", _auth_guard(create_start))],
        states={
            CREATE_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _auth_guard(create_name)
                )
            ],
            CREATE_VCPUS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _auth_guard(create_vcpus)
                )
            ],
            CREATE_MEMORY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _auth_guard(create_memory)
                )
            ],
            CREATE_DISK: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _auth_guard(create_disk)
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", _auth_guard(create_cancel))],
    )
    application.add_handler(create_handler)
