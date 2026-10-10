#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import flask, webview, yt_dlp, mcp' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
if [ ! -x .spotify-venv/bin/python ]; then
  .venv/bin/python scripts/setup_spotify.py
fi
exec .venv/bin/python desktop.py
