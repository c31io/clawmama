"""Shared fixtures for Hyper-V integration tests."""

import asyncio
import uuid
from typing import Generator

import pytest

from clawmama.vm.hyperv import HyperVManager


def is_hyperv_available() -> bool:
    """Check if Hyper-V is available."""
    return HyperVManager.is_available()


@pytest.fixture(scope="session")
def hyperv_available():
    """Skip if Hyper-V is not available."""
    if not is_hyperv_available():
        pytest.skip("Hyper-V is not available on this system")
    return True


@pytest.fixture
def unique_vm_name() -> str:
    """Generate unique VM name for test isolation."""
    return f"clawmama-test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def hyperv_manager(unique_vm_name, hyperv_available) -> Generator[HyperVManager, None, None]:
    """Create a HyperVManager.

    Yields the manager and ensures VM is deleted on cleanup even if tests fail.
    """
    manager = HyperVManager(unique_vm_name)

    # Pre-cleanup: remove any existing VM with this name
    asyncio.run(manager.delete_vm())

    yield manager

    # Post-cleanup: ensure VM is deleted
    try:
        asyncio.run(manager.delete_vm())
    except Exception:
        pass  # Best effort cleanup
