"""Firecracker microVM manager."""

import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import aiohttp
from aiohttp import UnixConnector

from clawmama.config import config
from clawmama.vm.interface import VMManager

logger = logging.getLogger("clawmama.firecracker")


class FirecrackerManager(VMManager):
    """Manages Firecracker microVMs."""

    def __init__(self, vm_name: str):
        self.vm_name = vm_name
        self.vm_dir = Path(config.vm_dir) / vm_name
        self.socket_path = f"/tmp/firecracker-{vm_name}.sock"
        self.kernel_args = "console=ttyS0 reboot=k panic=1 ip=dhcp random.trust_cpu=on"
        self.vsock_only_kernel_args = (
            "console=ttyS0 reboot=k panic=1 ip=none random.trust_cpu=on"
        )

    @classmethod
    def is_available(cls) -> bool:
        """Check if Firecracker is available on this system.

        Returns True if firecracker binary and kernel are available.
        """
        try:
            firecracker_path = Path(config.firecracker_binary)
            kernel_path = Path(config.kernel_path)
            return firecracker_path.exists() and kernel_path.exists()
        except Exception:
            return False

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
        vcpus: int | None = None,
        memory_mib: int | None = None,
        disk_gb: int | None = None,
    ) -> dict:
        """Create a new Firecracker microVM."""
        logger.info(f"[{self.vm_name}] Creating VM configuration...")
        vcpus = vcpus or config.default_vcpus
        memory_mib = memory_mib or config.default_memory_mib
        disk_gb = disk_gb or config.default_disk_gb

        # Enforce resource limits
        vcpus = min(vcpus, config.max_vcpus)
        memory_mib = min(memory_mib, config.max_memory_mib)
        disk_gb = min(disk_gb, config.max_disk_gb)

        self._ensure_vm_dir()
        logger.info(f"[{self.vm_name}] VM directory: {self.vm_dir}")

        # Create disk image if it doesn't exist
        disk_path = self._get_drive_path()
        if not Path(disk_path).exists():
            logger.info(
                f"[{self.vm_name}] Creating disk image: {disk_gb}G at {disk_path}"
            )
            # Create sparse disk image
            subprocess.run(["truncate", "-s", f"{disk_gb}G", disk_path], check=True)
            # Format as ext4
            logger.info(f"[{self.vm_name}] Formatting disk as ext4...")
            mkfs_path = shutil.which("mkfs.ext4") or "/usr/sbin/mkfs.ext4"
            subprocess.run([mkfs_path, "-F", disk_path], check=True)
        else:
            logger.info(f"[{self.vm_name}] Using existing disk: {disk_path}")

        # Check vsock-only mode
        vsock_only = os.environ.get("CLAWMAMA_VSOCK_ONLY", "").lower() in (
            "1",
            "true",
            "yes",
        )
        print(
            f"[DEBUG] CLAWMAMA_VSOCK_ONLY env var: {os.environ.get('CLAWMAMA_VSOCK_ONLY', 'NOT SET')}, vsock_only: {vsock_only}"
        )
        boot_args = self.vsock_only_kernel_args if vsock_only else self.kernel_args

        # Generate firecracker config
        fc_config = {
            "boot-source": {
                "kernel_image_path": config.kernel_path,
                "boot_args": boot_args,
            },
            "drives": [
                {
                    "drive_id": "rootfs",
                    "path_on_host": disk_path,
                    "is_root_device": True,
                    "is_read_only": False,
                }
            ],
            "machine-config": {
                "vcpu_count": vcpus,
                "mem_size_mib": memory_mib,
                "smt": False,
            },
            "metrics": {"metrics_path": str(self.vm_dir / "metrics.json")},
        }

        # Only add network if not in vsock-only mode
        vsock_only = os.environ.get("CLAWMAMA_VSOCK_ONLY", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if vsock_only:
            # vsock-only mode: add vsock but no network
            fc_config["vsock"] = {
                "vsock_id": "vsock0",
                "guest_cid": 3,
            }
            logger.info(f"[{self.vm_name}] Running in vsock-only mode (no network)")
        else:
            # Normal mode: add network
            fc_config["network-interfaces"] = [
                {
                    "iface_id": "eth0",
                    "guest_mac": self._generate_mac(),
                    "host_dev_name": self._get_network_iface(),
                }
            ]

        # Write config to temp file
        config_path = self.vm_dir / "fc_config.json"
        logger.info(f"[{self.vm_name}] Writing Firecracker config to: {config_path}")
        with open(config_path, "w") as f:
            json.dump(fc_config, f, indent=2)

        logger.info(
            f"[{self.vm_name}] VM configuration complete: {vcpus} vCPU, {memory_mib} MB, {disk_gb} GB"
        )

        return {
            "vcpus": vcpus,
            "memory_mib": memory_mib,
            "disk_gb": disk_gb,
            "socket_path": self.socket_path,
            "config_path": str(config_path),
        }

    def _generate_mac(self) -> str:
        """Generate a valid MAC address for the VM."""
        # Use a fixed prefix for consistency
        # Valid MAC: 02:XX:XX:XX:XX:XX (locally administered, unicast)
        mac_int = hash(self.vm_name) % (256**5)
        mac_bytes = mac_int.to_bytes(6, "big")
        # Set bit 1 (locally administered) and clear bit 0 (unicast)
        mac_bytes = bytes([mac_bytes[0] & 0xFE | 0x02]) + mac_bytes[1:]
        return ":".join(f"{b:02x}" for b in mac_bytes)

    async def start_vm(self) -> str | None:
        """Start the Firecracker microVM."""
        logger.info(f"[{self.vm_name}] Starting VM...")

        # Check kernel exists
        if not Path(config.kernel_path).exists():
            logger.error(f"[{self.vm_name}] Kernel not found at {config.kernel_path}")
            raise FileNotFoundError(
                f"Kernel not found at {config.kernel_path}. "
                "Please download the Firecracker kernel."
            )

        logger.info(f"[{self.vm_name}] Using kernel: {config.kernel_path}")

        # Setup TAP interface (skip in vsock-only mode)
        vsock_only = os.environ.get("CLAWMAMA_VSOCK_ONLY", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if not vsock_only:
            tap_iface = self._get_network_iface()
            logger.info(f"[{self.vm_name}] Setting up TAP interface: {tap_iface}")
            await self._setup_network(tap_iface)
        else:
            logger.info(f"[{self.vm_name}] Skipping TAP setup (vsock-only mode)")

        # Check firecracker binary exists
        if not Path(config.firecracker_binary).exists():
            logger.error(
                f"[{self.vm_name}] Firecracker binary not found at {config.firecracker_binary}"
            )
            raise FileNotFoundError(
                f"Firecracker binary not found at {config.firecracker_binary}. "
                "Please install Firecracker."
            )

        # Start firecracker in background (use sudo for network access)
        cmd = [
            "sudo",
            config.firecracker_binary,
            "--api-sock",
            self.socket_path,
            "--config-file",
            str(self.vm_dir / "fc_config.json"),
        ]
        logger.info(f"[{self.vm_name}] Starting firecracker: {' '.join(cmd)}")

        # Ensure VM directory exists
        self._ensure_vm_dir()

        # Create subprocess with nohup to prevent signal handling
        subprocess.Popen(
            cmd,
            stdout=open(self.vm_dir / "firecracker.log", "w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        logger.info(
            f"[{self.vm_name}] Firecracker process started, waiting for boot..."
        )

        # Wait for VM to boot and get IP
        await asyncio.sleep(3)

        # Try to get IP via DHCP
        ip_address = await self._wait_for_dhcp()
        logger.info(f"[{self.vm_name}] VM started with IP: {ip_address}")

        return ip_address

    async def _setup_network(self, tap_iface: str):
        """Setup TAP interface - use pre-created pool, call network service if needed."""
        logger.info(f"[{tap_iface}] Setting up TAP interface...")

        # Check if TAP already exists
        result = subprocess.run(
            ["ip", "link", "show", tap_iface],
            capture_output=True,
        )

        if result.returncode != 0:
            # TAP doesn't exist, find any available TAP from whole system
            logger.warning(f"[{tap_iface}] Not found, searching for available TAP...")
            # Search for existing TAPs (created by network service)
            for i in range(250, 500):
                pool_tap = f"tap{i}"
                result = subprocess.run(
                    ["ip", "link", "show", pool_tap],
                    capture_output=True,
                )
                if result.returncode == 0:
                    tap_iface = pool_tap
                    logger.info(f"[{tap_iface}] Using available TAP")
                    break
            else:
                # No TAPs available, call network service
                logger.warning("No TAP devices available, calling network service...")
                try:
                    subprocess.run(
                        ["sudo", "systemctl", "start", "clawmama-network"],
                        check=True,
                        capture_output=True,
                    )
                    # Try again after network service
                    for i in range(250, 500):
                        pool_tap = f"tap{i}"
                        result = subprocess.run(
                            ["ip", "link", "show", pool_tap],
                            capture_output=True,
                        )
                        if result.returncode == 0:
                            tap_iface = pool_tap
                            logger.info(
                                f"[{tap_iface}] Using TAP after network service"
                            )
                            break
                    else:
                        logger.error("Network service ran but no TAP devices available")
                        return
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to start network service: {e.stderr}")
                    return

        # Set up TAP interface properly with sudo
        try:
            # Bring up the interface
            result = subprocess.run(
                ["sudo", "ip", "link", "set", tap_iface, "up"],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"[{tap_iface}] Set interface up")
        except subprocess.CalledProcessError as e:
            logger.error(f"[{tap_iface}] Failed to set interface up: {e.stderr}")
            return

        # Attach to bridge
        try:
            result = subprocess.run(
                ["sudo", "ip", "link", "set", tap_iface, "master", "br-clawmama"],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"[{tap_iface}] Attached to bridge br-clawmama")
        except subprocess.CalledProcessError as e:
            logger.error(f"[{tap_iface}] Failed to attach to bridge: {e.stderr}")
            return
            logger.info(f"[{tap_iface}] Added to bridge br-clawmama")
        except subprocess.CalledProcessError as e:
            logger.warning(f"[{tap_iface}] Failed to add to bridge: {e.stderr}")

    async def _wait_for_dhcp(self, timeout: int = 30) -> Optional[str]:
        """Wait for DHCP assignment."""
        logger.info(f"[{self.vm_name}] Waiting for DHCP assignment...")
        # In practice, we'd need to monitor the tap interface
        # For now, return a generated IP based on VM name
        ip = self._calculate_ip()
        logger.info(f"[{self.vm_name}] Assigned IP: {ip}")
        return ip

    def _calculate_ip(self) -> str:
        """Calculate IP based on VM name for consistency."""
        ip_int = hash(self.vm_name) % 254 + 2
        return f"172.30.0.{ip_int}"

    async def stop_vm(self) -> bool:
        """Stop the Firecracker microVM."""
        logger.info(f"[{self.vm_name}] Stopping VM...")

        try:
            connector = UnixConnector(path=self.socket_path)
            async with aiohttp.ClientSession(connector=connector) as session:
                # Send CtrlAltDel
                await session.put(
                    "http://localhost/-actions",
                    params={"action_type": "SendCtrlAltDel"},
                )
                logger.info(f"[{self.vm_name}] Sent CtrlAltDel")
        except Exception as e:
            logger.debug(
                f"[{self.vm_name}] Failed to send CtrlAltDel (VM may not be running): {e}"
            )

        # Kill the firecracker process
        try:
            subprocess.run(["pkill", "-f", f"firecracker.*{self.vm_name}"], check=True)
            logger.info(f"[{self.vm_name}] Killed firecracker process")
        except subprocess.CalledProcessError:
            logger.debug(f"[{self.vm_name}] No firecracker process found")

        # Clean up TAP interface
        tap_iface = self._get_network_iface()
        try:
            subprocess.run(
                ["ip", "link", "del", tap_iface], check=True, capture_output=True
            )
            logger.info(f"[{tap_iface}] Deleted TAP interface")
        except subprocess.CalledProcessError as e:
            logger.debug(f"[{tap_iface}] Failed to delete TAP interface: {e.stderr}")

        return True

    async def pause_vm(self) -> bool:
        """Pause the VM (freeze CPU)."""
        logger.info(f"[{self.vm_name}] Pausing VM...")
        connector = UnixConnector(path=self.socket_path)
        async with aiohttp.ClientSession(connector=connector) as session:
            await session.put("http://localhost/vm", params={"action_type": "Pause"})
        return True

    async def resume_vm(self) -> bool:
        """Resume the VM (unfreeze CPU)."""
        logger.info(f"[{self.vm_name}] Resuming VM...")
        connector = UnixConnector(path=self.socket_path)
        async with aiohttp.ClientSession(connector=connector) as session:
            await session.put("http://localhost/vm", params={"action_type": "Resume"})
        return True

    async def get_status(self) -> dict:
        """Get VM status."""
        try:
            connector = UnixConnector(path=self.socket_path)
            async with aiohttp.ClientSession(connector=connector) as session:
                resp = await session.get("http://localhost/vm")
                return await resp.json()
        except Exception:
            return {"state": "stopped"}

    async def get_instance_info(self) -> dict:
        """Get VM instance info."""
        try:
            connector = UnixConnector(path=self.socket_path)
            async with aiohttp.ClientSession(connector=connector) as session:
                resp = await session.get("http://localhost/instance-info")
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
        logger.info(f"[{self.vm_name}] Deleting VM...")
        await self.stop_vm()
        # Remove VM directory
        if self.vm_dir.exists():
            import shutil

            shutil.rmtree(self.vm_dir)
            logger.info(f"[{self.vm_name}] Removed VM directory: {self.vm_dir}")
