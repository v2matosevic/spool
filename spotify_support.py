"""Spotify identifies the song; an isolated spotDL helper finds the audio source."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from runtime import DATA, ROOT, binary, process_options
import diagnostics as diag

SPOTIFY_HOSTS = {'open.spotify.com','www.open.spotify.com','spotify.link','spotify.app.link'}
_cache = {}
_lock = threading.Lock()


def is_spotify(url):
    return urlsplit(url).hostname in SPOTIFY_HOSTS


def canonical_track(url):
    parsed = urlsplit(url)
    if parsed.hostname not in {'open.spotify.com','www.open.spotify.com'}:
        raise ValueError('Use the full open.spotify.com track link.')
    match = re.fullmatch(r'/(?:intl-[A-Za-z-]+/)?track/([A-Za-z0-9]{22})/?',parsed.path)
    if not match:
        raise ValueError('Paste an individual Spotify song link. Albums, playlists and podcasts are not supported here yet; you can paste several track links as a batch.')
    return 'https://open.spotify.com/track/' + match[1]


def normalize_url(url):
    if not is_spotify(url):
        return url
    if urlsplit(url).hostname in {'spotify.link','spotify.app.link'}:
        from downloader import validate_url
        for _ in range(4):
            validate_url(url)
            if urlsplit(url).hostname in {'open.spotify.com','www.open.spotify.com'}:
                break
            if urlsplit(url).hostname not in SPOTIFY_HOSTS:
                raise ValueError('This Spotify share link redirects to an unexpected website.')
            parsed = urlsplit(url)
            # Keep the request authority literal after validation. Remote
            # redirects never choose a new request host outside this allowlist.
            origin = 'https://spotify.link' if parsed.hostname == 'spotify.link' else 'https://spotify.app.link'
            request_url = origin + parsed.path + ('?' + parsed.query if parsed.query else '')
            response = requests.get(request_url,allow_redirects=False,stream=True,timeout=12)
            try:
                if response.status_code not in {301,302,303,307,308} or 'Location' not in response.headers:
                    raise ValueError('Could not expand this Spotify share link. Paste its full track URL.')
                url = urljoin(request_url,response.headers['Location'])
            finally:
                response.close()
    return canonical_track(url)


def resolver_command():
    executable = ROOT / 'spotify-resolver' / ('SpotifyResolver.exe' if sys.platform == 'win32' else 'SpotifyResolver')
    if executable.is_file():
        return [str(executable)]
    python = ROOT / '.spotify-venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if python.is_file() and (ROOT / 'spotify_worker.py').is_file():
        return [str(python),str(ROOT / 'spotify_worker.py')]
    return None


def ready():
    return resolver_command() is not None


def audio_options(options):
    from downloader import AUDIO_MODES
    result = dict(options)
    if result['mode'] not in AUDIO_MODES:
        result['mode'] = 'mp3'
    result['subtitles'] = False
    return result


def validate_result(result):
    if not isinstance(result,dict):
        raise ValueError('The song matcher returned invalid data.')
    if not result.get('ok'):
        raise ValueError('Spotify matching failed: ' + str(result.get('error','No matching source was returned.'))[:700])
    track = result.get('track')
    if not isinstance(track,dict) or not isinstance(track.get('name'),str) or not track['name'].strip() or not isinstance(track.get('artists'),list) or not track['artists']:
        raise ValueError('Spotify returned incomplete track information.')
    if not all(isinstance(artist,str) for artist in track['artists']):
        raise ValueError('Spotify returned invalid artist information.')
    parsed = urlsplit(result.get('source_url',''))
    video_id = parse_qs(parsed.query).get('v',[''])[0]
    if parsed.scheme != 'https' or parsed.hostname not in {'www.youtube.com','youtube.com','music.youtube.com'} or parsed.path != '/watch' or not re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id):
        raise ValueError('The song matcher returned an unsupported source URL.')
    result['source_url'] = 'https://www.youtube.com/watch?v=' + video_id
    return result


def resolve_track(url):
    url = canonical_track(url)
    with _lock:
        cached = _cache.get(url)
        if cached and time.monotonic() - cached[0] < 1200:
            diag.record('spotify.cache_hit', source=diag.url_ref(url))
            return json.loads(json.dumps(cached[1]))
        command = resolver_command()
        if command is None:
            raise ValueError('Spotify matching is not installed. Run the updated installer or scripts/setup_spotify.py for a source installation.')
        cache_dir = DATA / 'spotify'
        cache_dir.mkdir(parents=True,exist_ok=True)
        request = {'url':url,'cache_dir':str(cache_dir),'ffmpeg':binary('ffmpeg'),'node':binary('node')}
        started = time.monotonic()
        diag.record('spotify.match_started', source=diag.url_ref(url))
        try:
            process = subprocess.run(command,input=json.dumps(request)+'\n',capture_output=True,text=True,
                                     encoding='utf-8',timeout=100,cwd=cache_dir,**process_options())
        except subprocess.TimeoutExpired as error:
            diag.failure('spotify.match_timeout', error, elapsed_ms=round((time.monotonic()-started)*1000))
            raise ValueError('Spotify matching took too long. Retry this track in a moment.') from None
        diag.record('spotify.helper_finished', 'warning' if process.returncode else 'info', exit_code=process.returncode,
                    elapsed_ms=round((time.monotonic()-started)*1000), stderr=process.stderr[-2000:] if process.returncode else None)
        try:
            result = validate_result(json.loads(process.stdout))
        except json.JSONDecodeError:
            raise ValueError('The Spotify matcher could not start. Reinstall the latest app bundle.') from None
        if len(_cache) >= 50:
            _cache.pop(next(iter(_cache)))
        _cache[url] = (time.monotonic(),result)
        return json.loads(json.dumps(result))


def summary(match, source_info, mode):
    track = match['track']
    expected = track.get('duration')
    actual = source_info.get('duration')
    if expected and actual and abs(actual-expected) > max(20,expected*.15):
        raise ValueError('The matched source has a different duration from the Spotify song. No file was downloaded; try the exact recording using its YouTube link.')
    return {'title':', '.join(track['artists']) + ' - ' + track['name'],
            'uploader':', '.join(track['artists']),'platform':'Spotify',
            'thumbnail':track.get('cover_url'),'source':'Matched YouTube audio · Spotify metadata',
            'matched_source_url':match['source_url'],'matched_source_title':source_info.get('title'),
            'spotify_url':track['url'],'spotify_id':track.get('song_id'),
            'album':track.get('album_name'),'output_mode':mode}


def cover_image(url):
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'i.scdn.co','image-cdn-ak.spotifycdn.com','image-cdn-fa.spotifycdn.com'}:
        return None
    with requests.get(url,stream=True,timeout=15,allow_redirects=False) as response:
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > 5 * 1024 * 1024:
                return None
        data = bytes(content)
        if data.startswith(b'\xff\xd8\xff'):
            return data,'image/jpeg'
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return data,'image/png'
    return None


def tag_audio(path, track, source_url, artwork=None):
    """Embed provenance, title/artist/album and cover without re-encoding audio."""
    import mutagen
    from mutagen.id3 import TIT2,TPE1,TALB,TPE2,TDRC,TRCK,TPOS,TSRC,TXXX,APIC
    from mutagen.mp4 import MP4,MP4Cover
    from mutagen.flac import FLAC,Picture
    from mutagen.mp3 import MP3
    from mutagen.wave import WAVE
    media = mutagen.File(path)
    if media is None:
        raise ValueError('Downloaded audio format could not be tagged.')
    if media.tags is None:
        media.add_tags()
    date = str(track.get('date') or track.get('year') or '')
    artist = track['artists']
    if isinstance(media,(MP3,WAVE)):
        for frame in (TIT2(encoding=3,text=track['name']),TPE1(encoding=3,text=artist),
                      TALB(encoding=3,text=track.get('album_name') or ''),TPE2(encoding=3,text=track.get('album_artist') or artist),
                      TDRC(encoding=3,text=date),TRCK(encoding=3,text=str(track.get('track_number') or '')),
                      TPOS(encoding=3,text=str(track.get('disc_number') or '')),
                      TXXX(encoding=3,desc='SPOTIFY_URL',text=track['url']),
                      TXXX(encoding=3,desc='AUDIO_SOURCE_URL',text=source_url)):
            media.tags.add(frame)
        if track.get('isrc'):
            media.tags.add(TSRC(encoding=3,text=track['isrc']))
        if artwork:
            media.tags.add(APIC(encoding=3,mime=artwork[1],type=3,desc='Cover',data=artwork[0]))
    elif isinstance(media,MP4):
        media.tags.update({'\xa9nam':[track['name']],'\xa9ART':artist,'\xa9alb':[track.get('album_name') or ''],
                           'aART':[track.get('album_artist') or artist[0]],'\xa9day':[date],
                           '----:com.apple.iTunes:SPOTIFY_URL':[track['url'].encode()],
                           '----:com.apple.iTunes:AUDIO_SOURCE_URL':[source_url.encode()]})
        if track.get('track_number'):
            media.tags['trkn'] = [(track['track_number'],track.get('tracks_count') or 0)]
        if artwork:
            media.tags['covr'] = [MP4Cover(artwork[0],imageformat=MP4Cover.FORMAT_JPEG if artwork[1]=='image/jpeg' else MP4Cover.FORMAT_PNG)]
    else:
        media.tags.update({'title':track['name'],'artist':artist,'album':track.get('album_name') or '',
                           'albumartist':track.get('album_artist') or artist[0],'date':date,
                           'spotify_url':track['url'],'audio_source_url':source_url})
        if track.get('track_number'):
            media.tags['tracknumber'] = str(track['track_number'])
        if artwork:
            picture = Picture()
            picture.data,picture.mime,picture.type = artwork[0],artwork[1],3
            if isinstance(media,FLAC):
                media.clear_pictures()
                media.add_picture(picture)
            else:
                media.tags['metadata_block_picture'] = [base64.b64encode(picture.write()).decode()]
    media.save()
