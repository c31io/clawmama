#!/bin/bash
# clawkid - VM Daemon for ClawMama

## Installation on VM

1. Copy clawkid.py to your Firecracker VM
2. Make it executable: `chmod +x clawkid.py`
3. Run at startup:

```bash
# Add to /etc/rc.local or systemd service
python3 /path/to/clawkid.py
```

## Usage

### On VM:
```bash
python3 clawkid.py
```

This will:
- Listen for commands from host on vsock port 5001
- Send heartbeat to host every 30 seconds on vsock port 5000

### On Host (clawmama):

```python
from clawmama.clawkid_host import ClawkidManager, ClawkidHostServer

# Start listening for VM
manager = ClawkidManager()
server = manager.register_vm("my-vm")

# Wait for heartbeat
time.sleep(5)
if server.is_alive():
    print(f"VM is alive! Hostname: {server.vm_hostname}")
    
    # Run command in VM
    result = server.send_command("uname -a")
    print(result)
    
    # Configure proxy
    server.configure_proxy(8888)
```

## Protocol

### Heartbeat (VM → Host)
- Port: 5000
- JSON: `{"type": "heartbeat", "hostname": "...", "uptime": float, "timestamp": float}`

### Command (Host → VM)
- Port: 5001
- Send: `{"command": "shell command"}`
- Receive: `{"type": "result", "command": "...", "returncode": 0, "stdout": "...", "stderr": "..."}`

## Proxy Setup

If TAP doesn't work (e.g., in nested virtualization):

1. Start proxy on host:
   ```bash
   # Using tinyproxy or ssh -D
   ssh -D 8888 user@localhost
   ```

2. Tell VM to use proxy:
   ```bash
   # In VM
   export http_proxy=http://172.30.0.1:8888
   export https_proxy=http://172.30.0.1:8888
   ```

Or use clawkid command:
```python
server.configure_proxy(8888)
```
