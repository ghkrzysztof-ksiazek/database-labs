#!/usr/bin/env bash
# Screenshot of the HAProxy stats page (needs a headless Chrome); used by run-experiments.sh via SHOT_CMD.
exec google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=1280,640 --screenshot="$1" http://127.0.0.1:18404/
