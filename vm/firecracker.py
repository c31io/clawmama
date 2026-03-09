"""Firecracker microVM manager."""
import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import aiohttp

from config import config


class FirecrackerManager:
    """Manages Firecracker microVMs."""

    def __init__(self, vm_name: str):
        self.vm_name = vm_name
        self.vm_dir = Path(config.vm_dir) / vm_name
        self.socket_path = f"/tmp/firecracker-{vm_name}.sock"
        self.kernel_args = (
            "console=ttyS0 reboot=k panic=1 "
            "ip=dhcp random.trust_cpu=on"
        )

    def _ensure_vm_dir(self):
        """Ensure VM directory exists."""
        self.vm_dir.mkdir(parents=True, exist_ok=True)

    def _get_drive_path(self) -> str:
        """Get path to VM drive."""
        return str(self.vm_dir / "root.img")

    def _get_network_iface(self) -> str:
        """Get TAP interface name for this VM."""
        return f"tap{hash(self.vm_name) % 1000:03d}"

    async def create_vm(
        self,
        vcpus: int = None,
        memory_mib: int = None,
        disk_gb: int = None,
    ) -> dict:
        """Create a new Firecracker microVM."""
        vcpus = vcpus or config.default_vcpus
        memory_mib = memory_mib or config.default_memory_mib
        disk_gb = disk_gb or config.default_disk_gb

        # Enforce resource limits
        vcpus = min(vcpus, config.max_vcpus)
        memory_mib = min(memory_mib, config.max_memory_mib)
        disk_gb = min(disk_gb, config.max_disk_gb)

        self._ensure_vm_dir()

        # Create disk image if it doesn't exist
        disk_path = self._get_drive_path()
        if not Path(disk_path).exists():
            # Create sparse disk image
            subprocess.run(
                ["truncate", "-s", f"{disk_gb}G", disk_path],
                check=True
            )
            # Format as ext4
            subprocess.run(
                ["mkfs.ext4", "-F", disk_path],
                check=True
            )

        # Generate firecracker config
        fc_config = {
            "boot-source": {
                "kernel_image_path": config.kernel_path,
                "boot_args": self.kernel_args
            },
            "drives": [
                {
                    "drive_id": "rootfs",
                    "path_on_host": disk_path,
                    "is_root_device": True,
                    "is_read_only": False
                }
            ],
            "machine-config": {
                "vcpu_count": vcpus,
                "mem_size_mib": memory_mib,
                "ht_enabled": False
            },
            "network-interfaces": [
                {
                    "iface_id": "eth0",
                    "guest_mac": self._generate_mac(),
                    "host_dev_name": self._get_network_iface()
                }
            ],
            "metrics": {
                "metrics_path": str(self.vm_dir / "metrics.json")
            }
        }

        # Write config to temp file
        config_path = self.vm_dir / "fc_config.json"
        with open(config_path, "w") as f:
            json.dump(fc_config, f)

        return {
            "vcpus": vcpus,
            "memory_mib": memory_mib,
            "disk_gb": disk_gb,
            "socket_path": self.socket_path,
            "config_path": str(config_path)
        }

    def _generate_mac(self) -> str:
        """Generate a MAC address for the VM."""
        # Use a fixed prefix for consistency
        mac_int = hash(self.vm_name) % (256**3)
        return f"02:00:00:{mac_int:06x}"

    async def start_vm(self) -> bool:
        """Start the Firecracker microVM."""
        if not Path(config.kernel_path).exists():
            raise FileNotFoundError(
                f"Kernel not found at {config.kernel_path}. "
                "Please download the Firecracker kernel."
            )

        # Setup TAP interface
        tap_iface = self._get_network_iface()
        await self._setup_network(tap_iface)

        # Start firecracker in background
        cmd = [
            config.firecracker_binary,
            "--api-sock", self.socket_path,
            "--config-file", str(self.vm_dir / "fc_config.json")
        ]

        # Create subprocess with nohup to prevent signal handling
        process = subprocess.Popen(
            cmd,
            stdout=open(self.vm_dir / "firecracker.log", "w"),
            stderr=subprocess.STDOUT,
            start_new_session=True
        )

        # Wait for VM to boot and get IP
        await asyncio.sleep(3)

        # Try to get IP via DHCP
        ip_address = await self._wait_for_dhcp()

        return ip_address

    async def _setup_network(self, tap_iface: str):
        """Setup TAP interface and iptables rules."""
        try:
            # Create TAP interface
            subprocess.run(
                ["ip", "tuntap", "add", "mode", "tap", "dev", tap_iface],
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["ip", "link", "set", "tap_iface", "up"],
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["ip", "link", "set", tap_iface, "master", "br-clawmama"],
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError:
            # Interface might already exist, try to find it
            pass

    async def _wait_for_dhcp(self, timeout: int = 30) -> Optional[str]:
        """Wait for DHCP assignment."""
        # In practice, we'd need to monitor the tap interface
        # For now, return a generated IP based on VM name
        return self._calculate_ip()

    def _calculate_ip(self) -> str:
        """Calculate IP based on VM name for consistency."""
        ip_int = hash(self.vm_name) % 254 + 2
        return f"172.30.0.{ip_int}"

    async def stop_vm(self) -> bool:
        """Stop the Firecracker microVM."""
        try:
            async with aiohttp.ClientSession() as session:
                # Send CtrlAltDel
                await session.put(
                    f"http://localhost/-actions",
                    params={"action_type": "SendCtrlAltDel"},
                    socket=self.socket_path
                )
        except Exception:
            pass

        # Kill the firecracker process
        try:
            subprocess.run(
                ["pkill", "-f", f"firecracker.*{self.vm_name}"],
                check=True
            )
        except subprocess.CalledProcessError:
            pass

        # Clean up TAP interface
        tap_iface = self._get_network_iface()
        try:
            subprocess.run(
                ["ip", "link", "del", tap_iface],
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError:
            pass

        return True

    async def pause_vm(self) -> bool:
        """Pause the VM (freeze CPU)."""
        async with aiohttp.ClientSession() as session:
            await session.put(
                f"http://localhost/vm",
                params={"action_type": "Pause"},
                socket=self.socket_path
            )
        return True

    async def resume_vm(self) -> bool:
        """Resume the VM (unfreeze CPU)."""
        async with aiohttp.ClientSession() as session:
            await session.put(
                f"http://localhost/vm",
                params={"action_type": "Resume"},
                socket=self.socket_path
            )
        return True

    async def get_status(self) -> dict:
        """Get VM status."""
        try:
            async with aiohttp.ClientSession() as session:
                resp = await session.get(
                    "http://localhost/vm",
                    socket=self.socket_path
                )
                return await resp.json()
        except Exception:
            return {"state": "stopped"}

    async def get_instance_info(self) -> dict:
        """Get VM instance info."""
        try:
            async with aiohttp.ClientSession() as session:
                resp = await session.get(
                    "http://localhost/instance-info",
                    socket=self.socket_path
                )
                return await resp.json()
        except Exception:
            return {}

    def cleanup(self):
        """Clean up VM resources."""
        # Remove socket file
        if Path(self.socket_path).exists():
            os.remove(self.socket_path)

    async def delete_vm(self):
        """Delete the VM and all its resources."""
        await self.stop_vm()
        # Remove VM directory
        if self.vm_dir.exists():
            import shutil
            shutil.rmtree(self.vm_dir)
