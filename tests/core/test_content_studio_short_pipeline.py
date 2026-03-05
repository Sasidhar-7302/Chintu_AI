from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


def test_generate_youtube_short_respects_output_dir(monkeypatch, tmp_path: Path) -> None:
    from chintu_backend.automation import content_studio

    monkeypatch.setattr(
        content_studio,
        "get_config",
        lambda: SimpleNamespace(data_dir=tmp_path / "data"),
    )
    monkeypatch.setattr(content_studio, "_get_router_from_context", lambda _context=None: object())
    monkeypatch.setattr(
        content_studio,
        "_generate_text",
        lambda _router, _prompt, system="": json.dumps(
            {
                "title": "Local LLM Workflows",
                "script": "Hook. Main value. CTA.",
                "caption_lines": ["Hook", "Main value", "CTA"],
                "tags": ["llm", "localai"],
                "description": "A quick explainer.",
            }
        ),
    )
    monkeypatch.setattr(content_studio, "_download_background_asset", lambda *_args, **_kwargs: (False, ""))
    monkeypatch.setattr(content_studio, "_ffmpeg_available", lambda: False)

    out_root = tmp_path / "bench_out" / "shorts"
    result = content_studio.generate_youtube_short(
        topic="local llm workflows",
        duration_seconds=30,
        output_dir=out_root,
        context={},
    )

    run_dir = Path(result["dir"])
    assert run_dir.exists()
    assert out_root in run_dir.parents

    metadata_path = Path(result["metadata"])
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert int(payload["duration_seconds"]) == 30
    assert "background_asset_used" in payload
    assert "background_asset_path" in payload


def test_youtube_short_capability_parses_duration_and_benchmark_output(monkeypatch, tmp_path: Path) -> None:
    from chintu_backend.automation import automation_capabilities as ac
    from chintu_backend.automation import content_studio

    captured = {}

    def fake_generate_youtube_short(*, topic, voice="default", style="", duration_seconds=60, output_dir=None, context=None):
        captured["topic"] = topic
        captured["duration_seconds"] = duration_seconds
        captured["output_dir"] = output_dir
        run_dir = Path(output_dir) / "demo_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        metadata = run_dir / "metadata.json"
        metadata.write_text("{}", encoding="utf-8")
        return {
            "dir": str(run_dir),
            "title": "Demo",
            "script": str(run_dir / "script.txt"),
            "audio": "",
            "subtitles": "",
            "video": "",
            "metadata": str(metadata),
        }

    monkeypatch.setattr(content_studio, "generate_youtube_short", fake_generate_youtube_short)

    context = {"_bench_out_dir": str(tmp_path)}
    result = ac.handle_youtube_short_generate_assets(
        "Build short video about local llm workflows duration 30 seconds",
        context,
    )

    assert result.success is True
    assert captured["duration_seconds"] == 30
    assert Path(captured["output_dir"]) == (tmp_path / "shorts")
