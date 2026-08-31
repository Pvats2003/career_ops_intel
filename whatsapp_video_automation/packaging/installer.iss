; Inno Setup script for InstaCore Sync.
; Build the PyInstaller output first (packaging/build.bat), then compile
; this script with Inno Setup 6 (https://jrsoftware.org/isinfo.php):
;   iscc packaging\installer.iss
;
; Produces InstaCoreSync-Setup-<version>.exe in packaging\output\.

#define MyAppName "InstaCore Sync"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Career Ops Intel"
#define MyAppExeName "InstaCoreSync.exe"

[Setup]
AppId={{6C9E6C0B-6E9B-4C1B-9E1A-0B6C6C6D5B22}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=InstaCoreSync-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "autostart"; Description: "Start {#MyAppName} automatically when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\InstaCoreSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\config\settings.example.yaml"; DestDir: "{userappdata}\InstacoreSync\config"; DestName: "settings.local.yaml"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\InstacoreSync\logs"
