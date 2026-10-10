"""Generate a deterministic asset inventory, checksums and release text."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime import VERSION


def main():
    dist=ROOT/'dist'
    tag=sys.argv[1]
    if tag!='v'+VERSION:
        raise SystemExit('Tag must match runtime.VERSION.')
    required=[f'Spool-{VERSION}-Setup.exe',f'Spool-{VERSION}-windows-x64.zip',
              f'Spool-{VERSION}-macos-arm64.dmg',f'Spool-{VERSION}-macos-arm64.zip',
              f'Spool-{VERSION}-macos-x86_64.dmg',f'Spool-{VERSION}-macos-x86_64.zip']
    for name in required:
        if not (dist/name).is_file():raise SystemExit('Missing target artifact: '+name)
    native=list(dist.glob('Spool-*-native-verification.json'))
    if len(native)!=3 or any(not json.loads(p.read_text())['passed'] for p in native):
        raise SystemExit('All three native window checks must pass before public release.')
    archive=dist/f'Spool-{VERSION}-source.zip'
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
        for relative in tracked:
            if not relative:continue
            path=ROOT/relative
            info=zipfile.ZipInfo('Spool/'+relative)
            info.create_system=3;info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100755 if path.suffix in {'.command','.sh'} else 0o100644)<<16
            output.writestr(info,path.read_bytes())
    files=sorted(path for path in dist.iterdir() if path.is_file() and path.name!='SHA256SUMS.txt' and path.suffix in {'.exe','.zip','.dmg','.json','.png'})
    (dist/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in files),encoding='utf-8')
    text=f'''Spool {VERSION}: local video and audio downloads with a persistent queue, library, JSON CLI and thirteen MCP tools.

Choose **Setup.exe** or **windows-x64.zip** for Windows 10/11 x64. Choose **macos-arm64.dmg** for Apple silicon or **macos-x86_64.dmg** for Intel, on macOS 13+. Mac ZIPs are also supplied. The source ZIP is for development, not a prebuilt app.

Windows packages are unsigned. Mac packages are ad-hoc signed and not Apple-notarized. Verify SHA256SUMS.txt, then follow the per-app [installation instructions](https://github.com/v2matosevic/spool/blob/{tag}/docs/INSTALLATION.md). Do not disable OS protection globally.

Each native target passed source tests, bundled executable diagnostics, offline export, the 13-tool MCP handshake, synthetic MP3/M4A/FLAC/WAV conversions and an automated native window/DOM/bridge check. Verification JSONs record exact scope. A user's first Gatekeeper/SmartScreen launch, account cookies, every upstream site and manual editor drops are not established by those checks.

Source and corresponding third-party source archives accompany the binaries. The release uses standalone LGPL FFmpeg with GPL/nonfree components disabled; [license notices](https://github.com/v2matosevic/spool/blob/{tag}/THIRD_PARTY_NOTICES.md) describe all components. No private development history or user data is included.

There is no automatic updater. Preserve active downloads and deliberately exit the old service before replacing its program files. History and media remain in their separate user folders.
'''
    (ROOT/'build/release-notes.md').write_text(text,encoding='utf-8')
    print(f'Validated {len(required)} desktop artifacts and created source/checksums.')


if __name__=='__main__':main()
