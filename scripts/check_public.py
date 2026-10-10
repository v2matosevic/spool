"""Fail closed on accidental private files and broken local documentation links."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOT = {'app.py','desktop.py','runtime.py','downloader.py','diagnostics.py','options.py',
                'platforms.py','agent_client.py','agent_cli.py','mcp_server.py','spotify_support.py',
                'spotify_worker.py','launch.pyw','pytest.ini','README.md','LICENSE','SECURITY.md',
                'CONTRIBUTING.md','CHANGELOG.md','THIRD_PARTY_NOTICES.md','AGENTS.md','CLAUDE.md',
                '.gitignore','.gitattributes','.mcp.json', 'requirements.txt','requirements-dev.txt',
                'requirements-build.txt','requirements-spotify.txt','requirements-lock.txt',
                'requirements-spotify-lock.txt','Start Spool.cmd','Start Spool.command',
                'Build desktop.cmd','Build desktop.command','Install Spool.command','Update engine.cmd'}
ALLOWED_DIRS = {'scripts','packaging','static','templates','tests','docs','.github'}
errors = []
files = subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'], cwd=ROOT).decode().split('\0')
for relative in set(files) - {''}:
    path = ROOT / relative
    if path.is_symlink() or not path.is_file():
        errors.append(f'Unexpected linked/missing file: {relative}')
        continue
    first = relative.split('/')[0]
    if relative not in ALLOWED_ROOT and first not in ALLOWED_DIRS and relative not in {'.ade/logo.png','.ade/logo.svg'}:
        errors.append(f'Unapproved public path: {relative}')
    if re.search(r'(^|/)(?:connection\.json|cookies\.txt|\.env(?:\..*)?|SESSION[^/]*|VERIFICATION[^/]*|STATUS\.md|ADE-INTEGRATION\.md)$',relative,re.I):
        errors.append(f'Private state/record: {relative}')
    if path.suffix in {'.py','.js','.md','.json','.toml','.yml','.yaml','.txt','.html','.cs','.iss','.command','.cmd'}:
        content = path.read_text(encoding='utf-8')
        # No output includes matching values. These checks supplement Gitleaks.
        patterns = [r'[A-Za-z]:[\\/]Users[\\/](?!Public\b)[^\s\"\']+',
                    r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{32,})',
                    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
                    r'ade-[0-9a-f]{8}-[0-9a-f-]{27,}']
        if any(re.search(pattern,content) for pattern in patterns):
            errors.append(f'Private marker/credential candidate: {relative}')
        if path.suffix == '.md':
            for link in re.findall(r'\]\(([^)]+)\)',content):
                target = link.split('#',1)[0].split(' ',1)[0]
                if not target or re.match(r'(?:https?://|mailto:)',target):
                    continue
                if not (path.parent / target).is_file():
                    errors.append(f'Broken documentation link in {relative}: {target}')
if errors:
    raise SystemExit('\n'.join(sorted(set(errors))))
print(f'Public allowlist, privacy markers and documentation links passed for {len(set(files)-{chr(0),""})} files.')
