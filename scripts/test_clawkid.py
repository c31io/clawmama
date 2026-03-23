#!/usr/bin/env python3
"""Test clawkid components."""

from clawmama.clawkid_host import ClawkidHostServer, ClawkidManager, ProxyManager


def test_imports():
    print("Testing imports...")
    from clawmama.clawkid_host import ClawkidHostServer, ClawkidManager, ProxyManager

    print("✓ Imports OK")


def test_clawkid_manager():
    print("Testing ClawkidManager...")
    manager = ClawkidManager()
    server = manager.register_vm("test-vm")
    print(f"✓ Registered VM, CID: {server.vm_cid}")
    print(f"✓ is_alive: {server.is_alive()}")
    manager.unregister_vm("test-vm")
    print("✓ Unregistered VM")


def test_proxy_manager():
    print("Testing ProxyManager...")
    pm = ProxyManager(port=8888)
    print(f"✓ ProxyManager created (port {pm.port})")
    # Don't start actual proxy in test


if __name__ == "__main__":
    test_imports()
    test_clawkid_manager()
    test_proxy_manager()
    print("\n✅ All tests passed!")
