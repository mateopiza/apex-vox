#!/usr/bin/env bash
# package-extension.sh — Empaqueta la versión de producción (versionenvio) en un archivo ZIP limpio para Chrome Web Store.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROD_DIR="$EXT_ROOT/versionenvio"

VERSION=$(python3 -c "import json; print(json.load(open('$PROD_DIR/manifest.json'))['version'])")
OUTPUT_ZIP="$PROD_DIR/apex-box-v${VERSION}-chrome-webstore.zip"

rm -f "$OUTPUT_ZIP"

cd "$PROD_DIR"
zip -r -q "$OUTPUT_ZIP" \
  manifest.json \
  service-worker.js \
  content/ \
  icons/ \
  recorder/ \
  -x "*.DS_Store" -x "Thumbs.db" -x "*.zip" -x "*.map" -x "*.md"

echo "✅ Paquete listo para Chrome Web Store: $OUTPUT_ZIP ($(du -h "$OUTPUT_ZIP" | cut -f1))"
