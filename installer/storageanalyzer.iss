; Inno Setup script for StorageAnalyzer.
;
; Wraps the standalone dist\storageanalyzer.exe in a per-user installer that
;   * installs to %LOCALAPPDATA%\Programs\StorageAnalyzer (no admin needed),
;   * optionally adds that folder to the user PATH so `storageanalyzer` works
;     from any terminal,
;   * registers a proper uninstaller (Apps & features),
;   * stamps publisher / version metadata.
;
; The version is injected by build-installer.ps1 from storageanalyzer.__version__;
; the default below is only used if you run ISCC by hand.
;
; Build:   ISCC.exe /DMyAppVersion=1.0.0 installer\storageanalyzer.iss
; Or just: .\build-installer.ps1   (builds the exe first, then this)

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "StorageAnalyzer"
#define MyAppPublisher "Cameron Crow"
#define MyAppURL "https://github.com/CameronCrow/StorageAnalyzer"
#define MyAppExeName "storageanalyzer.exe"

[Setup]
; A stable AppId keeps upgrades/uninstall coherent across versions -- do not change.
AppId={{75FD88CC-FE15-46C9-894F-5A5CABD9E1A5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
; Per-user install -- no UAC prompt, installs under %LOCALAPPDATA%\Programs.
PrivilegesRequired=lowest
ChangesEnvironment=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=StorageAnalyzer-Setup-{#MyAppVersion}
SetupIconFile=..\packaging\storageanalyzer.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "addtopath"; Description: "Add StorageAnalyzer to my PATH (run ""storageanalyzer"" from any terminal)"; Flags: checkedonce

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} on GitHub"; Filename: "{#MyAppURL}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Code]
const
  EnvironmentKey = 'Environment';

procedure EnvAddPath(Path: string);
var
  Paths: string;
begin
  { Read the existing user PATH (empty if unset). }
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', Paths) then
    Paths := '';

  { Skip if already present (delimited, case-insensitive). }
  if Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(Paths) + ';') > 0 then
    exit;

  { Append, normalising the trailing delimiter. }
  if Paths = '' then
    Paths := Path
  else if Copy(Paths, Length(Paths), 1) = ';' then
    Paths := Paths + Path
  else
    Paths := Paths + ';' + Path;

  if RegWriteStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', Paths) then
    Log('PATH: added ' + Path)
  else
    Log('PATH: FAILED to add ' + Path);
end;

procedure EnvRemovePath(Path: string);
var
  Paths: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', Paths) then
    exit;

  P := Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(Paths) + ';');
  if P = 0 then
    exit;

  Delete(Paths, P - 1, Length(Path) + 1);
  RegWriteStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', Paths);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    EnvAddPath(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    EnvRemovePath(ExpandConstant('{app}'));
end;
