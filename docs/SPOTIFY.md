# Spotify track matching

Spotify links supply metadata. The isolated spotDL helper finds a matching YouTube recording, and Spool downloads that recording's audio. It never obtains Spotify's protected audio stream.

Paste an individual open.spotify.com/track link, including locale-prefixed/short share links. A batch can contain individual tracks. Albums, playlists and podcasts are rejected. Video-format selections become MP3 for Spotify jobs; explicit audio formats are preserved. Preview shows the match title/source URL. Check it when a particular version or remaster matters.

Tags include title, artists, album, date/track data, cover when available and source provenance. Matching is heuristic and may fail or choose another recording; substantial duration mismatches fail before downloading. Lossless outputs cannot restore upstream quality. No API key or Spotify login is required for public-track metadata; explicitly selected sessions apply only to the final media download.

spotDL is kept in .spotify-venv with an explicit matching-only dependency set. Its upstream 4.5.2 initializer imports the CLI, which normally pulls in obsolete FastAPI/Starlette web packages. Spool blocks that unused CLI import before loading the unchanged matching library; it does not run spotDL's CLI/web application. setup_spotify.py installs the audited matching dependencies, then the upstream library with --no-deps. Do not install the full spotDL console dependency set into this environment. Packaged releases exclude the same web modules and verify their absence at helper startup.

Run python scripts/setup_spotify.py for source use. Existing environments are preserved; use a fresh environment for a release rather than assuming an old environment lost unused packages. Packaged releases include the isolated helper in _internal/spotify-resolver. The helper emits only narrow JSON; matched source URLs are restricted to HTTPS YouTube, covers to known Spotify image hosts and 5 MiB. Lyrics fetching is disabled.

Upstream: [spotDL](https://github.com/spotDL/spotify-downloader). Live matching depends on changing remote endpoints; source tests and packaging checks are not a promise for every recording or account.
