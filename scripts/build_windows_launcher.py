"""Build the windowed GUI entry point with the existing Windows .NET compiler."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime import VERSION


def compiler():
    windows = Path(os.environ.get('WINDIR', 'C:/Windows'))
    choices = [windows / 'Microsoft.NET' / arch / 'v4.0.30319/csc.exe'
               for arch in ('Framework64', 'Framework')]
    found = next((path for path in choices if path.is_file()), None)
    if found is None:
        raise RuntimeError('The existing .NET Framework C# compiler is required for the Windows launcher.')
    return found


def build_launcher(destination):
    if sys.platform != 'win32':
        raise RuntimeError('The Windows launcher must be built on Windows.')
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    version = destination / 'launcher-version.cs'
    version.write_text('[assembly: System.Reflection.AssemblyVersion("' + VERSION + '.0")]\n'
                       '[assembly: System.Reflection.AssemblyFileVersion("' + VERSION + '.0")]\n', encoding='utf-8')
    output = destination / 'Spool.exe'
    subprocess.run([str(compiler()), '/nologo', '/target:winexe', '/platform:anycpu',
                    '/reference:System.Windows.Forms.dll', '/reference:System.Web.Extensions.dll',
                    '/win32icon:' + str(ROOT / 'static/spool.ico'),
                    '/out:' + str(output), str(ROOT / 'packaging/windows-launcher.cs'), str(version)], check=True)
    # The generated assembly metadata belongs in build output, not the payload.
    version.unlink()
    return output


if __name__ == '__main__':
    print(build_launcher(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'dist/VideoDownloader'))
