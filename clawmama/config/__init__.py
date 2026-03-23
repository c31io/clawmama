"""Configuration module for ClawMama."""

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _expand_path(path: str) -> Path:
    """Expand ~ and environment variables in path."""
    return Path(os.path.expanduser(os.path.expandvars(path)))


class Config:
    """Application configuration."""

    _instance = None
    _config: dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        """Load configuration following XDG conventions.

        Search order:
        1. $XDG_CONFIG_HOME/clawmama/config.yaml
        2. ./config.yaml (local development)
        """
        # XDG_CONFIG_HOME defaults to ~/.config
        xdg_config = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        xdg_config_path = Path(xdg_config) / "clawmama" / "config.yaml"

        config_paths = [
            xdg_config_path,
            Path(__file__).parent.parent.parent / "config.yaml",
        ]

        for config_path in config_paths:
            if config_path.exists():
                with open(config_path, "r") as f:
                    self._config = yaml.safe_load(f) or {}
                logger.info("Using config file: %s", config_path)
                return

        logger.warning("No config file found, using defaults")
        self._config = {}

    @property
    def bot_token(self) -> str:
        """Get Telegram bot token."""
        return os.environ.get(
            "TELEGRAM_BOT_TOKEN", self._config.get("bot", {}).get("token", "")
        )

    @property
    def bot_user_id(self) -> int | None:
        """Get authorized Telegram user ID."""
        user_id = os.environ.get("TELEGRAM_BOT_USER_ID") or self._config.get(
            "bot", {}
        ).get("user_id")
        if user_id is None:
            return None
        try:
            return int(user_id)
        except (ValueError, TypeError):
            return None

    @property
    def firecracker_binary(self) -> str:
        """Get firecracker binary path."""
        return str(
            _expand_path(
                self._config.get("firecracker", {}).get(
                    "binary_path", "~/.local/bin/firecracker"
                )
            )
        )

    def _get_vm_path(self, key: str, default: str) -> str:
        """Get a path from vm section."""
        vm_config = self._config.get("vm", {})
        if key in vm_config:
            return str(_expand_path(vm_config[key]))
        return str(_expand_path(default))

    @property
    def kernel_path(self) -> str:
        """Get kernel path."""
        return self._get_vm_path("kernel_path", "~/.local/share/clawmama/vmlinux")

    @property
    def image_path(self) -> str:
        """Get base image path."""
        return self._get_vm_path(
            "image_path", "~/.local/share/clawmama/ubuntu-base.img"
        )

    @property
    def vm_dir(self) -> str:
        """Get VM working directory."""
        return self._get_vm_path("vm_dir", "~/.local/share/clawmama/vms")

    @property
    def data_dir(self) -> str:
        """Get data directory for database and images."""
        return self._get_vm_path("data_dir", "~/.local/share/clawmama")

    def _get_vm_default(self, key: str, default: int) -> int:
        """Get a default resource value from vm section."""
        vm_defaults = self._config.get("vm", {}).get("default", {})
        if key in vm_defaults:
            return vm_defaults[key]
        return default

    @property
    def default_vcpus(self) -> int:
        """Get default vCPU count."""
        return self._get_vm_default("vcpus", 2)

    @property
    def default_memory_mib(self) -> int:
        """Get default memory in MiB."""
        return self._get_vm_default("memory_mib", 2048)

    @property
    def default_disk_gb(self) -> int:
        """Get default disk size in GB."""
        return self._get_vm_default("disk_size_gb", 10)

    @property
    def host_ip(self) -> str:
        """Get host IP for VM network."""
        return self._config.get("network", {}).get("host_ip", "172.30.0.1")

    @property
    def vm_ip_start(self) -> str:
        """Get starting IP for VMs."""
        return self._config.get("network", {}).get("vm_ip_start", "172.30.0.2")

    @property
    def network_cidr(self) -> str:
        """Get network CIDR."""
        return self._config.get("network", {}).get("cidr", "172.30.0.0/30")

    @property
    def isolate_network(self) -> bool:
        """Get network isolation setting."""
        return self._config.get("security", {}).get("isolate_network", True)

    @property
    def block_inbound(self) -> bool:
        """Get block inbound setting."""
        return self._config.get("security", {}).get("block_inbound", True)

    @property
    def max_vcpus(self) -> int:
        """Get maximum vCPUs per VM."""
        return self._config.get("security", {}).get("max_vcpus", 4)

    @property
    def max_memory_mib(self) -> int:
        """Get maximum memory per VM in MiB."""
        return self._config.get("security", {}).get("max_memory_mib", 4096)

    @property
    def max_disk_gb(self) -> int:
        """Get maximum disk size per VM in GB."""
        return self._config.get("security", {}).get("max_disk_gb", 20)

    @property
    def backup_dir(self) -> str:
        """Get backup directory."""
        return str(
            _expand_path(
                self._config.get("backup", {}).get(
                    "dir", "~/.local/share/clawmama/backups"
                )
            )
        )

    @property
    def backup_compression(self) -> int:
        """Get backup compression level (zstd 1-22)."""
        return self._config.get("backup", {}).get("compression", 3)

    @property
    def log_dir(self) -> Path:
        """Get log directory path."""
        return _expand_path(
            self._config.get("log", {}).get("dir", "~/.local/share/clawmama/logs")
        )

    @property
    def log_level(self) -> str:
        """Get log level."""
        return self._config.get("log", {}).get("level", "info")


config = Config()
