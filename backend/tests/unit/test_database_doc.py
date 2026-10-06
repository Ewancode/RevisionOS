from app.core.settings import BACKEND_ROOT
from scripts.database_doc import render

COMMITTED = BACKEND_ROOT.parent / "docs" / "database.md"


def test_database_doc_is_up_to_date() -> None:
    """docs/database.md is generated from the models. If this fails, run
    `make db-docs` and commit the result."""
    assert render() == COMMITTED.read_text(encoding="utf-8")
