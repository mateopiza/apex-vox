#!/usr/bin/env bash
# package-extension.sh — Genera el ZIP para Chrome Web Store desde extension/, sin permisos de localhost.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$EXT_ROOT/.." && pwd)"

OUTPUT_ZIP="$(python3 "$REPO_ROOT/app/services/extension_package.py" "$EXT_ROOT" "$REPO_ROOT/dist")"

echo "✅ Paquete listo para Chrome Web Store: $OUTPUT_ZIP ($(du -h "$OUTPUT_ZIP" | cut -f1))"
