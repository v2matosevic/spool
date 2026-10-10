# Contributing

Search existing issues before opening one. Include Spool version, OS/architecture, the selected format, reproducible steps and actual versus expected behavior. Share a public sample only if you have permission; replace private links with a minimal reproduction. Do not attach your data directory or cookies.

Use a project-local virtual environment and the commands in [README](README.md). Install `requirements-dev.txt`; Node and FFmpeg/ffprobe are source prerequisites. Spotify matching uses `.spotify-venv`, never the main MCP environment. Platform-dependent tests skip outside their target OS.

Keep changes focused. Run `python -m pytest -q`, `node --check static/app.js`, `python scripts/check_public.py` and `git diff --check`. UI changes also need an actual browser check. Packaging changes need checks of the resulting executable on its target OS. Tests do not establish native UI behavior or universal platform availability.

Preserve loopback/auth checks, redaction and clean protocol stdout. Remove/Clear must never delete media. Cancellation must not silently retry. Keep stable executable/data identifiers and installer AppId. Build on each target OS; PyInstaller is not a cross-compiler.

Document behavior changes and verification scope. Do not commit media, user databases, secrets, environment directories or build artifacts. GitHub Actions use read-only permissions by default and release publication requires the explicit release workflow.

By contributing, you license your contribution under GPL-3.0-or-later. Be respectful and keep discussion about the work.
