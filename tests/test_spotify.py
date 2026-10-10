import copy
import json
import subprocess
from pathlib import Path

import pytest

import app
import downloader
import spotify_support as spotify

URL = 'https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT'
MATCH = {'ok':True,'track':{'name':'Test song','artists':['Test Artist'],'artist':'Test Artist',
         'album_name':'Test album','album_artist':'Test Artist','duration':210,'date':'2020-01-01',
         'year':2020,'track_number':1,'tracks_count':5,'disc_number':1,'disc_count':1,
         'song_id':'4cOdK2wGLETKBW3PvgPWqT','url':URL,'isrc':None,'cover_url':None},
         'source_url':'https://www.youtube.com/watch?v=dQw4w9WgXcQ','matcher':'spotDL 4.5.2'}


def test_spotify_canonicalization():
    assert spotify.canonical_track(URL+'?si=tracking') == URL
    assert spotify.canonical_track(URL.replace('/track/','/intl-en/track/')) == URL
    assert not spotify.is_spotify('https://open.spotify.com.evil.example/track/x')


@pytest.mark.parametrize('target',['https://evil.example/track/x','http://127.0.0.1/private','https://spotify.link.evil.example/x'])
def test_share_redirect_never_requests_an_unapproved_host(monkeypatch,target):
    from types import SimpleNamespace
    calls=[]
    closed=[]
    monkeypatch.setattr(downloader,'validate_url',lambda url:url)
    def get(url,**kwargs):
        calls.append((url,kwargs))
        return SimpleNamespace(status_code=302,headers={'Location':target},close=lambda:closed.append(True))
    monkeypatch.setattr(spotify.requests,'get',get)
    with pytest.raises(ValueError,match='unexpected website'):
        spotify.normalize_url('https://spotify.link/example')
    assert len(calls)==1 and calls[0][0]=='https://spotify.link/example'
    assert calls[0][1]['allow_redirects'] is False and calls[0][1]['stream'] is True
    assert closed==[True]


def test_share_redirect_returns_only_a_canonical_track(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(downloader,'validate_url',lambda url:url)
    monkeypatch.setattr(spotify.requests,'get',lambda url,**kwargs:SimpleNamespace(status_code=302,headers={'Location':URL+'?si=tracking'},close=lambda:None))
    assert spotify.normalize_url('https://spotify.app.link/example')==URL


@pytest.mark.parametrize('value',['https://open.spotify.com/playlist/123','https://open.spotify.com/album/123','https://open.spotify.com/episode/123','https://open.spotify.com/track/bad'])
def test_non_track_spotify_links_rejected(value):
    with pytest.raises(ValueError,match='individual Spotify'):
        spotify.canonical_track(value)


@pytest.mark.parametrize('value',['http://127.0.0.1/a','https://evil.example/watch?v=dQw4w9WgXcQ','file:///song.mp3','https://www.youtube.com/watch?v=bad'])
def test_matcher_output_must_be_a_real_youtube_url(value):
    result = copy.deepcopy(MATCH)
    result['source_url'] = value
    with pytest.raises(ValueError):
        spotify.validate_result(result)


def test_empty_or_wrong_matcher_response_fails():
    for value in ([],None,{'ok':False,'error':'Unavailable'},{'ok':True,'track':{},'source_url':MATCH['source_url']}):
        with pytest.raises(ValueError):
            spotify.validate_result(value)


def test_spotify_maps_video_to_mp3_preserves_audio():
    assert spotify.audio_options(downloader.validate_options({}))['mode'] == 'mp3'
    assert spotify.audio_options(downloader.validate_options({'mode':'m4a'}))['mode'] == 'm4a'
    assert spotify.audio_options(downloader.validate_options({'mode':'audio'}))['mode'] == 'audio'


def test_wrong_duration_is_rejected_before_downloading():
    with pytest.raises(ValueError,match='different duration'):
        spotify.summary(MATCH,{'duration':90,'title':'Wrong clip'},'mp3')
    result = spotify.summary(MATCH,{'duration':214,'title':'Matching title'},'mp3')
    assert result['source'] == 'Matched YouTube audio · Spotify metadata'
    assert result['matched_source_title'] == 'Matching title'


def test_preview_keeps_spotify_and_source_provenance(monkeypatch):
    monkeypatch.setattr(spotify,'resolve_track',lambda url:copy.deepcopy(MATCH))
    class Engine:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def extract_info(self,url,download=False):
            assert url == MATCH['source_url']
            return {'title':'YouTube match','id':'dQw4w9WgXcQ','duration':210,'ext':'webm'}
    monkeypatch.setattr(downloader,'create_engine',lambda *args,**kwargs:Engine())
    result = downloader.inspect_video(URL,downloader.validate_options({}))
    assert result['title'] == 'Test Artist - Test song'
    assert result['platform'] == 'Spotify'
    assert result['output_mode'] == 'mp3'
    assert result['matched_source_url'] == MATCH['source_url']


def test_mixed_batch_preserves_video_and_selects_audio_for_spotify(tmp_path):
    store = app.Store(tmp_path)
    worker = app.Downloads(store,start_worker=False)
    jobs = worker.enqueue(['https://youtube.com/watch?v=abc',URL],downloader.validate_options({'mode':'mp4'}))
    assert [j['options']['mode'] for j in jobs] == ['mp4','mp3']


def test_api_blocks_spotify_if_helper_is_missing(tmp_path,monkeypatch):
    application = app.create_app(tmp_path,start_worker=False)
    client = application.test_client()
    monkeypatch.setattr(app,'validate_url',lambda url:url)
    monkeypatch.setattr(spotify,'ready',lambda:False)
    headers = {'Authorization':'Bearer '+application.extensions['agent_token']}
    response = client.post('/api/jobs',json={'urls':[URL]},headers=headers)
    assert response.status_code == 400
    assert 'not installed' in response.json['error']


def test_worker_downloads_match_and_tags_media(tmp_path,monkeypatch):
    store = app.Store(tmp_path)
    store.set_folder(str(tmp_path/'downloads'))
    worker = app.Downloads(store,start_worker=False)
    monkeypatch.setattr(spotify,'resolve_track',lambda url:copy.deepcopy(MATCH))
    tagged=[]
    monkeypatch.setattr(spotify,'tag_audio',lambda path,track,source,artwork:tagged.append((path,track,source)))
    class Engine:
        def __init__(self,directory): self.directory=directory
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def extract_info(self,url,download=False):
            assert url == MATCH['source_url']
            return {'title':'YouTube title','id':'dQw4w9WgXcQ','duration':210,'ext':'mp3'}
        def process_info(self,info):
            assert info['title'] == 'Test Artist - Test song'
            (self.directory/'song.mp3').write_bytes(b'media')
    monkeypatch.setattr(app,'create_engine',lambda options,**kwargs:Engine(kwargs['directory']))
    job = worker.enqueue([URL],downloader.validate_options({}))[0]
    worker.run(job['id'])
    result=store.get(job['id'])
    assert result['status']=='completed'
    assert result['matched_source_url']==MATCH['source_url']
    assert tagged[0][1]['name']=='Test song'
    assert result['options']['mode']=='mp3'


@pytest.mark.parametrize('extension,codec',[('mp3','libmp3lame'),('m4a','aac'),('flac','flac'),('wav','pcm_s16le'),('opus','libopus')])
def test_real_audio_tags_and_cover_roundtrip(tmp_path,extension,codec):
    import mutagen
    from runtime import ROOT,binary,process_options
    if not binary('ffmpeg'):
        pytest.skip('FFmpeg is required for metadata roundtrip checks.')
    file=tmp_path/('tone.'+extension)
    subprocess.run([binary('ffmpeg'),'-hide_banner','-loglevel','error','-f','lavfi','-i',
                    'sine=frequency=400:duration=0.15','-c:a',codec,'-threads','1',str(file)],
                   capture_output=True,check=True,**process_options())
    artwork=((ROOT/'.ade/logo.png').read_bytes(),'image/png')
    spotify.tag_audio(file,MATCH['track'],MATCH['source_url'],artwork)
    tagged=mutagen.File(file)
    assert tagged.info.length > 0
    if extension in {'mp3','wav'}:
        assert str(tagged.tags['TIT2']) == 'Test song'
        assert str(tagged.tags['TPE1']) == 'Test Artist'
        assert tagged.tags.getall('APIC')
        assert str(tagged.tags['TXXX:AUDIO_SOURCE_URL']) == MATCH['source_url']
    elif extension == 'm4a':
        assert tagged.tags['\xa9nam'] == ['Test song']
        assert tagged.tags['covr']
        assert tagged.tags['----:com.apple.iTunes:AUDIO_SOURCE_URL'][0].decode() == MATCH['source_url']
    else:
        assert tagged.tags['title'] == ['Test song']
        assert tagged.tags['audio_source_url'] == [MATCH['source_url']]
        assert tagged.pictures if extension=='flac' else tagged.tags['metadata_block_picture']
