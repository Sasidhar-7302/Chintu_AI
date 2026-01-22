import sys
import os
import shutil
import socket
import importlib.util

def check_package(package_name):
    """Check if a python package is installed."""
    if importlib.util.find_spec(package_name) is None:
        return False
    return True

def check_ffmpeg():
    """Check if ffmpeg is in system PATH or venv Scripts."""
    if shutil.which("ffmpeg") is not None:
        return True
    
    # Check in venv/Scripts (same dir as python.exe)
    local_ffmpeg = os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe")
    # print(f"DEBUG: Checking for FFmpeg at: {local_ffmpeg}")
    if os.path.exists(local_ffmpeg):
        # print("DEBUG: Found local FFmpeg!")
        return True

    print("❌ CRITICAL: 'ffmpeg' not found in PATH.")
    print("   Audio features (Wake Word, STT, TTS) will NOT work.")
    print("   Action: Install FFmpeg and add it to System Variables.")
    return False
    return True

def check_ollama():
    """Check if Ollama is running (simplistic check or just warning)."""
    # Just checking ping might be slow, let's checking connectivity to default port 11434
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    result = sock.connect_ex(('127.0.0.1', 11434))
    sock.close()
    if result != 0:
        print("⚠️ WARNING: Ollama does not seem to be running on port 11434.")
        print("   Chintu needs Ollama for intelligence.")
        print("   Action: Ensure 'ollama serve' is running in another terminal.")
        # We don't block launch for this, but warn.
        return True # Soft pass
    return True

def check_microphone():
    """Check for audio input devices using PyAudio."""
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        info = p.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount')
        input_devices = 0
        for i in range(0, numdevices):
            if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                input_devices += 1
        p.terminate()
        
        if input_devices == 0:
            print("❌ CRITICAL: No microphone found!")
            print("   Chintu cannot hear you.")
            return False
        return True
    except Exception as e:
        print(f"⚠️ WARNING: Could not verify microphone: {e}")
        return True # Soft pass if PyAudio fails to load

def check_python_dependencies():
    """Check if key packages are installed (lenient check)."""
    # Only check a few critical packages, not all dependencies
    # Full dependency resolution is handled by pip install
    critical_packages = [
        "numpy", "pyaudio", "faster_whisper", "edge_tts", 
        "chromadb", "websockets", "pydantic"
    ]
    
    missing = []
    for pkg in critical_packages:
        if not check_package(pkg):
            missing.append(pkg)
    
    if missing:
        print(f"📦 Critical packages missing: {', '.join(missing)}")
        return 1
    
    return 0

def main():
    print("🏥 Running System Health Check...")
    
    # 1. Python Dependencies
    deps_status = check_python_dependencies()
    if deps_status != 0:
        # If deps missing, return 1 immediately so pip install runs
        # We don't check others yet because they might depend on libs (like pyaudio)
        return 1
        
    print("   ✅ Python Libraries: OK")

    # 2. System Tools (FFmpeg)
    if not check_ffmpeg():
        return 3 # Special code for FFmpeg Missing (Trigger Auto-Install)

    # 3. Hardware (Mic)
    if not check_microphone():
        print("\n❌ System checks failed. Please fix issues above.")
        return 2

    # 4. Services (Ollama)
    check_ollama()
    
    print("   ✅ System Health: OK")
    print("🚀 Ready to launch!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
