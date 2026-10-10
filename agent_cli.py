"""Machine-readable command-line interface. stdout is JSON except --help."""
import argparse
import json
from pathlib import Path
import time
import diagnostics as diag
from urllib.parse import quote
from agent_client import AgentClient
from options import MODES, QUALITIES, BROWSERS
from runtime import APP_NAME, agent_configuration


class DiagnosticParser(argparse.ArgumentParser):
    def error(self, message):
        # Argparse can echo arbitrary supplied values. Record the validation
        # category/flag only, not argv or the rejected value.
        diag.record('cli.invalid_arguments', 'warning', problem=message.split(':',1)[0])
        super().error(message)


def main(argv=None):
    parser = DiagnosticParser(prog=f'{APP_NAME} --cli', description='Local media tools for people and agents. Results are JSON.')
    parser.add_argument('--connection-file', help='Local descriptor for an isolated instance')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    commands.add_parser('list')
    commands.add_parser('mcp-config')
    commands.add_parser('retry-failed')
    diagnostic = commands.add_parser('diagnostics')
    diagnostic.add_argument('--job', dest='job_id')
    diagnostic.add_argument('--request', dest='request_id')
    diagnostic.add_argument('--error', dest='error_id')
    diagnostic.add_argument('--limit', type=int, default=200)
    diagnostic.add_argument('--output', help='Save a redacted JSON report to a new file')
    clear = commands.add_parser('clear')
    clear.add_argument('--status',action='append',choices=['completed','failed','cancelled','interrupted'])
    restore = commands.add_parser('restore')
    restore.add_argument('ids',nargs='+')
    platforms = commands.add_parser('platforms')
    platforms.add_argument('query', nargs='?', default='')
    folder = commands.add_parser('folder')
    folder.add_argument('path', nargs='?')
    for action in ['inspect','download']:
        command = commands.add_parser(action)
        command.add_argument('urls', nargs='+' if action == 'download' else None)
        command.add_argument('--format', choices=sorted(MODES), default='original', dest='mode')
        command.add_argument('--quality', choices=sorted(QUALITIES), default='best')
        command.add_argument('--browser', choices=sorted(BROWSERS), default='none')
        command.add_argument('--allow-watermarked', action='store_true')
        command.add_argument('--subtitles', action='store_true')
        if action == 'download':
            command.add_argument('--folder', help='Destination for this batch only')
            command.add_argument('--flat', action='store_true', help='Save directly in the destination, without per-job subfolders')
            command.add_argument('--wait', action='store_true')
            command.add_argument('--timeout', type=int, default=600)
    for action in ['job','retry','cancel','remove','wait']:
        command = commands.add_parser(action)
        command.add_argument('id')
        if action == 'wait':
            command.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args(argv)
    started = time.monotonic()
    diag.record('cli.started', command=args.command)
    code = 0
    try:
        if args.command == 'diagnostics':
            from runtime import DATA
            directory = Path(args.connection_file).parent if args.connection_file else DATA
            output = diag.LogStore(directory).report(job_id=args.job_id, request_id=args.request_id, error_id=args.error_id, limit=args.limit)
            if args.output:
                path = Path(args.output).expanduser().resolve()
                with path.open('x',encoding='utf-8') as handle:
                    json.dump(output,handle,ensure_ascii=True,indent=2)
                output = {'saved_to':str(path), 'event_count':len(output['events']), 'redacted':True}
        elif args.command == 'mcp-config':
            output = agent_configuration()
        else:
            client = AgentClient(args.connection_file, autostart=args.connection_file is None, client_kind='cli')
            if args.command in {'status','list'}:
                output = client.request('/api/state')
                if args.command == 'status':
                    output['counts'] = {status:sum(j['status']==status for j in output['jobs']) for status in {j['status'] for j in output['jobs']}}
                    output.pop('jobs')
            elif args.command == 'platforms':
                output = client.request('/api/platforms?q=' + quote(args.query))
            elif args.command == 'folder':
                output = client.request('/api/settings', {'folder':args.path}) if args.path else {'folder':client.request('/api/state')['folder']}
            elif args.command == 'clear':
                output = client.request('/api/jobs/clear', {'statuses':args.status} if args.status else {})
            elif args.command == 'restore':
                output = client.request('/api/jobs/restore', {'ids':args.ids})
            elif args.command == 'retry-failed':
                output = client.request('/api/jobs/retry-failed', {})
            elif args.command in {'inspect','download'}:
                options = {'mode':args.mode,'quality':args.quality,'browser':args.browser,'clean':not args.allow_watermarked,'subtitles':args.subtitles}
                if args.command == 'inspect':
                    output = client.request('/api/inspect', {'url':args.urls,'options':options})
                else:
                    body = {'urls':args.urls,'options':options}
                    if args.folder:
                        body['folder'] = args.folder
                    if args.flat:
                        body['flat'] = True
                    output = client.request('/api/jobs', body)
                    if args.wait and output['jobs']:
                        output = client.wait([job['id'] for job in output['jobs']],args.timeout)
            elif args.command == 'job':
                output = client.request('/api/jobs/' + quote(args.id,safe=''))
            elif args.command == 'wait':
                output = client.wait([args.id],args.timeout)
            else:
                output = client.request('/api/jobs/' + quote(args.id,safe='') + '/' + args.command, {})
            if output.get('timed_out'):
                code = 3
            elif args.command in {'download','wait'} and any(j['status'] in {'failed','cancelled','interrupted'} for j in output.get('jobs',[])):
                code = 2
        print(json.dumps(output,ensure_ascii=True))
    except Exception as error:
        error_id = diag.failure('cli.failed', error, command=args.command)
        print(json.dumps({'error':diag.redact(error), 'error_id':getattr(error,'error_id',None) or error_id,
                          'request_id':getattr(error,'request_id',None)},ensure_ascii=True))
        code = 1
    diag.record('cli.finished', command=args.command, exit_code=code, elapsed_ms=round((time.monotonic()-started)*1000))
    return code


if __name__ == '__main__':
    diag.setup('cli')
    raise SystemExit(main())
