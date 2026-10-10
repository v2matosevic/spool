"""Assemble a correctly classified macOS bundle while retaining a console engine."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

MACHO = {bytes.fromhex(value) for value in ('feedface','cefaedfe','feedfacf','cffaedfe','cafebabe','bebafeca','cafebabf','bfbafeca')}


def bundle_app(root, payload, helper_dir, build, dist, icon, name, version):
    """Reuse PyInstaller's cached analysis and its BUNDLE file-placement rules.

    Metadata/data belongs in Resources; executable code belongs in Frameworks
    or MacOS. Copying a mixed _internal tree into MacOS breaks codesigning.
    The original generated EXE remains console=True for the CLI/MCP contract.
    """
    root, payload, helper_dir, build, dist, icon = map(Path,(root,payload,helper_dir,build,dist,icon))
    notices = build / 'bundle-licenses'
    shutil.copytree(payload / 'licenses',notices,dirs_exist_ok=True)
    entries = []
    def collect(folder,prefix):
        for source in sorted(folder.rglob('*')):
            dest = prefix + '/' + source.relative_to(folder).as_posix()
            if source.is_symlink():
                entries.append((dest,os.readlink(source),'SYMLINK'))
            elif source.is_file():
                with source.open('rb') as handle:
                    magic=handle.read(4)
                entries.append((dest,str(source),'BINARY' if magic in MACHO else 'DATA'))
    collect(helper_dir,'spotify-resolver')
    collect(notices,'licenses')
    collect(root/'docs','docs')
    for doc in ('README.md','AGENTS.md','CLAUDE.md','LICENSE','SECURITY.md','THIRD_PARTY_NOTICES.md','CHANGELOG.md'):
        source=root/doc
        if source.is_file():entries.append((doc,str(source),'DATA'))
    generated=(build/'VideoDownloader.spec').read_text(encoding='utf-8')
    # The second COLLECT replaces its own generated directory. Extra sources
    # are outside it, so no helper/notices disappear during the rebuild.
    plist={'CFBundleName':name,'CFBundleDisplayName':name,'CFBundleVersion':version,
           'CFBundleShortVersionString':version,'LSMinimumSystemVersion':'13.0',
           'NSHighResolutionCapable':True,'LSBackgroundOnly':False,'LSUIElement':False}
    spec=build/'Spool-bundle.spec'
    spec.write_text(generated + '\napp = BUNDLE(coll, ' + repr(entries) + ', name=' + repr(name+'.app') +
                    ', icon=' + repr(str(icon)) + ", bundle_identifier='local.videodownloader.desktop', version=" +
                    repr(version) + ', info_plist=' + repr(plist) + ')\n',encoding='utf-8')
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--distpath',str(dist),
             '--workpath',str(build/'pyinstaller'),str(spec)]
    with (build/'bundle-packaging.log').open('w',encoding='utf-8') as log:
        subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
    app=dist/(name+'.app')
    subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
    return app
