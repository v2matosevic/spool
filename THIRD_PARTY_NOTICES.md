# Third-party notices

Spool's application code is GPL-3.0-or-later. Dependencies keep their own licenses; the application license does not replace their notices.

| Component | Purpose | Upstream / license |
| --- | --- | --- |
| yt-dlp, yt-dlp-ejs | Maintained extraction | [yt-dlp](https://github.com/yt-dlp/yt-dlp), Unlicense and component notices |
| FFmpeg | Remuxing and audio conversion | [FFmpeg](https://ffmpeg.org/), public release configuration uses LGPL-2.1-or-later without GPL/nonfree components |
| LAME | MP3 encoder in standalone FFmpeg | [LAME](https://lame.sourceforge.io/), LGPL-2.0-or-later |
| Node.js | JavaScript extraction runtime | [Node.js](https://nodejs.org/), MIT and bundled third-party notices |
| Python | Frozen application runtime | [Python](https://www.python.org/), PSF and bundled notices |
| Flask, Waitress | Local HTTP service | [Flask](https://github.com/pallets/flask), BSD-3-Clause; [Waitress](https://github.com/Pylons/waitress), ZPL-2.1 |
| pywebview | Native web view | [pywebview](https://github.com/r0x0r/pywebview), BSD-3-Clause |
| MCP Python SDK | Agent transport | [MCP](https://github.com/modelcontextprotocol/python-sdk), MIT |
| curl_cffi | Platform networking | [curl_cffi](https://github.com/lexiforest/curl_cffi), MIT plus bundled curl/TLS notices |
| spotDL | Isolated Spotify metadata matching | [spotDL](https://github.com/spotDL/spotify-downloader), MIT and dependency notices |
| Mona Sans | Bundled interface font | [Mona Sans](https://github.com/github/mona-sans), SIL Open Font License 1.1; full notice in static/fonts |
| PyInstaller | Freezing/build tooling | [PyInstaller](https://github.com/pyinstaller/pyinstaller), GPL with bootloader exception |

Binary packages contain `licenses/`, actual dependency/source inventories and the application license. A companion third-party source archive accompanies every release. It includes exact FFmpeg/LAME source and build configuration, Node/Python source, available source distributions for the actual Python dependency versions and native vendor source references. See its manifest rather than assuming all platforms use identical dependencies.

Source-level setup uses your installed FFmpeg. Its configuration may have different obligations; never redistribute a local build just because its filename matches. [FFmpeg legal guidance](https://ffmpeg.org/legal.html). Binary releases do not include user data, cookies, private history or local agent credentials.
