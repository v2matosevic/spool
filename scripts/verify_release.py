"""Headless checks of the produced executable and its actual bundled tools."""
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
    payload=ROOT/'dist/VideoDownloader' if sys.platform=='win32' else ROOT/'dist/Spool.app'
    executable=payload/'VideoDownloader.exe' if sys.platform=='win32' else payload/'Contents/MacOS/VideoDownloader'
    data=ROOT/'build/release-check-data'
    environment={**os.environ,'VIDEO_DOWNLOADER_DATA_DIR':str(data),'VIDEO_DOWNLOADER_PORT':'15780'}
    diagnostic=json.loads(subprocess.check_output([str(executable),'--diagnose'],env=environment,text=True))
    assert diagnostic['version']==VERSION and diagnostic['frozen'] and diagnostic['assets']
    assert diagnostic['spotify_matcher'] is True
    internal=payload/'_internal' if sys.platform=='win32' else payload/'Contents/Frameworks'
    helper=internal/'spotify-resolver'/('SpotifyResolver.exe' if sys.platform=='win32' else 'SpotifyResolver')
    helper_check=json.loads(subprocess.check_output([str(helper),'--check-runtime'],env=environment,text=True))
    assert helper_check['ok'] and not helper_check['web_stack_loaded']
    for tool,path in diagnostic['tools'].items():
        assert Path(path).resolve().is_relative_to(payload.resolve()),f'External tool: {tool}'
        subprocess.run([path,'--version' if tool=='node' else '-version'],check=True,stdout=subprocess.DEVNULL)
    source=data/'fixture.wav'
    data.mkdir(parents=True,exist_ok=True)
    import wave
    with wave.open(str(source),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(44100);output.writeframes(b'\x00\x00'*44100)
    for extension in ('mp3','m4a','flac','wav'):
        output=data/('converted.'+extension)
        subprocess.run([diagnostic['tools']['ffmpeg'],'-v','error','-y','-i',str(source),str(output)],check=True)
        result=json.loads(subprocess.check_output([diagnostic['tools']['ffprobe'],'-v','error','-show_format','-of','json',str(output)],text=True))
        assert float(result['format']['duration'])>=.9
    report=json.loads(subprocess.check_output([str(executable),'--cli','diagnostics'],env=environment,text=True))
    assert 'events' in report
    process=subprocess.Popen([str(executable),'--mcp'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=environment)
    def request(identifier,method,params):
        process.stdin.write(json.dumps({'jsonrpc':'2.0','id':identifier,'method':method,'params':params})+'\n')
        process.stdin.flush()
        while True:
            line=process.stdout.readline()
            if not line:raise RuntimeError('Packaged MCP stream closed before response '+str(identifier))
            reply=json.loads(line)
            if reply.get('id')==identifier:
                if 'error' in reply:raise RuntimeError('MCP rejected '+method+': '+str(reply['error']['code']))
                return reply['result']
    initialization=request(1,'initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'release-check','version':'1'}})
    assert initialization['protocolVersion']
    process.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n')
    process.stdin.flush()
    tools=request(2,'tools/list',{})['tools']
    process.stdin.close()
    assert process.wait()==0
    assert len(tools)==13 and {'download_videos','get_diagnostics'}<={t['name'] for t in tools}
    if sys.platform=='darwin':
        import plistlib
        app=ROOT/'dist/Spool.app'
        with (app/'Contents/Info.plist').open('rb') as handle:
            plist=plistlib.load(handle)
        assert plist['CFBundleShortVersionString']==VERSION
        subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
        subprocess.run(['hdiutil','verify',str(ROOT/f'dist/Spool-{VERSION}-macos-{platform.machine()}.dmg')],check=True)
        dependencies=subprocess.check_output(['otool','-L',diagnostic['tools']['ffmpeg']],text=True)
        assert all(line.strip().startswith(('/usr/lib/','/System/Library/')) for line in dependencies.splitlines()[1:]),'Non-system FFmpeg dependency'
    output={'version':VERSION,'platform':sys.platform,'architecture':platform.machine(),'diagnostics':'passed',
            'bundled_tools':'passed','audio_conversions':['mp3','m4a','flac','wav'],'offline_diagnostics':'passed','mcp_tools':len(tools),
            'native_interactive_launch':'not tested','publisher_signed':False,'apple_notarized':False}
    (ROOT/'dist'/f'Spool-{VERSION}-{sys.platform}-{platform.machine()}-verification.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(output))


if __name__=='__main__':
    main()
