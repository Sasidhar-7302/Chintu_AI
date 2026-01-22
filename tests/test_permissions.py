"""
Test script to check microphone and webcam permissions.
Run this to verify your system can access audio and video.
"""

import sys
import time


def _open_camera(index: int = 0):
    """Open a camera with backend fallbacks."""
    import cv2

    backends = [cv2.CAP_ANY]
    if sys.platform.startswith("win"):
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]

    for backend in backends:
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            continue

        frame = None
        for _ in range(3):
            ret, frame = cap.read()
            if ret and frame is not None:
                return cap, frame
            time.sleep(0.1)

        cap.release()

    return None, None


def test_microphone():
    """Test microphone access."""
    print("\nTesting MICROPHONE access...")
    print("-" * 40)

    try:
        import sounddevice as sd

        print("\nAvailable audio devices:")
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                print(f"  [{i}] {dev['name']} (inputs: {dev['max_input_channels']})")

        print("\nRecording 1 second of audio...")
        recording = sd.rec(int(16000 * 1), samplerate=16000, channels=1, dtype="float32")
        sd.wait()

        max_level = abs(recording).max()
        print(f"[OK] Microphone works. Max audio level: {max_level:.4f}")

        if max_level < 0.001:
            print("[WARN] Audio level is very low. Check if microphone is muted.")

        return True

    except ImportError:
        print("[FAIL] sounddevice not installed")
        print("       Run: pip install sounddevice")
        return False

    except Exception as e:
        print(f"[FAIL] Microphone error: {e}")
        print("\nTroubleshooting:")
        print("1. Windows Settings > Privacy > Microphone")
        print("2. Ensure 'Let desktop apps access your microphone' is ON")
        print("3. Check if another app is using the microphone")
        return False


def test_webcam():
    """Test webcam access."""
    print("\nTesting WEBCAM access...")
    print("-" * 40)

    try:
        cap, frame = _open_camera(0)
        if cap is None or frame is None:
            print("[FAIL] Could not open camera or capture a frame")
            print("\nTroubleshooting:")
            print("1. Windows Settings > Privacy > Camera")
            print("2. Ensure 'Let desktop apps access your camera' is ON")
            print("3. Check if another app is using the camera")
            return False

        h, w = frame.shape[:2]
        cap.release()
        print(f"[OK] Webcam works. Resolution: {w}x{h}")
        return True

    except ImportError:
        print("[FAIL] opencv-python not installed")
        print("       Run: pip install opencv-python")
        return False

    except Exception as e:
        print(f"[FAIL] Webcam error: {e}")
        return False


def test_mediapipe():
    """Test MediaPipe for hand tracking."""
    print("\nTesting MEDIAPIPE (hand tracking)...")
    print("-" * 40)

    try:
        import mediapipe as mp
        import cv2

        mp_hands = mp.solutions.hands
        hands = mp_hands.Hands(
            static_image_mode=True,
            max_num_hands=1,
            min_detection_confidence=0.5,
        )

        cap, frame = _open_camera(0)
        if cap is None or frame is None:
            print("[FAIL] Could not capture frame for MediaPipe test")
            hands.close()
            return False

        cap.release()
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        if results.multi_hand_landmarks:
            print(f"[OK] MediaPipe works. Detected {len(results.multi_hand_landmarks)} hand(s)")
        else:
            print("[OK] MediaPipe initialized (no hands detected in test frame)")

        hands.close()
        return True

    except ImportError:
        print("[FAIL] mediapipe not installed")
        print("       Run: pip install mediapipe")
        return False

    except Exception as e:
        print(f"[FAIL] MediaPipe error: {e}")
        return False


def main():
    print("=" * 50)
    print("  Chintu Permission Test")
    print("=" * 50)

    mic_ok = test_microphone()
    cam_ok = test_webcam()
    mp_ok = test_mediapipe()

    print("\n" + "=" * 50)
    print("  Summary")
    print("=" * 50)
    print(f"  Microphone: {'OK' if mic_ok else 'FAILED'}")
    print(f"  Webcam:     {'OK' if cam_ok else 'FAILED'}")
    print(f"  MediaPipe:  {'OK' if mp_ok else 'FAILED'}")
    print("=" * 50)

    if mic_ok and cam_ok:
        print("\nAll permissions granted. Chintu can use audio and video.")
    else:
        print("\nSome permissions missing. Check Windows Privacy Settings.")


if __name__ == "__main__":
    main()
