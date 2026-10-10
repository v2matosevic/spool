"""Loopback-only desktop companion, with a durable queue and no hosted services."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request, send_file, g
from werkzeug.exceptions import HTTPException
import yt_dlp.version

from downloader import (DATA, DEFAULT_DOWNLOADS, Cancelled, create_engine, inspect_video,
                        safe_error, validate_options, validate_url, video_info)
from runtime import APP_ID, APP_NAME, VERSION, ROOT, binary, open_folder as reveal_folder, private_json, agent_configuration
from platforms import platform_data
import spotify_support as spotify
import diagnostics as diag

ACTIVE_STATUSES = {'queued', 'inspecting', 'downloading', 'processing', 'cancelling'}
TERMINAL_STATUSES = {'completed', 'failed', 'cancelled', 'interrupted'}
ATTENTION_STATUSES = {'failed', 'cancelled', 'interrupted'}
RETRYABLE_STATUSES = {'failed', 'cancelled', 'interrupted'}
MAX_ACTIVE_JOBS = 100


def now():
    return datetime.now(timezone.utc).isoformat()


def completed_file_paths(job, indexes=None):
    if job['status'] != 'completed' or job.get('removed_at'):
        raise ValueError('This file is not available.')
    names = job.get('files', [])
    indexes = list(range(len(names))) if indexes is None else indexes
    if (not isinstance(indexes, list) or not indexes or len(indexes) > len(names)
            or any(type(index) is not int or not 0 <= index < len(names) for index in indexes)):
        raise ValueError('Choose a saved file from this download.')
    folder = Path(job['folder']).resolve()
    paths = []
    for index in dict.fromkeys(indexes):
        original = folder / names[index]
        path = original.resolve()
        if Path(names[index]).name != names[index] or original.is_symlink() or path.parent != folder or not path.is_file():
            raise ValueError('This file was moved or is no longer available.')
        paths.append(path)
    return paths


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'history.sqlite3'
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            conn.execute("CREATE INDEX IF NOT EXISTS jobs_visibility_status ON jobs (json_extract(data, '$.removed_at'), json_extract(data, '$.status'))")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def jobs(self, *, include_removed=False, statuses=None, limit=500):
        conditions, params = [], []
        if not include_removed:
            conditions.append("json_extract(data, '$.removed_at') IS NULL")
        if statuses is not None:
            statuses = list(statuses)
            if not statuses:
                return []
            conditions.append("json_extract(data, '$.status') IN (" + ','.join('?' for _ in statuses) + ')')
            params.extend(statuses)
        query = 'SELECT data FROM jobs'
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
        query += ' ORDER BY rowid DESC'
        if limit is not None:
            query += ' LIMIT ?'
            params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [json.loads(row[0]) for row in rows]

    def counts(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT json_extract(data, '$.status'), count(*) FROM jobs WHERE json_extract(data, '$.removed_at') IS NULL GROUP BY json_extract(data, '$.status')").fetchall()
            removed = conn.execute("SELECT count(*) FROM jobs WHERE json_extract(data, '$.removed_at') IS NOT NULL").fetchone()[0]
        statuses = dict(rows)
        return {'active':sum(statuses.get(key,0) for key in ACTIVE_STATUSES),
                'attention':sum(statuses.get(key,0) for key in ATTENTION_STATUSES),
                'completed':statuses.get('completed',0),'visible':sum(statuses.values()),
                'removed':removed,'by_status':statuses}

    def get(self, job_id):
        with self.connect() as conn:
            row = conn.execute('SELECT data FROM jobs WHERE id = ?', (job_id,)).fetchone()
        if row is None:
            raise ValueError('This download was not found.')
        return json.loads(row[0])

    def save(self, job):
        self.save_many([job])

    def save_many(self, jobs):
        with self.connect() as conn:
            conn.executemany('INSERT INTO jobs VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                             [(job['id'],json.dumps(job)) for job in jobs])

    def folder(self):
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='folder'").fetchone()
        return Path(row[0]) if row else DEFAULT_DOWNLOADS

    def set_folder(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Choose a local folder.')
        folder = Path(value).expanduser()
        if not folder.is_absolute() or str(folder).startswith(('\\\\', '//')):
            raise ValueError('Enter an absolute folder path on this PC.')
        folder.mkdir(parents=True, exist_ok=True)
        # Test actual write access before recording a destination.
        import tempfile
        with tempfile.TemporaryFile(dir=folder):
            pass
        with self.connect() as conn:
            conn.execute("INSERT INTO settings VALUES ('folder', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(folder.resolve()),))


class Downloads:
    def __init__(self, store, start_worker=True):
        self.store = store
        self.lock = threading.RLock()
        self.queue = queue.Queue()
        self.cancelled = set()
        self.progress_times = {}
        self.logs = diag.LogStore(store.path.parent)
        if start_worker:
            self.start()

    def start(self):
        for job in self.store.jobs(statuses=ACTIVE_STATUSES,limit=None):
            job.update(status='interrupted', stage=None, speed=None, eta=None,
                       error='The app stopped before this download finished. Retry to resume partial files.')
            self.store.save(job)
            self.logs.event('job.interrupted', 'warning', component='queue', job_id=job['id'], attempt=job.get('attempt'), previous_state='active_at_startup')
        threading.Thread(target=self.worker, daemon=True, name='download-queue').start()

    def update(self, job_id, *, expected_attempt=None, **changes):
        with self.lock:
            job = self.store.get(job_id)
            if expected_attempt is not None and job.get('attempt',0) != expected_attempt:
                return job
            if job['status'] == 'cancelling' and changes.get('status') in ACTIVE_STATUSES:
                changes['status'] = 'cancelling'
            previous = job.get('status')
            job.update(changes, updated=now())
            self.store.save(job)
            if job.get('status') != previous or changes.get('stage'):
                self.logs.event('job.state', component='queue', job_id=job_id, attempt=job.get('attempt'),
                                request_id=diag.CONTEXT.get().get('request_id') or job.get('request_id'),
                                previous=previous, status=job['status'], stage=job.get('stage'))
            return job

    def enqueue(self, urls, options, folder=None, flat=False):
        if not isinstance(flat, bool):
            raise ValueError('The one-folder option must be on or off.')
        with self.lock:
            active = self.store.jobs(statuses=ACTIVE_STATUSES,limit=None)
            destination = (Path(folder) if folder else self.store.folder()).resolve()
            candidates = []
            for url in dict.fromkeys(urls):
                job_options = spotify.audio_options(options) if spotify.is_spotify(url) else dict(options)
                if any(j['url'] == url and j['options'] == job_options and j.get('flat', False) == flat
                       and Path(j.get('destination', Path(j['folder']).parent)).resolve() == destination for j in active):
                    continue
                candidates.append((url,job_options))
            if len(active) + len(candidates) > MAX_ACTIVE_JOBS:
                raise ValueError('The queue is full. Wait for downloads to finish before adding more.')
            jobs = []
            for url,job_options in candidates:
                job_id = uuid.uuid4().hex[:12]
                job = {'id': job_id, 'url': url, 'title': url, 'status': 'queued',
                       'options': job_options, 'folder': str(destination if flat else destination / job_id),
                       'destination': str(destination), 'flat': flat, 'attempt':1,
                       'created': now(), 'updated': now(), 'queued_at':now(), 'progress': 0,
                       'files': [], 'error': None, 'warning': None,
                       'request_id':diag.CONTEXT.get().get('request_id'),
                       'origin':diag.CONTEXT.get().get('client','ui')}
                self.store.save(job)
                self.logs.event('job.queued', component='queue', job_id=job_id, attempt=1,
                                request_id=job['request_id'], origin=job['origin'], options=job_options, source=diag.url_ref(url))
                self.queue.put((job_id,job['attempt']))
                jobs.append(job)
            return jobs

    def cancel(self, job_id):
        with self.lock:
            job = self.store.get(job_id)
            if job.get('removed_at') or job['status'] not in ACTIVE_STATUSES:
                raise ValueError('This download is no longer running.')
            self.cancelled.add((job_id,job.get('attempt',0)))
            return self.update(job_id, status='cancelled' if job['status'] == 'queued' else 'cancelling',
                               stage=None,speed=None,eta=None)

    def retry(self, job_id):
        with self.lock:
            job = self.store.get(job_id)
            if job.get('removed_at'):
                raise ValueError('Restore this removed entry before retrying it.')
            if job['status'] not in RETRYABLE_STATUSES:
                raise ValueError('Only failed, cancelled or interrupted downloads can be retried.')
            if len(self.store.jobs(statuses=ACTIVE_STATUSES,limit=None)) >= MAX_ACTIVE_JOBS:
                raise ValueError('The queue is full. Wait for downloads to finish before retrying.')
            attempt = job.get('attempt',0) + 1
            result = self.update(job_id, status='queued', error=None, warning=None, progress=0,stage=None,
                                 speed=None,eta=None,downloaded=0,total=None,attempt=attempt,queued_at=now(), error_id=None,
                                 request_id=diag.CONTEXT.get().get('request_id'), origin=diag.CONTEXT.get().get('client','ui'))
            self.logs.event('job.retried', component='queue', job_id=job_id, attempt=attempt,
                            request_id=result.get('request_id'), origin=result.get('origin'))
            self.queue.put((job_id,attempt))
            return result

    def retry_failed(self):
        with self.lock:
            # Explicit cancellations are user intent, so bulk retry skips them.
            jobs = self.store.jobs(statuses={'failed','interrupted'},limit=None)
            available = MAX_ACTIVE_JOBS - len(self.store.jobs(statuses=ACTIVE_STATUSES,limit=None))
            selected = list(reversed(jobs))[:max(0,available)]
            return {'jobs':[self.retry(job['id']) for job in selected], 'skipped':len(jobs)-len(selected)}

    def remove(self, job_id):
        with self.lock:
            job = self.store.get(job_id)
            if job['status'] in ACTIVE_STATUSES:
                raise ValueError('Cancel this download and wait for it to stop before removing the entry.')
            if job['status'] not in TERMINAL_STATUSES:
                raise ValueError('This entry cannot be removed in its current state.')
            if job.get('removed_at'):
                return {'removed_ids':[], 'count':0, 'files_deleted':False}
            self.update(job_id,removed_at=now())
            self.logs.event('history.removed', component='queue', job_id=job_id, files_deleted=False)
            return {'removed_ids':[job_id], 'count':1, 'files_deleted':False}

    def clear(self, statuses=None):
        statuses = list(ATTENTION_STATUSES) if statuses is None else statuses
        if not isinstance(statuses,list) or not statuses or any(not isinstance(s,str) or s not in TERMINAL_STATUSES for s in statuses):
            raise ValueError('Cleanup accepts completed, failed, cancelled or interrupted states only.')
        with self.lock:
            jobs = self.store.jobs(statuses=statuses,limit=None)
            timestamp = now()
            for job in jobs:
                job.update(removed_at=timestamp,updated=timestamp)
            self.store.save_many(jobs)
            self.logs.event('history.cleared', component='queue', count=len(jobs), statuses=statuses,
                            first_job_ids=[job['id'] for job in jobs[:30]], files_deleted=False)
            return {'removed_ids':[job['id'] for job in jobs], 'count':len(jobs), 'files_deleted':False}

    def restore(self, ids):
        if not isinstance(ids,list) or not ids or any(not isinstance(job_id,str) or not job_id for job_id in ids):
            raise ValueError('Provide the entry IDs returned by Remove or Clear.')
        with self.lock:
            # Validate the whole group before writing so Undo is all-or-nothing.
            jobs = [self.store.get(job_id) for job_id in dict.fromkeys(ids)]
            restored = []
            for job in jobs:
                if job.get('removed_at'):
                    job.update(removed_at=None,updated=now())
                    restored.append(job)
            self.store.save_many(restored)
            self.logs.event('history.restored', component='queue', count=len(restored), first_job_ids=[job['id'] for job in restored[:30]])
            return {'restored_ids':[job['id'] for job in restored], 'count':len(restored)}

    def worker(self):
        while True:
            job_id,attempt = self.queue.get()
            try:
                self.run(job_id,attempt)
            except Exception as error:
                error_id = self.logs.failure('queue.worker_failed', error, component='queue', job_id=job_id, attempt=attempt)
                try:
                    self.update(job_id,expected_attempt=attempt,status='failed',error=safe_error(error),error_id=error_id)
                except Exception as store_error:
                    self.logs.failure('queue.state_write_failed', store_error, component='queue', job_id=job_id, attempt=attempt)
            finally:
                self.queue.task_done()

    def run(self, job_id, attempt=None):
        job = self.store.get(job_id)
        with diag.context(store=self.logs, component='download', job_id=job_id,
                          attempt=attempt or job.get('attempt',0), request_id=job.get('request_id'), client=job.get('origin','ui')):
            return self._run(job_id, attempt)

    def _run(self, job_id, attempt=None):
        with self.lock:
            job = self.store.get(job_id)
            attempt = job.get('attempt',0) if attempt is None else attempt
            ticket = (job_id,attempt)
            if job.get('removed_at') or job['status'] != 'queued' or job.get('attempt',0) != attempt:
                self.cancelled.discard(ticket)
                return
            self.update(job_id, status='inspecting')
        target = Path(job['folder'])
        target.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        milestones = set()
        diag.record('download.started', source=diag.url_ref(job['url']), options=job['options'])

        def check():
            if ticket in self.cancelled:
                raise Cancelled('Download cancelled. Partial files are kept for Retry.')

        def progress(data):
            check()
            stamp = time.monotonic()
            if data['status'] == 'downloading' and stamp - self.progress_times.get(ticket, 0) < .4:
                return
            self.progress_times[ticket] = stamp
            total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
            downloaded = data.get('downloaded_bytes') or 0
            milestone = min(100, int(downloaded / total * 100) // 25 * 25) if total else 0
            format_id = (data.get('info_dict') or {}).get('format_id')
            if (format_id,milestone) not in milestones:
                milestones.add((format_id,milestone))
                diag.record('download.progress', format_id=format_id, percent=milestone, bytes=downloaded, total=total, speed=data.get('speed'))
            self.update(job_id, status='downloading' if data['status'] == 'downloading' else 'processing', stage=None,
                        progress=min(99, downloaded / total * 100) if total else 0,
                        downloaded=downloaded, total=total, speed=data.get('speed'), eta=data.get('eta'))

        def postprocess(data):
            check()
            diag.record('download.postprocess', name=data.get('postprocessor'), status=data.get('status'))
            self.update(job_id, status='processing', progress=99, stage=None)

        try:
            match = None
            source_url = job['url']
            if spotify.is_spotify(job['url']):
                self.update(job_id,platform='Spotify',stage='Matching song on YouTube')
                match = spotify.resolve_track(job['url'])
                source_url = match['source_url']
                check()
            with create_engine(job['options'], directory=target, progress=progress, postprocess=postprocess,
                               filename_tag=job_id if job.get('flat') else None,
                               warning=lambda message: self.update(job_id, warning=message),
                               cancelled=lambda: ticket in self.cancelled) as engine:
                check()
                info = engine.extract_info(source_url, download=False)
                selected = info.get('requested_formats') or [info]
                diag.record('download.source_selected', extractor=info.get('extractor_key'),
                            engine=yt_dlp.version.__version__, formats=[{key:item.get(key) for key in
                            ('format_id','ext','protocol','vcodec','acodec','width','height','abr','filesize')} for item in selected])
                summary = video_info(info)
                if match:
                    summary.update(spotify.summary(match,info,job['options']['mode']))
                    info['title'] = summary['title']
                self.update(job_id, **summary)
                check()
                # Use the inspected source immediately, preserving extractor headers/cookies.
                engine.process_info(info)
                check()
            allowed = {'.mp4', '.mkv', '.webm', '.mov', '.m4a', '.mp3', '.opus', '.ogg', '.flac', '.wav', '.aac', '.vtt', '.srt'}
            files = [p.name for p in target.iterdir() if p.is_file() and p.suffix.lower() in allowed and not p.is_symlink()
                     and (not job.get('flat') or f' [spool-{job_id}].' in p.name)]
            if not any(Path(name).suffix.lower() not in {'.vtt', '.srt'} for name in files):
                raise ValueError('The engine finished without producing a media file. Try another format.')
            if match:
                self.update(job_id,status='processing',stage='Adding song details and cover art')
                artwork = None
                try:
                    artwork = spotify.cover_image(match['track'].get('cover_url'))
                except Exception:
                    self.update(job_id,warning='Audio saved; Spotify cover art could not be fetched.')
                for filename in files:
                    check()
                    if Path(filename).suffix.lower() not in {'.srt','.vtt'}:
                        spotify.tag_audio(target / filename,match['track'],match['source_url'],artwork)
            with self.lock:
                check()
                self.update(job_id, status='completed', progress=100, files=sorted(files), speed=None, eta=None,
                            size=sum((target / name).stat().st_size for name in files), error=None, error_id=None, stage=None)
                diag.record('download.completed', elapsed_ms=round((time.monotonic()-started)*1000),
                            bytes=sum((target / name).stat().st_size for name in files), file_count=len(files),
                            extensions=sorted({Path(name).suffix for name in files}))
        except Exception as error:
            cancelled = isinstance(error, Cancelled) or ticket in self.cancelled
            error_id = (diag.record('download.cancelled', elapsed_ms=round((time.monotonic()-started)*1000)) if cancelled else
                        diag.failure('download.failed', error, elapsed_ms=round((time.monotonic()-started)*1000)))
            self.update(job_id, status='cancelled' if cancelled else 'failed', error=safe_error(error), error_id=error_id,
                        speed=None, eta=None,stage=None)
        finally:
            self.progress_times.pop(ticket, None)
            self.cancelled.discard(ticket)


def create_app(data_dir=DATA, start_worker=True, folder_picker=None):
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
    token = secrets.token_urlsafe(32)
    agent_token = secrets.token_urlsafe(32)
    store = Store(Path(data_dir))
    downloads = Downloads(store, start_worker)
    app.extensions.update(downloads=downloads, store=store, agent_token=agent_token)

    @app.before_request
    def diagnostic_context():
        reference = request.headers.get('X-Spool-Request-ID','')
        reference = reference if len(reference) == 32 and all(c in '0123456789abcdef' for c in reference) else uuid.uuid4().hex
        authenticated = secrets.compare_digest(request.headers.get('Authorization',''), 'Bearer ' + agent_token)
        client = request.headers.get('X-Spool-Client') if authenticated else 'ui'
        client = client if client in {'cli','mcp','ui'} else 'agent'
        g.diagnostic_start = time.monotonic()
        g.diagnostic_token = diag.CONTEXT.set({'_store':downloads.logs, 'component':'api', 'request_id':reference, 'client':client})

    @app.teardown_request
    def diagnostic_cleanup(error):
        if error:
            diag.failure('api.unhandled', error)
        token = g.pop('diagnostic_token', None)
        if token is not None:
            diag.CONTEXT.reset(token)

    @app.before_request
    def local_only():
        host = urlsplit('http://' + request.host).hostname
        if host not in {'127.0.0.1', 'localhost', '::1'} or request.remote_addr not in {'127.0.0.1', '::1', None}:
            return jsonify(error='This app is available only on this PC.'), 403
        navigation = request.method == 'GET' and request.path == '/' and request.headers.get('Sec-Fetch-Mode') == 'navigate'
        if request.headers.get('Sec-Fetch-Site') == 'cross-site' and not navigation:
            return jsonify(error='Cross-site requests are not allowed.'), 403
        origin = request.headers.get('Origin')
        if origin and origin != request.host_url.rstrip('/') and not navigation:
            return jsonify(error='Cross-site requests are not allowed.'), 403
        authenticated_agent = secrets.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + agent_token)
        if request.method == 'POST' and not authenticated_agent and not secrets.compare_digest(request.headers.get('X-Local-Token', ''), token):
            return jsonify(error='Refresh this page to reconnect to the app.'), 403

    @app.after_request
    def security_headers(response):
        reference = diag.CONTEXT.get().get('request_id')
        if reference:
            response.headers['X-Spool-Request-ID'] = reference
        elapsed = round((time.monotonic()-g.get('diagnostic_start',time.monotonic()))*1000)
        route = request.url_rule.rule if request.url_rule else 'unmatched'
        if response.status_code >= 400 or elapsed >= 1000 or (request.method == 'POST' and not route.startswith('/api/diagnostics')):
            body = response.get_json(silent=True) if response.status_code >= 400 else None
            action = (request.view_args or {}).get('action')
            job_id = (request.view_args or {}).get('job_id')
            job_id = job_id if job_id and len(job_id)==12 and all(c in '0123456789abcdef' for c in job_id) else None
            diag.record('api.request', 'warning' if response.status_code >= 400 else 'info',
                        route=route, method=request.method, http_status=response.status_code, elapsed_ms=elapsed,
                        job_id=job_id, action=action if action in {'cancel','retry','remove','restore','open'} else None,
                        response_error=body.get('error') if isinstance(body,dict) else None,
                        response_error_id=body.get('error_id') if isinstance(body,dict) else None)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' https: http: data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.errorhandler(Exception)
    def api_error(error):
        code = error.code if isinstance(error, HTTPException) else (400 if isinstance(error, (ValueError, OSError)) else 500)
        error_id = diag.failure('api.failed', error, route=request.url_rule.rule if request.url_rule else 'unmatched')
        return jsonify(error=safe_error(error), error_id=error_id, request_id=diag.CONTEXT.get().get('request_id')), code

    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('Send a JSON object.')
        return data

    @app.get('/')
    def index():
        return render_template('index.html', token=token)

    @app.get('/api/health')
    def health():
        return jsonify(app=APP_ID, display_name=APP_NAME, version=VERSION)

    @app.get('/api/state')
    def state():
        folder = store.folder()
        try:
            free = shutil.disk_usage(folder if folder.exists() else folder.anchor).free
        except OSError:
            free = None
        return jsonify(jobs=store.jobs(), counts=store.counts(), app_name=APP_NAME, folder=str(folder), engine=yt_dlp.version.__version__, version=VERSION,
                       dependencies={name: bool(binary(name)) for name in ['ffmpeg', 'ffprobe', 'node']},
                       cookies=(DATA / 'cookies.txt').exists(), free_bytes=free, native_picker=folder_picker is not None, native_drag=os.name == 'nt',
                       spotify={'available':spotify.ready(),'mode':'Spotify metadata + matched YouTube audio','tracks_only':True},
                       diagnostics=downloads.logs.status())

    @app.post('/api/diagnostics')
    def diagnostics_report():
        body = payload()
        return jsonify(downloads.logs.report(job_id=body.get('job_id'), request_id=body.get('request_id'), error_id=body.get('error_id'), limit=body.get('limit',100)))

    @app.post('/api/diagnostics/client-error')
    def client_error():
        body = payload()
        # Whitelist only error context, never page content, form values or headers.
        error_id = diag.record('ui.failed', 'error', message=str(body.get('message',''))[:2000],
                               stack=str(body.get('stack',''))[:6000], line=body.get('line'),
                               parent_request_id=str(body.get('request_id',''))[:64])
        return jsonify(error_id=error_id)

    @app.get('/api/platforms')
    def platforms():
        return jsonify(platform_data(request.args.get('q', '')[:150]))

    @app.get('/api/integrations')
    def integrations():
        return jsonify(mcp=agent_configuration(), connection_file=str(Path(data_dir) / 'connection.json'))

    @app.get('/api/jobs/<job_id>')
    def job_status(job_id):
        job = store.get(job_id)
        job['file_paths'] = [str(Path(job['folder']) / name) for name in job['files']]
        return jsonify(job)

    @app.post('/api/inspect')
    def inspect():
        body = payload()
        url = spotify.normalize_url(validate_url(body.get('url', '')))
        options = validate_options(body.get('options', {}))
        try:
            return jsonify(inspect_video(url, options))
        except Exception as error:
            error_id = diag.failure('inspect.failed', error, source=diag.url_ref(url), options=options)
            return jsonify(error=safe_error(error), error_id=error_id, request_id=diag.CONTEXT.get().get('request_id')), 422

    @app.post('/api/jobs')
    def add_jobs():
        body = payload()
        raw_urls = body.get('urls')
        if not isinstance(raw_urls, list) or not 1 <= len(raw_urls) <= 30:
            raise ValueError('Paste between 1 and 30 video links, one per line.')
        urls = [spotify.normalize_url(validate_url(url)) for url in raw_urls]
        if any(spotify.is_spotify(url) for url in urls) and not spotify.ready():
            raise ValueError('Spotify matching is not installed. Use the updated app installer.')
        options = validate_options(body.get('options', {}))
        missing = [name for name in ('ffmpeg', 'ffprobe', 'node') if not binary(name)]
        if missing:
            raise ValueError('Missing required tools: ' + ', '.join(missing))
        folder = body.get('folder')
        if folder is not None:
            if not isinstance(folder, str) or not Path(folder).is_absolute() or folder.startswith(('\\\\', '//')):
                raise ValueError('The output folder must be an absolute local path.')
            Path(folder).mkdir(parents=True, exist_ok=True)
        return jsonify(jobs=downloads.enqueue(urls, options, folder, flat=body.get('flat', False))), 201

    @app.post('/api/jobs/<job_id>/<action>')
    def action(job_id, action):
        if action == 'cancel':
            return jsonify(downloads.cancel(job_id))
        if action == 'retry':
            return jsonify(downloads.retry(job_id))
        if action == 'remove':
            return jsonify(downloads.remove(job_id))
        if action == 'restore':
            return jsonify(downloads.restore([job_id]))
        if action == 'open':
            folder = Path(store.get(job_id)['folder'])
            if not folder.is_dir():
                raise ValueError('This download folder no longer exists.')
            reveal_folder(folder)
            return jsonify(ok=True)
        raise ValueError('Unknown download action.')

    @app.post('/api/jobs/clear')
    def clear_jobs():
        return jsonify(downloads.clear(payload().get('statuses')))

    @app.post('/api/jobs/restore')
    def restore_jobs():
        return jsonify(downloads.restore(payload().get('ids')))

    @app.post('/api/jobs/retry-failed')
    def retry_failed_jobs():
        return jsonify(downloads.retry_failed())

    @app.get('/api/jobs/<job_id>/files/<int:index>')
    def media(job_id, index):
        return send_file(completed_file_paths(store.get(job_id), [index])[0], as_attachment=True)

    @app.post('/api/jobs/<job_id>/file-paths')
    def file_paths(job_id):
        # Native export accepts job IDs/indexes, never arbitrary paths from JS.
        return jsonify(file_paths=[str(path) for path in completed_file_paths(store.get(job_id), payload().get('indexes'))])

    @app.post('/api/settings')
    def settings():
        store.set_folder(payload().get('folder'))
        return jsonify(folder=str(store.folder()))

    @app.post('/api/pick-folder')
    def pick_folder():
        if folder_picker is None:
            return jsonify(error='Use Browse in the desktop app, or paste a folder path here.'), 409
        selected = folder_picker()
        return jsonify(folder=selected)

    @app.post('/api/open-folder')
    def open_folder():
        folder = store.folder()
        folder.mkdir(parents=True, exist_ok=True)
        reveal_folder(folder)
        return jsonify(ok=True)

    @app.post('/api/cookies')
    def cookies():
        upload = request.files.get('file')
        if upload is None:
            raise ValueError('Select a Netscape cookies.txt file.')
        raw = upload.read(2 * 1024 * 1024)
        text = raw.decode('utf-8-sig')
        if not text.startswith(('# Netscape HTTP Cookie File', '# HTTP Cookie File')):
            raise ValueError('This must be an exported Netscape cookies.txt file.')
        from http.cookiejar import MozillaCookieJar
        staging = DATA / ('cookies-' + uuid.uuid4().hex + '.tmp')
        DATA.mkdir(parents=True, exist_ok=True)
        staging.write_text(text, encoding='utf-8')
        try:
            jar = MozillaCookieJar(str(staging))
            jar.load(ignore_discard=True, ignore_expires=True)
            if not list(jar):
                raise ValueError('The cookie file contains no cookies.')
            staging.replace(DATA / 'cookies.txt')
        finally:
            staging.unlink(missing_ok=True)
        return jsonify(ok=True)

    return app


def make_server(port=None, data_dir=DATA, folder_picker=None):
    from waitress import create_server
    from runtime import PORT
    port = PORT if port is None else port
    # Do not touch active job state until this instance has won the listen socket.
    app = create_app(data_dir, start_worker=False, folder_picker=folder_picker)
    server = create_server(app, host='127.0.0.1', port=port, threads=6, max_request_body_size=2 * 1024 * 1024)
    app.extensions['downloads'].start()
    app.extensions['downloads'].logs.event('service.ready', component='service', port=server.effective_port,
                                           engine=yt_dlp.version.__version__, counts=app.extensions['store'].counts())
    private_json(Path(data_dir) / 'connection.json', {'url':f'http://127.0.0.1:{server.effective_port}',
                 'token':app.extensions['agent_token'], 'pid':os.getpid(), 'version':VERSION})
    return server


if __name__ == '__main__':
    diag.setup('service')
    diag.install_crash_hooks()
    make_server().run()
