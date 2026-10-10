import copy
import json
from pathlib import Path
import re
import threading

import pytest

import app as module
import downloader
from downloader import SourceDownloader, engine_options, validate_options, validate_url, video_info


@pytest.fixture
def client(tmp_path):
    app = module.create_app(tmp_path, start_worker=False)
    app.config['TESTING'] = True
    client = app.test_client()
    html = client.get('/').text
    client.token = re.search(r'name="local-token" content="([^"]+)"', html)[1]
    client.local_headers = {'X-Local-Token': client.token}
    client.store = app.extensions['store']
    client.downloads = app.extensions['downloads']
    client.store.set_folder(str(tmp_path / 'downloads'))
    return client


@pytest.mark.parametrize('url', ['file:///C:/Windows/win.ini','ftp://example.com/a','http://localhost/a','http://127.0.0.1/','http://[::1]/','http://10.0.0.1/','https://user:pass@example.com/','https://example.com:9000/','https://[broken/','-o evil','http://169.254.169.254/'])
def test_reject_unsafe_urls(url):
    with pytest.raises(ValueError):
        validate_url(url, resolve=False)


def test_dns_cannot_point_to_private_network(monkeypatch):
    monkeypatch.setattr(downloader.socket, 'getaddrinfo', lambda *_: [(2, 1, 6, '', ('192.168.1.2', 0))])
    with pytest.raises(ValueError, match='public'):
        validate_url('https://example.com/video')


def test_local_api_protection(client):
    assert client.get('/api/health').json['app'] == 'VideoDownloader'
    assert client.get('/', headers={'Host': 'evil.test'}).status_code == 403
    assert client.post('/api/jobs', json={}).status_code == 403
    assert client.post('/api/jobs', json={}, headers={**client.local_headers, 'Origin':'https://evil.test'}).status_code == 403
    assert client.get('/api/state', headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403
    assert client.get('/', headers={'Sec-Fetch-Site':'cross-site', 'Sec-Fetch-Mode':'navigate'}).status_code == 200
    assert "frame-ancestors 'none'" in client.get('/').headers['Content-Security-Policy']


def test_bad_batch_is_atomic(client, monkeypatch):
    monkeypatch.setattr(module, 'validate_url', lambda url: validate_url(url, resolve=False))
    response = client.post('/api/jobs', json={'urls':['https://youtube.com/watch?v=test', 'file:///bad']}, headers=client.local_headers)
    assert response.status_code == 400
    assert client.store.jobs() == []


def test_dedupe_cancel_retry_and_persist(client, monkeypatch):
    monkeypatch.setattr(module, 'validate_url', lambda url: validate_url(url, resolve=False))
    monkeypatch.setattr(module.shutil, 'which', lambda name: name)
    body = {'urls':['https://youtube.com/watch?v=test'] * 2}
    response = client.post('/api/jobs', json=body, headers=client.local_headers)
    assert response.status_code == 201
    job = response.json['jobs'][0]
    assert len(response.json['jobs']) == 1
    assert client.post('/api/jobs', json=body, headers=client.local_headers).json['jobs'] == []
    assert client.post(f"/api/jobs/{job['id']}/retry", json={}, headers=client.local_headers).status_code == 400
    assert client.post(f"/api/jobs/{job['id']}/cancel", json={}, headers=client.local_headers).json['status'] == 'cancelled'
    assert client.post(f"/api/jobs/{job['id']}/retry", json={}, headers=client.local_headers).json['status'] == 'queued'
    assert module.Store(client.store.path.parent).get(job['id'])['status'] == 'queued'


def info(formats):
    return {'id':'test','title':'Test','extractor':'test','extractor_key':'TikTok', 'webpage_url':'https://example.com/video', 'formats':formats}


def fmt(format_id, width, height, note=None, vcodec='h264', acodec='aac', ext='mp4'):
    return {'format_id':format_id,'url':f'https://example.com/{format_id}.{ext}','width':width,'height':height,'format_note':note,'vcodec':vcodec,'acodec':acodec,'ext':ext}


def test_clean_source_over_watermarked_high_resolution():
    params = engine_options(validate_options({}))
    with SourceDownloader(params) as engine:
        result = engine.process_video_result(info([fmt('play',720,1280),fmt('download',1080,1920,'watermarked')]), download=False)
    assert result['format_id'] == 'play'
    assert video_info(result)['source'] == 'Original playback source'


def test_only_watermarked_source_fails_closed():
    with SourceDownloader(engine_options(validate_options({}))) as engine:
        with pytest.raises(Exception, match='Only a watermarked'):
            engine.process_video_result(info([fmt('download',1080,1920,'watermarked')]), download=False)


def test_opt_out_allows_watermarked_source():
    with SourceDownloader(engine_options(validate_options({'clean':False})), clean=False) as engine:
        result = engine.process_video_result(info([fmt('download',1080,1920,'watermarked')]), download=False)
    assert video_info(result)['source'] == 'Known watermarked source'


def test_resolution_limit_uses_short_edge_for_portrait():
    with SourceDownloader(engine_options(validate_options({'quality':'1080'}))) as engine:
        result = engine.process_video_result(info([fmt('hd',720,1280),fmt('fhd',1080,1920),fmt('4k',2160,3840)]), download=False)
    assert result['format_id'] == 'fhd'


def test_best_video_merges_separate_audio():
    with SourceDownloader(engine_options(validate_options({}))) as engine:
        result = engine.process_video_result(info([fmt('combined',640,360),fmt('video',3840,2160,acodec='none'),fmt('audio',None,None,vcodec='none',ext='m4a')]), download=False)
    assert {f['format_id'] for f in result['requested_formats']} == {'video','audio'}


def test_mp4_mode_selects_compatible_codecs():
    with SourceDownloader(engine_options(validate_options({'mode':'mp4'}))) as engine:
        result = engine.process_video_result(info([fmt('av1',3840,2160,vcodec='av01'),fmt('h264',1920,1080,vcodec='avc1.640028')]), download=False)
    assert result['format_id'] == 'h264'


@pytest.mark.parametrize('payload', [{'_type':'playlist','entries':[]}, {'_type':'multi_video','entries':[]}])
def test_profiles_playlists_rejected(payload):
    with pytest.raises(ValueError, match='one video'):
        video_info(payload)


def test_live_stream_rejected():
    with SourceDownloader(engine_options(validate_options({}))) as engine:
        with pytest.raises(Exception, match='live or upcoming'):
            engine.process_video_result({'is_live':True}, download=False)


def test_worker_success_and_failure(client, monkeypatch):
    class FakeEngine:
        def __init__(self, directory): self.directory = directory
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def extract_info(self, url, download=False): return {'title':'Safe title', 'id':'one', 'ext':'mp4'}
        def process_info(self, info): (self.directory / 'video.mp4').write_bytes(b'test')
    monkeypatch.setattr(module, 'create_engine', lambda options, **kwargs: FakeEngine(kwargs['directory']))
    job = client.downloads.enqueue(['https://example.com/a'], validate_options({}))[0]
    client.downloads.run(job['id'])
    result = client.store.get(job['id'])
    assert result['status'] == 'completed'
    assert result['files'] == ['video.mp4']
    assert client.get(f"/api/jobs/{job['id']}/files/0").data == b'test'
    assert client.get(f"/api/jobs/{job['id']}/files/9").status_code == 400
    result['files'] = ['../history.sqlite3']
    client.store.save(result)
    assert client.get(f"/api/jobs/{job['id']}/files/0").status_code == 400
    def fail(*_, **__): raise RuntimeError('Source is unavailable')
    monkeypatch.setattr(module, 'create_engine', fail)
    second = client.downloads.enqueue(['https://example.com/b'], validate_options({}))[0]
    client.downloads.run(second['id'])
    assert client.store.get(second['id'])['status'] == 'failed'


def test_restart_marks_work_interrupted(tmp_path, monkeypatch):
    store = module.Store(tmp_path)
    worker = module.Downloads(store, start_worker=False)
    job = worker.enqueue(['https://example.com/a'], validate_options({}))[0]
    monkeypatch.setattr(threading.Thread, 'start', lambda self: None)
    module.Downloads(store)
    assert store.get(job['id'])['status'] == 'interrupted'


def test_imported_cookie_is_loaded_without_rewriting(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, 'DATA', tmp_path)
    content = '# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t2147483647\tsession\tdummy\n'
    (tmp_path / 'cookies.txt').write_text(content)
    with downloader.create_engine(validate_options({'browser':'cookies'})) as engine:
        assert [c.name for c in engine.cookiejar] == ['session']
    assert (tmp_path / 'cookies.txt').read_text() == content


def test_settings_rejects_relative_path(client):
    assert client.post('/api/settings', json={'folder':'relative/path'}, headers=client.local_headers).status_code == 400


def test_error_redacts_signed_urls():
    assert 'secret' not in downloader.safe_error('Failed https://cdn.example.com/a?token=secret')
