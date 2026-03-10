"""VM Provisioner - sets up Ubuntu with OpenClaw."""

import logging
import os
import subprocess
import requests
from pathlib import Path

from clawmama.config import config

logger = logging.getLogger("clawmama.provisioner")


class VMProvisioner:
    """Provisions Ubuntu VMs with OpenClaw."""

    # Ubuntu cloud image URL (Focal Fossa)
    UBUNTU_IMAGE_URL = (
        "https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img"
    )

    # Firecracker kernel URL
    FIRECRACKER_KERNEL_URL = (
        "https://s3.amazonaws.com/firecracker-artifacts-core/vmlinux/vmlinux-5.10.204"
    )

    def __init__(self):
        self.vm_dir = Path(config.vm_dir)
        self.image_dir = Path(config.data_dir)

    def _ensure_dirs(self):
        """Ensure required directories exist."""
        self.vm_dir.mkdir(parents=True, exist_ok=True)
        self.image_dir.mkdir(parents=True, exist_ok=True)

    async def download_kernel(self) -> str:
        """Download Firecracker kernel if not present."""
        kernel_path = Path(config.kernel_path)
        if kernel_path.exists():
            return str(kernel_path)

        self._ensure_dirs()
        logger.info(f"Downloading Firecracker kernel to {kernel_path}...")

        response = requests.get(self.FIRECRACKER_KERNEL_URL, stream=True)
        response.raise_for_status()
        with open(kernel_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        os.chmod(kernel_path, 0o755)

        return str(kernel_path)

    async def download_base_image(self) -> str:
        """Download Ubuntu cloud image if not present."""
        image_path = Path(config.image_path)
        if image_path.exists():
            return str(image_path)

        self._ensure_dirs()
        logger.info(f"Downloading Ubuntu base image to {image_path}...")

        response = requests.get(self.UBUNTU_IMAGE_URL, stream=True)
        response.raise_for_status()
        with open(image_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return str(image_path)

    async def setup_networking(self) -> bool:
        """Setup host networking for VMs (requires root)."""
        # Create bridge for VMs
        try:
            subprocess.run(
                ["ip", "link", "add", "br-clawmama", "type", "bridge"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass  # Bridge might already exist

        # Setup NAT
        try:
            # Enable IP forwarding
            with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
                f.write("1")

            # Add NAT rule
            subprocess.run(
                [
                    "iptables",
                    "-t",
                    "nat",
                    "-A",
                    "POSTROUTING",
                    "-s",
                    "172.30.0.0/30",
                    "!",
                    "-d",
                    "172.30.0.0/30",
                    "-j",
                    "MASQUERADE",
                ],
                check=True,
                capture_output=True,
            )

            # Allow forwarding from bridge
            subprocess.run(
                ["iptables", "-A", "FORWARD", "-i", "br-clawmama", "-j", "ACCEPT"],
                check=True,
                capture_output=True,
            )

            # Block inbound to VMs (security)
            if config.block_inbound:
                subprocess.run(
                    ["iptables", "-A", "INPUT", "-i", "br-clawmama", "-j", "DROP"],
                    check=True,
                    capture_output=True,
                )

            return True

        except Exception as e:
            logger.warning(f"Networking setup failed (may require root): {e}")
            return False

    async def prepare(self):
        """Prepare the host for running VMs."""
        self._ensure_dirs()
        await self.download_kernel()
        await self.setup_networking()
