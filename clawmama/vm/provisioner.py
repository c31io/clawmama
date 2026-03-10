"""VM Provisioner - sets up Ubuntu with OpenClaw."""

import logging
import os
import subprocess
import requests
from pathlib import Path

from clawmama.config import config

logger = logging.getLogger("clawmama.provisioner")


# Fix SOCKS proxy scheme for requests (socks:// -> socks5://)
for var in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
    proxy = os.environ.get(var, "")
    if proxy.startswith("socks://"):
        logger.warning(
            f"Converting {var} from socks:// to socks5:// (requests supports SOCKS5 only)"
        )
        os.environ[var] = proxy.replace("socks://", "socks5://", 1)


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

        # Get latest release info
        response = requests.get(self.FIRECRACKER_RELEASE_API)
        response.raise_for_status()
        release = response.json()

        # Find x86_64 release asset
        tarball_url = None
        for asset in release.get("assets", []):
            if asset["name"].endswith("-x86_64.tgz"):
                tarball_url = asset["browser_download_url"]
                break

        if not tarball_url:
            raise RuntimeError("Could not find Firecracker release tarball")

        # Download and extract
        import tarfile
        import io

        logger.info(f"Downloading Firecracker release from {tarball_url}...")
        response = requests.get(tarball_url, stream=True)
        response.raise_for_status()

        # Extract vmlinux from tarball
        with tarfile.open(fileobj=io.BytesIO(response.content)) as tar:
            for member in tar.getmembers():
                if member.name.endswith("/vmlinux"):
                    logger.info("Extracting vmlinux...")
                    kernel_file = tar.extractfile(member)
                    if kernel_file:
                        with open(kernel_path, "wb") as f:
                            f.write(kernel_file.read())
                    break

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
