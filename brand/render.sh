#!/usr/bin/env bash
# Render brand/*.html to PNG with headless Chrome.
#   OG images -> app/static/og/   (served as og:image)
#   Ads       -> brand/out/       (campaign assets)
set -euo pipefail
cd "$(dirname "$0")/.."
CHROME="${CHROME:-google-chrome}"
mkdir -p app/static/og brand/out

render() { # src width height out
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --virtual-time-budget=15000 --run-all-compositor-stages-before-draw --window-size="$2,$3" \
    --screenshot="$PWD/$4" "file://$PWD/$1" >/dev/null 2>&1
  echo "rendered $4"
}

render brand/og-es.html 1200 630 app/static/og/og-es.png
render brand/og-en.html 1200 630 app/static/og/og-en.png
render brand/ad-square-es.html 1080 1080 brand/out/ad-square-es.png
render brand/banner-970x250-es.html 970 250 brand/out/banner-970x250-es.png
