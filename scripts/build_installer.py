"""Compile the existing desktop bundle into a per-user Windows installer."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime import APP_NAME, VERSION

parser = argparse.ArgumentParser()
parser.add_argument('--payload-dir',type=Path,default=ROOT / 'dist/VideoDownloader')
parser.add_argument('--output-dir',type=Path,default=ROOT / 'dist')
args = parser.parse_args()
payload = args.payload_dir.resolve()
output = args.output_dir.resolve()
output.mkdir(parents=True,exist_ok=True)

if sys.platform != 'win32':
    raise SystemExit('Windows installer compilation must run on Windows.')
compiler = shutil.which('ISCC')
if not compiler:
    candidates = [Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)')) / 'Inno Setup 6' / 'ISCC.exe',
                  Path(os.environ.get('LOCALAPPDATA','')) / 'Programs' / 'Inno Setup 6' / 'ISCC.exe']
    compiler = next((str(path) for path in candidates if path.is_file()),None)
if not compiler:
    raise SystemExit('Inno Setup is required. No global tools are installed automatically.')
if not (payload / 'VideoDownloader.exe').is_file():
    raise SystemExit('Run scripts/build_desktop.py first.')
if not (payload / 'Spool.exe').is_file():
    raise SystemExit('The windowed Spool.exe launcher is missing. Run scripts/build_windows_launcher.py.')
(ROOT / 'build').mkdir(exist_ok=True)
with (ROOT / 'build/installer.log').open('w',encoding='utf-8') as log:
    subprocess.run([compiler,'/Q',f'/O{output}',f'/DAppVersion={VERSION}',f'/DAppNameValue={APP_NAME}',
                    f'/DPayloadDir={payload}',f'/DIconFile={ROOT / "static/spool.ico"}',str(ROOT / 'packaging/windows.iss')],
                   cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
print(output / f'{APP_NAME}-{VERSION}-Setup.exe')
