"""Bounded, redacted local diagnostics shared by desktop, service and agents.

SQLite serializes writers from separate MCP/CLI processes. No diagnostic output
is written to stdout: it belongs to the CLI/MCP protocol. Failures here must not
break a download, and are exposed by status() instead of disappearing silently.
"""
from __future__ import annotations
from contextlib import contextmanager, closing
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import platform
import re
import sqlite3
import sys
import threading
import time
import traceback
from urllib.parse import urlsplit
import uuid

from runtime import DATA, ROOT, VERSION, binary

CONTEXT = ContextVar('spool_diagnostics', default={})
DEFAULT = None
SESSION = uuid.uuid4().hex
RETENTION_DAYS = 30
MAX_EVENTS = 10000
MAX_BYTES = 32 * 1024 * 1024
SECRET = re.compile(r'authorization|cookie|password|passwd|secret|token|api.?key|signature|visitor.?data', re.I)
IDENTIFIER = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


def redact(value):
    text = str(value)[:16000]
    text = re.sub(r'https?://[^\s<>"\']+', '[source URL]', text, flags=re.I)
    text = re.sub(r'(?im)\b(?:authorization|cookie|set-cookie)\s*[\"\']?\s*[:=].*$', '[credential removed]', text)
    text = re.sub(r'(?i)\bBearer\s+[^\s,;\"\']+', 'Bearer [redacted]', text)
    text = re.sub(r'(?im)\binput_value\s*[:=].*$', 'input_value=[redacted]', text)
    text = re.sub(r'''(?i)(--?(?:cookies?|cookies-from-browser|password|username|api-key|token|headers?)\s+)(?:"[^"]*"|'[^']*'|\S+)''', r'\1[redacted]', text)
    text = re.sub(r'''(?ix)(["']?(?:password|passwd|secret|access_token|refresh_token|token|api[_-]?key|po_token|signature)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;\}\]]+)''', r'\1[redacted]', text)
    for path in (str(DATA), str(ROOT), str(Path.home())):
        text = re.sub(re.escape(path), '[local path]', text, flags=re.I)
        text = re.sub(re.escape(path.replace('\\', '/')), '[local path]', text, flags=re.I)
    text = re.sub(r'''[A-Za-z]:[\\/][^\r\n"'<>]*''', '[local path]', text)
    text = re.sub(r'''/(?:Users|home|Volumes|private|tmp)/[^\r\n"'<>]*''', '[local path]', text)
    text = re.sub(r'[A-Za-z0-9_+/=-]{48,}', '[long value removed]', text)
    text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', text)
    return text[:3000]


def clean(value, depth=0):
    if depth > 6:
        return '[depth limited]'
    if isinstance(value, dict):
        return {str(k)[:80]: '[redacted]' if SECRET.search(str(k)) else clean(v, depth+1)
                for k, v in list(value.items())[:40] if not str(k).startswith('_')}
    if isinstance(value, (list, tuple)):
        return [clean(item, depth+1) for item in value[:30]]
    if isinstance(value,float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact(value)


def url_ref(url):
    """Identify a source without retaining its path, query, account or signature."""
    try:
        host = urlsplit(url).hostname or 'unknown'
    except ValueError:
        host = 'invalid'
    return {'host': host, 'url_hash': hashlib.sha256(str(url).encode()).hexdigest()[:16]}


def error_info(error):
    chain, seen, current = [], set(), error
    while current is not None and id(current) not in seen and len(chain) < 4:
        seen.add(id(current))
        status = getattr(current, 'code', None)
        status = status if isinstance(status, int) and 100 <= status < 600 else None
        message = redact(current)
        match = re.search(r'\b(?:HTTP(?: Error)?|status(?: code)?)[: ]+(\d{3})\b', str(current), re.I)
        status = status or (int(match[1]) if match else None)
        frames = [{'file':Path(frame.filename).name, 'function':frame.name, 'line':frame.lineno}
                  for frame in traceback.extract_tb(current.__traceback__)[-15:]]
        chain.append({'type':type(current).__name__, 'message':message, 'http_status':status,
                      'errno':getattr(current, 'errno', None), 'frames':frames})
        nested = getattr(current, 'exc_info', None)
        current = current.__cause__ or current.__context__ or (nested[1] if isinstance(nested, tuple) and len(nested) > 1 else None)
    status = next((item['http_status'] for item in chain if item['http_status']), None)
    message = ' '.join(item['message'] for item in chain).lower()
    category = ('upstream_forbidden' if status == 403 else 'rate_limited' if status == 429 else
                'upstream_http' if status else 'timeout' if 'timed out' in message or 'timeout' in message else
                'storage' if any(word in message for word in ('disk', 'permission denied', 'no space')) else
                'missing_dependency' if 'not installed' in message or 'not found' in message else 'operation_failed')
    return {'category':category, 'http_status':status, 'chain':chain}


class LogStore:
    def __init__(self, directory=DATA, *, max_events=MAX_EVENTS, max_bytes=MAX_BYTES, days=RETENTION_DAYS):
        self.path = Path(directory) / 'logs' / 'diagnostics.sqlite3'
        self.max_events, self.max_bytes, self.days = max_events, max_bytes, days
        self.dropped = 0
        self.contention_retries = 0
        self.last_error = None
        self._initialized = False
        self._lock = threading.Lock()
        self._writes = 0
        self._pruned = 0

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=.25)
        try:
            conn.execute('PRAGMA busy_timeout=250')
            conn.execute('PRAGMA wal_autocheckpoint=256')
            conn.execute('PRAGMA journal_size_limit=2097152')
            conn.execute('PRAGMA max_page_count=24576')
            if not self._initialized:
                with self._lock:
                    if not self._initialized:
                        conn.execute('PRAGMA auto_vacuum=INCREMENTAL')
                        conn.execute('PRAGMA journal_mode=WAL')
                        conn.executescript('''CREATE TABLE IF NOT EXISTS events (
                            seq INTEGER PRIMARY KEY, time REAL NOT NULL, event_id TEXT NOT NULL,
                            job_id TEXT, request_id TEXT, level TEXT NOT NULL, bytes INTEGER NOT NULL, data TEXT NOT NULL);
                            CREATE INDEX IF NOT EXISTS events_job ON events(job_id,seq);
                            CREATE INDEX IF NOT EXISTS events_request ON events(request_id,seq);
                            CREATE INDEX IF NOT EXISTS events_time ON events(time);''')
                        self._initialized = True
            return conn
        except Exception:
            conn.close()
            raise

    def prune(self, conn):
        conn.execute('DELETE FROM events WHERE time < ?', (time.time()-self.days*86400,))
        count, total = conn.execute('SELECT count(*), coalesce(sum(bytes),0) FROM events').fetchone()
        if count > self.max_events:
            conn.execute('DELETE FROM events WHERE seq IN (SELECT seq FROM events ORDER BY seq LIMIT ?)', (count-self.max_events,))
        if total <= self.max_bytes:
            self._pruned = time.monotonic()
            return
        used, keep, cutoff = 0, 0, None
        for seq, size in conn.execute('SELECT seq, bytes FROM events ORDER BY seq DESC'):
            used += size
            keep += 1
            if keep > self.max_events or used > self.max_bytes:
                cutoff = seq
                break
        if cutoff is not None:
            conn.execute('DELETE FROM events WHERE seq <= ?', (cutoff,))
        self._pruned = time.monotonic()

    def event(self, event, level='info', **fields):
        event_id = uuid.uuid4().hex
        context = {k:v for k,v in CONTEXT.get().items() if not k.startswith('_')}
        data = clean({**context, **fields})
        if len(json.dumps(data).encode()) > 12000:
            data = {'detail':redact(json.dumps(data)), 'truncated':True,
                    **{key:data[key] for key in ('job_id','attempt','request_id','component') if key in data}}
        item = {**data, 'id':event_id, 'time':datetime.now(timezone.utc).isoformat(), 'level':level,
                'event':event, 'version':VERSION, 'pid':os.getpid(), 'session':SESSION}
        encoded = json.dumps(item, ensure_ascii=True, default=str)
        for retry in range(4):
            try:
                with closing(self.connect()) as conn, conn:
                    conn.execute('INSERT INTO events(time,event_id,job_id,request_id,level,bytes,data) VALUES(?,?,?,?,?,?,?)',
                                 (time.time(),event_id,data.get('job_id'),data.get('request_id'),level,len(encoded),encoded))
                    self._writes += 1
                    self.prune(conn)
                    if self._writes % 50 == 1:
                        conn.execute('PRAGMA incremental_vacuum(64)')
                self.last_error = None
                return event_id
            except (OSError, sqlite3.Error) as error:
                if isinstance(error, sqlite3.OperationalError) and any(word in str(error).lower() for word in ('locked','busy')) and retry < 3:
                    self.contention_retries += 1
                    time.sleep(.02 * (retry+1))
                    continue
                self.dropped += 1
                self.last_error = type(error).__name__
                return None

    def failure(self, event, error, **fields):
        return self.event(event, 'error', error=error_info(error), **fields)

    def read(self, *, job_id=None, request_id=None, error_id=None, limit=100):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 2000:
            raise ValueError('Choose a diagnostic limit from 1 to 2000.')
        for identifier in (job_id, request_id, error_id):
            if identifier is not None and (not isinstance(identifier,str) or not IDENTIFIER.fullmatch(identifier)):
                raise ValueError('Use a valid job or request reference.')
        clauses, args = ['time >= ?'], [time.time()-self.days*86400]
        for key, value in (('job_id',job_id),('request_id',request_id),('event_id',error_id)):
            if value:
                clauses.append(key+' = ?')
                args.append(value)
        try:
            with closing(self.connect()) as conn:
                rows = conn.execute('SELECT data FROM events WHERE '+' AND '.join(clauses)+' ORDER BY seq DESC LIMIT ?', (*args,limit)).fetchall()
            return [json.loads(row[0]) for row in reversed(rows)]
        except (OSError, sqlite3.Error) as error:
            self.last_error = type(error).__name__
            return []

    def status(self):
        return {'available':self.last_error is None, 'dropped_events':self.dropped,
                'last_error':self.last_error, 'contention_retries':self.contention_retries, 'retention_days':self.days,
                'max_events':self.max_events, 'max_content_bytes':self.max_bytes}

    def launcher_events(self):
        events = []
        for name in ('launcher.previous.jsonl','launcher.jsonl'):
            path = self.path.parent / name
            try:
                with path.open('rb') as handle:
                    handle.seek(max(0,path.stat().st_size-65536))
                    lines = handle.read(65536).decode('utf-8',errors='replace').splitlines()
                for line in lines:
                    try:
                        item = json.loads(line)
                        if isinstance(item,dict):
                            events.append(clean(item))
                    except ValueError:
                        continue
            except OSError:
                continue
        return events[-100:]

    def report(self, **filters):
        events = self.read(**filters)
        return {'app':'Spool', 'version':VERSION, 'generated_at':datetime.now(timezone.utc).isoformat(),
                'system':{'platform':sys.platform, 'python':platform.python_version(),
                          'frozen':bool(getattr(sys,'frozen',False)),
                          'tools':{name:bool(binary(name)) for name in ('ffmpeg','ffprobe','node')}},
                'logging':self.status(), 'events':events,
                'launcher_events':self.launcher_events() if not any(filters.get(k) for k in ('job_id','request_id')) else [],
                'notice':'Local diagnostic records. Credentials, full source URLs and local paths are redacted. Review before sharing. Earlier failures cannot be reconstructed retroactively.'}


def setup(component, directory=DATA):
    global DEFAULT
    DEFAULT = LogStore(directory)
    CONTEXT.set({'component':component})
    record('process.started', platform=sys.platform, python=platform.python_version(), frozen=bool(getattr(sys,'frozen',False)))
    return DEFAULT


class DiagnosticHandler(logging.Handler):
    def emit(self, item):
        if item.msg == 'Tool %r rejected arguments: %r' and isinstance(item.args,tuple) and len(item.args)==2:
            record('mcp.arguments_rejected', 'warning', tool=item.args[0], fields=item.args[1])
            return
        if item.exc_info and item.exc_info[1]:
            failure('python.log', item.exc_info[1], logger=item.name)
        else:
            record('python.log', item.levelname.lower(), logger=item.name, message=item.getMessage())


def install_crash_hooks():
    if not any(isinstance(handler,DiagnosticHandler) for handler in logging.getLogger().handlers):
        logging.getLogger().addHandler(DiagnosticHandler(level=logging.WARNING))
    sdk = logging.getLogger('mcp.server.mcpserver.server')
    if not any(isinstance(handler,DiagnosticHandler) for handler in sdk.handlers):
        handler = DiagnosticHandler(level=logging.INFO)
        handler.addFilter(lambda item: item.levelno==logging.INFO and item.msg=='Tool %r rejected arguments: %r')
        sdk.addHandler(handler)
        sdk.setLevel(logging.INFO)
    def uncaught(kind, error, tb):
        failure('process.unhandled', error)
        sys.__excepthook__(kind,error,tb)
    def thread_error(args):
        failure('thread.unhandled', args.exc_value, thread=args.thread.name)
    sys.excepthook = uncaught
    threading.excepthook = thread_error


@contextmanager
def context(store=None, **fields):
    token = CONTEXT.set({**CONTEXT.get(), **fields, **({'_store':store} if store else {})})
    try:
        yield
    finally:
        CONTEXT.reset(token)


def record(event, level='info', **fields):
    store = CONTEXT.get().get('_store') or DEFAULT
    return store.event(event, level, **fields) if store else None


def failure(event, error, **fields):
    store = CONTEXT.get().get('_store') or DEFAULT
    return store.failure(event, error, **fields) if store else None
