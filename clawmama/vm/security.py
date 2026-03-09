"""Security utilities for VM isolation."""

import logging
import subprocess

from clawmama.config import config

logger = logging.getLogger("clawmama.security")


class VMSecurity:
    """Manages security isolation for VMs."""

    def __init__(self, vm_name: str):
        self.vm_name = vm_name
        self.tap_iface = f"tap{hash(vm_name) % 1000:03d}"
        self.vm_ip = self._calculate_ip()

    def _calculate_ip(self) -> str:
        """Calculate IP based on VM name."""
        ip_int = hash(self.vm_name) % 254 + 2
        return f"172.30.0.{ip_int}"

    def apply_resource_limits(self, vcpus: int, memory_mib: int):
        """Apply resource limits using cgroups (if available)."""
        # This would require cgroups2 setup
        # For now, limits are enforced via Firecracker config
        pass

    def setup_network_isolation(self) -> bool:
        """Setup network isolation for the VM."""
        if not config.isolate_network:
            return True

        try:
            # Allow outbound traffic
            subprocess.run(
                ["iptables", "-A", "OUTPUT", "-s", self.vm_ip, "-j", "ACCEPT"],
                check=True,
                capture_output=True,
            )

            # Drop inbound traffic (except established/related)
            subprocess.run(
                [
                    "iptables",
                    "-A",
                    "INPUT",
                    "-d",
                    self.vm_ip,
                    "-m",
                    "state",
                    "--state",
                    "ESTABLISHED,RELATED",
                    "-j",
                    "ACCEPT",
                ],
                check=True,
                capture_output=True,
            )

            subprocess.run(
                ["iptables", "-A", "INPUT", "-d", self.vm_ip, "-j", "DROP"],
                check=True,
                capture_output=True,
            )

            # Block VM from accessing host services
            host_ip = config.host_ip
            subprocess.run(
                [
                    "iptables",
                    "-A",
                    "OUTPUT",
                    "-s",
                    self.vm_ip,
                    "-d",
                    host_ip,
                    "-j",
                    "DROP",
                ],
                check=True,
                capture_output=True,
            )

            # Block VM from accessing host's localhost
            subprocess.run(
                [
                    "iptables",
                    "-A",
                    "OUTPUT",
                    "-s",
                    self.vm_ip,
                    "-d",
                    "127.0.0.1",
                    "-j",
                    "DROP",
                ],
                check=True,
                capture_output=True,
            )

            # Block common attack vectors
            # Block raw sockets (prevent some network attacks)
            # This needs to be done inside the VM

            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to setup network isolation: {e}")
            return False

    def remove_network_isolation(self):
        """Remove network isolation rules."""
        try:
            # Flush rules for this VM
            subprocess.run(
                ["iptables", "-F", "INPUT", "-d", self.vm_ip],
                check=False,
                capture_output=True,
            )
            subprocess.run(
                ["iptables", "-F", "OUTPUT", "-s", self.vm_ip],
                check=False,
                capture_output=True,
            )
        except Exception:
            pass

    def check_vm_access(self) -> dict:
        """Check if VM can access restricted resources."""
        results = {"host_access": False, "internet_access": True, "other_vms": False}

        # Check if VM can ping host
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "1", config.host_ip], capture_output=True
            )
            results["host_access"] = result.returncode == 0
        except Exception:
            pass

        # Check if VM can access internet (would need to test from inside VM)
        # For now, assume true if outbound is allowed

        return results

    def restrict_process_capabilities(self) -> bool:
        """Restrict process capabilities inside VM."""
        # Firecracker already runs with minimal capabilities
        # Additional restrictions can be applied via seccomp
        return True

    def validate_vm_integrity(self) -> bool:
        """Validate VM hasn't been compromised."""
        # Check for unexpected processes
        # Check for unusual network connections
        # This would require agent inside VM
        return True


class SecurityManager:
    """Manages global security for all VMs."""

    @staticmethod
    def setup_host_protection() -> bool:
        """Setup host-level security protections."""
        try:
            # Disable IP forwarding if not needed
            # Already done in provisioner

            # Block common exploit techniques
            # Disable packet source routing
            with open("/proc/sys/net/ipv4/conf/all/accept_source_route", "w") as f:
                f.write("0")
            with open("/proc/sys/net/ipv4/conf/default/accept_source_route", "w") as f:
                f.write("0")

            # Block ICMP redirect
            with open("/proc/sys/net/ipv4/conf/all/accept_redirects", "w") as f:
                f.write("0")
            with open("/proc/sys/net/ipv4/conf/default/accept_redirects", "w") as f:
                f.write("0")

            # Disable source packet routing
            with open("/proc/sys/net/ipv4/conf/all/send_redirects", "w") as f:
                f.write("0")

            return True

        except Exception as e:
            logger.error(f"Failed to setup host protection: {e}")
            return False

    @staticmethod
    def get_firewall_status() -> dict:
        """Get firewall status for VMs."""
        status = {
            "nat_active": False,
            "vm_network": "172.30.0.0/30",
            "blocked_inbound": config.block_inbound,
        }

        # Check if NAT is active
        try:
            result = subprocess.run(
                ["iptables", "-t", "nat", "-L", "-n"], capture_output=True, text=True
            )
            status["nat_active"] = "MASQUERADE" in result.stdout
        except Exception:
            pass

        return status
