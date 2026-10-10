#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ "$(uname -s)" != Darwin ]; then
  echo 'This installer runs on macOS.'
  exit 1
fi
for tool in python3 ffmpeg ffprobe node; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing prerequisite: $tool. Install it before running this app installer."
    exit 1
  fi
done
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or newer is required"'
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python scripts/build_desktop.py
task_destination="$HOME/Applications/Spool.app"
mkdir -p "$HOME/Applications"
if [ -e "$task_destination" ]; then
  echo "An app already exists at $task_destination. It was preserved."
  echo 'The new app and installer DMG are in the dist folder.'
  open dist
  exit 0
fi
ditto dist/Spool.app "$task_destination"
# Existing agent configurations use this stable bundle path.
task_legacy="$HOME/Applications/VideoDownloader.app"
if [ ! -e "$task_legacy" ] && [ ! -L "$task_legacy" ]; then
  ln -s "$task_destination" "$task_legacy"
fi
open "$task_destination"
