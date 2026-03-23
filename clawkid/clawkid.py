#!/usr/bin/env python3
"""
clawkid - ClawMama Kid VM Daemon
Runs inside Firecracker VMs, communicates with host via vsock.

Features:
- Heartbeat: Periodic "I'm alive" messages to host
- Command execution: Receive and run commands from host
"""

import socket
import time
import json
import os
import sys
import subprocess
import signal

# Configuration
VM_CID = 3  # Host Context ID for vsock
HEARTBEAT_PORT = 5000
COMMAND_PORT = 5001
HEARTBEAT_INTERVAL = 30  # seconds


class Clawkid:
    def __init__(self):
        self.running = True
        self.last_heartbeat = time.time()

    def log(self, msg):
        print(f"[clawkid] {msg}", flush=True)

    def send_heartbeat(self):
        """Send heartbeat to host via vsock."""
        try:
            # Connect to host vsock port
            sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((VM_CID, HEARTBEAT_PORT))

            heartbeat_data = {
                "type": "heartbeat",
                "hostname": socket.gethostname(),
                "uptime": self.get_uptime(),
                "timestamp": time.time(),
            }

            sock.send(json.dumps(heartbeat_data).encode())
            sock.close()
            self.log(f"Heartbeat sent: {heartbeat_data['hostname']}")
            self.last_heartbeat = time.time()
            return True
        except Exception as e:
            self.log(f"Heartbeat failed: {e}")
            return False

    def get_uptime(self):
        """Get system uptime in seconds."""
        try:
            with open("/proc/uptime", "r") as f:
                return float(f.readline().split()[0])
        except:
            return 0

    def handle_command(self, cmd_data):
        """Execute command from host."""
        try:
            cmd = cmd_data.get("command", "")
            self.log(f"Executing: {cmd}")

            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60
            )

            response = {
                "type": "result",
                "command": cmd,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            return response
        except subprocess.TimeoutExpired:
            return {"type": "result", "command": cmd, "error": "Timeout"}
        except Exception as e:
            return {"type": "result", "command": cmd, "error": str(e)}

    def run_command_server(self):
        """Listen for commands from host."""
        try:
            sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((socket.VMADDR_CID_ANY, COMMAND_PORT))
            sock.listen(1)
            self.log(f"Command server listening on port {COMMAND_PORT}")

            while self.running:
                sock.settimeout(5)
                try:
                    conn, addr = sock.accept()
                    data = conn.recv(4096)
                    if data:
                        cmd_data = json.loads(data.decode())
                        response = self.handle_command(cmd_data)
                        conn.send(json.dumps(response).encode())
                    conn.close()
                except socket.timeout:
                    continue
                except Exception as e:
                    self.log(f"Command server error: {e}")
        except Exception as e:
            self.log(f"Command server failed: {e}")

    def signal_handler(self, signum, frame):
        self.log("Received signal, shutting down...")
        self.running = False
        sys.exit(0)

    def run(self):
        """Main loop."""
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

        self.log("clawkid starting...")
        self.log(f"Heartbeat interval: {HEARTBEAT_INTERVAL}s")
        self.log(f"Host CID: {VM_CID}")

        # Send initial heartbeat
        self.send_heartbeat()

        # Main loop
        while self.running:
            time.sleep(HEARTBEAT_INTERVAL)
            if self.running:
                self.send_heartbeat()


if __name__ == "__main__":
    clawkid = Clawkid()
    clawkid.run()
