"""Write the OpenAPI schema to a file for frontend client generation.

Usage: ``python -m scripts.export_openapi ../frontend/openapi.json``
Needs no database or Redis: the schema is built without starting the app.
"""

import json
import sys
from pathlib import Path

from app.main import create_app


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m scripts.export_openapi <output.json>", file=sys.stderr)
        return 2
    schema = create_app().openapi()
    Path(argv[0]).write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
