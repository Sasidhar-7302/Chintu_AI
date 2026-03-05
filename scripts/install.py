"""Chintu AI Smart Installer - One-Click Setup."""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def print_banner():
    print("""
    #################################################
    #                                               #
    #          CHINTU AI SMART INSTALLER            #
    #        Making Perfection Effortless           #
    #                                               #
    #################################################
    """)

def check_env():
    print("[1/4] Checking System Dependencies...")
    
    # Check Ollama
    if shutil.which("ollama"):
        print("  [OK] Ollama detected.")
    else:
        print("  [!!] Ollama not found. Please install it from ollama.com")

    # Check Flutter
    if shutil.which("flutter"):
        print("  [OK] Flutter/Dart detected.")
    else:
        print("  [!!] Flutter not found. UI development mode will be unavailable.")

def setup_python():
    print("[2/4] Syncing Python Environment...")
    venv_path = Path("venv")
    
    if not venv_path.exists():
        print("  Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", "venv"], check=True)
    
    pip_cmd = [str(venv_path / "Scripts" / "pip"), "install", "-r", "requirements.txt"]
    print("  Installing/Updating packages (this may take a minute)...")
    subprocess.run(pip_cmd, check=True)

def verify_config():
    print("[3/4] Verifying Configuration...")
    env_file = Path(".env")
    if not env_file.exists():
        if Path(".env.example").exists():
            shutil.copy(".env.example", ".env")
            print("  Created .env from template.")
        else:
            env_file.touch()
            print("  Created empty .env file.")
    else:
        print("  .env file found.")

def final_touch():
    print("[4/4] Finalizing...")
    # Create logs dir if missing
    Path("logs").mkdir(exist_ok=True)
    print("  Ready to launch!")

def main():
    print_banner()
    try:
        check_env()
        setup_python()
        verify_config()
        final_touch()
        print("\n[SUCCESS] Chintu AI is now ready.")
        print("Run 'scripts\\start_chintu.bat' to start your assistant.")
    except Exception as e:
        print(f"\n[ERROR] Installation failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
