"""One entry point for native app, service, JSON CLI and MCP."""
from __future__ import annotations
import json
import subprocess
import sys
import time
from urllib.request import urlopen
from runtime import APP_ID, APP_NAME, DATA, ROOT, URL, VERSION, WINDOWS_APP_ID, binary, command, process_options
import diagnostics as diag


def health():
    try:
        with urlopen(URL + '/api/health', timeout=1) as response:
            return json.load(response)
    except Exception:
        return None


def ensure_server():
    current = health()
    if current:
        if current.get('app') != APP_ID or current.get('version') != VERSION:
            diag.record('service.version_mismatch', 'error', expected=VERSION, observed=current.get('version'))
            raise RuntimeError('An older downloader or another app is using the local port. Restart the downloader to apply this update.')
        return URL
    DATA.mkdir(parents=True,exist_ok=True)
    process = subprocess.Popen(command('--serve'),cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                               start_new_session=sys.platform != 'win32',**process_options())
    diag.record('service.spawned', child_pid=process.pid)
    for _ in range(200):
        current = health()
        if current and current.get('app') == APP_ID and current.get('version') == VERSION:
            diag.record('service.connected', child_pid=process.pid)
            return URL
        time.sleep(.1)
    raise RuntimeError('The downloader did not start. Run VideoDownloader.exe --cli diagnostics to read the startup report.')


class DesktopAPI:
    def __init__(self):
        # Public properties are recursively exposed by pywebview. Keep the native
        # window private: exposing it is both slow and far too much capability.
        self._window = None

    def choose_folder(self):
        import webview
        choice = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return choice[0] if choice else None

    def drag_files(self, job_id, indexes):
        if sys.platform != 'win32':
            raise ValueError('Native file dragging is available on Windows. Use Copy path or Save a copy here.')
        if not isinstance(job_id, str) or len(job_id) != 12 or any(c not in '0123456789abcdef' for c in job_id):
            raise ValueError('Choose a completed download.')
        from agent_client import AgentClient
        paths = AgentClient(autostart=False).request('/api/jobs/' + job_id + '/file-paths', {'indexes': indexes}, timeout=5)['file_paths']
        return _drag_windows(self._window.native, paths)


def _file_drop_data(paths):
    """The shell receives existing files plus text paths, never source URLs."""
    from System.Collections.Specialized import StringCollection
    from System.Windows.Forms import DataObject, DataFormats
    files = StringCollection()
    for path in paths:
        files.Add(path)
    data = DataObject()
    data.SetFileDropList(files)
    data.SetData(DataFormats.UnicodeText, '\r\n'.join(paths))
    return data


def _drag_windows(native, paths):
    from System import Action
    from System.Windows.Forms import Control, DragDropEffects, MouseButtons
    result = {'started': False, 'effect': 'None'}
    def start():
        # The bridge runs on a worker thread. OLE dragging must use the UI's
        # STA thread, and a slow request must not start after mouse release.
        if Control.MouseButtons & MouseButtons.Left:
            result['started'] = True
            result['effect'] = str(native.DoDragDrop(_file_drop_data(paths), DragDropEffects.Copy))
    native.Invoke(Action(start))
    return result


def native_background():
    """Match the page's system theme before its first paint on Windows."""
    if sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                if winreg.QueryValueEx(key,'AppsUseLightTheme')[0]:
                    return '#f5f2ec'
        except OSError:
            pass
    return '#0e0d0c'


def windows_identity(set_identity=False):
    """Use one stable shell identity for the native process and its shortcuts."""
    if sys.platform != 'win32':
        return None
    import ctypes
    from ctypes import wintypes
    shell = ctypes.windll.shell32
    if set_identity:
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
        shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        if shell.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID) != 0:
            raise RuntimeError('Windows could not set the Spool taskbar identity.')
    value = ctypes.c_wchar_p()
    shell.GetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
    shell.GetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    if shell.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(value)) != 0:
        return None
    try:
        return value.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.ole32.CoTaskMemFree(value)


def native_window(check=False):
    windows_identity(set_identity=True)
    import webview
    started = time.monotonic()
    bridge = DesktopAPI()
    window = webview.create_window(APP_NAME,ensure_server(),js_api=bridge,width=1280,height=900,
                                  min_size=(780,620),background_color=native_background(),hidden=check)
    bridge._window = window
    diag.record('desktop.window_created', taskbar_app_id=windows_identity())
    window.events.loaded += lambda: diag.record('desktop.loaded', elapsed_ms=round((time.monotonic()-started)*1000))
    window.events.closed += lambda: diag.record('desktop.closed')
    webview.settings['ALLOW_DOWNLOADS'] = True
    if check:
        def verify():
            result = {}
            try:
                # WebView2 can suspend rendering in an invisible window. Show
                # the verification view before requesting its rendered image.
                window.show()
                time.sleep(.3)
                result = json.loads(window.evaluate_js('JSON.stringify({title:document.title,heading:document.querySelector("h1")?.textContent,hasBridge:!!window.pywebview,methods:Object.keys(window.pywebview?.api||{}),formats:document.querySelector("#mode")?.options.length,pickerEnabled:!document.querySelector("#browse-folder")?.disabled})'))
                result['ready_seconds'] = round(time.monotonic() - started,3)
                result['passed'] = result.get('title') == APP_NAME and sorted(result.get('methods', [])) == ['choose_folder', 'drag_files'] and result.get('formats') == 10 and result.get('pickerEnabled') is True
                if sys.platform == 'win32':
                    result['taskbar_app_id'] = windows_identity()
                    result['icon_path'] = str(ROOT / 'static/spool.ico')
                    result['passed'] = result['passed'] and result['taskbar_app_id'] == WINDOWS_APP_ID and (ROOT / 'static/spool.ico').is_file()
                    from System import Action
                    from System.IO import FileStream, FileMode
                    from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
                    stream = FileStream(str(DATA / 'native-check.png'),FileMode.Create)
                    capture = []
                    try:
                        window.native.Invoke(Action(lambda: capture.append(window.native.browser.webview.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png,stream))))
                        if not capture[0].Wait(10000):
                            raise TimeoutError('Native screenshot capture timed out.')
                    finally:
                        stream.Close()
            except Exception as error:
                result.update(passed=False,error=str(error))
            finally:
                (DATA / 'native-check.json').write_text(json.dumps(result),encoding='utf-8')
                window.destroy()
        window.events.loaded += verify
    webview.start(gui='edgechromium' if sys.platform == 'win32' else None,debug=False,
                  icon=str(ROOT / 'static/spool.ico') if sys.platform == 'win32' else None,
                  private_mode=False,storage_path=str(DATA / 'webview'))
    if check and not json.loads((DATA / 'native-check.json').read_text(encoding='utf-8')).get('passed'):
        raise RuntimeError('Native verification failed; see native-check.json in the app data folder.')


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    component = 'mcp' if '--mcp' in args else 'cli' if '--cli' in args else 'service' if '--serve' in args else 'desktop'
    diag.setup(component)
    diag.install_crash_hooks()
    if '--cli' in args:
        from agent_cli import main as cli
        return cli(args[args.index('--cli') + 1:])
    if '--mcp' in args:
        from mcp_server import main as mcp_main
        mcp_main()
        return 0
    if '--serve' in args:
        from app import make_server
        make_server().run()
        return 0
    if '--diagnose' in args:
        import importlib.metadata
        import webview
        import spotify_support
        result = {'app_name':APP_NAME,'version':VERSION,'platform':sys.platform,'frozen':bool(getattr(sys,'frozen',False)),
                  'data':str(DATA),'assets':(ROOT / 'templates/index.html').is_file(),
                  'tools':{name:binary(name) for name in ('ffmpeg','ffprobe','node')},
                  'spotify_matcher':spotify_support.ready(),
                  'packages':{name:importlib.metadata.version(name) for name in ('yt-dlp','pywebview','mcp')}}
        print(json.dumps(result))
        return 0 if all(result['tools'].values()) and result['assets'] else 1
    if '--no-browser' in args:
        ensure_server()
        return 0
    if '--browser' in args:
        import webbrowser
        webbrowser.open(ensure_server())
        return 0
    native_window(check='--native-check' in args)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        diag.failure('desktop.entry_failed', error)
        if any(arg in sys.argv for arg in ('--cli','--mcp','--serve','--diagnose','--native-check')):
            raise
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,str(error),APP_NAME,16)
        else:
            raise
