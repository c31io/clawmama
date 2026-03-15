#!/usr/bin/env python3
"""
VSOCK Proxy - provides internet access to VMs via vsock

VM connects to this proxy via vsock CID 2 (host), and this proxy
forwards traffic to the internet.

Usage:
    python3 vsock_proxy.py
    
Then in VM:
    export http_proxy=http://<vsock-host-ip>:8888
    # Or use SOCKS5 if we implement it
"""

import socket
import threading
import selectors
import sys

# VSOCK constants
VMADDR_CID_ANY = socket.VMADDR_CID_ANY
LISTEN_PORT = 8888
VSOCK_LISTEN_PORT = 5005

class VSOCKProxy:
    """Proxy that accepts connections via vsock and forwards to internet."""
    
    def __init__(self, listen_port=LISTEN_PORT, vsock_port=VSOCK_LISTEN_PORT):
        self.listen_port = listen_port
        self.vsock_port = vsock_port
        self.selector = selectors.DefaultSelector()
        self.running = False
        
    def log(self, msg):
        print(f"[VSOCKProxy] {msg}")
        
    def handle_vsock_client(self, client_sock, addr):
        """Handle a vsock client connection."""
        try:
            self.log(f"Client connected from CID {addr}")
            
            # Connect to destination (forwards to internet)
            # For simplicity, we'll just echo for now
            # Real implementation would forward HTTP/SOCKS requests
            
            data = client_sock.recv(4096)
            self.log(f"Received: {data[:100]}")
            
            # Echo back for testing
            client_sock.send(b"VSOCK Proxy OK\r\n")
            
        except Exception as e:
            self.log(f"Error: {e}")
        finally:
            client_sock.close()
    
    def start_vsock_listener(self):
        """Listen for vsock connections."""
        try:
            sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((VMADDR_CID_ANY, self.vsock_port))
            sock.listen(5)
            self.log(f"Listening on vsock port {self.vsock_port}")
            
            while self.running:
                sock.settimeout(1)
                try:
                    client, addr = sock.accept()
                    thread = threading.Thread(
                        target=self.handle_vsock_client,
                        args=(client, addr),
                        daemon=True
                    )
                    thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.log(f"Accept error: {e}")
        except Exception as e:
            self.log(f"VSOCK listen failed: {e}")
    
    def start_tcp_listener(self):
        """Listen for TCP connections (fallback if vsock doesn't work)."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', self.listen_port))
            sock.listen(5)
            self.log(f"Listening on TCP port {self.listen_port}")
            
            while self.running:
                sock.settimeout(1)
                try:
                    client, addr = sock.accept()
                    self.log(f"TCP client: {addr}")
                    # Forward to internet
                    self.handle_tcp_client(client, addr)
                except socket.timeout:
                    continue
        except Exception as e:
            self.log(f"TCP listen failed: {e}")
    
    def handle_tcp_client(self, client_sock, addr):
        """Handle TCP client - simple HTTP proxy."""
        try:
            # Read HTTP request
            request = b""
            while b"\r\n\r\n" not in request:
                data = client_sock.recv(4096)
                if not data:
                    return
                request += data
            
            # Parse Host header
            host, port = "80", 80
            for line in request.decode().split('\r\n'):
                if line.lower().startswith('host:'):
                    host_port = line.split(':')[1].strip()
                    if ':' in host_port:
                        host, port = host_port.split(':')
                    else:
                        host = host_port
                    break
            
            # Connect to target
            target = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            target.connect((host, int(port)))
            target.send(request)
            
            # Forward response
            while True:
                data = target.recv(4096)
                if not data:
                    break
                client_sock.send(data)
                
        except Exception as e:
            self.log(f"Proxy error: {e}")
        finally:
            client_sock.close()
    
    def run(self):
        """Start the proxy."""
        self.running = True
        
        # Start vsock listener
        vsock_thread = threading.Thread(target=self.start_vsock_listener, daemon=True)
        vsock_thread.start()
        
        # Start TCP listener (for VM to connect via IP)
        tcp_thread = threading.Thread(target=self.start_tcp_listener, daemon=True)
        tcp_thread.start()
        
        self.log("VSOCK Proxy running!")
        self.log(f"VM can connect via:")
        self.log(f"  - vsock CID 2 port {self.vsock_port} (if supported)")
        self.log(f"  - TCP localhost:{self.listen_port}")
        
        try:
            while self.running:
                input()
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self):
        self.running = False
        self.log("Stopped")


if __name__ == "__main__":
    proxy = VSOCKProxy()
    proxy.run()
