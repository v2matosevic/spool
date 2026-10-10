import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
import app
import runtime
from agent_client import AgentClient
from downloader import SourceDownloader, engine_options, validate_options
from platforms import platform_data


@pytest.fixture
def client(tmp_path):
    application = app.create_app(tmp_path,start_worker=False)
    client = application.test_client()
    client.token = application.extensions['agent_token']
    client.headers = {'Authorization':'Bearer ' + client.token}
    client.store = application.extensions['store']
    client.store.set_folder(str(tmp_path / 'downloads'))
    return client


def test_agent_auth_and_cross_origin_are_independent(client,tmp_path):
    assert client.post('/api/settings',json={'folder':str(tmp_path / 'a')},headers=client.headers).status_code == 200
    assert client.post('/api/settings',json={'folder':str(tmp_path / 'b')},headers={'Authorization':'Bearer invalid'}).status_code == 403
    assert client.post('/api/settings',json={'folder':str(tmp_path / 'c')},headers={**client.headers,'Origin':'https://example.com'}).status_code == 403
    assert 'token' not in client.get('/api/integrations').json


def test_platform_search_is_real_engine_catalog(client):
    response = client.get('/api/platforms?q=bluesky').json
    assert response['matched'] >= 1
    assert all('bluesky' in (item['name']+item['description']).lower() for item in response['results'])
    assert {'YouTube','TikTok','Bluesky','Soundcloud'} <= {item['name'] for item in response['featured']}


def test_per_batch_folder_does_not_change_default(client,tmp_path,monkeypatch):
    monkeypatch.setattr(app,'validate_url',lambda url:url)
    monkeypatch.setattr(app,'binary',lambda name:name)
    default = client.store.folder()
    response = client.post('/api/jobs',json={'urls':['https://example.com/test'],'folder':str(tmp_path / 'batch')},headers=client.headers)
    assert response.status_code == 201
    job = response.json['jobs'][0]
    assert Path(job['folder']).parent == tmp_path / 'batch'
    assert client.store.folder() == default
    assert client.get('/api/jobs/' + job['id']).json['file_paths'] == []


def test_invalid_output_option_is_rejected(client,monkeypatch):
    monkeypatch.setattr(app,'validate_url',lambda url:url)
    response = client.post('/api/jobs',json={'urls':['https://example.com/test'],'options':{'mode':['mp4']}},headers=client.headers)
    assert response.status_code == 400


@pytest.mark.parametrize('mode,codec',[('audio','best'),('mp3','mp3'),('m4a','m4a'),('flac','flac'),('wav','wav')])
def test_audio_options(mode,codec):
    params = engine_options(validate_options({'mode':mode}))
    assert params['postprocessors'][0]['preferredcodec'] == codec
    assert params['format'] == 'ba/b'


@pytest.mark.parametrize('mode,target',[('mkv','mkv'),('mp4','mp4'),('mp4-best','mp4'),('webm','webm')])
def test_explicit_video_container_is_remuxed(mode,target):
    params = engine_options(validate_options({'mode':mode}))
    assert params['postprocessors'] == [{'key':'FFmpegVideoRemuxer','preferedformat':target}]


def test_clean_filter_accepts_audio_only_sources():
    info = {'id':'track','title':'Audio track','extractor':'test','formats':[{'format_id':'a','url':'https://example.com/audio.mp3','ext':'mp3','vcodec':'none','acodec':'mp3'}]}
    with SourceDownloader(engine_options(validate_options({'mode':'audio'}))) as engine:
        result = engine.process_video_result(info,download=False)
    assert result['format_id'] == 'a'


def test_mp4_accepts_h264_codec_spelling():
    info = {'id':'test','title':'Test','extractor':'test','formats':[{'format_id':'p','url':'https://example.com/video.mp4','ext':'mp4','vcodec':'h264','acodec':'aac','width':720,'height':1280}]}
    with SourceDownloader(engine_options(validate_options({'mode':'mp4'}))) as engine:
        assert engine.process_video_result(info,download=False)['format_id'] == 'p'


@pytest.mark.parametrize('url',['https://evil.example','http://127.0.0.1.evil.example','http://user@127.0.0.1:5780','http://127.0.0.1:5780/evil','file:///tmp/file'])
def test_agent_credential_never_sent_to_remote_host(tmp_path,url):
    connection = tmp_path / 'connection.json'
    connection.write_text(json.dumps({'url':url,'token':'x'*40}))
    with pytest.raises(ValueError):
        AgentClient(connection,autostart=False).connection()


def test_native_picker_callback(client,tmp_path):
    application = app.create_app(tmp_path / 'picker',start_worker=False,folder_picker=lambda:str(tmp_path))
    picker = application.test_client()
    headers = {'Authorization':'Bearer ' + application.extensions['agent_token']}
    assert picker.post('/api/pick-folder',json={},headers=headers).json['folder'] == str(tmp_path)
    assert client.post('/api/pick-folder',json={},headers=client.headers).status_code == 409


def test_packaged_binary_resolution(tmp_path,monkeypatch):
    tools = tmp_path / 'tools'
    tools.mkdir()
    filename = 'ffmpeg.exe' if sys.platform=='win32' else 'ffmpeg'
    (tools / filename).write_bytes(b'test')
    monkeypatch.setattr(runtime,'ROOT',tmp_path)
    assert runtime.binary('ffmpeg') == str(tools / filename)


def test_native_bridge_exposes_only_guarded_file_actions():
    from desktop import DesktopAPI
    bridge = DesktopAPI()
    bridge._window = object()
    assert [name for name in dir(bridge) if not name.startswith('_')] == ['choose_folder', 'drag_files']


def test_mcp_tools_register_and_call_through_sdk(monkeypatch):
    from mcp import Client
    import mcp_server
    class FakeClient:
        def request(self,path,body=None):
            return {'path':path,'body':body}
    monkeypatch.setattr(mcp_server,'client',lambda:FakeClient())
    async def run():
        async with Client(mcp_server.mcp) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {'download_videos','download_status','supported_platforms','set_download_folder'} <= names
            result = await client.call_tool('download_videos',{'urls':['https://example.com/video'],'output_format':'mkv'})
            assert not result.is_error
            assert result.structured_content['body']['options']['mode'] == 'mkv'
    asyncio.run(run())
