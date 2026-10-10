from pathlib import Path
import queue

import pytest

import app
from downloader import validate_options


@pytest.fixture
def manager(tmp_path):
    store=app.Store(tmp_path)
    store.set_folder(str(tmp_path/'downloads'))
    return app.Downloads(store,start_worker=False)


def finished(manager,status='failed',url='https://example.com/video'):
    job=manager.enqueue([url],validate_options({}))[0]
    return manager.update(job['id'],status=status,error='Test failure' if status=='failed' else None)


@pytest.mark.parametrize('status',['failed','cancelled','interrupted','completed'])
def test_remove_is_reversible_and_keeps_files(manager,status):
    job=finished(manager,status)
    folder=Path(job['folder'])
    folder.mkdir(parents=True)
    media=folder/'video.mp4'
    partial=folder/'video.part'
    media.write_bytes(b'saved media')
    partial.write_bytes(b'partial media')
    result=manager.remove(job['id'])
    assert result=={'removed_ids':[job['id']],'count':1,'files_deleted':False}
    assert manager.store.jobs()==[]
    assert media.read_bytes()==b'saved media'
    assert partial.read_bytes()==b'partial media'
    assert manager.restore(result['removed_ids'])['count']==1
    assert manager.store.jobs()[0]['status']==status
    assert manager.restore(result['removed_ids'])['count']==0


@pytest.mark.parametrize('status',sorted(app.ACTIVE_STATUSES))
def test_active_entries_cannot_be_removed(manager,status):
    job=finished(manager,status)
    with pytest.raises(ValueError,match='Cancel'):
        manager.remove(job['id'])
    assert manager.store.jobs()[0]['status']==status


def test_bulk_cleanup_ignores_running_and_saved_by_default(manager):
    jobs=[finished(manager,status,'https://example.com/'+status) for status in ['failed','cancelled','interrupted','completed','queued']]
    result=manager.clear()
    assert set(result['removed_ids'])=={j['id'] for j in jobs[:3]}
    assert {j['status'] for j in manager.store.jobs()}=={'completed','queued'}
    assert manager.store.counts()['removed']==3
    assert manager.store.counts()['active']==1
    assert manager.restore(result['removed_ids'])['count']==3


def test_invalid_clear_and_restore_are_atomic(manager):
    job=finished(manager)
    with pytest.raises(ValueError): manager.clear(['failed','downloading'])
    assert manager.store.jobs()
    manager.remove(job['id'])
    with pytest.raises(ValueError): manager.restore([job['id'],'missing-id'])
    assert manager.store.jobs()==[]


def test_removed_rows_do_not_hide_visible_history_at_display_limit(manager):
    older=finished(manager)
    newer=finished(manager,url='https://example.com/new')
    manager.remove(newer['id'])
    assert manager.store.jobs(limit=1)[0]['id']==older['id']
    assert len(manager.store.jobs(include_removed=True))==2


def test_retry_resets_transient_fields_but_keeps_folder(manager):
    job=finished(manager)
    manager.update(job['id'],progress=87,downloaded=100,total=200,speed=11,eta=9,stage='Old stage',warning='Old warning',queued_at='2000-01-01T00:00:00+00:00')
    result=manager.retry(job['id'])
    assert result['folder']==job['folder']
    assert result['progress']==0 and result['downloaded']==0
    assert all(result[key] is None for key in ['error','warning','speed','eta','total','stage'])
    assert result['attempt']==2
    assert result['queued_at']!='2000-01-01T00:00:00+00:00'
    assert result['created']==job['created']


def test_stale_queue_ticket_cannot_jump_a_retry_ahead(manager,monkeypatch):
    first,second=manager.enqueue(['https://example.com/first','https://example.com/second'],validate_options({}))
    old_ticket=manager.queue.get_nowait()
    manager.cancel(first['id'])
    manager.retry(first['id'])
    manager.run(*old_ticket)
    assert manager.store.get(first['id'])['status']=='queued'
    assert manager.queue.get_nowait()[0]==second['id']
    assert manager.queue.get_nowait()==(first['id'],2)


def test_removed_cancelled_job_is_ignored_by_worker(manager):
    job=manager.enqueue(['https://example.com/test'],validate_options({}))[0]
    ticket=manager.queue.get_nowait()
    manager.cancel(job['id'])
    manager.remove(job['id'])
    manager.run(*ticket)
    assert manager.store.get(job['id'])['status']=='cancelled'
    assert not Path(job['folder']).exists()
    assert ticket not in manager.cancelled


def test_bulk_retry_leaves_cancelled_and_removed_entries_alone(manager):
    jobs=[finished(manager,status,'https://example.com/'+status) for status in ['failed','interrupted','cancelled']]
    hidden=finished(manager,url='https://example.com/hidden')
    manager.remove(hidden['id'])
    result=manager.retry_failed()
    assert {j['id'] for j in result['jobs']}=={j['id'] for j in jobs[:2]}
    assert manager.store.get(jobs[2]['id'])['status']=='cancelled'
    with pytest.raises(ValueError,match='Restore'):
        manager.retry(hidden['id'])


def test_cancellation_is_not_erased_by_late_progress(manager):
    job=finished(manager,'downloading')
    manager.cancel(job['id'])
    manager.update(job['id'],status='processing',progress=99)
    assert manager.store.get(job['id'])['status']=='cancelling'


def test_capacity_counts_only_real_new_jobs_and_retry_limit(manager,monkeypatch):
    monkeypatch.setattr(app,'MAX_ACTIVE_JOBS',1)
    job=manager.enqueue(['https://example.com/a'],validate_options({}))[0]
    assert manager.enqueue([job['url'],job['url']],validate_options({}))==[]
    manager.cancel(job['id'])
    manager.enqueue(['https://example.com/b'],validate_options({}))
    with pytest.raises(ValueError,match='queue is full'):
        manager.retry(job['id'])


def test_destination_is_part_of_active_deduplication(manager,tmp_path):
    first=manager.enqueue(['https://example.com/a'],validate_options({}))[0]
    second=manager.enqueue([first['url']],validate_options({}),tmp_path/'elsewhere')
    assert len(second)==1


def test_cleanup_api_is_authenticated_and_undo_survives_restart(tmp_path):
    application=app.create_app(tmp_path,start_worker=False)
    manager=application.extensions['downloads']
    job=finished(manager)
    client=application.test_client()
    headers={'Authorization':'Bearer '+application.extensions['agent_token']}
    assert client.post('/api/jobs/clear',json={}).status_code==403
    response=client.post('/api/jobs/clear',json={},headers=headers)
    assert response.status_code==200
    assert client.get('/api/state').json['jobs']==[]
    fresh=app.Store(tmp_path)
    assert fresh.jobs()==[] and fresh.get(job['id'])['removed_at']
    undo=client.post('/api/jobs/restore',json={'ids':response.json['removed_ids']},headers=headers)
    assert undo.json['count']==1
    assert client.get('/api/state').json['counts']['attention']==1
