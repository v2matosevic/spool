from pathlib import Path
import sys

import pytest

import app
from downloader import create_engine, engine_options, validate_options


@pytest.fixture
def manager(tmp_path):
    store = app.Store(tmp_path / 'state')
    store.set_folder(str(tmp_path / 'downloads'))
    return app.Downloads(store, start_worker=False)


def test_flat_batch_destination_deduplication_and_retry(manager, tmp_path):
    options = validate_options({})
    first, second = manager.enqueue(['https://example.com/a', 'https://example.com/b'], options, flat=True)
    assert first['folder'] == second['folder'] == str(manager.store.folder())
    assert manager.enqueue([first['url']], options, flat=True) == []
    nested = manager.enqueue([first['url']], options)[0]
    assert Path(nested['folder']).parent == manager.store.folder()
    elsewhere = manager.enqueue([first['url']], options, tmp_path / 'batch only', flat=True)[0]
    assert Path(elsewhere['folder']) == tmp_path / 'batch only'
    assert manager.store.folder() != Path(elsewhere['folder'])
    manager.update(first['id'], status='failed')
    retry = manager.retry(first['id'])
    assert retry['flat'] is True and retry['folder'] == first['folder']
    # Old history has no new fields and must retain active deduplication.
    nested.pop('destination')
    nested.pop('flat')
    manager.store.save(nested)
    assert manager.enqueue([first['url']], options) == []


def test_flat_jobs_only_record_their_files_and_keep_neighbours(manager, monkeypatch):
    first, second = manager.enqueue(['https://example.com/a', 'https://example.com/b'], validate_options({}), flat=True)
    neighbour = manager.store.folder() / 'existing.mp4'
    neighbour.write_bytes(b'original')
    class Engine:
        def __init__(self, directory, tag): self.directory, self.tag = directory, tag
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def extract_info(self, *_, **__): return {'id':'same source', 'title':'same title', 'ext':'mp4'}
        def process_info(self, _):
            for extension in ('mp4', 'en.vtt'):
                (self.directory / f'Same [spool-{self.tag}].{extension}').write_bytes(self.tag.encode())
    monkeypatch.setattr(app, 'create_engine', lambda options, **kw: Engine(kw['directory'], kw['filename_tag']))
    for job in (first, second):
        manager.run(job['id'])
        saved = manager.store.get(job['id'])
        assert saved['status'] == 'completed'
        assert len(saved['files']) == 2
        assert all(job['id'] in name for name in saved['files'])
    assert len(list(manager.store.folder().iterdir())) == 5
    assert neighbour.read_bytes() == b'original'
    manager.remove(first['id'])
    assert len(list(manager.store.folder().iterdir())) == 5


def test_flat_empty_output_cannot_claim_a_neighbours_video(manager, monkeypatch):
    job = manager.enqueue(['https://example.com/a'], validate_options({}), flat=True)[0]
    (manager.store.folder() / 'somebody-else.mp4').write_bytes(b'existing')
    class Engine:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def extract_info(self, *_, **__): return {'id':'one', 'title':'Video', 'ext':'mp4'}
        def process_info(self, _): pass
    monkeypatch.setattr(app, 'create_engine', lambda *_, **__: Engine())
    manager.run(job['id'])
    saved = manager.store.get(job['id'])
    assert saved['status'] == 'failed'
    assert saved['files'] == []
    assert 'without producing' in saved['error']


def test_flat_template_is_unique_bounded_and_retry_stable(tmp_path):
    options = validate_options({})
    info = {'title':'Very long title ' * 50, 'id':'long-source-id' * 50, 'ext':'mp4'}
    with create_engine(options, directory=tmp_path, filename_tag='012345abcdef') as engine:
        first = engine.prepare_filename(info)
        assert '[spool-012345abcdef].mp4' in first
        assert len(Path(first).name.encode()) < 160
        assert engine.prepare_filename(info) == first
    with create_engine(options, directory=tmp_path, filename_tag='abcdef012345') as engine:
        assert engine.prepare_filename(info) != first
    assert '[spool-' not in engine_options(options, directory=tmp_path)['outtmpl']


def test_file_paths_endpoint_requires_token_and_validates_live_files(tmp_path):
    application = app.create_app(tmp_path / 'state', start_worker=False)
    manager = application.extensions['downloads']
    manager.store.set_folder(str(tmp_path / 'media'))
    job = manager.enqueue(['https://example.com/a'], validate_options({}), flat=True)[0]
    path = manager.store.folder() / 'video.mp4'
    path.write_bytes(b'test')
    manager.update(job['id'], status='completed', files=[path.name])
    client = application.test_client()
    route = f"/api/jobs/{job['id']}/file-paths"
    headers = {'Authorization':'Bearer ' + application.extensions['agent_token']}
    assert client.post(route, json={'indexes':[0]}).status_code == 403
    assert client.post(route, json={'indexes':[0]}, headers=headers).json['file_paths'] == [str(path)]
    for indexes in ([], [-1], [1], [True], '0'):
        assert client.post(route, json={'indexes':indexes}, headers=headers).status_code == 400
    moved = path.with_name('moved.mp4')
    path.rename(moved)
    assert client.post(route, json={'indexes':[0]}, headers=headers).status_code == 400
    assert client.get(f"/api/jobs/{job['id']}/files/0").status_code == 400
    manager.update(job['id'], files=['../state/history.sqlite3'])
    assert client.post(route, json={'indexes':[0]}, headers=headers).status_code == 400
    manager.update(job['id'], files=[moved.name], status='downloading')
    assert client.post(route, json={'indexes':[0]}, headers=headers).status_code == 400
    manager.update(job['id'], status='completed', removed_at='removed')
    assert client.post(route, json={'indexes':[0]}, headers=headers).status_code == 400


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows shell data format')
def test_native_drag_payload_contains_real_files_and_text(tmp_path):
    import clr
    clr.AddReference('System.Windows.Forms')
    from System.Windows.Forms import DataFormats
    from desktop import _file_drop_data
    paths = [str(tmp_path / 'A file.mp4'), str(tmp_path / 'čćž.mp4')]
    data = _file_drop_data(paths)
    assert data.GetDataPresent(DataFormats.FileDrop)
    assert list(data.GetFileDropList()) == paths
    assert data.GetData(DataFormats.UnicodeText) == '\r\n'.join(paths)


def test_flat_api_and_agent_arguments(manager, monkeypatch):
    import agent_cli
    import mcp_server
    from types import SimpleNamespace
    class Client:
        def request(self, path, body): return {'path':path, 'body':body}
    monkeypatch.setattr(mcp_server, 'client', lambda: Client())
    result = mcp_server.download_videos(['https://example.com/a'], folder=str(manager.store.folder()), flat=True)
    assert result['body']['flat'] is True
    assert result['body']['folder'] == str(manager.store.folder())
    monkeypatch.setattr(agent_cli, 'AgentClient', lambda *_, **__: Client())
    assert agent_cli.main(['download', 'https://example.com/a', '--flat']) == 0
    with pytest.raises(ValueError, match='on or off'):
        manager.enqueue(['https://example.com/a'], validate_options({}), flat='true')
