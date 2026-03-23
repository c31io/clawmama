"""Tests for FirecrackerManager."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawmama.vm.firecracker import FirecrackerManager


class TestFirecrackerManager:
    """Test cases for FirecrackerManager."""

    @pytest.fixture
    def fc_manager(self, mocker, tmp_path):
        """Create a FirecrackerManager with mocked config."""
        mock_cfg = MagicMock()
        mock_cfg.vm_dir = str(tmp_path / "vms")
        mock_cfg.kernel_path = str(tmp_path / "vmlinux")
        mock_cfg.firecracker_binary = str(tmp_path / "firecracker")
        mock_cfg.default_vcpus = 2
        mock_cfg.default_memory_mib = 2048
        mock_cfg.default_disk_gb = 10
        mock_cfg.max_vcpus = 4
        mock_cfg.max_memory_mib = 4096
        mock_cfg.max_disk_gb = 20

        mocker.patch("clawmama.vm.firecracker.config", mock_cfg)

        manager = FirecrackerManager("test-vm")
        return manager

    def test_ensure_vm_dir_creates_directory(self, fc_manager, tmp_path):
        """Test that _ensure_vm_dir creates the VM directory."""
        vm_dir = tmp_path / "vms" / "test-vm"
        assert not vm_dir.exists()

        fc_manager._ensure_vm_dir()

        assert vm_dir.exists()
        assert vm_dir.is_dir()

    def test_get_drive_path(self, fc_manager, tmp_path):
        """Test that _get_drive_path returns correct path."""
        expected = str(tmp_path / "vms" / "test-vm" / "root.img")
        assert fc_manager._get_drive_path() == expected

    def test_get_network_iface(self, fc_manager):
        """Test that _get_network_iface returns consistent TAP name."""
        iface1 = fc_manager._get_network_iface()
        iface2 = fc_manager._get_network_iface()
        assert iface1 == iface2
        assert iface1.startswith("tap")

    def test_generate_mac_returns_valid_format(self, fc_manager):
        """Test that _generate_mac returns a valid MAC address."""
        mac = fc_manager._generate_mac()

        # Should be 6 bytes separated by colons
        parts = mac.split(":")
        assert len(parts) == 6
        for part in parts:
            assert len(part) == 2
            assert all(c in "0123456789abcdef" for c in part)

        # First octet should have local bit set (bit 1) and unicast bit clear (bit 0)
        first_octet = int(parts[0], 16)
        assert first_octet & 0x01 == 0  # Unicast (bit 0 clear)
        assert first_octet & 0x02 == 2  # Local (bit 1 set)

    def test_generate_mac_is_deterministic(self, fc_manager):
        """Test that _generate_mac returns consistent MAC for same VM name."""
        mac1 = fc_manager._generate_mac()
        mac2 = fc_manager._generate_mac()
        assert mac1 == mac2

    def test_generate_mac_different_for_different_names(self, mocker, tmp_path):
        """Test that different VM names generate different MACs."""
        mock_cfg = MagicMock()
        mock_cfg.vm_dir = str(tmp_path / "vms")
        mock_cfg.kernel_path = str(tmp_path / "vmlinux")
        mock_cfg.firecracker_binary = str(tmp_path / "firecracker")
        mock_cfg.default_vcpus = 2
        mock_cfg.default_memory_mib = 2048
        mock_cfg.default_disk_gb = 10
        mock_cfg.max_vcpus = 4
        mock_cfg.max_memory_mib = 4096
        mock_cfg.max_disk_gb = 20
        mocker.patch("clawmama.vm.firecracker.config", mock_cfg)

        fc1 = FirecrackerManager("vm-one")
        fc2 = FirecrackerManager("vm-two")

        assert fc1._generate_mac() != fc2._generate_mac()

    async def test_create_vm_enforces_limits(self, fc_manager, mocker):
        """Test that create_vm enforces resource limits."""
        # Mock subprocess to avoid actual disk creation
        mocker.patch("subprocess.run")
        mocker.patch("pathlib.Path.exists", return_value=False)

        # Request more than max
        result = await fc_manager.create_vm(vcpus=100, memory_mib=100000, disk_gb=1000)

        # Should be capped to max values
        assert result["vcpus"] == 4  # max_vcpus
        assert result["memory_mib"] == 4096  # max_memory_mib
        assert result["disk_gb"] == 20  # max_disk_gb

    async def test_create_vm_writes_config_json(self, fc_manager, mocker, tmp_path):
        """Test that create_vm writes firecracker config to JSON file."""
        # Mock subprocess to avoid actual disk creation
        mocker.patch("subprocess.run")

        # Set vsock-only mode
        mocker.patch.dict("os.environ", {"CLAWMAMA_VSOCK_ONLY": "true"})

        result = await fc_manager.create_vm()

        config_path = Path(result["config_path"])
        # Config should have been written
        assert config_path.exists(), f"Config file not found at {config_path}"

        import json

        with open(config_path) as f:
            config = json.load(f)

        assert "boot-source" in config
        assert "drives" in config
        assert "machine-config" in config
        assert "vsock" in config  # vsock-only mode

    async def test_create_vm_without_vsock_only(self, fc_manager, mocker, tmp_path):
        """Test that create_vm adds network interface when not vsock-only."""
        import json as json_module

        mocker.patch("subprocess.run")
        mocker.patch.dict("os.environ", {}, clear=True)

        result = await fc_manager.create_vm()

        config_path = Path(result["config_path"])
        assert config_path.exists(), f"Config file not found at {config_path}"
        with open(config_path) as f:
            config = json_module.load(f)

        assert "network-interfaces" in config
        assert "vsock" not in config

    async def test_cleanup_removes_socket(self, fc_manager, tmp_path, mocker):
        """Test that cleanup removes the socket file."""
        # Create a fake socket file
        socket_path = Path(fc_manager.socket_path)
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        socket_path.touch()

        assert socket_path.exists()

        fc_manager.cleanup()

        assert not socket_path.exists()

    async def test_cleanup_does_not_fail_if_socket_missing(self, fc_manager):
        """Test that cleanup does not fail if socket doesn't exist."""
        # Should not raise
        fc_manager.cleanup()

    async def test_get_status_returns_stopped_on_error(self, fc_manager, mocker):
        """Test that get_status returns stopped when VM is not running."""
        # Make aiohttp.ClientSession raise an exception
        mocker.patch(
            "aiohttp.ClientSession",
            side_effect=Exception("Connection failed"),
        )
        mocker.patch("clawmama.vm.firecracker.UnixConnector")

        status = await fc_manager.get_status()
        assert status["state"] == "stopped"

    async def test_get_instance_info_returns_empty_on_error(self, fc_manager, mocker):
        """Test that get_instance_info returns empty dict on error."""
        mocker.patch(
            "aiohttp.ClientSession",
            side_effect=Exception("Connection failed"),
        )
        mocker.patch("clawmama.vm.firecracker.UnixConnector")

        info = await fc_manager.get_instance_info()
        assert info == {}

    async def test_stop_vm_returns_true(self, fc_manager, mocker):
        """Test that stop_vm returns True."""
        # Mock subprocess to avoid actual pkill
        mocker.patch("subprocess.run")
        # Mock aiohttp
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={})
        mock_session.put = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mocker.patch("aiohttp.ClientSession", return_value=mock_session)
        mocker.patch("clawmama.vm.firecracker.UnixConnector")

        result = await fc_manager.stop_vm()
        assert result is True

    async def test_pause_vm(self, fc_manager, mocker):
        """Test that pause_vm calls the correct API."""
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_session.put = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mocker.patch("aiohttp.ClientSession", return_value=mock_session)
        mocker.patch("clawmama.vm.firecracker.UnixConnector")

        await fc_manager.pause_vm()

        # Verify pause was called
        mock_session.put.assert_called_once()

    async def test_resume_vm(self, fc_manager, mocker):
        """Test that resume_vm calls the correct API."""
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_session.put = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mocker.patch("aiohttp.ClientSession", return_value=mock_session)
        mocker.patch("clawmama.vm.firecracker.UnixConnector")

        await fc_manager.resume_vm()

        # Verify resume was called
        mock_session.put.assert_called_once()
