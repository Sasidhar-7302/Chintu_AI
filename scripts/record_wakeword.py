"""
Record wake-word samples for custom model training.
Saves 16 kHz mono WAV files suitable for openWakeWord tooling.
"""

import argparse
import os
import sys
import time
import wave

try:
    import numpy as np
    import sounddevice as sd
except ImportError as exc:
    print(f"Missing dependency: {exc}. Install sounddevice and numpy.")
    sys.exit(1)


def _countdown(seconds: int) -> None:
    for i in range(seconds, 0, -1):
        print(f"  {i}...")
        time.sleep(1)


def _record_sample(duration: float, rate: int, channels: int, device: int | None):
    frames = int(duration * rate)
    audio = sd.rec(
        frames,
        samplerate=rate,
        channels=channels,
        dtype="float32",
        device=device,
    )
    sd.wait()
    if channels > 1:
        audio = np.mean(audio, axis=1)
    else:
        audio = audio.reshape(-1)
    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767).astype(np.int16)


def _write_wav(path: str, audio: np.ndarray, rate: int) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(audio.tobytes())


def main() -> int:
    parser = argparse.ArgumentParser(description="Record wake-word samples.")
    parser.add_argument("--phrase", default="hey chintu", help="Wake phrase to record.")
    parser.add_argument("--out", default="data/wakeword/positive", help="Output directory.")
    parser.add_argument("--count", type=int, default=30, help="Number of samples to record.")
    parser.add_argument("--duration", type=float, default=1.6, help="Seconds per sample.")
    parser.add_argument("--rate", type=int, default=16000, help="Sample rate.")
    parser.add_argument("--channels", type=int, default=1, help="Number of channels.")
    parser.add_argument("--device", type=int, default=None, help="Input device index.")
    parser.add_argument("--manual", action="store_true", help="Press Enter before each sample.")
    parser.add_argument("--list-devices", action="store_true", help="List audio input devices and exit.")
    args = parser.parse_args()

    if args.list_devices:
        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                print(f"{idx}: {dev.get('name')}")
        return 0

    os.makedirs(args.out, exist_ok=True)

    print("Wake-word recording")
    print(f"Phrase: {args.phrase}")
    print(f"Samples: {args.count}")
    print(f"Duration: {args.duration:.2f}s @ {args.rate} Hz")
    print(f"Output: {args.out}")
    print("")

    for i in range(1, args.count + 1):
        if args.manual:
            input(f"Sample {i}/{args.count}: Press Enter to start...")
        else:
            print(f"Sample {i}/{args.count}: Get ready to say '{args.phrase}'")
            _countdown(2)

        print("  Recording...")
        audio = _record_sample(args.duration, args.rate, args.channels, args.device)

        filename = f"{args.phrase.replace(' ', '_')}_{i:03d}.wav"
        path = os.path.join(args.out, filename)
        _write_wav(path, audio, args.rate)
        print(f"  Saved: {path}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
