import json
from pathlib import Path

from app.core.settings import BACKEND_ROOT
from scripts.export_openapi import main

COMMITTED_SCHEMA = BACKEND_ROOT.parent / "frontend" / "openapi.json"


def test_export_writes_schema(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    assert main([str(out)]) == 0
    schema = json.loads(out.read_text(encoding="utf-8"))
    assert "/api/v1/health" in schema["paths"]
    assert "/api/v1/health/ready" in schema["paths"]


def test_frontend_schema_is_up_to_date(tmp_path: Path) -> None:
    """The typed frontend client is generated from frontend/openapi.json.
    If this fails, run `make api-client` and commit the result."""
    out = tmp_path / "openapi.json"
    main([str(out)])
    assert out.read_text(encoding="utf-8") == COMMITTED_SCHEMA.read_text(encoding="utf-8")
