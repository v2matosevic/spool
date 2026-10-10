"""Isolated spotDL metadata/matching helper. One JSON request in, one result out."""
import contextlib
import io
import json
import logging
from pathlib import Path
import re
import shlex
import sys
import types


def matching_api():
    """Load upstream matching without its unrelated console/web application.

    spotDL 4.5.2 imports its CLI from the library initializer. Spool only uses
    the matching API; keeping that CLI import would require vulnerable pinned
    FastAPI/Starlette dependencies that never serve requests in this helper.
    """
    if 'spotdl.console' not in sys.modules:
        console = types.ModuleType('spotdl.console')
        def unavailable(*args, **kwargs):
            raise RuntimeError('This helper provides matching only, not the spotDL CLI or web server.')
        console.console_entry_point = unavailable
        sys.modules['spotdl.console'] = console
    from spotdl import Spotdl
    from spotdl.types.song import Song
    return Spotdl, Song


def resolve(request):
    # The main process validates/canonicalizes URLs. Check again at the boundary.
    url = request.get('url','')
    if not re.fullmatch(r'https://open\.spotify\.com/track/[A-Za-z0-9]{22}',url):
        raise ValueError('Use an individual Spotify track link.')
    Spotdl, Song = matching_api()
    import spotdl.utils.config as config
    cache = Path(request['cache_dir'])
    cache.mkdir(parents=True,exist_ok=True)
    # Keep spotDL's internal caches inside this app's user-data directory.
    config.get_spotdl_path = lambda: cache
    spot = Spotdl(client_id='',client_secret='',headless=True,no_cache=True,
                  downloader_settings={'audio_providers':['youtube-music','youtube'],
                                       'lyrics_providers':[], 'threads':1,'format':'opus',
                                       'ffmpeg':request['ffmpeg'],'simple_tui':True,
                                       'yt_dlp_args':'--socket-timeout 15 --retries 1 --extractor-retries 1 --js-runtimes ' + shlex.quote('node:' + request['node'])})
    song = Song.from_url(url)
    match = spot.downloader.search(song)
    if not match:
        raise ValueError('No matching audio source was found for this Spotify track.')
    return {'track':{key:getattr(song,key,None) for key in (
        'name','artists','artist','album_name','album_artist','duration','year','date',
        'track_number','tracks_count','disc_number','disc_count','song_id','url','isrc','cover_url')},
        'source_url':match,'matcher':'spotDL 4.5.2'}


def main():
    logging.disable(logging.CRITICAL)
    if '--check-runtime' in sys.argv:
        matching_api()
        forbidden = {'fastapi','starlette','uvicorn','anyio'} & set(sys.modules)
        if forbidden:
            raise RuntimeError('Unneeded web stack loaded in matching helper.')
        print(json.dumps({'ok':True,'matching_api':'spotDL 4.5.2','web_stack_loaded':False}))
        return 0
    captured = io.StringIO()
    try:
        request = json.loads(sys.stdin.readline())
        # Third-party progress output must never corrupt the protocol or leak logs.
        with contextlib.redirect_stdout(captured),contextlib.redirect_stderr(captured):
            result = resolve(request)
        print(json.dumps({'ok':True,**result},ensure_ascii=True))
        return 0
    except Exception as error:
        message = re.sub(r'https?://\S+','[source link]',str(error))
        print(json.dumps({'ok':False,'error':message[:700]},ensure_ascii=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
