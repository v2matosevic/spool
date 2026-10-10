import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import HTTPError

import pytest

import app
import diagnostics as diag
from downloader import validate_options


@pytest.fixture(autouse=True)
def isolated_default(monkeypatch):
    monkeypatch.setattr(diag, 'DEFAULT', None)
    token = diag.CONTEXT.set({})
    yield
    diag.CONTEXT.reset(token)


def test_redaction_before_disk_and_report(tmp_path):
    logs = diag.LogStore(tmp_path)
    secrets = ['sensitive-cookie','private-password','fake-access-key','signed-secret','private-bearer']
    logs.event('test', cookie=secrets[0], nested={'password':secrets[1], 'api_key':secrets[2]},
               message='HTTP Error 403 https://cdn.example/video?sig='+secrets[3]+' Bearer '+secrets[4],
               path=r'D:\Personal\Secret folder\video.mp4', value=float('nan'))
    report = json.dumps(logs.report())
    with sqlite3.connect(logs.path) as conn:
        stored = conn.execute('SELECT data FROM events').fetchone()[0]
    for text in secrets+[r'Personal', 'cdn.example/video']:
        assert text not in stored and text not in report
    assert logs.read()[0]['value'] is None
    assert 'private-cookie' not in diag.redact("ffmpeg -cookies 'SID=private-cookie; domain=example.com' -i https://example.com/")


def test_exception_chain_keeps_http_status_frames_without_source_urls(tmp_path):
    logs = diag.LogStore(tmp_path)
    try:
        try:
            raise HTTPError('https://cdn.example/media?token=private',403,'Forbidden',{},None)
        except HTTPError as error:
            raise RuntimeError('Download failed') from error
    except RuntimeError as error:
        error_id = logs.failure('download.failed', error, job_id='abc123', attempt=1)
    event = logs.read(error_id=error_id)[0]
    assert event['error']['category'] == 'upstream_forbidden'
    assert event['error']['http_status'] == 403
    assert event['error']['chain'][0]['frames']
    assert 'https://' not in json.dumps(event)
    assert event['attempt'] == 1


def test_retention_bounds_count_bytes_and_age(tmp_path):
    logs = diag.LogStore(tmp_path, max_events=3, max_bytes=2000)
    for i in range(12):
        logs.event('event', number=i, message='x'*200)
    with sqlite3.connect(logs.path) as conn:
        count, size = conn.execute('SELECT count(*),sum(bytes) FROM events').fetchone()
        assert count <= 3 and size <= 2000
        conn.execute('UPDATE events SET time=?',(time.time()-31*86400,))
    logs.event('fresh')
    assert [event['event'] for event in logs.read()] == ['fresh']


def test_concurrent_writers_preserve_events(tmp_path):
    # Separate store instances emulate separate CLI/MCP writers to one file.
    writers = [diag.LogStore(tmp_path) for _ in range(4)]
    def write(writer):
        for n in range(20):
            assert writer.event('parallel', number=n)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write,writers))
    assert len(writers[0].read(limit=200)) == 80


def test_separate_processes_write_one_diagnostic_store(tmp_path):
    import subprocess
    import sys
    code = '''import sys
from diagnostics import LogStore
store=LogStore(sys.argv[1])
for i in range(25):
    assert store.event('process.concurrent',number=i), store.last_error
'''
    processes=[subprocess.Popen([sys.executable,'-c',code,str(tmp_path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(4)]
    for process in processes:
        stdout,stderr=process.communicate(timeout=30)
        assert process.returncode==0,(stdout,stderr)
    events=diag.LogStore(tmp_path).read(limit=200)
    assert len(events)==100 and len({event['pid'] for event in events})==4


def test_logging_failure_is_visible_and_does_not_raise(tmp_path):
    (tmp_path/'logs').write_text('not a directory')
    logs = diag.LogStore(tmp_path)
    assert logs.event('test') is None
    assert logs.status()['available'] is False
    assert logs.status()['dropped_events'] == 1
    assert logs.read() == []


def test_invalid_cli_arguments_are_logged_without_the_rejected_value(tmp_path,monkeypatch,capsys):
    from agent_cli import main
    logs=diag.LogStore(tmp_path)
    monkeypatch.setattr(diag,'DEFAULT',logs)
    with pytest.raises(SystemExit):
        main(['inspect','https://example.com','--format','private-value'])
    capsys.readouterr()
    events=logs.read()
    assert any(event['event']=='cli.invalid_arguments' for event in events)
    assert 'private-value' not in json.dumps(events)
    assert 'private-value' not in diag.redact("Input invalid [input_value='private-value', input_type=str]")


def test_api_reference_authentication_and_no_credentials(tmp_path,monkeypatch):
    application = app.create_app(tmp_path,start_worker=False)
    client = application.test_client()
    headers = {'Authorization':'Bearer '+application.extensions['agent_token'],
               'X-Spool-Client':'mcp','X-Spool-Request-ID':'a'*32}
    assert client.post('/api/diagnostics',json={}).status_code == 403
    denied = application.extensions['downloads'].logs.read()
    assert any(event.get('response_error')=='Refresh this page to reconnect to the app.' for event in denied)
    failed = client.post('/api/jobs',headers=headers,json={'urls':[]})
    assert failed.status_code == 400 and failed.json['error_id']
    assert failed.headers['X-Spool-Request-ID'] == 'a'*32
    report = client.post('/api/diagnostics',headers=headers,json={'request_id':'a'*32}).json
    assert any(event['event']=='api.failed' and event['client']=='mcp' for event in report['events'])
    assert application.extensions['agent_token'] not in json.dumps(report)
    assert client.post('/api/diagnostics',headers=headers,json={'limit':True}).status_code == 400


def test_download_failure_and_retry_keep_both_attempts(tmp_path,monkeypatch):
    store = app.Store(tmp_path)
    store.set_folder(str(tmp_path/'downloads'))
    downloads = app.Downloads(store,start_worker=False)
    class Engine:
        failed = True
        def __init__(self,directory): self.directory=directory
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def extract_info(self,*args,**kwargs):
            return {'title':'Test','id':'example','ext':'mp4','format_id':'251'}
        def process_info(self,info):
            if self.failed:
                raise HTTPError('https://cdn.example/media?sig=secret',403,'Forbidden',{},None)
            (self.directory/'video.mp4').write_bytes(b'fixture')
    monkeypatch.setattr(app,'create_engine',lambda options,**kwargs:Engine(kwargs['directory']))
    with diag.context(request_id='b'*32,client='mcp'):
        job = downloads.enqueue(['https://example.com/video'],validate_options({}))[0]
    downloads.run(job['id'])
    failed = store.get(job['id'])
    assert failed['status']=='failed' and failed['error_id']
    assert downloads.logs.read(error_id=failed['error_id'])[0]['error']['http_status']==403
    Engine.failed=False
    with diag.context(request_id='c'*32,client='cli'):
        downloads.retry(job['id'])
    downloads.run(job['id'])
    assert store.get(job['id'])['status']=='completed'
    events=downloads.logs.read(job_id=job['id'])
    assert {event.get('attempt') for event in events}=={1,2}
    assert any(event['event']=='download.failed' and event['request_id']=='b'*32 for event in events)
    assert any(event['event']=='download.completed' and event['request_id']=='c'*32 for event in events)


def test_cancel_uses_control_request_reference(tmp_path):
    store=app.Store(tmp_path)
    store.set_folder(str(tmp_path/'downloads'))
    downloads=app.Downloads(store,start_worker=False)
    with diag.context(request_id='a'*32,client='mcp'):
        job=downloads.enqueue(['https://example.com/test'],validate_options({}))[0]
    with diag.context(request_id='b'*32,client='ui'):
        downloads.cancel(job['id'])
    events=downloads.logs.read(job_id=job['id'])
    cancelled=next(event for event in events if event.get('status')=='cancelled')
    assert cancelled['request_id']=='b'*32 and cancelled['client']=='ui'


def test_cli_diagnostics_work_offline_and_stdout_is_json(tmp_path,capsys):
    from agent_cli import main
    logs=diag.LogStore(tmp_path)
    logs.event('known',job_id='example')
    output=tmp_path/'report.json'
    assert main(['--connection-file',str(tmp_path/'connection.json'),'diagnostics','--job','example','--output',str(output)])==0
    assert json.loads(capsys.readouterr().out)['redacted'] is True
    assert json.loads(output.read_text())['events'][0]['event']=='known'
    assert main(['--connection-file',str(tmp_path/'connection.json'),'diagnostics','--output',str(output)])==1
    assert json.loads(capsys.readouterr().out)['error']


def test_diagnostic_cli_does_not_import_engine_or_sdk(tmp_path):
    import os
    import subprocess
    import sys
    code = '''import builtins, sys
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.split('.')[0] in {'yt_dlp','mcp','flask','webview'}:
        raise ImportError('Simulated unavailable dependency')
    return original(name,*args,**kwargs)
builtins.__import__=guarded
from agent_cli import main
raise SystemExit(main(['diagnostics']))
'''
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,
                          env={**os.environ,'VIDEO_DOWNLOADER_DATA_DIR':str(tmp_path)},timeout=20)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['logging']['available'] is True


def test_agent_http_failure_correlates_request_and_server_error(tmp_path,monkeypatch):
    from agent_client import AgentClient, AgentRequestError
    import agent_client
    connection=tmp_path/'connection.json'
    connection.write_text(json.dumps({'url':'http://127.0.0.1:5780','token':'s'*40}))
    logs=diag.LogStore(tmp_path)
    seen={}
    def fake_open(request,timeout):
        seen.update(dict(request.header_items()))
        raise HTTPError(request.full_url,422,'Unprocessable',{},io.BytesIO(json.dumps({'error':'HTTP Error 403: Forbidden','error_id':'e'*32}).encode()))
    monkeypatch.setattr(agent_client,'urlopen',fake_open)
    with diag.context(store=logs,component='mcp',call_id='d'*32):
        with pytest.raises(AgentRequestError) as caught:
            AgentClient(connection,autostart=False,client_kind='mcp').request('/api/inspect',{'url':'https://example.com/'})
    assert caught.value.error_id=='e'*32
    events=logs.read(request_id=caught.value.request_id)
    assert any(event.get('response_error_id')=='e'*32 for event in events)
    assert seen['X-spool-client']=='mcp'
    assert 's'*40 not in json.dumps(events)


def test_mcp_diagnostics_is_structured_and_works_without_service(tmp_path,monkeypatch):
    import asyncio
    import mcp_server
    from mcp import Client
    logs=diag.LogStore(tmp_path)
    logs.event('test.error','error',job_id='sample')
    monkeypatch.setattr(diag,'DEFAULT',logs)
    async def run():
        async with Client(mcp_server.mcp) as client:
            result=await client.call_tool('get_diagnostics',{'job_id':'sample'})
            assert not result.is_error
            assert result.structured_content['events'][0]['event']=='test.error'
    asyncio.run(run())


def test_mcp_schema_rejection_logs_fields_not_input_values(tmp_path,monkeypatch):
    import asyncio
    import logging
    import sys
    import threading
    import mcp_server
    from mcp import Client
    logs=diag.LogStore(tmp_path)
    monkeypatch.setattr(diag,'DEFAULT',logs)
    root, sdk = logging.getLogger(), logging.getLogger('mcp.server.mcpserver.server')
    handlers, sdk_handlers, level = root.handlers[:], sdk.handlers[:], sdk.level
    old_hook, old_thread_hook = sys.excepthook, threading.excepthook
    try:
        diag.install_crash_hooks()
        async def run():
            async with Client(mcp_server.mcp) as client:
                result=await client.call_tool('get_diagnostics',{'limit':'private-value'})
                assert result.is_error
        asyncio.run(run())
        events=logs.read()
        assert any(event['event']=='mcp.arguments_rejected' and event['fields']==['limit'] for event in events)
        assert 'private-value' not in json.dumps(events)
    finally:
        root.handlers, sdk.handlers, sdk.level = handlers, sdk_handlers, level
        sys.excepthook, threading.excepthook = old_hook, old_thread_hook
