"""VM Provisioner - sets up Ubuntu with OpenClaw."""
import asyncio
import os
import subprocess
import urllib.request
from pathlib import Path

from clawmama.config import config


class VMProvisioner:
    """Provisions Ubuntu VMs with OpenClaw."""

    # Ubuntu cloud image URL (Focal Fossa)
    UBUNTU_IMAGE_URL = (
        "https://cloud-images.ubuntu.com/focal/current/"
        "focal-server-cloudimg-amd64.img"
    )

    # Firecracker kernel URL
    FIRECRACKER_KERNEL_URL = (
        "https://s3.amazonaws.com/firecracker-artifacts-core/"
        "vmlinux/vmlinux-5.10.204"
    )

    def __init__(self):
        self.vm_dir = Path(config.vm_dir)
        self.image_dir = Path("/var/lib/clawmama")

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
        print(f"Downloading Firecracker kernel to {kernel_path}...")

        # Download with progress
        urllib.request.urlretrieve(
            self.FIRECRACKER_KERNEL_URL,
            kernel_path
        )
        os.chmod(kernel_path, 0o755)

        return str(kernel_path)

    async def download_base_image(self) -> str:
        """Download Ubuntu cloud image if not present."""
        image_path = Path(config.image_path)
        if image_path.exists():
            return str(image_path)

        self._ensure_dirs()
        print(f"Downloading Ubuntu base image to {image_path}...")

        # Download Ubuntu cloud image
        urllib.request.urlretrieve(
            self.UBUNTU_IMAGE_URL,
            image_path
        )

        return str(image_path)

    async def prepare_vm_disk(
        self,
        vm_name: str,
        disk_gb: int,
        with_openclaw: bool = True,
    ) -> str:
        """Prepare VM disk with Ubuntu and optionally OpenClaw."""
        vm_dir = self.vm_dir / vm_name
        vm_dir.mkdir(parents=True, exist_ok=True)

        # Copy base image to VM directory
        disk_path = vm_dir / "root.img"

        if not disk_path.exists():
            base_image = await self.download_base_image()
            # Copy and resize
            subprocess.run(
                ["cp", base_image, disk_path],
                check=True
            )
            # Resize disk
            subprocess.run(
                ["truncate", "-s", f"{disk_gb}G", str(disk_path)],
                check=True
            )
            subprocess.run(
                ["resize2fs", str(disk_path)],
                check=True
            )

        # Mount and configure
        if with_openclaw:
            await self._install_openclaw(disk_path, vm_name)

        return str(disk_path)

    async def _install_openclaw(
        self,
        disk_path: str,
        vm_name: str,
    ):
        """Install OpenClaw in the VM disk."""
        # This would need to be done via guestfish or similar
        # For now, we'll set up cloud-init to install it on first boot
        print(f"Setting up OpenClaw installation for {vm_name}")

        # Create cloud-init user-data
        cloud_init_dir = Path(disk_path).parent / "cloud-init"
        cloud_init_dir.mkdir(exist_ok=True)

        user_data = """#cloud-config
autoinstall:
  version: 1
  locale: en_US
  keyboard:
    layout: us
  identity:
    hostname: {hostname}
    password: "$6$rounds=4096$xyz$hashedpassword"  # Change this!
    username: ubuntu
  ssh:
    install-server: true
    allow-pw: true
  storage:
    layout:
      name: lvm
  packages:
    - openssh-server
    - curl
    - wget
    - git
runcmd:
  - curl -sL https://claude.com/Claude.sh | sh
  - systemctl enable ssh
""".format(hostname=vm_name)

        (cloud_init_dir / "user-data").write_text(user_data)

    async def setup_networking(self) -> bool:
        """Setup host networking for VMs."""
        # Create bridge for VMs
        try:
            subprocess.run(
                ["ip", "link", "add", "br-clawmama", "type", "bridge"],
                check=True,
                capture_output=True
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
                    "iptables", "-t", "nat", "-A", "POSTROUTING",
                    "-s", "172.30.0.0/30", "!", "-d", "172.30.0.0/30",
                    "-j", "MASQUERADE"
                ],
                check=True,
                capture_output=True
            )

            # Allow forwarding from bridge
            subprocess.run(
                [
                    "iptables", "-A", "FORWARD", "-i", "br-clawmama",
                    "-j", "ACCEPT"
                ],
                check=True,
                capture_output=True
            )

            # Block inbound to VMs (security)
            if config.block_inbound:
                subprocess.run(
                    [
                        "iptables", "-A", "INPUT", "-i", "br-clawmama",
                        "-j", "DROP"
                    ],
                    check=True,
                    capture_output=True
                )

            return True

        except subprocess.CalledProcessError as e:
            print(f"Failed to setup networking: {e}")
            return False

    async def prepare(self):
        """Prepare the host for running VMs."""
        self._ensure_dirs()
        await self.download_kernel()
        await self.setup_networking()
