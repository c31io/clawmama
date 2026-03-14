#!/bin/bash
# ClawMama network setup script
# Run as: sudo ./setup-network.sh

set -e

BRIDGE_NAME="br-clawmama"
BRIDGE_IP="172.30.0.1"
VM_NETWORK="172.30.0.0/30"

echo "Setting up ClawMama network..."

# Create bridge if not exists
if ! ip link show "$BRIDGE_NAME" > /dev/null 2>&1; then
    echo "Creating bridge $BRIDGE_NAME..."
    ip link add name "$BRIDGE_NAME" type bridge
    ip addr add "${BRIDGE_IP}/30" dev "$BRIDGE_NAME"
    ip link set "$BRIDGE_NAME" up
fi

# Enable IP forwarding
echo "Enabling IP forwarding..."
echo 1 > /proc/sys/net/ipv4/ip_forward

# Setup NAT
echo "Setting up NAT..."
iptables -t nat -C POSTROUTING -s "$VM_NETWORK" ! -d "$VM_NETWORK" -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -s "$VM_NETWORK" ! -d "$VM_NETWORK" -j MASQUERADE

# Allow forwarding
iptables -C FORWARD -i "$BRIDGE_NAME" -j ACCEPT 2>/dev/null || \
    iptables -A FORWARD -i "$BRIDGE_NAME" -j ACCEPT

# Block inbound to VMs (security)
if [ "$BLOCK_INBOUND" = "true" ]; then
    iptables -C INPUT -i "$BRIDGE_NAME" -j DROP 2>/dev/null || \
        iptables -A INPUT -i "$BRIDGE_NAME" -j DROP
fi

echo "Network setup complete!"
echo "Bridge: $BRIDGE_NAME ($BRIDGE_IP)"
echo "VM network: $VM_NETWORK"
