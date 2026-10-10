# Security policy

The latest release receives fixes. Older packaged engines are not automatically updated. The app is designed for a trusted single-user desktop, not shared hosting or a public listener.

## Report a vulnerability

Use [private vulnerability reporting](https://github.com/v2matosevic/spool/security/advisories/new). Include the affected version, OS, reproducible steps and impact. Do not publish credentials, cookies, signed media URLs, personal history or unredacted diagnostics in an issue. A response deadline is not promised.

## Local boundary

Spool binds to `127.0.0.1`. Host, Origin, Fetch Metadata and request-token checks guard browser mutations. Local CLI/MCP uses a rotating credential stored in `connection.json`. The private descriptor is never a shareable MCP config. File export validates completed-job ownership, resolved paths and symlinks. Metadata is untrusted and escaped by the interface.

Source URLs are checked before extraction. Extractors and redirected media requests contact remote servers, so this remains a desktop trust boundary, not a hardened network sandbox. Keep yt-dlp and dependencies current. Cookies are accessed only when selected; do not grant an agent account-session access by default.

History, cookie files, WebView storage and local diagnostic reports can contain personal information. Redaction lowers disclosure risk; inspect a report before sharing it. Keep private data-directory backups private. There is no telemetry or automatic report upload.

## Distribution

Download only from this repository's release page. Verify the published SHA-256 checksums. Checksums detect a mismatch; they are not publisher identity or a signing certificate. Windows builds lack Authenticode signing and Mac builds use ad-hoc signing without notarization. Never disable OS security globally to install Spool.
