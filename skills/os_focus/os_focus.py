import ctypes
import os
import subprocess


def minimize_windows() -> None:
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(New-Object -ComObject Shell.Application).MinimizeAll()",
        ],
        capture_output=True,
        text=True,
    )


def set_master_volume(percent: int) -> None:
    percent = max(0, min(100, percent))
    level = int(percent / 100 * 0xFFFF)
    ctypes.windll.winmm.waveOutSetVolume(0, level | (level << 16))


def launch_app(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0:
        return "Launched"
    return f"Failed: {result.stderr.strip() or result.stdout.strip()}"


def main() -> None:
    if os.getenv("CHINTU_VALIDATE_DRY_RUN", "").strip() == "1":
        print("=== Focus Protocol ===")
        print("[dry-run] Would minimize all windows.")
        print("[dry-run] Would set system volume to 25%.")
        print("[dry-run] Would open Spotify.")
        print("[dry-run] Would launch Visual Studio Code.")
        return

    print("=== Focus Protocol ===")
    print("Minimizing all windows...")
    minimize_windows()
    print("Setting system volume to 25%...")
    try:
        set_master_volume(25)
    except Exception as exc:
        print(f"Volume tweak failed: {exc}")
    print("Opening Spotify...")
    print(launch_app(["powershell", "-NoProfile", "-Command", "Start-Process", "spotify:"]))
    print("Launching Visual Studio Code...")
    print(launch_app(["powershell", "-NoProfile", "-Command", "Start-Process", "code"]))


if __name__ == "__main__":
    main()
