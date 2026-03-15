"""
Clawkid Host Server - runs on host, communicates with VM clawkid daemon.
Includes proxy support for VM internet via vsock.
"""

import socket
import json
import threading
import time
import subprocess
import os
from typing import Optional, Dict, Any

# Vsock constants
VMADDR_CID_ANY = socket.VMADDR_CID_ANY
VMADDR_CID_HOST = 2  # Host context ID
VMADDR_CID_LOCAL = 1  # Local (loopback)

HEARTBEAT_PORT = 5000
COMMAND_PORT = 5001
PROXY_PORT = 8888

class ProxyManager:
    """Manages proxy for VM internet access."""
    
    def __init__(self, port: int = PROXY_PORT):
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        
    def log(self, msg):
        print(f"[ProxyManager] {msg}")
        
    def start_ssh_proxy(self) -> bool:
        """Start SSH SOCKS proxy."""
        try:
            # Check if SSH key exists
            key_path = os.path.expanduser("~/.ssh/id_ed25519")
            if not os.path.exists(key_path):
                key_path = os.path.expanduser("~/.ssh/id_rsa")
            
            # Start SSH tunnel (SOCKS5 proxy)
            cmd = [
                "ssh", "-N", "-D", str(self.port), 
                "-o", "StrictHostKeyChecking=no",
                "-o", "ServerAliveInterval=60",
                "localhost"  # Proxy to localhost on host
            ]
            
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            time.sleep(2)
            
            if self.process.poll() is None:
                self.log(f"SSH SOCKS proxy started on port {self.port}")
                return True
            else:
                self.log("SSH proxy failed to start")
                return False
                
        except Exception as e:
            self.log(f"Failed to start SSH proxy: {e}")
            return False
    
    def start_python_proxy(self) -> bool:
        """Start simple Python HTTP proxy."""
        try:
            # Simple proxy using ssh -D is preferred
            # Fallback: use basic forwarding
            return self.start_ssh_proxy()
        except Exception as e:
            self.log(f"Proxy start failed: {e}")
            return False
    
    def stop(self):
        """Stop the proxy."""
        if self.process:
            self.process.terminate()
            self.process.wait()
            self.log("Proxy stopped")
            
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

class ClawkidHostServer:
    """Server that listens for clawkid heartbeats and commands."""
    
    def __init__(self, vm_name: str):
        self.vm_name = vm_name
        self.vm_cid: Optional[int] = None
        self.last_heartbeat: Optional[float] = None
        self.vm_hostname: Optional[str] = None
        self.vm_uptime: Optional[float] = None
        self.running = False
        self._heartbeat_thread: Optional[threading.Thread] = None
        
    def log(self, msg):
        print(f"[ClawkidHost:{self.vm_name}] {msg}")
        
    def start_heartbeat_listener(self, port: int = HEARTBEAT_PORT):
        """Start listening for VM heartbeats."""
        self.running = True
        
        def listener():
            try:
                sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((VMADDR_CID_ANY, port))
                sock.listen(5)
                self.log(f"Listening for heartbeats on port {port}")
                
                while self.running:
                    sock.settimeout(1)
                    try:
                        conn, addr = sock.accept()
                        data = conn.recv(1024)
                        if data:
                            heartbeat = json.loads(data.decode())
                            self.vm_cid = addr[0]
                            self.last_heartbeat = time.time()
                            self.vm_hostname = heartbeat.get('hostname')
                            self.vm_uptime = heartbeat.get('uptime')
                            self.log(f"Heartbeat: {self.vm_hostname} (uptime: {self.vm_uptime}s)")
                        conn.close()
                    except socket.timeout:
                        continue
                    except Exception as e:
                        if self.running:
                            self.log(f"Error: {e}")
            except Exception as e:
                self.log(f"Heartbeat listener failed: {e}")
        
        self._heartbeat_thread = threading.Thread(target=listener, daemon=True)
        self._heartbeat_thread.start()
        
    def stop(self):
        """Stop the server."""
        self.running = False
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
            
    def is_alive(self, timeout: int = 90) -> bool:
        """Check if VM is alive (heartbeat within timeout)."""
        if self.last_heartbeat is None:
            return False
        return (time.time() - self.last_heartbeat) < timeout
    
    def send_command(self, command: str, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """Send command to VM and get result."""
        if self.vm_cid is None:
            self.log("No VM CID - VM not connected")
            return None
            
        try:
            sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((self.vm_cid, COMMAND_PORT))
            
            cmd_data = {"command": command}
            sock.send(json.dumps(cmd_data).encode())
            
            response = sock.recv(65536)
            sock.close()
            
            return json.loads(response.decode())
        except Exception as e:
            self.log(f"Command failed: {e}")
            return None
    
    def configure_proxy(self, proxy_port: int = 8888) -> Optional[str]:
        """Tell VM to use host as proxy via vsock or bridge IP."""
        # Use bridge IP (host is gateway for VMs)
        # For vsock proxy, we'd need a proxy in the path - simpler to use IP
        proxy_cmd = f"export http_proxy=http://172.30.0.1:{proxy_port}; export https_proxy=http://172.30.0.1:{proxy_port}; echo 'Proxy configured: http://172.30.0.1:{proxy_port}'"
        return self.send_command(proxy_cmd)
    
    def configure_vsock_proxy(self, vsock_port: int = 5005) -> Optional[str]:
        """Tell VM to use host vsock port as SOCKS5 proxy."""
        # Connect to host via vsock CID 2
        proxy_cmd = f"export SOCKS5_PROXY=vsock://2:{vsock_port}; echo 'VSOCK proxy configured'"
        return self.send_command(proxy_cmd)


class ClawkidManager:
    """Manages clawkid connections for all VMs."""
    
    def __init__(self):
        self.servers: Dict[str, ClawkidHostServer] = {}
        
    def register_vm(self, vm_name: str) -> ClawkidHostServer:
        """Register a new VM and start listening."""
        if vm_name in self.servers:
            return self.servers[vm_name]
            
        server = ClawkidHostServer(vm_name)
        server.start_heartbeat_listener()
        self.servers[vm_name] = server
        return server
    
    def get_vm_status(self, vm_name: str) -> Optional[Dict[str, Any]]:
        """Get VM status."""
        if vm_name not in self.servers:
            return None
        server = self.servers[vm_name]
        return {
            "alive": server.is_alive(),
            "last_heartbeat": server.last_heartbeat,
            "hostname": server.vm_hostname,
            "uptime": server.vm_uptime
        }
    
    def unregister_vm(self, vm_name: str):
        """Remove VM."""
        if vm_name in self.servers:
            self.servers[vm_name].stop()
            del self.servers[vm_name]
