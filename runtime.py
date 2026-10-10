"""Shared paths and OS operations for source, packaged desktop and agent entry points."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

VERSION = '1.5.1'
APP_NAME = 'Spool'
# Windows shell identity is separate from service/data compatibility identifiers.
WINDOWS_APP_ID = 'Local.Spool.Desktop'
# Stable identifiers preserve existing installations, history and ADE tool config.
APP_ID = 'VideoDownloader'
ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('VIDEO_DOWNLOADER_PORT', '5780'))
URL = f'http://127.0.0.1:{PORT}'


def app_data_dir():
    if os.environ.get('VIDEO_DOWNLOADER_DATA_DIR'):
        return Path(os.environ['VIDEO_DOWNLOADER_DATA_DIR']).expanduser().resolve()
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'VideoDownloader'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'VideoDownloader'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'VideoDownloader'


DATA = app_data_dir()


def default_downloads():
    return Path.home() / 'Downloads' / 'VideoDownloader'


def binary(name):
    filename = name + ('.exe' if sys.platform == 'win32' else '')
    bundled = ROOT / 'tools' / filename
    return str(bundled) if bundled.is_file() else shutil.which(name)


def process_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}


def open_folder(path):
    path = Path(path).resolve()
    if not path.is_dir():
        raise ValueError('This folder no longer exists.')
    if sys.platform == 'win32':
        os.startfile(path)
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def command(*args):
    if getattr(sys, 'frozen', False):
        return [sys.executable, *args]
    executable = Path(sys.executable)
    if executable.name.lower() == 'pythonw.exe':
        executable = executable.with_name('python.exe')
    return [str(executable), str(ROOT / 'desktop.py'), *args]


def agent_configuration():
    cmd = command('--mcp')
    return {'mcpServers': {'video-downloader': {'command': cmd[0], 'args': cmd[1:]}}}


def private_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents a symlink from redirecting the initial write.
    staging = path.with_suffix('.tmp-' + __import__('uuid').uuid4().hex)
    descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        json.dump(data, handle)
    staging.replace(path)
