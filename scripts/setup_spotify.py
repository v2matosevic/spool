"""Install spotDL in its own project environment; never change the app's MCP stack."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
environment = ROOT / '.spotify-venv'
python = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
if not python.is_file():
    if environment.exists():
        raise SystemExit('An incomplete Spotify environment exists. Inspect it before replacing it.')
    subprocess.run([sys.executable,'-m','venv',str(environment)],check=True)
subprocess.run([str(python),'-m','pip','install','--upgrade','pip==26.2.1'],check=True)
subprocess.run([str(python),'-m','pip','install','-r',str(ROOT / 'requirements-spotify.txt')],check=True)
# Upstream 4.5.2 pins obsolete web-server dependencies. This matching-only
# adapter installs its maintained runtime dependencies explicitly, then the
# unchanged upstream library without console/web extras. Existing private
# environments are not uninstalled or automatically recreated.
subprocess.run([str(python),'-m','pip','install','--no-deps','spotdl==4.5.2'],check=True)
print('Spotify matcher environment ready.')
