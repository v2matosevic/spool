"""Small local wrapper around yt-dlp. Extraction stays upstream, never forked."""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import re
import shutil
import socket
from urllib.parse import urlsplit

import yt_dlp
from yt_dlp.utils import DownloadError
from runtime import ROOT, DATA, binary, default_downloads
import diagnostics as diag
from options import MODES, AUDIO_MODES, QUALITIES, BROWSERS

DEFAULT_DOWNLOADS = default_downloads()


class Cancelled(Exception):
    pass


def validate_url(value: str, *, resolve: bool = True) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError('Paste a video link, up to 4,096 characters.')
    value = value.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError('This link is not a valid web address.') from None
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a full http:// or https:// video link without a password.')
    if port not in (None, 80, 443):
        raise ValueError('Use the public video page, without a custom port.')
    host = parsed.hostname.lower()
    if host == 'localhost' or host.endswith(('.localhost', '.local')):
        raise ValueError('Use a public video link, not a local network address.')
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        if not resolve:
            return value
        try:
            addresses = [ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(host, None)]
        except socket.gaierror:
            raise ValueError('This website could not be reached. Check the link and your connection.') from None
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError('Use a public video link, not a local network address.')
    return value


def validate_options(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError('Download options must be an object.')
    options = {key: raw.get(key, default) for key, default in {
        'mode': 'original', 'quality': 'best', 'browser': 'none',
        'clean': True, 'subtitles': False,
    }.items()}
    if any(not isinstance(options[key], str) for key in ('mode', 'quality', 'browser')) or options['mode'] not in MODES or options['quality'] not in QUALITIES or options['browser'] not in BROWSERS:
        raise ValueError('Choose one of the available download options.')
    if not isinstance(options['clean'], bool) or not isinstance(options['subtitles'], bool):
        raise ValueError('Watermark and subtitle options must be on or off.')
    if options['browser'] == 'cookies' and not (DATA / 'cookies.txt').is_file():
        raise ValueError('Import a cookies.txt file in Settings first.')
    return options


def safe_error(error: Exception | str) -> str:
    message = re.sub(r'\x1b\[[0-9;]*m', '', str(error)).removeprefix('ERROR: ').strip()
    message = re.sub(r'https?://\S+', '[source link]', message)
    if any(word in message.lower() for word in ('dpapi', 'cookie database', 'decrypt', 'could not copy')):
        return 'The browser session could not be read. Try Firefox, or import a Netscape cookies.txt file in Settings. Chromium may lock or encrypt its cookies.'
    if 'requested format is not available' in message.lower():
        return 'No source matches these options. Try Original quality, a higher resolution limit, or turn off clean-source filtering.'
    if '[facebook]' in message.lower() and 'cannot parse data' in message.lower():
        return 'Facebook did not expose a downloadable video for this link. Try your logged-in browser session or a direct video/Reel link. Some Facebook pages currently fail in the download engine.'
    return message[:1000] or 'The download failed. Check the link and try again.'


def known_watermarked(fmt: dict) -> bool:
    note = str(fmt.get('format_note') or '').lower()
    return bool(fmt.get('has_watermark')) or 'watermark' in note


class SourceDownloader(yt_dlp.YoutubeDL):
    def __init__(self, params, *, clean=True, cancelled=lambda: False):
        self.clean = clean
        self.cancelled = cancelled
        super().__init__(params)

    def process_video_result(self, info_dict, download=True):
        if self.cancelled():
            raise Cancelled('Download cancelled.')
        if info_dict.get('is_live') or info_dict.get('live_status') == 'is_upcoming':
            raise DownloadError('This link is a live or upcoming stream. Try again after the broadcast ends.')
        formats = info_dict.get('formats') or []
        had_video = any(fmt.get('vcodec') != 'none' for fmt in formats)
        if self.clean:
            formats = [fmt for fmt in formats if not known_watermarked(fmt)]
            if had_video and not any(fmt.get('vcodec') != 'none' for fmt in formats):
                raise DownloadError('Only a watermarked video source is available. Turn off clean-source filtering to download it.')
            if info_dict.get('formats'):
                info_dict['formats'] = formats
        for fmt in formats:
            dims = [fmt.get(key) for key in ('width', 'height') if fmt.get(key)]
            if dims:
                fmt['short_edge'] = min(dims)
        return super().process_video_result(info_dict, download)


class QuietLogger:
    def __init__(self, warning=lambda value: None):
        self.on_warning = warning

    def debug(self, message):
        # Keep useful extractor/runtime decisions, not raw requests, challenge
        # payloads, command-line arguments, cookies or format/CDN inventories.
        if any(marker in message for marker in ('Downloading webpage', 'player API', 'm3u8 information',
               'yt-dlp version', 'exe versions:', 'JS runtimes:', 'JS Challenge Providers:', 'Request Handlers:',
               'ffmpeg command line:',
               'Invoking http downloader', 'Invoking hlsnative downloader', 'Some web client', 'SABR streaming')):
            diag.record('engine.detail', 'debug', message=message)

    def info(self, message):
        pass

    def warning(self, message):
        diag.record('engine.warning', 'warning', message=message)
        self.on_warning(safe_error(message))

    def error(self, message):
        diag.record('engine.error', 'error', message=message)


def engine_options(options: dict, *, directory: Path | None = None, progress=None, postprocess=None, warning=None, filename_tag=None) -> dict:
    limit = '' if options['quality'] == 'best' else f"[short_edge<=?{options['quality']}]"
    mode = options['mode']
    if mode in AUDIO_MODES:
        selection = 'ba/b'
    elif mode == 'mp4':
        avc = '[vcodec~="^(avc|h264)"]'
        selection = f'bv*[ext=mp4]{avc}{limit}+ba[ext=m4a]/b[ext=mp4]{avc}{limit}'
    elif mode == 'mp4-best':
        selection = f'bv*[ext=mp4]{limit}+ba[ext=m4a]/b[ext=mp4]{limit}'
    elif mode == 'webm':
        selection = f'bv*[ext=webm]{limit}+ba[ext=webm]/b[ext=webm]{limit}'
    else:
        selection = f'bv*{limit}+ba/b{limit}'
    params = {
        'format': selection, 'noplaylist': True, 'playlistend': 1,
        'quiet': True, 'no_warnings': False, 'noprogress': True, 'verbose': True,
        'logger': QuietLogger(warning or (lambda _: None)),
        'socket_timeout': 25, 'retries': 3, 'fragment_retries': 3,
        'extractor_retries': 2, 'concurrent_fragment_downloads': 3,
        'continuedl': True, 'overwrites': False,
        'windowsfilenames': True, 'trim_file_name': 160,
        'js_runtimes': {'node': {'path': binary('node') or 'node'}},
        'ffmpeg_location': str(Path(binary('ffmpeg')).parent) if binary('ffmpeg') else None,
        'merge_output_format': 'mp4' if mode in {'mp4', 'mp4-best'} else ('webm' if mode == 'webm' else 'mkv'),
        'postprocessors': [],
        'progress_hooks': [progress] if progress else [],
        'postprocessor_hooks': [postprocess] if postprocess else [],
    }
    if directory:
        # Flat jobs share a directory. A stable per-job suffix isolates their
        # final files and partial streams, including retries of the same source.
        suffix = f' [spool-{filename_tag}]' if filename_tag else ''
        stem = '%(title).90B [%(id).35B]' if filename_tag else '%(title).110B [%(id)s]'
        params['outtmpl'] = str(directory / (stem + suffix + '.%(ext)s'))
        if filename_tag:
            # yt-dlp's global trim counts the directory too and can cut off the
            # ownership suffix. The template already bounds the filename.
            params['trim_file_name'] = None
    if options['browser'] == 'cookies':
        # Read without telling yt-dlp to persist changes to the imported file.
        from http.cookiejar import MozillaCookieJar
        jar = MozillaCookieJar(str(DATA / 'cookies.txt'))
        jar.load(ignore_discard=True, ignore_expires=True)
        # Passed separately by create_engine below.
        params['_local_cookiejar'] = jar
    elif options['browser'] != 'none':
        params['cookiesfrombrowser'] = (options['browser'],)
    if mode in AUDIO_MODES:
        params['postprocessors'].append({'key': 'FFmpegExtractAudio', 'preferredcodec': 'best' if mode == 'audio' else mode, 'preferredquality': '0'})
    elif mode in {'mp4', 'mp4-best', 'mkv', 'webm'}:
        params['postprocessors'].append({'key':'FFmpegVideoRemuxer', 'preferedformat':'mp4' if mode.startswith('mp4') else mode})
    # Audio conversion is bounded; video modes only copy streams.
    params['postprocessor_args'] = {'ffmpeg_o':['-threads', '2']}
    if options['subtitles'] and mode not in AUDIO_MODES:
        params.update(writesubtitles=True, subtitleslangs=['en.*', 'hr.*'], subtitlesformat='srt/vtt/best')
    return params


def create_engine(options, **kwargs):
    cancelled = kwargs.pop('cancelled', lambda: False)
    params = engine_options(options, **kwargs)
    cookiejar = params.pop('_local_cookiejar', None)
    engine = SourceDownloader(params, clean=options['clean'], cancelled=cancelled)
    if cookiejar is not None:
        for cookie in cookiejar:
            engine.cookiejar.set_cookie(cookie)
    return engine


def video_info(info: dict) -> dict:
    if info.get('_type') in {'playlist', 'multi_video'} or info.get('entries') is not None:
        raise ValueError('Paste the link to one video, rather than a playlist or profile. You can paste multiple video links as a batch.')
    formats = info.get('formats') or []
    selected = info.get('requested_formats') or [info]
    size = sum(fmt.get('filesize') or fmt.get('filesize_approx') or 0 for fmt in selected)
    return {
        'title': info.get('title') or info.get('id') or 'Video',
        'uploader': info.get('uploader') or info.get('channel') or '',
        'duration': info.get('duration'), 'thumbnail': info.get('thumbnail'),
        'platform': info.get('extractor_key') or info.get('extractor') or 'Video',
        'width': info.get('width'), 'height': info.get('height'),
        'size': size or None, 'extension': info.get('ext'),
        'resolutions': sorted({min(f.get('width') or f.get('height') or 0, f.get('height') or f.get('width') or 0) for f in formats if f.get('vcodec') != 'none'} - {0}, reverse=True),
        'source': 'Known watermarked source' if any(known_watermarked(f) for f in selected) else ('Original playback source' if 'tiktok' in str(info.get('extractor_key', '')).lower() else 'Best matching source'),
    }


def inspect_video(url: str, options: dict) -> dict:
    from spotify_support import is_spotify, resolve_track, audio_options, summary
    warnings = []
    match = resolve_track(url) if is_spotify(url) else None
    if match:
        options = audio_options(options)
        url = match['source_url']
    with create_engine(options, warning=warnings.append) as engine:
        info = engine.extract_info(url, download=False)
        result = video_info(info)
        if match:
            result.update(summary(match,info,options['mode']))
    result['warnings'] = warnings[-3:]
    return result
