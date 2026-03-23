"""Hyper-V VM manager using WinRM."""

import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Optional

import winrm

from clawmama.config import config
from clawmama.vm.interface import VMManager

logger = logging.getLogger("clawmama.hyperv")


def is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system() == "Windows"


class HyperVManager(VMManager):
    """Manages Hyper-V VMs via WinRM."""

    def __init__(self, vm_name: str, host: str = "localhost"):
        self.vm_name = vm_name
        self.host = host
        self.session: Optional[winrm.Session] = None
        self.vm_dir = Path(config.vm_dir) / vm_name

    @staticmethod
    def is_available() -> bool:
        """Check if Hyper-V is available on this system."""
        if platform.system() != "Windows":
            return False
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-Command",
                    "Get-Command Get-VM -ErrorAction SilentlyContinue",
                ],
                capture_output=True,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def connect(self, username: str | None = None, password: str | None = None):
        """Connect to Hyper-V host via WinRM."""
        if platform.system() != "Windows":
            raise RuntimeError("Hyper-V is only available on Windows")

        # Use current user credentials if not provided
        if not username:
            username = os.environ.get("USERNAME", os.environ.get("USER", ""))

        self.session = winrm.Session(
            self.host,
            auth=(username, password or ""),
        )
        logger.info(f"[{self.vm_name}] Connected to {self.host} via WinRM")

    def _run_ps(self, script: str) -> winrm.Response:
        """Run PowerShell script via WinRM."""
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")
        return self.session.run_ps(script)

    async def create_vm(
        self,
        vcpus: int | None = None,
        memory_mib: int | None = None,
        disk_gb: int | None = None,
    ) -> dict:
        """Create a new Hyper-V VM."""
        logger.info(f"[{self.vm_name}] Creating Hyper-V VM...")
        vcpus = vcpus or config.default_vcpus
        memory_mib = memory_mib or config.default_memory_mib
        disk_gb = disk_gb or config.default_disk_gb

        # Enforce resource limits
        vcpus = min(vcpus, config.max_vcpus)
        memory_mib = min(memory_mib, config.max_memory_mib)
        disk_gb = min(disk_gb, config.max_disk_gb)

        # Ensure VM directory exists
        self.vm_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[{self.vm_name}] VM directory: {self.vm_dir}")

        # Check if VM already exists
        script = f'Get-VM -Name "{self.vm_name}" -ErrorAction SilentlyContinue'
        result = self._run_ps(script)
        std_out_str = (
            result.std_out.decode()
            if isinstance(result.std_out, bytes)
            else result.std_out
        )

        if result.status_code == 0 and self.vm_name in std_out_str:
            logger.info(f"[{self.vm_name}] VM already exists")
        else:
            # Create the VM
            create_script = f'''
            New-VM -Name "{self.vm_name}" -MemoryStartupBytes {memory_mib}MB -Generation 2
            Set-VMProcessor -VMName "{self.vm_name}" -Count {vcpus}
            '''
            result = self._run_ps(create_script)
            if result.status_code != 0:
                raise RuntimeError(f"Failed to create VM: {result.std_err}")
            logger.info(f"[{self.vm_name}] VM created")

        # Create VHDX disk if needed
        vhd_path = self.vm_dir / "root.vhdx"
        if not vhd_path.exists():
            logger.info(f"[{self.vm_name}] Creating VHDX: {disk_gb}GB")
            script = f'''
            New-VHD -Path "{vhd_path}" -SizeBytes {disk_gb}GB -Dynamic
            Add-VMHardDiskDrive -VMName "{self.vm_name}" -Path "{vhd_path}" -ControllerType SCSI
            '''
            result = self._run_ps(script)
            if result.status_code != 0:
                raise RuntimeError(f"Failed to create disk: {result.std_err}")
            logger.info(f"[{self.vm_name}] Disk created")
        else:
            logger.info(f"[{self.vm_name}] Using existing disk: {vhd_path}")

        # Set up networking (connect to default switch)
        script = f'''
        $switch = Get-VMSwitch -DefaultSwitch -ErrorAction SilentlyContinue
        if ($switch) {{
            Connect-VMNetworkAdapter -VMName "{self.vm_name}" -SwitchName $switch.Name
        }}
        '''
        result = self._run_ps(script)
        logger.info(f"[{self.vm_name}] Network configured")

        logger.info(
            f"[{self.vm_name}] VM configuration complete: {vcpus} vCPU, {memory_mib} MB, {disk_gb} GB"
        )

        return {
            "vcpus": vcpus,
            "memory_mib": memory_mib,
            "disk_gb": disk_gb,
            "vhd_path": str(vhd_path),
        }

    async def start_vm(self) -> str | None:
        """Start the Hyper-V VM."""
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")

        logger.info(f"[{self.vm_name}] Starting VM...")

        # Start VM
        script = f'Start-VM -Name "{self.vm_name}"'
        result = self._run_ps(script)

        if result.status_code != 0:
            raise RuntimeError(f"Failed to start VM: {result.std_err}")

        logger.info(f"[{self.vm_name}] VM started")

        # Wait for boot and get IP
        import asyncio

        await asyncio.sleep(5)

        return await self._get_vm_ip()

    async def _get_vm_ip(self, timeout: int = 60) -> Optional[str]:
        """Get VM IP address."""
        script = f'''
        $vm = Get-VM -Name "{self.vm_name}"
        $adapter = $vm.NetworkAdapters | Select-Object -First 1
        $adapter.IPAddresses | Where-Object {{ $_ -match "^\\d+\\.\\d+\\.\\d+\\.\\d+$" }} | Select-Object -First 1
        '''
        result = self._run_ps(script)
        std_out_bytes = result.std_out
        std_out_str = (
            std_out_bytes.decode()
            if isinstance(std_out_bytes, bytes)
            else std_out_bytes
        )

        if result.status_code == 0 and std_out_str.strip():
            ip = std_out_str.strip()
            logger.info(f"[{self.vm_name}] IP: {ip}")
            return ip

        logger.warning(f"[{self.vm_name}] Could not get IP address")
        return None

    async def stop_vm(self) -> bool:
        """Stop the Hyper-V VM."""
        if not self.session:
            logger.warning("[{self.vm_name}] Not connected, cannot stop VM")
            return False

        logger.info(f"[{self.vm_name}] Stopping VM...")

        script = f'Stop-VM -Name "{self.vm_name}" -Force'
        result = self._run_ps(script)

        if result.status_code != 0:
            logger.error(f"Failed to stop VM: {result.std_err}")
            return False

        logger.info(f"[{self.vm_name}] VM stopped")
        return True

    async def pause_vm(self) -> bool:
        """Pause the VM (suspend)."""
        if not self.session:
            return False

        logger.info(f"[{self.vm_name}] Pausing VM...")
        script = f'Suspend-VM -Name "{self.vm_name}"'
        result = self._run_ps(script)
        return result.status_code == 0

    async def resume_vm(self) -> bool:
        """Resume the VM (resume from suspend)."""
        if not self.session:
            return False

        logger.info(f"[{self.vm_name}] Resuming VM...")
        script = f'Resume-VM -Name "{self.vm_name}"'
        result = self._run_ps(script)
        return result.status_code == 0

    async def get_status(self) -> dict:
        """Get VM status."""
        if not self.session:
            return {"state": "disconnected"}

        script = f'''
        $vm = Get-VM -Name "{self.vm_name}" -ErrorAction SilentlyContinue
        if ($vm) {{
            @{{
                State = $vm.State
                CPUUsage = $vm.CPUUsage
                MemoryAssigned = $vm.MemoryAssigned
                MemoryDemand = $vm.MemoryDemand
            }} | ConvertTo-Json
        }} else {{
            {{"state": "not_found"}} | ConvertTo-Json
        }}
        '''
        result = self._run_ps(script)

        if result.status_code == 0:
            import json

            std_out_bytes = result.std_out
            std_out_str = (
                std_out_bytes.decode()
                if isinstance(std_out_bytes, bytes)
                else std_out_bytes
            )

            try:
                return json.loads(std_out_str)
            except json.JSONDecodeError:
                return {"state": "unknown"}
        return {"state": "error"}

    async def get_instance_info(self) -> dict:
        """Get VM instance info."""
        return await self.get_status()

    def cleanup(self):
        """Clean up resources."""
        self.session = None

    async def delete_vm(self):
        """Delete the VM and all its resources."""
        logger.info(f"[{self.vm_name}] Deleting VM...")

        # Stop if running
        await self.stop_vm()

        # Remove VM
        script = f'Remove-VM -Name "{self.vm_name}" -Force'
        result = self._run_ps(script)

        if result.status_code != 0:
            logger.warning(f"Failed to remove VM: {result.std_err}")

        # Optionally remove VHD
        vhd_path = self.vm_dir / "root.vhdx"
        if vhd_path.exists():
            vhd_path.unlink()
            logger.info(f"[{self.vm_name}] Removed disk: {vhd_path}")

        logger.info(f"[{self.vm_name}] VM deleted")
