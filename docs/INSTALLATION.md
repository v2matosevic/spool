# Install Spool

Use a published build from [GitHub Releases](https://github.com/v2matosevic/spool/releases). If no release is listed yet, use the source instructions in the README; CI artifacts are test candidates. Choose your OS and architecture. Check the release's verification notes before treating a build as a native UI test.

## Windows 10/11 x64

Run the Setup EXE for a per-user installation. No administrator privilege or automatic startup is requested. The portable ZIP contains the same app: extract everything, then run Spool.exe. Keep VideoDownloader.exe and _internal beside it. Microsoft Edge WebView2 Runtime and .NET Framework are prerequisites; [Microsoft's WebView2 download](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) supplies the runtime.

Fresh installs default to `%LOCALAPPDATA%\Programs\VideoDownloader`, and new download libraries default to your Downloads/VideoDownloader folder. Existing installation directories and saved library settings remain unchanged on upgrade. You can change the destination in Settings. User data remains in `%LOCALAPPDATA%\VideoDownloader`.

The EXE is unsigned. If Windows warns about an unknown publisher, first verify the repository URL and checksum. Only choose the per-file Run anyway action if you trust the source. Do not disable SmartScreen or antivirus.

## macOS 13+

Apple silicon uses the arm64 package; Intel uses x86_64. Open the DMG, drag Spool to Applications, then open it. ZIP packages are an alternative; move the extracted app to Applications. The release app bundles its runtime dependencies.

Spool is ad-hoc signed, not Developer ID signed or notarized. If Gatekeeper blocks the app, confirm its source/checksum, try Control-click the app → Open, or the per-app Open Anyway option in System Settings → Privacy & Security after the first attempted launch. A managed Mac may forbid this. Never disable Gatekeeper globally or strip quarantine recursively from other software. [Apple's guidance](https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unknown-developer-mh40616/mac).

Data lives in `~/Library/Application Support/VideoDownloader`; downloads default to `~/Downloads/VideoDownloader`. Native file dragging is implemented only on Windows. Mac users can use Copy path or Save a copy.

## Updates, removal and backups

There is no automatic updater. Finish active work and deliberately exit/restart the background service before replacing a running bundle. The app window closing alone does not stop the service. Install the new version over the existing program directory; keep user data separate. A version mismatch is reported instead of killing the older service automatically.

Uninstalling/removing program files preserves media and the separate data folder. Remove/Clear inside Spool hides history; it does not reclaim media disk space. Use SQLite online backup for a live history database, or copy it after a deliberate service exit. Private cookies, connection credentials and WebView storage must never be uploaded.

## Verify a download

Windows: `Get-FileHash .\Spool-VERSION-Setup.exe -Algorithm SHA256`. Mac: `shasum -a 256 Spool-VERSION-macos-arm64.dmg`. Compare the entire value to SHA256SUMS.txt on that release. Checksums do not replace publisher signing.

Troubleshooting: [diagnostics](LOGGING.md), [source setup/builds](BUILDING.md), [issue tracker](https://github.com/v2matosevic/spool/issues).
