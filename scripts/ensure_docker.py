"""
Ensure Docker is Running
------------------------
Checks if Docker Daemon is responsive.
If not, attempts to launch Docker Desktop and waits for it to initialize.
"""

import subprocess
import time
import os
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='[DockerCheck] %(message)s')
logger = logging.getLogger()

def is_docker_ready():
    """Check if docker daemon is responding."""
    try:
        # Run 'docker info' with a short timeout
        result = subprocess.run(
            ["docker", "info"], 
            capture_output=True, 
            text=True, 
            timeout=3
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def find_docker_executable():
    """Find Docker Desktop executable path."""
    common_paths = [
        r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
        r"C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe"
    ]
    for path in common_paths:
        if os.path.exists(path):
            return path
    return None

def main():
    if is_docker_ready():
        logger.info("✅ Docker is already running.")
        return 0

    logger.info("⚠️ Docker not detecting. Attempting to launch Docker Desktop...")
    
    docker_exe = find_docker_executable()
    if not docker_exe:
        logger.error("❌ Docker Desktop executable not found! Please install Docker Desktop.")
        # We don't exit with error because Chintu can run without Docker (just no Sandbox)
        return 0 

    try:
        # Launch Docker Desktop
        subprocess.Popen(docker_exe)
        logger.info(f"🚀 Launched: {docker_exe}")
        logger.info("⏳ Waiting for Docker Daemon to initialize (this may take 1-2 minutes)...")
    except Exception as e:
        logger.error(f"❌ Failed to launch Docker: {e}")
        return 0

    # Wait loop
    max_retries = 30 # 30 * 2s = 60 seconds (usually enough if just starting)
    for i in range(max_retries):
        if is_docker_ready():
            logger.info("✅ Docker started successfully!")
            return 0
        time.sleep(2)
        if i % 5 == 0:
            print(".", end="", flush=True)
    
    logger.warning("⚠️ Docker launched but is not yet ready. It might be starting in background.")
    logger.warning("   Chintu will continue, but 'Shadow Workspace' might be delayed.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
