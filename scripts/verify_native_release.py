"""Run an explicitly authorized disposable desktop window/bridge check."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime import VERSION


def main():
    executable=ROOT/'dist/VideoDownloader/VideoDownloader.exe' if sys.platform=='win32' else ROOT/'dist/Spool.app/Contents/MacOS/VideoDownloader'
    data=ROOT/'build/native-release-check-data'
    environment={**os.environ,'VIDEO_DOWNLOADER_DATA_DIR':str(data),'VIDEO_DOWNLOADER_PORT':'15781'}
    # --native-check intentionally opens and closes its own new view. The
    # release operator opts into this behavior in workflow_dispatch.
    subprocess.run([str(executable),'--native-check'],env=environment,check=True)
    result=json.loads((data/'native-check.json').read_text(encoding='utf-8'))
    assert result['passed'] and result['hasBridge'] and result['formats']==10
    assert sorted(result['methods'])==['choose_folder','drag_files'] and result['pickerEnabled']
    safe={key:result[key] for key in ('title','heading','hasBridge','methods','formats','pickerEnabled','ready_seconds','passed')}
    target=ROOT/'dist'/f'Spool-{VERSION}-{sys.platform}-{platform.machine()}-native-verification.json'
    target.write_text(json.dumps(safe,indent=2),encoding='utf-8')
    verification=ROOT/'dist'/f'Spool-{VERSION}-{sys.platform}-{platform.machine()}-verification.json'
    record=json.loads(verification.read_text(encoding='utf-8'))
    record['native_interactive_launch']='passed automated native window/DOM/bridge check'
    record['manual_user_workflow']='not tested'
    verification.write_text(json.dumps(record,indent=2),encoding='utf-8')
    if (data/'native-check.png').is_file():
        import shutil
        shutil.copy2(data/'native-check.png',ROOT/'dist'/f'Spool-{VERSION}-windows-native.png')
    print(json.dumps(safe))


if __name__=='__main__':main()
