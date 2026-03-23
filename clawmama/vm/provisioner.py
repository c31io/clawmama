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

    # Firecracker release API
    FIRECRACKER_RELEASE_API = (
        "https://api.github.com/repos/firecracker-microvm/firecracker/releases/latest"
    )

    # vmlinux from S3 (Firecracker official examples)
    VMLINUX_URL = (
        "https://s3.amazonaws.com/spec.ccfc.min/img/hello/kernel/hello-vmlinux.bin"
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
        # Ensure kernel parent dir exists
        logger.info(f"Creating kernel dir: {kernel_path.parent}")
        kernel_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Downloading Firecracker kernel to {kernel_path}...")

        # Download vmlinux from S3
        response = requests.get(self.VMLINUX_URL, stream=True)
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
        # Ensure image parent dir exists
        image_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Downloading Ubuntu base image to {image_path}...")

        response = requests.get(self.UBUNTU_IMAGE_URL, stream=True)
        response.raise_for_status()
        with open(image_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return str(image_path)

    async def setup_networking(self) -> bool:
        """Setup host networking for VMs (requires root via systemd service)."""
        import os

        # Check if bridge already exists
        result = subprocess.run(
            ["ip", "link", "show", "br-clawmama"],
            capture_output=True,
        )
        if result.returncode == 0:
            logger.info("Bridge br-clawmama already exists, skipping network setup")
            return True

        # Try to run network setup script via sudo
        script_path = (
            Path(__file__).parent.parent.parent / "scripts" / "setup-network.sh"
        )

        if script_path.exists():
            logger.info("Running network setup script via sudo...")
            try:
                result = subprocess.run(
                    ["sudo", str(script_path)],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    logger.info("Network setup complete")
                    return True
                else:
                    logger.error(f"Network setup failed: {result.stderr}")
                    return False
            except Exception as e:
                logger.error(f"Failed to run network setup: {e}")
                return False

        logger.warning("Network setup script not found, skipping")
        return False

    async def prepare(self):
        """Prepare the host for running VMs."""
        self._ensure_dirs()
        await self.download_kernel()
        await self.setup_networking()
