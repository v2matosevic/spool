"""Freeze the isolated matching helper for inclusion in the single app bundle."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
python = ROOT / '.spotify-venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
if not python.is_file():
    subprocess.run([sys.executable,str(ROOT / 'scripts/setup_spotify.py')],check=True)
build = ROOT / 'build'
build.mkdir(exist_ok=True)
command = [str(python),'-m','PyInstaller','--noconfirm','--onedir','--console','--name','SpotifyResolver',
           '--distpath',str(build / 'spotify-dist'),'--workpath',str(build / 'spotify-build'),
           '--specpath',str(build)]
for package in ('spotdl','SpotipyFree','spotapi','ytmusicapi','pykakasi'):
    command += ['--collect-all',package]
for package in ('spotdl','spotipyfree','ytmusicapi','yt-dlp'):
    command += ['--copy-metadata',package]
for package in ('pytest','tkinter','spotdl.console','spotdl.utils.web','fastapi','starlette','uvicorn','anyio','datastar_py'):
    command += ['--exclude-module',package]
command += [str(ROOT / 'spotify_worker.py')]
with (build / 'spotify-packaging.log').open('w',encoding='utf-8') as log:
    subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
print('SpotifyResolver packaged.')
