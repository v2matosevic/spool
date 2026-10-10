"""Build on the target OS. Produces one self-contained Windows ZIP or macOS app ZIP."""
import json
import argparse
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime import APP_NAME, VERSION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reuse-spotify', action='store_true')
    parser.add_argument('--release', action='store_true', help='Require audited release tools and corresponding source records')
    parser.add_argument('--work-root', type=Path, default=ROOT, help='Isolated build/output root; source stays in this repository')
    args = parser.parse_args()
    if sys.platform not in {'win32','darwin'}:
        raise SystemExit('Desktop packaging currently supports Windows and macOS.')
    from PIL import Image
    target = 'windows' if sys.platform == 'win32' else 'macos'
    tool_root = os.environ.get('SPOOL_RELEASE_TOOLS')
    source_root = os.environ.get('SPOOL_RELEASE_SOURCES')
    if args.release and (not tool_root or not source_root or not (Path(source_root)/'manifest.json').is_file()):
        raise SystemExit('Public builds require SPOOL_RELEASE_TOOLS and complete SPOOL_RELEASE_SOURCES.')
    tools = {name:(str(Path(tool_root)/(name+('.exe' if sys.platform=='win32' else ''))) if tool_root and name != 'node' else shutil.which(name)) for name in ('ffmpeg','ffprobe','node')}
    if args.release:
        for name in ('ffmpeg','ffprobe'):
            path = Path(tools[name])
            if not path.is_file() or not path.resolve().is_relative_to(Path(tool_root).resolve()):
                raise SystemExit('Missing audited release tool: '+name)
    if not all(tools.values()):
        raise SystemExit('Build prerequisites missing: ' + ', '.join(k for k,v in tools.items() if not v))
    work_root = args.work_root.resolve()
    build = work_root / 'build'
    dist = work_root / 'dist'
    # PyInstaller may replace these generated directories; never let them escape
    # the explicitly selected build root.
    assert build.resolve().is_relative_to(work_root) and dist.resolve().is_relative_to(work_root)
    build.mkdir(parents=True,exist_ok=True)
    helper_dir = ROOT / 'build/spotify-dist/SpotifyResolver'
    if args.reuse_spotify:
        helper = helper_dir / ('SpotifyResolver.exe' if sys.platform == 'win32' else 'SpotifyResolver')
        if not helper.is_file():
            raise SystemExit('No previously built Spotify helper is available to reuse.')
        print('Reusing the explicitly selected, previously verified Spotify helper.',flush=True)
    else:
        subprocess.run([sys.executable,str(ROOT / 'scripts/build_spotify.py')],check=True)
    dist.mkdir(parents=True,exist_ok=True)
    icon = build / ('icon.ico' if sys.platform == 'win32' else 'icon.icns')
    Image.open(ROOT / '.ade' / 'logo.png').save(icon)
    command = [sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--console','--name','VideoDownloader',
               '--distpath',str(dist),'--workpath',str(build / 'pyinstaller'),'--specpath',str(build),
               '--icon',str(icon),'--add-data',f'{ROOT / "static"}:static','--add-data',f'{ROOT / "templates"}:templates']
    if sys.platform == 'win32':
        command += ['--hide-console','hide-early']
        from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct
        version_tuple = tuple(int(part) for part in VERSION.split('.')) + (0,)
        resource = VSVersionInfo(ffi=FixedFileInfo(filevers=version_tuple,prodvers=version_tuple),kids=[
            StringFileInfo([StringTable('040904B0',[
                StringStruct('ProductName',APP_NAME),StringStruct('FileDescription',APP_NAME+' media downloader'),
                StringStruct('FileVersion',VERSION),StringStruct('ProductVersion',VERSION),
                StringStruct('OriginalFilename','VideoDownloader.exe')])]),
            VarFileInfo([VarStruct('Translation',[0x0409,1200])])])
        version_file = build / 'windows-version.txt'
        version_file.write_text(str(resource),encoding='utf-8')
        command += ['--version-file',str(version_file)]
    for path in tools.values():
        command += ['--add-binary',f'{path}:tools']
    for package in ('yt_dlp','yt_dlp_ejs','webview','mcp.server.mcpserver','mcp_types'):
        command += ['--collect-all',package]
    for package in ('yt-dlp','pywebview','mcp','curl_cffi','yt-dlp-ejs'):
        command += ['--copy-metadata',package]
    for package in ('PyQt5','PyQt6','PySide2','PySide6','gi','pytest','tkinter'):
        command += ['--exclude-module',package]
    command += [str(ROOT / 'desktop.py')]
    print(f'Building {target} {VERSION}; progress in {build / "packaging.log"}',flush=True)
    with (build / 'packaging.log').open('w',encoding='utf-8') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    payload = dist / 'VideoDownloader'
    if sys.platform == 'win32':
        from build_windows_launcher import build_launcher
        build_launcher(payload)
    shutil.copytree(helper_dir,payload / '_internal/spotify-resolver',dirs_exist_ok=True,symlinks=True)
    license_dir = payload / 'licenses'
    license_dir.mkdir(exist_ok=True)
    # Include installed distribution notices and original binary source locations.
    import importlib.metadata
    for distribution in importlib.metadata.distributions():
        for file in distribution.files or []:
            if '.dist-info/' in str(file).replace('\\','/') and any(word in file.name.lower() for word in ('license','copying','notice')):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    shutil.copy2(source,license_dir / (distribution.metadata['Name'] + '-' + file.name))
    if source_root:
        sources=Path(source_root)
        shutil.copytree(sources/'python-notices',license_dir,dirs_exist_ok=True)
        for notice in ('manifest.json','ffmpeg-license.txt','COPYING.LGPLv2.1','LAME-COPYING.txt','ffmpeg-version.txt'):
            shutil.copy2(sources/notice,license_dir/notice)
    (license_dir / 'BINARY-SOURCES.txt').write_text('Spool public source: https://github.com/v2matosevic/spool\nCorresponding third-party sources and build configuration accompany this version at https://github.com/v2matosevic/spool/releases\nFFmpeg: https://ffmpeg.org/\nNode.js: https://nodejs.org/\nPython: https://www.python.org/\nSee THIRD_PARTY_NOTICES.md and the exact-version source manifest.\n',encoding='utf-8')
    for doc in ('README.md','AGENTS.md','CLAUDE.md','LICENSE','SECURITY.md','THIRD_PARTY_NOTICES.md','CHANGELOG.md'):
        path = ROOT / doc
        if path.is_file():
            shutil.copy2(path,payload / path.name)
    shutil.copytree(ROOT / 'docs',payload / 'docs',dirs_exist_ok=True)
    if sys.platform == 'darwin':
        from mac_bundle import bundle_app
        app=bundle_app(ROOT,payload,helper_dir,build,dist,icon,APP_NAME,VERSION)
        archive = dist / f'{APP_NAME}-{VERSION}-macos-{platform.machine()}.zip'
        subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(archive)],check=True)
        staging = build / f'dmg-staging-{APP_NAME}'
        staging.mkdir(exist_ok=True)
        shutil.copytree(app,staging / app.name,dirs_exist_ok=True,symlinks=True)
        applications = staging / 'Applications'
        if not applications.exists() and not applications.is_symlink():
            applications.symlink_to('/Applications',target_is_directory=True)
        disk_image = dist / f'{APP_NAME}-{VERSION}-macos-{platform.machine()}.dmg'
        subprocess.run(['hdiutil','create','-volname',APP_NAME,'-srcfolder',str(staging),
                        '-ov','-format','UDZO',str(disk_image)],check=True)
    else:
        archive = Path(shutil.make_archive(str(dist / f'{APP_NAME}-{VERSION}-windows-x64'),'zip',dist,'VideoDownloader'))
    print(json.dumps({'artifact':str(archive),'bytes':archive.stat().st_size,'platform':target}),flush=True)


if __name__ == '__main__':
    main()
