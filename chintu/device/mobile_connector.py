"""Mobile device connector via SSH/Termux.

Handles:
- Network scanning for devices with SSH
- SSH connection to Termux on Android
- Auto-deployment of Chintu agent
- PM2 setup for keep-alive
"""

import os
import logging
import socket
import subprocess
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Try to import paramiko for SSH
try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False
    paramiko = None  # Prevent NameError in type hints
    logger.warning("paramiko not installed. Run: pip install paramiko")


@dataclass
class MobileDevice:
    """Represents a discovered/connected mobile device."""
    ip: str
    port: int = 8022  # Termux default SSH port
    username: str = ""
    connected: bool = False
    device_name: str = ""
    android_version: str = ""
    agent_installed: bool = False
    agent_running: bool = False
    last_seen: str = ""


class MobileConnector:
    """Manages connections to mobile devices via Termux/SSH."""
    
    TERMUX_SSH_PORT = 8022
    AGENT_INSTALL_PATH = "~/chintu_agent"
    
    def __init__(self):
        self._devices: Dict[str, MobileDevice] = {}
        # Avoid 'NoneType' has no attribute 'SSHClient' by using Any or quoted string if paramiko is missing
        self._ssh_clients: Dict[str, Any] = {}
        
        # Agent files to deploy
        self._agent_dir = Path(__file__).parent.parent / "mobile_agent"
        
    def scan_network(self, subnet: str = None, timeout: float = 1.0) -> List[MobileDevice]:
        """Scan local network for devices with Termux SSH running.
        
        Args:
            subnet: Subnet to scan (e.g., "192.168.1"). Auto-detects if None.
            timeout: Connection timeout per host
            
        Returns:
            List of discovered devices
        """
        if subnet is None:
            subnet = self._get_local_subnet()
            
        if not subnet:
            logger.error("Could not determine local subnet")
            return []
        
        logger.info(f"Scanning subnet {subnet}.* for Termux devices...")
        discovered = []
        
        def check_host(ip: str) -> Optional[MobileDevice]:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, self.TERMUX_SSH_PORT))
                sock.close()
                
                if result == 0:
                    logger.info(f"Found SSH on {ip}:{self.TERMUX_SSH_PORT}")
                    return MobileDevice(ip=ip, port=self.TERMUX_SSH_PORT)
            except Exception:
                pass
            return None
        
        # Scan IPs in parallel
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = {
                executor.submit(check_host, f"{subnet}.{i}"): i 
                for i in range(1, 255)
            }
            for future in as_completed(futures):
                device = future.result()
                if device:
                    discovered.append(device)
                    self._devices[device.ip] = device
        
        logger.info(f"Found {len(discovered)} devices with SSH")
        return discovered
    
    def connect(self, ip: str, username: str, password: str, 
                port: int = 8022) -> bool:
        """Connect to a mobile device via SSH.
        
        Args:
            ip: Device IP address
            username: Termux username (usually u0_aXXX)
            password: SSH password
            port: SSH port (default 8022 for Termux)
            
        Returns:
            True if connected successfully
        """
        if not PARAMIKO_AVAILABLE:
            logger.error("paramiko not installed")
            return False
        
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            logger.info(f"Connecting to {ip}:{port} as {username}...")
            client.connect(
                hostname=ip,
                port=port,
                username=username,
                password=password,
                timeout=10
            )
            
            self._ssh_clients[ip] = client
            
            # Update device info
            if ip not in self._devices:
                self._devices[ip] = MobileDevice(ip=ip, port=port)
            
            device = self._devices[ip]
            device.username = username
            device.connected = True
            
            # Get device info
            self._get_device_info(ip)
            
            logger.info(f"Connected to {ip}")
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    def disconnect(self, ip: str):
        """Disconnect from a device."""
        if ip in self._ssh_clients:
            try:
                self._ssh_clients[ip].close()
            except Exception:
                pass
            del self._ssh_clients[ip]
            
        if ip in self._devices:
            self._devices[ip].connected = False
    
    def install_agent(self, ip: str) -> bool:
        """Install/update Chintu agent on the device.
        
        Args:
            ip: Device IP address
            
        Returns:
            True if installation successful
        """
        if ip not in self._ssh_clients:
            logger.error(f"Not connected to {ip}")
            return False
        
        client = self._ssh_clients[ip]
        
        try:
            # Create agent directory
            self._run_command(client, f"mkdir -p {self.AGENT_INSTALL_PATH}")
            
            # Upload agent files via SFTP
            sftp = client.open_sftp()
            
            agent_files = [
                ("agent.py", self._get_agent_code()),
                ("requirements.txt", "flask\nrequests\n"),
            ]
            
            for filename, content in agent_files:
                remote_path = f"{self.AGENT_INSTALL_PATH}/{filename}"
                # Write to temp file first
                with sftp.file(remote_path.replace("~", "."), 'w') as f:
                    f.write(content)
                logger.debug(f"Uploaded {filename}")
            
            sftp.close()
            
            # Install Python dependencies
            self._run_command(client, f"cd {self.AGENT_INSTALL_PATH} && pip install -q -r requirements.txt")
            
            self._devices[ip].agent_installed = True
            logger.info(f"Agent installed on {ip}")
            return True
            
        except Exception as e:
            logger.error(f"Agent installation failed: {e}")
            return False
    
    def start_agent(self, ip: str, use_pm2: bool = True) -> bool:
        """Start the Chintu agent on the device.
        
        Args:
            ip: Device IP address
            use_pm2: Use PM2 for process management
            
        Returns:
            True if agent started
        """
        if ip not in self._ssh_clients:
            logger.error(f"Not connected to {ip}")
            return False
        
        client = self._ssh_clients[ip]
        
        try:
            if use_pm2:
                # Check if PM2 is installed
                _, stdout, _ = client.exec_command("which pm2")
                if not stdout.read().decode().strip():
                    logger.info("Installing PM2...")
                    self._run_command(client, "npm install -g pm2")
                
                # Start with PM2
                self._run_command(client, 
                    f"cd {self.AGENT_INSTALL_PATH} && pm2 start agent.py --name chintu-agent --interpreter python")
                self._run_command(client, "pm2 save")
            else:
                # Start directly (will stop when SSH disconnects)
                self._run_command(client,
                    f"cd {self.AGENT_INSTALL_PATH} && nohup python agent.py &")
            
            self._devices[ip].agent_running = True
            logger.info(f"Agent started on {ip}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start agent: {e}")
            return False
    
    def stop_agent(self, ip: str) -> bool:
        """Stop the agent on a device."""
        if ip not in self._ssh_clients:
            return False
        
        client = self._ssh_clients[ip]
        
        try:
            self._run_command(client, "pm2 stop chintu-agent")
            self._devices[ip].agent_running = False
            return True
        except Exception:
            return False
    
    def get_agent_status(self, ip: str) -> Dict[str, Any]:
        """Get the status of the agent on a device."""
        if ip not in self._ssh_clients:
            return {"connected": False}
        
        client = self._ssh_clients[ip]
        
        try:
            _, stdout, _ = client.exec_command("pm2 jlist")
            output = stdout.read().decode()
            
            return {
                "connected": True,
                "agent_running": "chintu-agent" in output,
                "pm2_output": output
            }
        except Exception as e:
            return {"connected": True, "error": str(e)}
    
    def _run_command(self, client: Any, command: str) -> str:
        """Run a command on the remote device."""
        logger.debug(f"Running: {command}")
        _, stdout, stderr = client.exec_command(command)
        output = stdout.read().decode()
        error = stderr.read().decode()
        if error:
            logger.debug(f"stderr: {error}")
        return output
    
    def _get_device_info(self, ip: str):
        """Get Android device information."""
        if ip not in self._ssh_clients:
            return
        
        client = self._ssh_clients[ip]
        device = self._devices[ip]
        
        try:
            # Get device name
            _, stdout, _ = client.exec_command("getprop ro.product.model")
            device.device_name = stdout.read().decode().strip() or "Unknown"
            
            # Get Android version
            _, stdout, _ = client.exec_command("getprop ro.build.version.release")
            device.android_version = stdout.read().decode().strip() or "Unknown"
            
        except Exception as e:
            logger.debug(f"Could not get device info: {e}")
    
    def _get_local_subnet(self) -> Optional[str]:
        """Get the local network subnet."""
        try:
            # Get local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            
            # Extract subnet (first 3 octets)
            parts = local_ip.split('.')
            return '.'.join(parts[:3])
        except Exception:
            return None
    
    def _get_agent_code(self) -> str:
        """Get the Python agent code to deploy."""
        return '''#!/usr/bin/env python3
"""Chintu Mobile Agent - runs on Android via Termux."""

import os
import json
import socket
import logging
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
MASTER_HOST = os.environ.get("CHINTU_MASTER", "")
AGENT_PORT = 5050

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "device": socket.gethostname(),
        "agent": "chintu-mobile"
    })

@app.route("/notify", methods=["POST"])
def notify():
    """Receive notification from master."""
    data = request.json
    message = data.get("message", "")
    logger.info(f"Notification: {message}")
    # TODO: Show Android notification via termux-notification
    return jsonify({"status": "received"})

@app.route("/command", methods=["POST"])
def command():
    """Execute a command from master."""
    data = request.json
    cmd = data.get("command", "")
    # Security: Only allow specific commands
    allowed = ["termux-battery-status", "termux-volume", "termux-brightness"]
    if cmd.split()[0] not in allowed:
        return jsonify({"error": "Command not allowed"}), 403
    
    import subprocess
    result = subprocess.run(cmd.split(), capture_output=True, text=True)
    return jsonify({
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode
    })

if __name__ == "__main__":
    logger.info(f"Starting Chintu Mobile Agent on port {AGENT_PORT}")
    app.run(host="0.0.0.0", port=AGENT_PORT, debug=False)
'''
    
    def get_devices(self) -> List[MobileDevice]:
        """Get list of all known devices."""
        return list(self._devices.values())


# Global instance
_connector: Optional[MobileConnector] = None


def get_mobile_connector() -> MobileConnector:
    """Get the global MobileConnector instance."""
    global _connector
    if _connector is None:
        _connector = MobileConnector()
    return _connector
