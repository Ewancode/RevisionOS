"""The deployment files agree with the app's config (Phase 13): the runtime
versions coding.yaml names are the ones the fetch script installs, and the
production Content-Security-Policy lets the browser reach their packages."""

import re
from urllib.parse import urlparse

from app.core.config import get_config
from app.core.settings import BACKEND_ROOT

REPO = BACKEND_ROOT.parent
FETCH = (REPO / "frontend" / "scripts" / "fetch-runtimes.sh").read_text(encoding="utf-8")
CADDY = (REPO / "infra" / "Caddyfile").read_text(encoding="utf-8")
RUNTIMES = get_config().coding.runtimes


def _pinned(name: str) -> str:
    match = re.search(rf"^{name}_VERSION=(\S+)$", FETCH, re.MULTILINE)
    assert match, f"{name}_VERSION missing from fetch-runtimes.sh"
    return match.group(1)


def _csp(matcher: str) -> dict[str, list[str]]:
    match = re.search(rf"header {matcher} Content-Security-Policy \"([^\"]+)\"", CADDY)
    assert match, f"no CSP for {matcher} in the Caddyfile"
    directives = (d.strip().split() for d in match.group(1).split(";") if d.strip())
    return {d[0]: d[1:] for d in directives}


def test_coding_yaml_names_the_versions_the_fetch_script_installs() -> None:
    assert RUNTIMES.python.base_url == f"/runtimes/pyodide/{_pinned('PYODIDE')}/"
    assert RUNTIMES.r.base_url == f"/runtimes/webr/{_pinned('WEBR')}/"
    manifest = REPO / "frontend" / "scripts" / f"webr-{_pinned('WEBR')}.sha256"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    assert lines and all(re.fullmatch(r"[0-9a-f]{64}  [\w./-]+", line) for line in lines)
    assert any(line.endswith("  webr.mjs") for line in lines)


def test_the_csp_allows_the_package_sources_and_nothing_else() -> None:
    origin = {name: f"https://{urlparse(r.package_url).netloc}" for name, r in RUNTIMES}
    app = _csp("@app")
    assert sorted(app["connect-src"]) == sorted(["'self'", origin["python"], origin["r"]])
    assert app["script-src"] == ["'self'", "'wasm-unsafe-eval'"]  # never eval on pages
    assert app["frame-ancestors"] == ["'none'"] and app["object-src"] == ["'none'"]
    # The R worker alone may eval (WebR links R's libraries with it), and
    # reaches only its own package source.
    webr = _csp("@webr")
    assert "'unsafe-eval'" in webr["script-src"]
    assert webr["connect-src"] == ["'self'", origin["r"]]
    assert "@webr path /runtimes/webr/*" in CADDY and "@app not path /runtimes/webr/*" in CADDY
