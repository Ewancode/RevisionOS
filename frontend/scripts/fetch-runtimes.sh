#!/bin/sh
# Downloads the pinned Python (Pyodide) and R (WebR) runtimes into
# public/runtimes/, so the app serves them from its own origin instead of a
# CDN (docs/security.md). Each archive's SHA-256 is checked before anything is
# unpacked; a mismatch stops here and nothing is installed.
#
# The versions must match backend/config/coding.yaml (a backend test checks).
# To upgrade: change a version and its SHA-256 here (for WebR, regenerate the
# manifest from the new version's files).
#
# Usage: sh scripts/fetch-runtimes.sh [destination]   (default public/runtimes)
# Already-present versions are skipped, so running it again is quick.
set -eu

PYODIDE_VERSION=314.0.7
PYODIDE_SHA256=2abdcc2e35208af406e07724cffa85bc582ced97e9028383ecf5462541393f95
PYODIDE_URL="https://github.com/pyodide/pyodide/releases/download/${PYODIDE_VERSION}/pyodide-core-${PYODIDE_VERSION}.tar.bz2"

# WebR's GitHub release archive is not the build its own site serves (it
# reports itself as 0.5.10-dev), so the site's 0.6.0 files are pinned one by
# one in webr-$WEBR_VERSION.sha256 (path and SHA-256 of each).
WEBR_VERSION=0.6.0
WEBR_URL="https://webr.r-wasm.org/v${WEBR_VERSION}"

DEST="${1:-public/runtimes}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

download() { # url sha256 file
  echo "Downloading $1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 -o "$3" "$1"
  else
    wget -q -O "$3" "$1"
  fi
  echo "$2  $3" | sha256sum -c - >/dev/null || {
    echo "Checksum mismatch for $1: refusing to install it." >&2
    exit 1
  }
}

target="$DEST/pyodide/$PYODIDE_VERSION"
if [ ! -f "$target/pyodide.mjs" ]; then
  download "$PYODIDE_URL" "$PYODIDE_SHA256" "$WORK/pyodide.tar.bz2"
  tar -xjf "$WORK/pyodide.tar.bz2" -C "$WORK" 2>/dev/null
  mkdir -p "$target"
  # Only what the browser loads (the archive also has a Node CLI).
  for f in pyodide.mjs pyodide.asm.mjs pyodide.asm.wasm pyodide-lock.json python_stdlib.zip package.json; do
    cp "$WORK/pyodide/$f" "$target/"
  done
  echo "Pyodide $PYODIDE_VERSION -> $target"
fi

target="$DEST/webr/$WEBR_VERSION"
if [ ! -f "$target/webr.mjs" ]; then
  manifest="$(cd "$(dirname "$0")" && pwd)/webr-$WEBR_VERSION.sha256"
  echo "Downloading WebR $WEBR_VERSION ($(wc -l < "$manifest") files)"
  src="$WORK/webr"
  while read -r sum path; do
    mkdir -p "$src/$(dirname "$path")"
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL --retry 3 -o "$src/$path" "$WEBR_URL/$path"
    else
      wget -q -O "$src/$path" "$WEBR_URL/$path"
    fi
  done < "$manifest"
  (cd "$src" && sha256sum -c "$manifest" >/dev/null) || {
    echo "Checksum mismatch in WebR: refusing to install it." >&2
    exit 1
  }
  # The site serves some files gzip-encoded (R.wasm), which browsers undo but
  # a download keeps: unpack any file that is gzip without being named .gz.
  # (The checksums above are of the files exactly as served.)
  find "$src" -type f ! -name '*.gz' | while read -r f; do
    if [ "$(head -c 2 "$f" | od -An -tx1 | tr -d ' \n')" = "1f8b" ]; then
      gunzip -c "$f" > "$f.plain" && mv "$f.plain" "$f"
    fi
  done
  mkdir -p "$(dirname "$target")"
  rm -rf "$target"
  mv "$src" "$target"
  echo "WebR $WEBR_VERSION -> $target"
fi
