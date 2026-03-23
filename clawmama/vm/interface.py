"""VM manager interface."""

from abc import ABC, abstractmethod
from typing import Optional


class VMManager(ABC):
    """Abstract base class for VM managers."""

    @abstractmethod
    async def create_vm(
        self,
        vcpus: int | None = None,
        memory_mib: int | None = None,
        disk_gb: int | None = None,
    ) -> dict:
        """Create a new VM."""
        pass

    @abstractmethod
    async def start_vm(self) -> str | None:
        """Start the VM. Returns IP address."""
        pass

    @abstractmethod
    async def stop_vm(self) -> bool:
        """Stop the VM."""
        pass

    @abstractmethod
    async def pause_vm(self) -> bool:
        """Pause the VM."""
        pass

    @abstractmethod
    async def resume_vm(self) -> bool:
        """Resume the VM."""
        pass

    @abstractmethod
    async def get_status(self) -> dict:
        """Get VM status."""
        pass

    @abstractmethod
    async def get_instance_info(self) -> dict:
        """Get VM instance info."""
        pass

    @abstractmethod
    async def delete_vm(self):
        """Delete the VM and all its resources."""
        pass

    def cleanup(self):
        """Clean up resources."""
        pass
