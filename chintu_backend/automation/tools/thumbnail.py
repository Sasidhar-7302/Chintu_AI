"""Programmatic thumbnail generation to replace manual GUI design steps."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from chintu_backend.core.config import Config, get_config

logger = logging.getLogger(__name__)

try:  # Optional dependency; handled gracefully when missing.
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

    PIL_AVAILABLE = True
except Exception:  # pragma: no cover - depends on environment.
    Image = ImageDraw = ImageFilter = ImageFont = ImageOps = None  # type: ignore
    PIL_AVAILABLE = False

try:  # Optional PDF support.
    from pdf2image import convert_from_path

    PDF2IMAGE_AVAILABLE = True
except Exception:  # pragma: no cover - depends on environment.
    convert_from_path = None  # type: ignore
    PDF2IMAGE_AVAILABLE = False


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "thumbnail"


def _load_font(size: int) -> "ImageFont.ImageFont":
    """Load a reasonable default font on Windows with safe fallbacks."""
    if not PIL_AVAILABLE:  # pragma: no cover - guarded by caller.
        raise RuntimeError("Pillow is not available.")

    candidates = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "arial.ttf",
        "segoeui.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


@dataclass
class ThumbnailResult:
    success: bool
    message: str
    output_path: Optional[Path] = None


class ThumbnailGenerator:
    """Generate clean thumbnails using code instead of GUI tooling."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.config, "thumbnail_enabled", True))

    @property
    def available(self) -> bool:
        return PIL_AVAILABLE

    def _load_source_image(self, source: Path) -> "Image.Image":
        suffix = source.suffix.lower()
        if suffix == ".pdf":
            if not PDF2IMAGE_AVAILABLE:
                raise RuntimeError(
                    "PDF input requires pdf2image. Install it or provide an image."
                )
            pages = convert_from_path(str(source), first_page=1, last_page=1)
            if not pages:
                raise RuntimeError("Could not render the PDF preview page.")
            return pages[0].convert("RGB")

        return Image.open(source).convert("RGB")

    def generate(
        self,
        source_path: Path,
        *,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        output_name: Optional[str] = None,
    ) -> ThumbnailResult:
        if not self.enabled:
            return ThumbnailResult(
                success=False,
                message="Thumbnail generation is disabled in config.",
            )
        if not self.available:
            return ThumbnailResult(
                success=False,
                message="Pillow is not installed. Add `pillow` to requirements.",
            )

        source = Path(source_path).expanduser()
        if not source.is_absolute():
            source = (Path.cwd() / source).resolve()
        if not source.exists():
            return ThumbnailResult(False, f"Source file not found: {source}")

        width = int(getattr(self.config, "thumbnail_width", 1280))
        height = int(getattr(self.config, "thumbnail_height", 720))

        try:
            source_img = self._load_source_image(source)
        except Exception as exc:
            logger.exception("Failed to load thumbnail source: %s", source)
            return ThumbnailResult(False, f"Could not load source: {exc}")

        # Build a subtle gradient background.
        canvas = Image.new("RGB", (width, height), color="#0f172a")
        bg_draw = ImageDraw.Draw(canvas)
        for y in range(height):
            t = y / max(height - 1, 1)
            r = int(15 + (30 - 15) * t)
            g = int(23 + (64 - 23) * t)
            b = int(42 + (175 - 42) * t)
            bg_draw.line([(0, y), (width, y)], fill=(r, g, b))

        # Fit the source preview into the left side with padding.
        preview_box = (int(width * 0.08), int(height * 0.1))
        preview_size = (int(width * 0.48), int(height * 0.8))
        preview = ImageOps.contain(source_img, preview_size)

        # Drop shadow to help the preview stand out.
        shadow = Image.new("RGBA", preview.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rectangle(
            [(0, 0), (preview.size[0] - 1, preview.size[1] - 1)],
            fill=(0, 0, 0, 180),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))

        shadow_pos = (preview_box[0] + 18, preview_box[1] + 24)
        canvas.paste(shadow.convert("RGB"), shadow_pos)
        canvas.paste(preview, preview_box)

        # Text block on the right.
        title_text = (title or source.stem.replace("_", " ").title()).strip()
        subtitle_text = (subtitle or "Clean, ATS-friendly template").strip()

        draw = ImageDraw.Draw(canvas)
        title_font = _load_font(size=int(height * 0.085))
        subtitle_font = _load_font(size=int(height * 0.045))

        text_x = int(width * 0.62)
        text_y = int(height * 0.22)
        draw.text(text_x, text_y, title_text, font=title_font, fill="#e5e7eb")
        draw.text(
            text_x,
            text_y + int(height * 0.14),
            subtitle_text,
            font=subtitle_font,
            fill="#cbd5e1",
        )

        out_dir = Path(getattr(self.config, "thumbnail_output_dir", Path.cwd()))
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = _slugify(output_name or f"{source.stem}-thumbnail")
        out_path = out_dir / f"{stem}.png"

        try:
            canvas.save(out_path, format="PNG", optimize=True)
        except Exception as exc:
            logger.exception("Failed to save thumbnail: %s", out_path)
            return ThumbnailResult(False, f"Failed to save thumbnail: {exc}")

        return ThumbnailResult(
            success=True,
            message=f"Thumbnail generated: {out_path}",
            output_path=out_path,
        )


_thumbnail_generator: Optional[ThumbnailGenerator] = None


def get_thumbnail_generator() -> ThumbnailGenerator:
    global _thumbnail_generator
    if _thumbnail_generator is None:
        _thumbnail_generator = ThumbnailGenerator()
    return _thumbnail_generator


def generate_thumbnail(
    source_path: Path,
    *,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    output_name: Optional[str] = None,
) -> Tuple[bool, str, Optional[Path]]:
    """Convenience wrapper for simple call sites."""
    result = get_thumbnail_generator().generate(
        source_path,
        title=title,
        subtitle=subtitle,
        output_name=output_name,
    )
    return result.success, result.message, result.output_path

