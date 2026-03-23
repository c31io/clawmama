"""Tests for HyperVManager."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clawmama.vm.hyperv import HyperVManager, is_windows


class TestHyperVManager:
    """Test cases for HyperVManager."""

    @pytest.fixture
    def hyperv_manager(self, mocker, tmp_path):
        """Create a HyperVManager with mocked config."""
        mock_cfg = MagicMock()
        mock_cfg.vm_dir = str(tmp_path / "vms")
        mock_cfg.default_vcpus = 2
        mock_cfg.default_memory_mib = 2048
        mock_cfg.default_disk_gb = 10
        mock_cfg.max_vcpus = 4
        mock_cfg.max_memory_mib = 4096
        mock_cfg.max_disk_gb = 20

        mocker.patch("clawmama.vm.hyperv.config", mock_cfg)

        manager = HyperVManager("test-vm")
        return manager

    @pytest.fixture
    def mock_ps_response(self, mocker):
        """Create a mock subprocess.CompletedProcess for PowerShell."""
        def make_response(stdout=b"", stderr=b"", returncode=0):
            response = MagicMock()
            response.stdout = stdout
            response.stderr = stderr
            response.returncode = returncode
            return response
        return make_response

    def test_is_windows_true_on_windows(self, mocker):
        """Test is_windows returns True on Windows."""
        mocker.patch("clawmama.vm.hyperv.platform.system", return_value="Windows")
        assert is_windows() is True

    def test_is_windows_false_on_linux(self, mocker):
        """Test is_windows returns False on Linux."""
        mocker.patch("clawmama.vm.hyperv.platform.system", return_value="Linux")
        assert is_windows() is False

    def test_is_available_true_when_get_vm_exists(self, mocker):
        """Test is_available returns True when Get-VM command exists."""
        mocker.patch("clawmama.vm.hyperv.platform.system", return_value="Windows")
        mock_run = mocker.patch("clawmama.vm.hyperv.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0)
        assert HyperVManager.is_available() is True

    def test_is_available_false_on_non_windows(self, mocker):
        """Test is_available returns False on non-Windows."""
        mocker.patch("clawmama.vm.hyperv.platform.system", return_value="Linux")
        assert HyperVManager.is_available() is False

    def test_is_available_false_when_powershell_missing(self, mocker):
        """Test is_available returns False when PowerShell not found."""
        mocker.patch("clawmama.vm.hyperv.platform.system", return_value="Windows")
        mocker.patch(
            "clawmama.vm.hyperv.subprocess.run",
            side_effect=FileNotFoundError,
        )
        assert HyperVManager.is_available() is False

    def test_run_ps_calls_subprocess_run(self, hyperv_manager, mocker, mock_ps_response):
        """Test that _run_ps calls subprocess.run with powershell."""
        mocker.patch("clawmama.vm.hyperv.subprocess.run", return_value=mock_ps_response())
        hyperv_manager._run_ps("Get-VM")
        from clawmama.vm.hyperv import subprocess
        subprocess.run.assert_called_once_with(
            ["powershell", "-Command", "Get-VM"],
            capture_output=True,
        )

    async def test_create_vm_enforces_resource_limits(self, hyperv_manager, mocker, tmp_path):
        """Test that create_vm enforces resource limits."""
        vm_dir = tmp_path / "vms" / "test-vm"
        vm_dir.mkdir(parents=True)

        mocker.patch.object(hyperv_manager, "_run_ps", return_value=MagicMock(returncode=0, stdout=b""))
        mocker.patch("pathlib.Path.mkdir")
        mocker.patch("pathlib.Path.exists", return_value=True)

        result = await hyperv_manager.create_vm(vcpus=100, memory_mib=100000, disk_gb=1000)

        # Should be capped to max values
        assert result["vcpus"] == 4  # max_vcpus
        assert result["memory_mib"] == 4096  # max_memory_mib
        assert result["disk_gb"] == 20  # max_disk_gb

    async def test_create_vm_existing_vm_skips_creation(
        self, hyperv_manager, mocker, tmp_path
    ):
        """Test that create_vm skips creation if VM already exists."""
        vm_dir = tmp_path / "vms" / "test-vm"
        vm_dir.mkdir(parents=True)

        mock_response = MagicMock(returncode=0, stdout=b"test-vm")
        mocker.patch.object(hyperv_manager, "_run_ps", return_value=mock_response)
        mocker.patch("pathlib.Path.exists", return_value=True)

        result = await hyperv_manager.create_vm()

        assert result["vcpus"] == 2  # default_vcpus
        # Should not have called New-VM
        calls = hyperv_manager._run_ps.call_args_list
        assert not any("New-VM" in str(call) for call in calls)

    async def test_create_vm_returns_correct_config(self, hyperv_manager, mocker, tmp_path):
        """Test that create_vm returns correct VM configuration."""
        vm_dir = tmp_path / "vms" / "test-vm"
        vm_dir.mkdir(parents=True)

        mocker.patch.object(hyperv_manager, "_run_ps", return_value=MagicMock(returncode=0, stdout=b""))
        mocker.patch("pathlib.Path.mkdir")
        mocker.patch("pathlib.Path.exists", return_value=True)

        result = await hyperv_manager.create_vm()

        assert "vcpus" in result
        assert "memory_mib" in result
        assert "disk_gb" in result
        assert "vhd_path" in result
        assert result["vhd_path"].endswith("root.vhdx")

    async def test_start_vm_calls_start_vm_script(self, hyperv_manager, mocker):
        """Test that start_vm calls Start-VM PowerShell script."""
        mocker.patch.object(
            hyperv_manager,
            "_run_ps",
            side_effect=[
                MagicMock(returncode=0, stdout=b""),  # Start-VM
                MagicMock(returncode=0, stdout=b"192.168.1.100"),  # Get IP
            ],
        )
        mocker.patch("asyncio.sleep", new_callable=AsyncMock)

        result = await hyperv_manager.start_vm()

        assert hyperv_manager._run_ps.called
        assert result == "192.168.1.100"

    async def test_start_vm_raises_on_failure(self, hyperv_manager, mocker):
        """Test that start_vm raises on failure."""
        mocker.patch.object(
            hyperv_manager,
            "_run_ps",
            return_value=MagicMock(returncode=1, stderr=b"Failed to start"),
        )
        mocker.patch("asyncio.sleep", new_callable=AsyncMock)

        with pytest.raises(RuntimeError, match="Failed to start"):
            await hyperv_manager.start_vm()

    async def test_stop_vm_calls_stop_vm_script(self, hyperv_manager, mocker):
        """Test that stop_vm calls Stop-VM PowerShell script."""
        mocker.patch.object(
            hyperv_manager,
            "_run_ps",
            return_value=MagicMock(returncode=0, stderr=b""),
        )

        result = await hyperv_manager.stop_vm()

        assert result is True
        assert hyperv_manager._run_ps.called

    async def test_pause_vm_calls_suspend_script(self, hyperv_manager, mocker):
        """Test that pause_vm calls Suspend-VM."""
        mocker.patch.object(
            hyperv_manager,
            "_run_ps",
            return_value=MagicMock(returncode=0),
        )

        result = await hyperv_manager.pause_vm()

        assert result is True
        hyperv_manager._run_ps.assert_called()

    async def test_resume_vm_calls_resume_script(self, hyperv_manager, mocker):
        """Test that resume_vm calls Resume-VM."""
        mocker.patch.object(
            hyperv_manager,
            "_run_ps",
            return_value=MagicMock(returncode=0),
        )

        result = await hyperv_manager.resume_vm()

        assert result is True
        hyperv_manager._run_ps.assert_called()

    async def test_get_status_returns_vm_info(self, hyperv_manager, mocker):
        """Test that get_status returns VM info."""
        mocker.patch.object(
            hyperv_manager,
            "_run_ps",
            return_value=MagicMock(
                returncode=0,
                stdout=b'{"State": "Running", "CPUUsage": 10}',
            ),
        )

        result = await hyperv_manager.get_status()

        assert result["State"] == "Running"
        assert result["CPUUsage"] == 10

    async def test_get_status_returns_not_found(self, hyperv_manager, mocker):
        """Test that get_status returns not_found when VM doesn't exist."""
        mocker.patch.object(
            hyperv_manager,
            "_run_ps",
            return_value=MagicMock(
                returncode=0,
                stdout=b'{"state": "not_found"}',
            ),
        )

        result = await hyperv_manager.get_status()

        assert result["state"] == "not_found"

    async def test_get_instance_info_returns_status(self, hyperv_manager, mocker):
        """Test that get_instance_info returns same as get_status."""
        mocker.patch.object(
            hyperv_manager,
            "_run_ps",
            return_value=MagicMock(
                returncode=0,
                stdout=b'{"State": "Running"}',
            ),
        )

        result = await hyperv_manager.get_instance_info()

        assert result["State"] == "Running"

    def test_cleanup_is_noop(self, hyperv_manager):
        """Test that cleanup is a no-op."""
        # Should not raise
        hyperv_manager.cleanup()

    async def test_delete_vm_stops_and_removes_vm(self, hyperv_manager, mocker):
        """Test that delete_vm stops and removes VM."""
        mocker.patch.object(
            hyperv_manager,
            "_run_ps",
            return_value=MagicMock(returncode=0, stderr=b""),
        )
        mocker.patch("asyncio.sleep", new_callable=AsyncMock)

        # Create fake VHD file
        vhd_path = hyperv_manager.vm_dir / "root.vhdx"
        vhd_path.parent.mkdir(parents=True, exist_ok=True)
        vhd_path.touch()

        await hyperv_manager.delete_vm()

        assert hyperv_manager._run_ps.called
        assert not vhd_path.exists()


class AsyncMock(MagicMock):
    """Mock that supports await."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)
