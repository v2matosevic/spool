import json
from pathlib import Path

import app
import runtime


def test_brand_uses_a_stable_service_identity(tmp_path):
    client=app.create_app(tmp_path,start_worker=False).test_client()
    health=client.get('/api/health').json
    assert health['display_name']=='Spool'
    assert health['app']=='VideoDownloader'
    assert client.get('/api/state').json['app_name']=='Spool'


def test_fresh_install_uses_user_folders_and_keeps_existing_destination(tmp_path,monkeypatch):
    monkeypatch.setattr(runtime.Path,'home',lambda:tmp_path)
    assert runtime.default_downloads()==tmp_path/'Downloads'/'VideoDownloader'
    store=app.Store(tmp_path/'state')
    chosen=tmp_path/'existing-library'
    store.set_folder(str(chosen))
    assert app.Store(tmp_path/'state').folder()==chosen
    installer=Path('packaging/windows.iss').read_text()
    assert "Result := ExpandConstant('{localappdata}\\Programs\\VideoDownloader')" in installer
    assert 'UsePreviousAppDir=yes' in installer


def test_existing_agent_config_and_user_data_stay_compatible(monkeypatch):
    monkeypatch.delenv('VIDEO_DOWNLOADER_DATA_DIR',raising=False)
    assert runtime.APP_ID=='VideoDownloader'
    assert runtime.agent_configuration()['mcpServers'].keys()=={'video-downloader'}
    assert runtime.app_data_dir().name=='VideoDownloader'
    configuration=json.loads(Path('.mcp.json').read_text())
    assert configuration['mcpServers']['video-downloader']['command'].endswith('VideoDownloader.exe')


def test_windows_shortcuts_match_native_identity_and_have_a_dedicated_icon():
    from PIL import Image
    installer=Path('packaging/windows.iss').read_text()
    shortcuts=installer.split('[Icons]',1)[1].split('[Run]',1)[0].strip().splitlines()
    assert len(shortcuts)==2
    for shortcut in shortcuts:
        assert 'Filename: "{app}\\Spool.exe"' in shortcut
        assert f'AppUserModelID: "{runtime.WINDOWS_APP_ID}"' in shortcut
        assert 'IconFilename: "{app}\\_internal\\static\\spool.ico"' in shortcut
    with Image.open('static/spool.ico') as icon:
        assert {(16,16),(32,32),(48,48),(256,256)} <= icon.ico.sizes()


def test_windows_identity_round_trip():
    import sys
    import pytest
    from desktop import windows_identity
    if sys.platform != 'win32':
        pytest.skip('Windows shell identity needs Windows')
    assert windows_identity(set_identity=True)==runtime.WINDOWS_APP_ID


def test_windowed_launcher_starts_engine_without_a_console(tmp_path):
    import subprocess
    import sys
    import time
    import pytest
    from scripts.build_windows_launcher import build_launcher, compiler
    if sys.platform != 'win32':
        pytest.skip('Windows launcher needs Windows')
    folder = tmp_path / 'launcher test with spaces'
    launcher = build_launcher(folder)
    executable = launcher.read_bytes()
    header = int.from_bytes(executable[0x3c:0x40], 'little')
    assert executable[header:header+4] == b'PE\0\0'
    assert int.from_bytes(executable[header+92:header+94], 'little') == 2  # Windows GUI
    probe = folder / 'probe.cs'
    probe.write_text('''using System; using System.IO; using System.Runtime.InteropServices;
class Probe {
 [DllImport("kernel32.dll")] static extern IntPtr GetConsoleWindow();
 static void Main() { File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,
 "console-result.txt"), GetConsoleWindow().ToInt64().ToString()); }
}''')
    subprocess.run([str(compiler()), '/nologo', '/target:exe', '/out:' + str(folder / 'VideoDownloader.exe'), str(probe)], check=True)
    import os
    subprocess.run([str(launcher)], check=True, env={**os.environ, 'VIDEO_DOWNLOADER_DATA_DIR':str(folder/'data')})
    result = folder / 'console-result.txt'
    deadline = time.monotonic() + 15
    while not result.exists() and time.monotonic() < deadline:
        time.sleep(.1)
    assert result.read_text() == '0'
