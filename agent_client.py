"""Authenticated loopback client shared by the CLI and MCP tools."""
from __future__ import annotations
import json
from pathlib import Path
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from runtime import DATA
import diagnostics as diag


class AgentRequestError(RuntimeError):
    def __init__(self, message, request_id, error_id=None):
        super().__init__(message)
        self.request_id, self.error_id = request_id, error_id


class AgentClient:
    def __init__(self, connection_file=None, autostart=True, client_kind='agent'):
        self.client_kind = client_kind
        self.connection_file = Path(connection_file or DATA / 'connection.json')
        if autostart and connection_file is None:
            from desktop import ensure_server
            ensure_server()

    def connection(self):
        try:
            info = json.loads(self.connection_file.read_text(encoding='utf-8'))
            parsed = urlsplit(info['url'])
            if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username or parsed.password or parsed.path not in {'','/'} or parsed.query or parsed.fragment:
                raise ValueError('Agent connection must use the loopback-only app.')
            if not isinstance(info.get('token'), str) or len(info['token']) < 32:
                raise ValueError('Invalid local agent credential.')
            return info
        except (OSError, KeyError, json.JSONDecodeError) as error:
            raise RuntimeError('Start VideoDownloader first. No valid local connection was found.') from error

    def request(self, path, body=None, timeout=120):
        if not path.startswith('/api/') or '://' in path:
            raise ValueError('Use a local API path.')
        connection = self.connection()
        request_id = uuid.uuid4().hex
        headers = {'Authorization':'Bearer ' + connection['token'], 'X-Spool-Request-ID':request_id,
                   'X-Spool-Client':self.client_kind}
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(body).encode()
        req = Request(connection['url'].rstrip('/') + path, data=data, headers=headers)
        started = time.monotonic()
        route = urlsplit(path).path
        parts = route.split('/')
        job_id = parts[3] if len(parts) > 3 and parts[2] == 'jobs' and len(parts[3]) == 12 else None
        route = '/api/jobs/<job>' + ('/'+parts[4] if len(parts) > 4 else '') if job_id else route
        # Poll successes are represented by queue state events; mutations and
        # errors retain every request reference without flooding the log.
        if body is not None:
            diag.record('agent.request', request_id=request_id, route=route, method='POST', job_id=job_id)
        try:
            with urlopen(req, timeout=timeout) as response:
                result = json.load(response)
                if body is not None or time.monotonic()-started >= 1:
                    diag.record('agent.response', request_id=request_id, route=route, job_id=job_id,
                                http_status=response.status, elapsed_ms=round((time.monotonic()-started)*1000))
                return result
        except HTTPError as error:
            try:
                result = json.load(error)
                message, error_id = result.get('error',str(error)), result.get('error_id')
            except (ValueError, AttributeError):
                message, error_id = str(error), None
            diag.failure('agent.request_failed', error, request_id=request_id, route=route, job_id=job_id,
                         response_error_id=error_id, response_message=message)
            raise AgentRequestError(diag.redact(message), request_id, error_id) from None
        except (URLError, OSError, ValueError) as error:
            error_id = diag.failure('agent.connection_failed', error, request_id=request_id, route=route, job_id=job_id)
            raise AgentRequestError('The local downloader is not reachable or returned an invalid response. Open the app and retry.', request_id, error_id) from None

    def wait(self, job_ids, timeout=600):
        deadline = time.monotonic() + max(1, min(float(timeout), 86400))
        while True:
            jobs = [self.request('/api/jobs/' + job_id) for job_id in job_ids]
            pending = any(job['status'] in {'queued','inspecting','downloading','processing','cancelling'} for job in jobs)
            if not pending:
                diag.record('agent.wait_finished', job_ids=job_ids, statuses=[job['status'] for job in jobs])
                return {'jobs':jobs, 'timed_out':False}
            if time.monotonic() >= deadline:
                diag.record('agent.wait_timeout', 'warning', job_ids=job_ids, timeout_seconds=timeout)
                return {'jobs':jobs, 'timed_out':True}
            time.sleep(.75)
