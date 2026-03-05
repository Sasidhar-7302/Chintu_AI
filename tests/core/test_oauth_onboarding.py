import json
from pathlib import Path

from chintu_backend.integrations.oauth_onboarding import _stage_credentials


def test_stage_credentials_allows_same_source_and_destination(tmp_path: Path):
    creds = tmp_path / "credentials.json"
    creds.write_text(json.dumps({"installed": {"client_id": "x"}}), encoding="utf-8")
    out = _stage_credentials(creds, creds)
    assert out.get("ok") is True
    assert Path(str(out.get("path"))).resolve() == creds.resolve()
