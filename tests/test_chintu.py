"""
Chintu Personal AI Assistant - Test Script
Run this to verify core components are working.
"""

import sys
import time


def _print_result(ok: bool, label: str, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"[{status}] {label}{suffix}")


def _try_import(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def test_imports():
    """Test required package imports."""
    print("\n=== Testing Imports ===")

    required = {
        "numpy": "NumPy",
        "websockets": "WebSockets",
        "pydantic": "Pydantic",
        "pydantic_settings": "Pydantic Settings",
        "cv2": "OpenCV",
        "mediapipe": "MediaPipe",
    }

    optional = {
        "openwakeword": "OpenWakeWord",
        "ollama": "Ollama",
        "sounddevice": "SoundDevice",
        "pyaudio": "PyAudio",
        "faster_whisper": "Faster-Whisper",
        "whisper": "OpenAI Whisper",
    }

    all_passed = True
    for module, name in required.items():
        ok = _try_import(module)
        _print_result(ok, name)
        all_passed = all_passed and ok

    # Optional modules
    for module, name in optional.items():
        ok = _try_import(module)
        status = "PASS" if ok else "WARN"
        print(f"[{status}] {name}")

    # Validate at least one audio backend
    audio_ok = _try_import("sounddevice") or _try_import("pyaudio")
    _print_result(audio_ok, "Audio backend", "sounddevice or pyaudio")
    all_passed = all_passed and audio_ok

    # Validate at least one STT backend for wake fallback
    stt_ok = _try_import("faster_whisper") or _try_import("whisper")
    _print_result(stt_ok, "STT backend", "faster-whisper or whisper")
    all_passed = all_passed and stt_ok

    return all_passed


def test_chintu_modules():
    """Test that Chintu modules can be imported."""
    print("\n=== Testing Chintu Modules ===")

    checks = [
        ("chintu.core", "Core modules"),
        ("chintu.audio", "Audio modules"),
        ("chintu.vision", "Vision modules"),
        ("chintu.automation", "Automation modules"),
        ("chintu.llm", "LLM module"),
        ("chintu.utils", "Utils modules"),
    ]

    all_passed = True
    for module, label in checks:
        ok = _try_import(module)
        _print_result(ok, label)
        all_passed = all_passed and ok

    return all_passed


def test_command_parser():
    """Test the command parser."""
    print("\n=== Testing Command Parser ===")

    from chintu.utils import CommandParser

    parser = CommandParser()

    test_cases = [
        ("open linkedin", "OPEN_URL"),
        ("open notepad", "OPEN_APP"),
        ("search for data science jobs", "SEARCH_JOBS"),
        ("draft a resume for software engineer", "DRAFT_RESUME"),
        ("what is the capital of France", "ASK_QUESTION"),
    ]

    all_passed = True
    for text, expected_type in test_cases:
        result = parser.parse(text)
        ok = result.type.name == expected_type
        _print_result(ok, f"{text} -> {result.type.name}")
        all_passed = all_passed and ok

    return all_passed


def test_one_euro_filter():
    """Test the One Euro Filter."""
    print("\n=== Testing One Euro Filter ===")

    from chintu.utils import OneEuroFilter
    import numpy as np

    f = OneEuroFilter(freq=30.0, min_cutoff=1.0, beta=0.007)
    noisy_values = [0.5 + np.random.normal(0, 0.1) for _ in range(10)]
    filtered_values = [f.filter(v) for v in noisy_values]

    noisy_var = np.var(noisy_values)
    filtered_var = np.var(filtered_values)

    ok = filtered_var < noisy_var
    _print_result(ok, "Filter reduces variance", f"{noisy_var:.4f} -> {filtered_var:.4f}")
    return ok


def test_audio_devices():
    """Test audio device availability."""
    print("\n=== Testing Audio Devices ===")

    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devices = [d for d in devices if d.get("max_input_channels", 0) > 0]

        if input_devices:
            default = sd.query_devices(kind="input")
            _print_result(True, "Audio input devices", f"{len(input_devices)} found")
            print(f"  Default: {default.get('name')}")
            return True
        _print_result(False, "Audio input devices", "none found")
        return False
    except Exception as exc:
        _print_result(False, "Audio input devices", str(exc))
        return False


def test_webcam():
    """Test webcam availability."""
    print("\n=== Testing Webcam ===")

    try:
        import cv2
        backends = [cv2.CAP_ANY]
        if sys.platform.startswith("win"):
            backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]

        for backend in backends:
            cap = cv2.VideoCapture(0, backend)
            if not cap.isOpened():
                cap.release()
                continue

            frame = None
            for _ in range(3):
                ret, frame = cap.read()
                if ret and frame is not None:
                    break
                time.sleep(0.1)
            cap.release()

            if frame is not None:
                _print_result(True, "Webcam", f"{frame.shape[1]}x{frame.shape[0]}")
                return True

        _print_result(False, "Webcam", "no frame")
        return False
    except Exception as exc:
        _print_result(False, "Webcam", str(exc))
        return False


def test_ollama():
    """Test Ollama connection."""
    print("\n=== Testing Ollama ===")

    try:
        from chintu.llm import OllamaClient
        client = OllamaClient()
        if client.is_available:
            _print_result(True, "Ollama client")
            if client.check_model():
                _print_result(True, f"Model '{client.model}' available")
            else:
                print(f"[WARN] Model '{client.model}' not found (run: ollama pull {client.model})")
            return True
        print("[WARN] Ollama not running (start with: ollama serve)")
        return True
    except Exception as exc:
        print(f"[WARN] Ollama test skipped: {exc}")
        return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Chintu Personal AI Assistant - Component Tests")
    print("=" * 60)

    results = {
        "Imports": test_imports(),
        "Chintu Modules": test_chintu_modules(),
        "Command Parser": test_command_parser(),
        "One Euro Filter": test_one_euro_filter(),
        "Audio Devices": test_audio_devices(),
        "Webcam": test_webcam(),
        "Ollama": test_ollama(),
    }

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        _print_result(result, name)

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\nAll tests passed. Chintu is ready to run.")
        print("To start Chintu, run:")
        print("  python main.py")
    else:
        print("\nSome tests failed. Review the output above.")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
