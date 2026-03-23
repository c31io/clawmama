"""VM management module."""

from clawmama.vm.database import VMDatabase
from clawmama.vm.firecracker import FirecrackerManager
from clawmama.vm.interface import VMManager
from clawmama.vm.provisioner import VMProvisioner
from clawmama.vm.backup import BackupManager

try:
    from clawmama.vm.hyperv import HyperVManager

    __all__ = [
        "VMDatabase",
        "VMManager",
        "FirecrackerManager",
        "HyperVManager",
        "VMProvisioner",
        "BackupManager",
    ]
except ImportError:
    # pywinrm not available
    __all__ = [
        "VMDatabase",
        "VMManager",
        "FirecrackerManager",
        "VMProvisioner",
        "BackupManager",
    ]
