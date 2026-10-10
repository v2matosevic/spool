"""Quiet source launcher; the packaged Desktop shortcut runs the native executable."""
from desktop import main, health
from runtime import APP_ID, APP_NAME, VERSION, URL

if __name__ == '__main__':
    try:
        current = health()
        if current and current.get('app') == APP_ID and current.get('version') != VERSION:
            # Preserve the existing user's launcher until an explicit service restart.
            import webbrowser
            webbrowser.open(URL)
        else:
            raise SystemExit(main())
    except Exception as error:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0,str(error),APP_NAME,16)
