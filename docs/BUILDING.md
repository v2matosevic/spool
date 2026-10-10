# Build and release

Build each desktop package on its target OS. Public release builds must originate from the public repository, never a workstation's private documentation or user-data directories. The desktop builder copies only repository docs/assets and distribution notices.

## Source prerequisites

Python 3.10+, Node, FFmpeg/ffprobe and a local .venv. Windows installer compilation needs Inno Setup 6 and the existing .NET Framework compiler. macOS uses clang, codesign, ditto and hdiutil. Source setup may use platform-aware requirements files; Windows lock snapshots are evidence of a Windows environment, not a universal Mac lock.

```text
python -m pip install -r requirements-build.txt -r requirements-dev.txt
python scripts/setup_spotify.py
python -m pytest -q
node --check static/app.js
python scripts/check_public.py
python scripts/build_desktop.py
```

On Windows, follow with `python scripts/build_installer.py`. On Mac the builder produces .app, ZIP and DMG. Install Spool.command builds locally and preserves an existing installed app. The source scripts do not install global prerequisites or change PATH.

## Public automation

CI tests Windows, Apple silicon and Intel Mac separately. Workflows pin third-party actions to full commit IDs, run repository/privacy checks, compile JavaScript syntax and verify Python behavior. Security scanning is independent of contributor-controlled pull-request code. Release builds use the explicit workflow dispatch and do not run on untrusted pull requests. Default workflow permissions are read-only; the final publication job alone gets release-write permission.

Release FFmpeg is built from pinned FFmpeg and LAME source with GPL/nonfree components disabled. It is a standalone LGPL tool, including MP3 support from libmp3lame. Sources, configuration, exact versions and SHA-256 hashes are archived with each release. No arbitrary workstation FFmpeg binary is accepted in a public build. Node/Python and installed Python dependency sources/notices are collected with their actual versions. The main and Spotify dependency inventories remain separate.

Set `SPOOL_RELEASE_TOOLS` to the release tools directory and `SPOOL_RELEASE_SOURCES` to its source-record directory when building public artifacts. `scripts/collect_sources.py` assembles third-party notices and source records. CI diagnostics use isolated user data so neither the build nor reports contain user history. Release version must match runtime.VERSION and the tag; publication fails on mismatch or a missing target.

## Required evidence

Source tests, public-file checks, JavaScript syntax, final executable diagnostics, tool dependency inspection, offline diagnostic export, stdio MCP initialization/schema check, synthetic FFmpeg audio conversions and an automated native desktop window/DOM/bridge check. The workflow's native_check option explicitly opts into opening/closing disposable test windows; disabling it builds artifacts without public publication. Mac signing/plist and DMG checks use the actual app. These do not establish a user's Finder/Gatekeeper first-run approval or a manual editor file drop. Do not describe those unperformed checks as passed.

`SHA256SUMS.txt` identifies uploaded assets; source/provenance archives enable inspection and rebuilding. Builds are recorded, not promised byte-for-byte reproducible. OS signing needs separate publisher certificates; no such secrets are required or shipped by this repository.
