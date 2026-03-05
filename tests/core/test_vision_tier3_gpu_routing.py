from chintu_backend.automation.vision_automation import VisionAutomation


def test_tier3_gpu_env_default_and_parse(monkeypatch):
    monkeypatch.delenv("CHINTU_TIER3_MAIN_GPU", raising=False)
    assert VisionAutomation._resolve_main_gpu() == 0

    monkeypatch.setenv("CHINTU_TIER3_MAIN_GPU", "1")
    assert VisionAutomation._resolve_main_gpu() == 1

    monkeypatch.setenv("CHINTU_TIER3_MAIN_GPU", "bad")
    assert VisionAutomation._resolve_main_gpu() == 0


def test_high_precision_candidate_ordering():
    candidates = [
        "qwen3-vl:2b",
        "qwen2.5-vl:7b",
        "llava:7b",
    ]
    ordered = VisionAutomation._reorder_candidates(candidates, high_precision=True)
    assert ordered[0] == "qwen2.5-vl:7b"
    assert ordered.index("qwen3-vl:2b") > ordered.index("qwen2.5-vl:7b")

    unchanged = VisionAutomation._reorder_candidates(candidates, high_precision=False)
    assert unchanged == candidates
