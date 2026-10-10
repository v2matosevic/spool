#ifndef AppVersion
  #define AppVersion "1.4.0"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\dist\VideoDownloader"
#endif
#ifndef IconFile
  #define IconFile "..\build\icon.ico"
#endif
#ifndef AppNameValue
  #define AppNameValue "Spool"
#endif

[Setup]
AppId={{A752B942-0937-4F08-929B-80205786DBEF}
AppName={#AppNameValue}
AppVersion={#AppVersion}
AppPublisher={#AppNameValue}
DefaultDirName={code:DefaultFolder}
DefaultGroupName={#AppNameValue}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename={#AppNameValue}-{#AppVersion}-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\_internal\static\spool.ico
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
SetupLogging=yes

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppNameValue}"; Filename: "{app}\Spool.exe"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\static\spool.ico"; AppUserModelID: "Local.Spool.Desktop"
Name: "{autodesktop}\{#AppNameValue}"; Filename: "{app}\Spool.exe"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\static\spool.ico"; AppUserModelID: "Local.Spool.Desktop"; Tasks: desktopicon

[Run]
Filename: "{app}\Spool.exe"; Description: "Open {#AppNameValue}"; Flags: nowait postinstall skipifsilent

[Code]
function DefaultFolder(Param: String): String;
begin
  Result := ExpandConstant('{localappdata}\Programs\VideoDownloader');
end;

procedure RemoveLegacyShortcut(Path: String);
var
  Shell, Link: Variant;
  Target: String;
begin
  if not FileExists(Path) then Exit;
  try
    Shell := CreateOleObject('WScript.Shell');
    Link := Shell.CreateShortcut(Path);
    Target := Link.TargetPath;
    { Remove only a shortcut pointing at this installation, never an unrelated one. }
    if CompareText(Target, ExpandConstant('{app}\VideoDownloader.exe')) = 0 then
    begin
      if DeleteFile(Path) then Log('Replaced legacy shortcut: ' + Path);
    end;
  except
    Log('Preserved unrecognized legacy shortcut: ' + Path);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    RemoveLegacyShortcut(ExpandConstant('{autoprograms}\VideoDownloader.lnk'));
    RemoveLegacyShortcut(ExpandConstant('{autodesktop}\VideoDownloader.lnk'));
  end;
end;
