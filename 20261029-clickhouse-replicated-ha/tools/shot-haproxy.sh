#!/usr/bin/env bash
# Screenshot of the HAProxy stats page (needs a headless Chrome or Chromium); used by run-experiments.sh via SHOT_CMD.
# Finds google-chrome / chromium on Linux, or Google Chrome in /Applications on macOS.
for c in google-chrome chromium chromium-browser "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
  if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then
    exec "$c" --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=1280,640 --screenshot="$1" http://127.0.0.1:18404/
  fi
done
echo "shot-haproxy.sh: no Chrome or Chromium found" >&2; exit 1
