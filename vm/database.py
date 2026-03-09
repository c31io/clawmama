"""Database module for VM state management."""
import aiosqlite
from pathlib import Path
from typing import Optional
from datetime import datetime


class VMDatabase:
    """SQLite database for managing VM state."""

    def __init__(self, db_path: str = "/var/lib/clawmama/vms.db"):
        self.db_path = db_path
        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async def init_db(self):
        """Initialize database tables."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS vms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    state TEXT NOT NULL DEFAULT 'stopped',
                    vcpus INTEGER NOT NULL,
                    memory_mib INTEGER NOT NULL,
                    disk_gb INTEGER NOT NULL,
                    ip_address TEXT,
                    socket_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    backup_path TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS backups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vm_name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size_bytes INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (vm_name) REFERENCES vms(name)
                )
            """)
            await db.commit()

    async def create_vm(
        self,
        name: str,
        vcpus: int,
        memory_mib: int,
        disk_gb: int,
        ip_address: str = None,
        socket_path: str = None,
    ) -> int:
        """Create a new VM record."""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO vms (name, state, vcpus, memory_mib, disk_gb,
                                ip_address, socket_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, "stopped", vcpus, memory_mib, disk_gb,
                 ip_address, socket_path, now, now)
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT id FROM vms WHERE name = ?", (name,)
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_vm(self, name: str) -> Optional[dict]:
        """Get VM by name."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM vms WHERE name = ?", (name,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def list_vms(self) -> list[dict]:
        """List all VMs."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM vms ORDER BY name")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_vm_state(self, name: str, state: str):
        """Update VM state."""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE vms SET state = ?, updated_at = ? WHERE name = ?",
                (state, now, name)
            )
            await db.commit()

    async def update_vm_ip(self, name: str, ip_address: str):
        """Update VM IP address."""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE vms SET ip_address = ?, updated_at = ? WHERE name = ?",
                (ip_address, now, name)
            )
            await db.commit()

    async def delete_vm(self, name: str):
        """Delete a VM record."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM vms WHERE name = ?", (name,))
            await db.commit()

    async def add_backup(
        self,
        vm_name: str,
        path: str,
        size_bytes: int = None
    ):
        """Add a backup record."""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO backups (vm_name, path, size_bytes, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (vm_name, path, size_bytes, now)
            )
            await db.commit()

    async def get_backups(self, vm_name: str) -> list[dict]:
        """Get backups for a VM."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM backups WHERE vm_name = ? ORDER BY created_at DESC",
                (vm_name,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def delete_backup(self, backup_id: int):
        """Delete a backup record."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM backups WHERE id = ?", (backup_id,))
            await db.commit()
