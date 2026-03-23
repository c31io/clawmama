"""Shared fixtures for VM module tests."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from clawmama.vm.database import VMDatabase


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_config(mocker):
    """Mock config object for VM modules."""
    config = mocker.MagicMock()
    config.vm_dir = "/tmp/vms"
    config.data_dir = "/tmp/data"
    config.kernel_path = "/tmp/kernel"
    config.image_path = "/tmp/image"
    config.backup_dir = "/tmp/backups"
    config.backup_compression = 3
    config.default_vcpus = 2
    config.default_memory_mib = 2048
    config.default_disk_gb = 10
    config.max_vcpus = 4
    config.max_memory_mib = 4096
    config.max_disk_gb = 20
    config.firecracker_binary = "/usr/bin/firecracker"
    return config


@pytest_asyncio.fixture
async def in_memory_db(tmp_path, mocker):
    """In-memory database for testing."""
    # Mock config before creating db
    mocker.patch("clawmama.config.config", data_dir=str(tmp_path), vm_dir=str(tmp_path / "vms"))
    db = VMDatabase(db_path=str(tmp_path / "test.db"))
    await db.init_db()
    return db


@pytest.fixture
def tmp_vm_dir(tmp_path):
    """Temporary VM directory."""
    vm_dir = tmp_path / "vms"
    vm_dir.mkdir()
    return vm_dir


@pytest.fixture
def tmp_backup_dir(tmp_path):
    """Temporary backup directory."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    return backup_dir
