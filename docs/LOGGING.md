# Spool diagnostics

Version 1.4 records local diagnostic evidence for desktop startup, download attempts, the queue, UI errors, CLI calls and MCP tools. It makes observed failure causes inspectable; it cannot reveal a platform's private reason for refusing a request, reconstruct events before logging was installed, or record a sudden power loss before the app can write.

## Find a failure

In the app, use **Details** beside a failed/cancelled/interrupted job. Settings → Diagnostics also has **View recent logs** and **Save diagnostic report**. Details includes earlier attempts, so a successful Retry does not erase the original failure. Reports are JSON and are saved locally; nothing is uploaded.

CLI examples, using the existing agent entry point:

```powershell
.\VideoDownloader.exe --cli diagnostics
.\VideoDownloader.exe --cli diagnostics --job JOB_ID
.\VideoDownloader.exe --cli diagnostics --request REQUEST_ID
.\VideoDownloader.exe --cli diagnostics --error ERROR_ID
.\VideoDownloader.exe --cli diagnostics --limit 2000 --output 'spool-report.json'
```

The output file must not already exist. The diagnostic CLI uses only Python's standard library and works without the service, downloader engine, WebView or MCP SDK importing successfully. Use `--connection-file` before the command for another instance's data directory; isolated tests also set `VIDEO_DOWNLOADER_DATA_DIR`.

MCP now exposes thirteen tools. `get_diagnostics(job_id?, request_id?, error_id?, limit=200)` reads the same local records without starting the service. Valid limit: 1–2000. It returns structured JSON and keeps protocol stdout clean. Agents should retrieve the failing job/reference, read its failed attempt and preceding engine events, then decide whether Retry, an input correction or an engine/dependency investigation is justified. Do not infer success from a queued job or enable a browser session without the owner's intent.

The UI/API route is authenticated `POST /api/diagnostics` with the same filters. Browser error reporting uses `POST /api/diagnostics/client-error`. Existing loopback, Host/Origin and local-token/bearer checks apply. Diagnostic API requests return `X-Spool-Request-ID`; handled API errors also return `error_id` and `request_id`.

## What is recorded

- Time in UTC, app version, component, process/session, event and severity.
- Each job's ID, attempt, originating UI/CLI/MCP request, safe options, source hostname and one-way URL fingerprint. No full source URL or media title is deliberately copied into structured job fields.
- Queue transitions, cancellation/control references, retries, interruption recovery, single-entry cleanup and bounded bulk-cleanup summaries. Cleanup summaries include a count and at most the first thirty IDs.
- Selected format IDs, protocols/codecs/resolution, engine/runtime details, sanitized engine warnings/errors, progress milestones per format, postprocessing stages, elapsed time, output count/bytes/extensions.
- Exception type, HTTP status when available, errno, bounded causal chain and traceback file/function/line. Tracebacks omit local variables and source-code lines.
- CLI validation categories, command success/failure/timeout; MCP tool start/end/failure, schema-rejection field names, and request/response references. Successful repetitive MCP status polling is sampled at most once per thirty seconds per tool/job; failures are always recorded.
- Early Windows launcher start/child PID, failure class/native code and early nonzero exit code. Its journal works before Python starts and shares child PIDs with the Python process records.

A typical failed agent download can be followed from `mcp.call_started` → `agent.request` → `job.queued` → `download.source_selected` → `download.failed`, using call/request/job IDs. A retry increments the attempt and gets its own request reference. Cancellation records the control request, not the original submission request.

## Storage, limits and privacy

Windows: `%LOCALAPPDATA%\VideoDownloader\logs`. macOS: `~/Library/Application Support/VideoDownloader/logs`. The stable data directory remains unchanged by the Spool name. `VIDEO_DOWNLOADER_DATA_DIR` overrides it for isolated tests.

Python components share `diagnostics.sqlite3`. SQLite/WAL coordinates independent service, CLI and MCP writers. Each write trims records older than thirty days, above 10,000 events, or above 32 MiB of serialized event content. SQLite indexes/free pages add overhead; a 96 MiB database-page ceiling and small WAL checkpoint target provide additional bounds. These are diagnostic limits, not media/history deletion. Early Windows startup uses `launcher.jsonl` and `launcher.previous.jsonl`, roughly 256 KiB each; exported startup history is limited to the most recent hundred records.

Credential-like fields, bearer values, cookies/header command arguments, full HTTP URLs, known local path prefixes and absolute Windows/user paths are redacted before Python records reach disk. Exception validation input values are removed. Engine debug capture is restricted to useful runtime/extraction/downloader/FFmpeg decisions; raw request bodies, cookies, headers, challenge payloads and format/CDN inventories are not collected. The early launcher writes only fixed metadata, never arguments, paths or exception messages.

Reports remain potentially sensitive: source hostnames, job/request references, timing and sanitized upstream messages can reveal activity. Redaction is not anonymization; inspect a report before sharing it. The export never copies `connection.json`, cookies, browser storage, downloaded media or old raw logs. Existing `server.log`/`desktop.log` files remain untouched; new service startup no longer appends raw output to `server.log`.

Logging failure must not break a download or the agent protocol. Failed diagnostic writes increment an in-process dropped counter and expose an unavailable status in Settings/API reports; later successful writes recover. Logging cannot persist its own error if the storage is inaccessible. Hard process termination can leave only an interrupted job on next startup. Frontend errors are limited to ten reports per minute and are best-effort while the service is reachable.

## Verification

`tests/test_diagnostics.py` covers pre-storage redaction, causal HTTP errors, count/size/age retention, concurrent writers, unavailable storage, request authentication/correlation, retry history, cancellation references, offline CLI/export, dependency-free diagnostics, agent error references, MCP structured results and schema errors. The Windows launcher probe checks that the GUI launcher still starts a console-capable child without allocating a console. Each release records its own checks and limits.
