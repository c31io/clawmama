"""Integration tests for Hyper-V VM lifecycle.

Prerequisites:
- Hyper-V role installed on the target host
- WinRM enabled (winrm quickconfig)
- HYPERV_HOST, HYPERV_USERNAME, HYPERV_PASSWORD env vars set
- User has Hyper-V administrator permissions

Run with: pytest tests/integration/ -v -m integration
"""

import pytest

from clawmama.vm.hyperv import HyperVManager


@pytest.mark.integration
class TestHyperVLifecycle:
    """Full VM lifecycle integration tests against real Hyper-V."""

    async def test_is_hyperv_available(self):
        """Verify Hyper-V is accessible on the configured host."""
        assert HyperVManager.is_available() is True

    async def test_create_vm(self, hyperv_manager):
        """Create a new Hyper-V VM with default resources."""
        result = await hyperv_manager.create_vm()

        assert result["vcpus"] == 2
        assert result["memory_mib"] == 2048
        assert result["disk_gb"] == 10
        assert "root.vhdx" in result["vhd_path"]

        status = await hyperv_manager.get_status()
        assert status["state"] == "Off"

    async def test_start_vm(self, hyperv_manager):
        """Start VM and verify it transitions to Running state."""
        await hyperv_manager.create_vm()
        ip = await hyperv_manager.start_vm()

        assert ip is not None  # IP assigned by DHCP

        status = await hyperv_manager.get_status()
        assert status["state"] == "Running"

    async def test_pause_resume_vm(self, hyperv_manager):
        """Pause a running VM and resume it."""
        await hyperv_manager.create_vm()
        await hyperv_manager.start_vm()

        paused = await hyperv_manager.pause_vm()
        assert paused is True

        status = await hyperv_manager.get_status()
        assert status["state"] == "Paused"

        resumed = await hyperv_manager.resume_vm()
        assert resumed is True

        status = await hyperv_manager.get_status()
        assert status["state"] == "Running"

    async def test_stop_vm(self, hyperv_manager):
        """Stop a running VM."""
        await hyperv_manager.create_vm()
        await hyperv_manager.start_vm()

        stopped = await hyperv_manager.stop_vm()
        assert stopped is True

        status = await hyperv_manager.get_status()
        assert status["state"] == "Off"

    async def test_full_lifecycle(self, hyperv_manager):
        """End-to-end: create -> start -> pause -> resume -> stop -> delete."""
        # Create
        await hyperv_manager.create_vm(vcpus=2, memory_mib=2048, disk_gb=10)

        # Start
        ip = await hyperv_manager.start_vm()
        assert ip is not None

        # Pause
        await hyperv_manager.pause_vm()
        status = await hyperv_manager.get_status()
        assert status["state"] == "Paused"

        # Resume
        await hyperv_manager.resume_vm()
        status = await hyperv_manager.get_status()
        assert status["state"] == "Running"

        # Stop
        await hyperv_manager.stop_vm()
        status = await hyperv_manager.get_status()
        assert status["state"] == "Off"

        # Delete
        await hyperv_manager.delete_vm()
        status = await hyperv_manager.get_status()
        assert status["state"] == "not_found"