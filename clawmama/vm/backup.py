"""Backup and recovery module for VMs."""
import gzip
import os
import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from clawmama.config import config
from clawmama.vm.database import VMDatabase


class BackupManager:
    """Manages VM backups and recovery."""

    def __init__(self, db: VMDatabase):
        self.db = db
        self.backup_dir = Path(config.backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    async def create_backup(self, vm_name: str) -> Optional[dict]:
        """Create a backup of a VM."""
        # Get VM info
        vm = await self.db.get_vm(vm_name)
        if not vm:
            return None

        vm_dir = Path(config.vm_dir) / vm_name
        if not vm_dir.exists():
            return None

        # Create backup filename with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{vm_name}_{timestamp}"
        backup_path = self.backup_dir / f"{backup_name}.tar.gz"

        # Create backup archive
        compression_level = config.backup_compression

        try:
            with gzip.open(backup_path, f"wb{compression_level}") as gz:
                with tarfile.open(fileobj=gz, mode="w") as tar:
                    # Add VM directory contents
                    tar.add(vm_dir, arcname=vm_name)

            # Get backup size
            backup_size = backup_path.stat().st_size

            # Record in database
            await self.db.add_backup(vm_name, str(backup_path), backup_size)

            return {
                "name": backup_name,
                "path": str(backup_path),
                "size_bytes": backup_size,
                "created_at": datetime.utcnow().isoformat()
            }

        except Exception as e:
            print(f"Backup failed: {e}")
            # Clean up failed backup
            if backup_path.exists():
                backup_path.unlink()
            return None

    async def list_backups(self, vm_name: str) -> list[dict]:
        """List all backups for a VM."""
        return await self.db.get_backups(vm_name)

    async def restore_backup(
        self,
        vm_name: str,
        backup_id: int = None,
        backup_path: str = None,
    ) -> Optional[dict]:
        """Restore a VM from backup."""
        # Find backup
        if backup_path:
            backup_file = Path(backup_path)
        elif backup_id:
            backups = await self.list_backups(vm_name)
            backup = next((b for b in backups if b["id"] == backup_id), None)
            if not backup:
                return None
            backup_file = Path(backup["path"])
        else:
            return None

        if not backup_file.exists():
            return None

        # Stop VM if running
        # (This would need the VM manager)

        # Create new VM directory
        new_vm_dir = Path(config.vm_dir) / vm_name
        if new_vm_dir.exists():
            # Backup existing VM first
            old_backup = await self.create_backup(f"{vm_name}_old")
            if not old_backup:
                return None

        new_vm_dir.mkdir(parents=True, exist_ok=True)

        # Extract backup
        try:
            with gzip.open(backup_file, "rb") as gz:
                with tarfile.open(fileobj=gz, mode="r") as tar:
                    # Extract to VM directory
                    tar.extractall(new_vm_dir)

            return {
                "success": True,
                "path": str(new_vm_dir),
                "backup_file": str(backup_file)
            }

        except Exception as e:
            print(f"Restore failed: {e}")
            return None

    async def delete_backup(self, backup_id: int) -> bool:
        """Delete a backup file and record."""
        # Get backup info
        async with aiosqlite.connect(self.db.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT path FROM backups WHERE id = ?",
                (backup_id,)
            )
            row = await cursor.fetchone()

            if not row:
                return False

            backup_path = Path(row["path"])

            # Delete file
            if backup_path.exists():
                backup_path.unlink()

            # Delete record
            await self.db.delete_backup(backup_id)

            return True

    async def cleanup_old_backups(self, vm_name: str, keep_count: int = 5):
        """Delete old backups, keeping only the most recent."""
        backups = await self.list_backups(vm_name)

        if len(backups) <= keep_count:
            return

        # Delete oldest backups
        for backup in backups[keep_count:]:
            await self.delete_backup(backup["id"])

    async def export_vm(self, vm_name: str, export_path: str) -> bool:
        """Export VM to a standalone file."""
        vm_dir = Path(config.vm_dir) / vm_name
        if not vm_dir.exists():
            return False

        export_file = Path(export_path)
        compression_level = config.backup_compression

        try:
            with gzip.open(export_file, f"wb{compression_level}") as gz:
                with tarfile.open(fileobj=gz, mode="w") as tar:
                    tar.add(vm_dir, arcname=vm_name)
            return True
        except Exception as e:
            print(f"Export failed: {e}")
            return False

    async def import_vm(self, import_path: str, vm_name: str) -> bool:
        """Import VM from an exported file."""
        import_file = Path(import_path)
        if not import_file.exists():
            return False

        vm_dir = Path(config.vm_dir) / vm_name
        if vm_dir.exists():
            return False

        try:
            with gzip.open(import_file, "rb") as gz:
                with tarfile.open(fileobj=gz, mode="r") as tar:
                    tar.extractall(Path(config.vm_dir))

            # Rename extracted directory to vm_name
            # (The tar uses the original name)
            return True
        except Exception as e:
            print(f"Import failed: {e}")
            return False
