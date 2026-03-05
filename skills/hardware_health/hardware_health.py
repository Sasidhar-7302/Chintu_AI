import subprocess
from pathlib import Path


def parse_gpu_stats(lines: list[str]) -> list[dict[str, str]]:
    records = []
    for line in lines:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 6:
            continue
        records.append(
            {
                "index": parts[0],
                "name": parts[1],
                "temperature.gpu": parts[2],
                "utilization.gpu": parts[3],
                "memory.total": parts[4],
                "memory.used": parts[5],
            }
        )
    return records


def check_gpu_status() -> tuple[str, bool]:
    cmd = [
        "nvidia-smi",
        "--query-gpu=index,name,temperature.gpu,utilization.gpu,memory.total,memory.used",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        return "nvidia-smi not available; no NVIDIA GPU detected.", False
    except subprocess.CalledProcessError as exc:
        return f"nvidia-smi failed: {exc.stderr.strip() or exc.stdout.strip()}", False

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    gpus = parse_gpu_stats(lines)
    if not gpus:
        return "No GPU stats could be parsed from nvidia-smi output.", False

    summaries = []
    idle = True
    for gpu in gpus:
        temp = gpu["temperature.gpu"]
        util = int(float(gpu["utilization.gpu"]))
        mem_total = int(float(gpu["memory.total"]))
        mem_used = int(float(gpu["memory.used"]))
        mem_usage_percent = round((mem_used / mem_total) * 100, 1) if mem_total else 0.0
        summaries.append(
            f'GPU {gpu["index"]} {gpu["name"]}: {temp}C | Util {util}% | Memory {mem_used}/{mem_total} MiB ({mem_usage_percent}%)'
        )
        if util > 15 or mem_usage_percent > 40:
            idle = False

    advice = (
        "GPU is idle; consider routing the brain model to this GPU for improved throughput."
        if idle
        else "GPU is active; keep the current brain model allocation."
    )
    return "\n".join(summaries) + "\n" + advice, idle


def main() -> None:
    status, idle = check_gpu_status()
    print("=== Hardware Health ===")
    print(status)
    if idle:
        config_hint = Path.cwd() / ".env"
        print(
            f"\nIf the brain model should target the RTX 3060, set "
            f"CHINTU_OLLAMA_MODEL=qwen2.5-coder:14b-instruct-q4_K_M in {config_hint} "
            "and restart Chintu."
        )


if __name__ == "__main__":
    main()
