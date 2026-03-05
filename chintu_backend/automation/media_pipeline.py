"""
Media pipeline utilities: image analysis, video summarization, news video creation.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from chintu_backend.core.config import get_config
from chintu_backend.vision.omniparser import OmniParser
from chintu_backend.brain.llm.ollama_client import OllamaClient
from chintu_backend.search.deep_search import deep_search
from chintu_backend.audio import get_tts

logger = logging.getLogger(__name__)


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def analyze_image(path: str, mode: str = "describe") -> Dict[str, Any]:
    image_path = Path(path).expanduser()
    if not image_path.exists():
        return {"error": "Image file not found."}
    parser = OmniParser()
    if mode == "ocr":
        result = parser.analyze_screen(image_path=str(image_path))
        text = result.get("text_content") or result.get("description") or ""
        return {"summary": text, "raw": result}
    if mode == "analyze":
        result = parser.analyze_screen(image_path=str(image_path))
        return {"summary": result.get("description") or "Image analyzed.", "raw": result}
    desc = parser.describe_screen(image_path=str(image_path))
    return {"summary": desc}


def summarize_video(path: str, max_frames: int = 20, fps: float = 0.2) -> Dict[str, Any]:
    video_path = Path(path).expanduser()
    if not video_path.exists():
        return {"error": "Video file not found."}
    if not _ffmpeg_available():
        return {"error": "ffmpeg is not installed."}

    out_dir = Path(get_config().data_dir) / "video_frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    frame_dir = out_dir / f"frames_{stamp}"
    frame_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-vf", f"fps={fps}",
        str(frame_dir / "frame_%04d.jpg"),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except Exception as exc:
        return {"error": f"ffmpeg failed: {exc}"}

    frames = sorted(frame_dir.glob("frame_*.jpg"))[:max_frames]
    if not frames:
        return {"error": "No frames extracted."}

    parser = OmniParser()
    descriptions: List[str] = []
    for frame in frames:
        try:
            desc = parser.describe_screen(image_path=str(frame))
            if desc:
                descriptions.append(desc)
        except Exception:
            continue

    if not descriptions:
        return {"error": "No descriptions generated."}

    llm = OllamaClient()
    prompt = "Summarize this video based on frame descriptions:\n\n" + "\n".join(descriptions[:max_frames])
    summary = llm.answer_question(prompt) if llm else "\n".join(descriptions[:3])
    return {
        "summary": summary,
        "frames": [str(f) for f in frames],
        "descriptions": descriptions,
    }


def build_news_video(topic: str = "technology news", voice: str = "default") -> Dict[str, Any]:
    config = get_config()
    base_dir = config.data_dir / "news_videos"
    base_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = base_dir / f"news_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    report = deep_search(topic, sources=["news"])
    llm = OllamaClient()
    script_prompt = (
        "Write a concise 60-90 second tech news script based on the report below. "
        "Use a friendly host tone and end with a short call to action.\n\nREPORT:\n"
        f"{report}"
    )
    script = llm.answer_question(script_prompt) if llm else report
    script_path = run_dir / "script.txt"
    script_path.write_text(script, encoding="utf-8")

    audio_path = run_dir / "voice.mp3"
    try:
        tts = get_tts()
        if tts and hasattr(tts, "synthesize_to_file"):
            tts.synthesize_to_file(script, audio_path)
    except Exception:
        pass

    # Optional: create a simple video using a static image if ffmpeg is available
    video_path = run_dir / "video.mp4"
    if _ffmpeg_available() and audio_path.exists():
        image_path = run_dir / "title.png"
        if not image_path.exists():
            try:
                from PIL import Image, ImageDraw, ImageFont
                img = Image.new("RGB", (1280, 720), color=(15, 15, 20))
                draw = ImageDraw.Draw(img)
                draw.text((40, 40), "Chintu Daily Tech News", fill=(255, 255, 255))
                img.save(image_path)
            except Exception:
                image_path = None
        if image_path and image_path.exists():
            cmd = [
                "ffmpeg",
                "-loop", "1",
                "-i", str(image_path),
                "-i", str(audio_path),
                "-c:v", "libx264",
                "-tune", "stillimage",
                "-c:a", "aac",
                "-shortest",
                str(video_path),
            ]
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
            except Exception:
                pass

    return {
        "report": report,
        "script": str(script_path),
        "audio": str(audio_path) if audio_path.exists() else "",
        "video": str(video_path) if video_path.exists() else "",
        "dir": str(run_dir),
    }
