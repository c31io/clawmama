#!/bin/bash
# ClawMama network setup script
# Run as: sudo ./setup-network.sh

set -e

BRIDGE_NAME="br-clawmama"
BRIDGE_IP="172.30.0.1"
VM_NETWORK="172.30.0.0/30"
TAP_RANGE_START=250
TAP_RANGE_END=254

echo "Setting up ClawMama network..."

# Create bridge if not exists
if ! ip link show "$BRIDGE_NAME" > /dev/null 2>&1; then
    echo "Creating bridge $BRIDGE_NAME..."
    ip link add name "$BRIDGE_NAME" type bridge
    ip addr add "${BRIDGE_IP}/30" dev "$BRIDGE_NAME"
fi

# Create TAP devices pool (for VMs to use)
echo "Creating TAP device pool..."
for i in $(seq $TAP_RANGE_START $TAP_RANGE_END); do
    TAP_NAME="tap$i"
    if ! ip link show "$TAP_NAME" > /dev/null 2>&1; then
        ip tuntap add "$TAP_NAME" mode tap 2>/dev/null || true
    fi
    # Bring up and add to bridge
    ip link set "$TAP_NAME" up 2>/dev/null || true
    ip link set "$TAP_NAME" master "$BRIDGE_NAME" 2>/dev/null || true
done

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

# Bring up bridge
ip link set "$BRIDGE_NAME" up

echo "Network setup complete!"
echo "Bridge: $BRIDGE_NAME ($BRIDGE_IP)"
echo "VM network: $VM_NETWORK"
echo "TAP pool: tap$TAP_RANGE_START-tap$TAP_RANGE_END"
