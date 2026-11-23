#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUTPUT="${1:-$ROOT/dist}"
APP="$OUTPUT/ZLibrary Workbench.app"
RESOURCES="$APP/Contents/Resources"
RUNTIME="${PYTHON_RUNTIME:-$(uv python find 3.14.9)}"
PREFIX="$(cd "$(dirname "$RUNTIME")/.." && pwd)"

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo "This build targets Apple Silicon macOS." >&2
  exit 1
fi

mkdir -p "$OUTPUT"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RESOURCES"
ditto "$PREFIX" "$RESOURCES/python"
uv export --quiet --project "$ROOT" --locked --extra desktop --no-dev --no-emit-project --no-header --format requirements.txt --output-file "$OUTPUT/desktop-requirements.txt"
uv pip install --python "$RUNTIME" --target "$RESOURCES/python/lib/python3.14/site-packages" --requirement "$OUTPUT/desktop-requirements.txt"
uv pip install --python "$RUNTIME" --target "$RESOURCES/python/lib/python3.14/site-packages" --no-deps "$ROOT"
swiftc -O -target arm64-apple-macos13.0 "$ROOT/packaging/macos/ZLibraryWorkbench.swift" -framework AppKit -framework WebKit -o "$APP/Contents/MacOS/ZLibraryWorkbench"
cp "$ROOT/packaging/macos/Info.plist" "$APP/Contents/Info.plist"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$RESOURCES/python/lib/python3.14/site-packages" "$RUNTIME" "$ROOT/packaging/macos/make_icon.py" "$OUTPUT/ZLibraryWorkbench.iconset"
iconutil -c icns "$OUTPUT/ZLibraryWorkbench.iconset" -o "$RESOURCES/AppIcon.icns"
rm -rf "$OUTPUT/ZLibraryWorkbench.iconset"
find "$RESOURCES/python" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$RESOURCES/python" -type f -name '*.pyc' -delete
find "$RESOURCES/python" -type f -name direct_url.json -delete
codesign --force --deep --sign - "$APP"
ditto -c -k --keepParent "$APP" "$OUTPUT/ZLibrary-Workbench-macOS-arm64.zip"
echo "$APP"
