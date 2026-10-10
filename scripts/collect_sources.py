"""Archive exact runtime/dependency sources and notices for public binary builds."""
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/release-sources'
OUT.mkdir(parents=True,exist_ok=True)
if (ROOT/'build/ffmpeg-source-records').is_dir():
    shutil.copytree(ROOT/'build/ffmpeg-source-records',OUT,dirs_exist_ok=True)


def fetch(url, target, expected=None):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url,timeout=90) as response:
                content=response.read()
            digest=hashlib.sha256(content).hexdigest()
            if expected and digest != expected:
                raise ValueError('Source checksum mismatch: '+target.name)
            target.write_bytes(content)
            return digest
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def distributions(python):
    code="import importlib.metadata as m,json; print(json.dumps([{'name':d.metadata['Name'],'version':d.version} for d in m.distributions()]))"
    return json.loads(subprocess.check_output([str(python),'-c',code],text=True))


def main():
    helper=ROOT/'.spotify-venv'/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    environments={'application':distributions(sys.executable),'spotify-helper':distributions(helper)}
    notices=OUT/'python-notices'
    notices.mkdir(exist_ok=True)
    for distribution in metadata.distributions():
        for file in distribution.files or []:
            if '.dist-info/' in str(file).replace('\\','/') and any(word in file.name.lower() for word in ('license','copying','notice')):
                source=Path(distribution.locate_file(file))
                if source.is_file():
                    shutil.copy2(source,notices/(distribution.metadata['Name']+'-'+file.name))
    # The helper's notices are gathered with its interpreter as well.
    helper_code='''import importlib.metadata as m,pathlib,shutil,sys
out=pathlib.Path(sys.argv[1])
for d in m.distributions():
 for f in d.files or []:
  if '.dist-info/' in str(f).replace('\\\\','/') and any(w in f.name.lower() for w in ('license','copying','notice')):
   p=pathlib.Path(d.locate_file(f))
   if p.is_file(): shutil.copy2(p,out/(d.metadata['Name']+'-'+f.name))
'''
    subprocess.run([str(helper),'-c',helper_code,str(notices)],check=True)
    dependencies=sorted({(d['name'],d['version']) for group in environments.values() for d in group})
    records=[]
    for name,version in dependencies:
        with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json',timeout=60) as response:
            package=json.load(response)
        sources=[item for item in package['urls'] if item['packagetype']=='sdist']
        if not sources:
            if name.lower()=='pywin32':
                url=f'https://github.com/mhammond/pywin32/archive/refs/tags/b{version}.tar.gz'
                target=OUT/f'pywin32-{version}-source.tar.gz'
                records.append({'name':name,'version':version,'source':url,'file':target.name,'sha256':fetch(url,target)})
                continue
            raise RuntimeError(f'No source distribution for {name} {version}; supply corresponding source before releasing.')
        source=sources[0]
        target=OUT/source['filename']
        digest=fetch(source['url'],target,source['digests']['sha256'])
        records.append({'name':name,'version':version,'source':source['url'],'file':target.name,'sha256':digest})
    python_version=platform.python_version()
    python_url=f'https://www.python.org/ftp/python/{python_version}/Python-{python_version}.tar.xz'
    target=OUT/f'Python-{python_version}.tar.xz'
    records.append({'name':'Python','version':python_version,'source':python_url,'file':target.name,'sha256':fetch(python_url,target)})
    node=subprocess.check_output(['node','--version'],text=True).strip()
    node_url=f'https://nodejs.org/dist/{node}/node-{node}.tar.xz'
    target=OUT/f'node-{node}.tar.xz'
    records.append({'name':'Node.js','version':node,'source':node_url,'file':target.name,'sha256':fetch(node_url,target)})
    (OUT/'manifest.json').write_text(json.dumps({'platform':sys.platform,'architecture':platform.machine(),
        'environments':environments,'sources':records},indent=2),encoding='utf-8')
    shutil.copy2(ROOT/'scripts/build_ffmpeg.sh',OUT/'build_ffmpeg.sh')
    shutil.copy2(ROOT/'THIRD_PARTY_NOTICES.md',OUT/'THIRD_PARTY_NOTICES.md')
    print(f'Archived {len(records)} exact dependency/runtime source distributions.')


if __name__=='__main__':
    main()
