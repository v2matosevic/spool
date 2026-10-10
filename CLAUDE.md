# Implementation contract

Spool is a local desktop downloader with a single loopback service and queue. Version comes from `runtime.VERSION`.

- Bind only to 127.0.0.1; retain Host, Origin, Fetch Metadata and mutation-token checks.
- Use maintained yt-dlp extractors. Do not fork platform extraction or promise every catalog URL works.
- Preserve original streams by default; remux rather than transcode video. Do not upscale or imply lossless conversion restores detail.
- Remove/Clear hide terminal history and never delete files; Undo survives restart. Active removal is rejected. Bulk retry skips cancellations.
- Preserve per-attempt queue tickets and reset stale progress. Flat batches keep a unique stable job suffix across conversion, subtitles and retry.
- Export only recorded existing non-symlink files from visible completed jobs, resolved inside the job folder.
- Display name is Spool; VideoDownloader executable/data ID, MCP key, installer AppId and Local.Spool.Desktop Windows shell ID stay stable.
- Windows desktop/menu uses the windowed Spool.exe launcher; CLI/MCP uses VideoDownloader.exe and clean stdio.
- Log through diagnostics.py with pre-storage redaction, bounded retention and fail-soft writes. No credentials, full URLs, argv, bodies, traceback locals or protocol-stdout logs.
- Cookie access is opt-in. Assets resolve beside runtime.py; mutable state lives in the OS user-data directory, never the package.
- Bind the listen socket before queue recovery. A losing concurrent launch must not alter a running queue.
- Native bridge exposes only choose_folder and guarded drag_files. Keep native window private as _window; Windows file dragging uses the UI thread and Copy only.
- Escape remote metadata. Preserve typed structuredContent and legacy stdio MCP compatibility.
- Spotify means metadata plus a matched YouTube recording; show provenance, reject playlist expansion and isolate spotDL dependencies.
- Build on each target OS; never infer Mac runtime support from Windows tests. Review package notices/source obligations before release.

Use the project .venv. Checks: `python -m pytest -q`, `node --check static/app.js`, `python scripts/check_public.py`, `git diff --check`. Packaging: `python scripts/build_desktop.py`, and on Windows `python scripts/build_installer.py`. See docs/BUILDING.md for public dependency/source records and artifact verification.
