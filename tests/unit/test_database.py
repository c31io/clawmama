"""Tests for VMDatabase."""

import pytest

from clawmama.vm.database import VMDatabase


class TestVMDatabase:
    """Test cases for VMDatabase."""

    async def test_init_db_creates_tables(self, in_memory_db):
        """Test that init_db creates the vms and backups tables."""
        db = in_memory_db
        # Tables should exist - verify by creating a vm
        vm_id = await db.create_vm(
            name="test-vm",
            vcpus=2,
            memory_mib=2048,
            disk_gb=10,
        )
        assert vm_id is not None
        assert vm_id > 0

    async def test_create_vm_inserts_record(self, in_memory_db):
        """Test that create_vm inserts a VM record."""
        db = in_memory_db
        vm_id = await db.create_vm(
            name="test-vm",
            vcpus=2,
            memory_mib=2048,
            disk_gb=10,
            ip_address="172.30.0.2",
            socket_path="/tmp/firecracker-test-vm.sock",
        )
        assert vm_id is not None

        # Verify record
        vm = await db.get_vm("test-vm")
        assert vm is not None
        assert vm["name"] == "test-vm"
        assert vm["vcpus"] == 2
        assert vm["memory_mib"] == 2048
        assert vm["disk_gb"] == 10
        assert vm["ip_address"] == "172.30.0.2"
        assert vm["socket_path"] == "/tmp/firecracker-test-vm.sock"
        assert vm["state"] == "stopped"

    async def test_get_vm_returns_dict(self, in_memory_db):
        """Test that get_vm returns a dict with VM info."""
        db = in_memory_db
        await db.create_vm(
            name="test-vm",
            vcpus=2,
            memory_mib=2048,
            disk_gb=10,
        )

        vm = await db.get_vm("test-vm")
        assert vm is not None
        assert isinstance(vm, dict)
        assert "name" in vm
        assert "vcpus" in vm

    async def test_get_vm_returns_none_for_nonexistent(self, in_memory_db):
        """Test that get_vm returns None for nonexistent VM."""
        db = in_memory_db
        vm = await db.get_vm("nonexistent-vm")
        assert vm is None

    async def test_list_vms_returns_all(self, in_memory_db):
        """Test that list_vms returns all VMs."""
        db = in_memory_db
        await db.create_vm(name="vm1", vcpus=2, memory_mib=2048, disk_gb=10)
        await db.create_vm(name="vm2", vcpus=4, memory_mib=4096, disk_gb=20)

        vms = await db.list_vms()
        assert len(vms) == 2
        names = {vm["name"] for vm in vms}
        assert names == {"vm1", "vm2"}

    async def test_list_vms_returns_empty_list(self, in_memory_db):
        """Test that list_vms returns empty list when no VMs."""
        db = in_memory_db
        vms = await db.list_vms()
        assert vms == []

    async def test_update_vm_state(self, in_memory_db):
        """Test updating VM state."""
        db = in_memory_db
        await db.create_vm(name="test-vm", vcpus=2, memory_mib=2048, disk_gb=10)

        await db.update_vm_state("test-vm", "running")
        vm = await db.get_vm("test-vm")
        assert vm["state"] == "running"

    async def test_update_vm_ip(self, in_memory_db):
        """Test updating VM IP address."""
        db = in_memory_db
        await db.create_vm(name="test-vm", vcpus=2, memory_mib=2048, disk_gb=10)

        await db.update_vm_ip("test-vm", "172.30.0.100")
        vm = await db.get_vm("test-vm")
        assert vm["ip_address"] == "172.30.0.100"

    async def test_delete_vm_removes_record(self, in_memory_db):
        """Test that delete_vm removes the VM record."""
        db = in_memory_db
        await db.create_vm(name="test-vm", vcpus=2, memory_mib=2048, disk_gb=10)

        await db.delete_vm("test-vm")
        vm = await db.get_vm("test-vm")
        assert vm is None

    async def test_add_and_get_backups(self, in_memory_db):
        """Test adding and getting backups."""
        db = in_memory_db
        await db.create_vm(name="test-vm", vcpus=2, memory_mib=2048, disk_gb=10)

        await db.add_backup("test-vm", "/tmp/backup1.tar.zst", 1024)
        await db.add_backup("test-vm", "/tmp/backup2.tar.zst", 2048)

        backups = await db.get_backups("test-vm")
        assert len(backups) == 2
        # Should be ordered by created_at DESC
        paths = [b["path"] for b in backups]
        assert "/tmp/backup2.tar.zst" in paths
        assert "/tmp/backup1.tar.zst" in paths

    async def test_get_backups_returns_empty_for_no_backups(self, in_memory_db):
        """Test get_backups returns empty list when no backups."""
        db = in_memory_db
        backups = await db.get_backups("test-vm")
        assert backups == []

    async def test_delete_backup_removes_record(self, in_memory_db):
        """Test deleting a backup record."""
        db = in_memory_db
        await db.create_vm(name="test-vm", vcpus=2, memory_mib=2048, disk_gb=10)
        await db.add_backup("test-vm", "/tmp/backup1.tar.zst", 1024)

        backups = await db.get_backups("test-vm")
        backup_id = backups[0]["id"]

        await db.delete_backup(backup_id)
        backups = await db.get_backups("test-vm")
        assert len(backups) == 0
