"""Integration tests for Firecracker microVM lifecycle.

Prerequisites:
- Firecracker binary installed at ~/.local/bin/firecracker
- Linux kernel (vmlinux) at ~/.local/share/clawmama/vmlinux
- KVM virtualization enabled (for starting VMs)

Run with: pytest tests/integration/ -v -m integration
"""

import asyncio
import os
import subprocess
import uuid
from typing import Generator

import pytest

from clawmama.vm.firecracker import FirecrackerManager


def is_firecracker_available() -> bool:
    """Check if Firecracker is available."""
    return FirecrackerManager.is_available()


def is_kvm_available() -> bool:
    """Check if KVM is available and can run Firecracker VMs.

    This performs an actual check by trying to start firecracker briefly.
    """
    import tempfile
    import time

    # First check if /dev/kvm exists
    try:
        result = subprocess.run(
            ["ls", "/dev/kvm"],
            capture_output=True,
        )
        if result.returncode != 0:
            return False
    except FileNotFoundError:
        return False

    # Check if kernel exists
    kernel_path = os.path.expanduser("~/.local/share/clawmama/vmlinux")
    if not os.path.exists(kernel_path):
        return False

    # Try to run firecracker briefly to see if it can use KVM
    # We use a minimal config and kill it quickly
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = f"{tmpdir}/test.sock"

        # Minimal firecracker config
        import json
        config = {
            "boot-source": {
                "kernel_image_path": kernel_path,
                "boot_args": "console=ttyS0 panic=1",
            },
            "machine-config": {
                "vcpu_count": 1,
                "mem_size_mib": 128,
            },
        }
        config_path = f"{tmpdir}/config.json"
        with open(config_path, "w") as f:
            json.dump(config, f)

        # Try to start firecracker (will fail quickly if KVM doesn't work)
        proc = subprocess.Popen(
            ["firecracker", "--api-sock", socket_path, "--config-file", config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait a bit to see if it starts
        time.sleep(1)

        # Check if process is still running
        if proc.poll() is not None:
            # Process exited - KVM likely not working properly
            return False

        # Kill the process
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        return True


@pytest.fixture(scope="session")
def firecracker_available():
    """Skip if Firecracker is not available."""
    if not is_firecracker_available():
        pytest.skip(
            "Firecracker is not available. "
            "Please install firecracker binary and kernel."
        )
    return True


@pytest.fixture(autouse=True)
def vsock_only_mode():
    """Run tests in vsock-only mode to avoid network/TAP requirements."""
    original = os.environ.get("CLAWMAMA_VSOCK_ONLY")
    os.environ["CLAWMAMA_VSOCK_ONLY"] = "1"
    yield
    if original is None:
        os.environ.pop("CLAWMAMA_VSOCK_ONLY", None)
    else:
        os.environ["CLAWMAMA_VSOCK_ONLY"] = original


@pytest.fixture
def unique_vm_name() -> str:
    """Generate unique VM name for test isolation."""
    return f"clawmama-test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def firecracker_manager(
    unique_vm_name, firecracker_available
) -> Generator[FirecrackerManager, None, None]:
    """Create a FirecrackerManager.

    Yields the manager and ensures VM is deleted on cleanup even if tests fail.
    """
    manager = FirecrackerManager(unique_vm_name)

    # Pre-cleanup: remove any existing VM with this name
    asyncio.run(manager.delete_vm())

    yield manager

    # Post-cleanup: ensure VM is deleted
    try:
        asyncio.run(manager.delete_vm())
    except Exception:
        pass  # Best effort cleanup


@pytest.mark.integration
class TestFirecrackerLifecycle:
    """Full VM lifecycle integration tests against real Firecracker."""

    async def test_is_firecracker_available(self):
        """Verify Firecracker is accessible on the configured host."""
        assert FirecrackerManager.is_available() is True

    async def test_create_vm(self, firecracker_manager):
        """Create a new Firecracker microVM with default resources."""
        result = await firecracker_manager.create_vm()

        assert result["vcpus"] == 2
        assert result["memory_mib"] == 2048
        assert result["disk_gb"] == 10

    async def test_start_vm(self, firecracker_manager):
        """Start VM and verify it starts."""
        await firecracker_manager.create_vm()
        ip = await firecracker_manager.start_vm()

        assert ip is not None  # IP assigned

    async def test_pause_resume_vm(self, firecracker_manager):
        """Pause a running VM and resume it."""
        # This test requires KVM virtualization to actually run the VM
        # Skip if KVM is not properly available
        if not is_kvm_available():
            pytest.skip("KVM not available for running VM")

        await firecracker_manager.create_vm()
        await firecracker_manager.start_vm()

        paused = await firecracker_manager.pause_vm()
        assert paused is True

        resumed = await firecracker_manager.resume_vm()
        assert resumed is True

    async def test_stop_vm(self, firecracker_manager):
        """Stop a running VM."""
        await firecracker_manager.create_vm()
        await firecracker_manager.start_vm()

        stopped = await firecracker_manager.stop_vm()
        assert stopped is True

    async def test_full_lifecycle(self, firecracker_manager):
        """End-to-end: create -> start -> pause -> resume -> stop -> delete."""
        # This test requires KVM virtualization to actually run the VM
        # Skip if KVM is not properly available
        if not is_kvm_available():
            pytest.skip("KVM not available for running VM")

        # Create
        await firecracker_manager.create_vm(vcpus=2, memory_mib=2048, disk_gb=10)

        # Start
        ip = await firecracker_manager.start_vm()
        assert ip is not None

        # Pause
        await firecracker_manager.pause_vm()

        # Resume
        await firecracker_manager.resume_vm()

        # Stop
        await firecracker_manager.stop_vm()

        # Delete
        await firecracker_manager.delete_vm()
