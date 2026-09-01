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
AppVerName={#MyAppName} {#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; Let a non-technical user pick a different install location if they want
; to (e.g. a drive with more free space) -- this is the wizard page that
; shows DefaultDirName as an editable, browsable field; it is not disabled
; anywhere in this script.
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=InstaCoreSync-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\src\instacore_sync\ui\resources\icons\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "autostart"; Description: "Start {#MyAppName} automatically when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\InstaCoreSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Must match where the running app itself looks for its config: a frozen
; build resolves config/credentials.json/settings.local.yaml relative to
; the installed .exe's own folder ({app}), NOT %appdata% -- see
; resource_paths.app_base_dir(). Seeding to the wrong directory here would
; make this step silently pointless: the app would just auto-create its
; own fresh settings.local.yaml next to the exe on first run anyway.
Source: "..\config\settings.example.yaml"; DestDir: "{app}\config"; DestName: "settings.local.yaml"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
// InstaCore Sync's default OCR engine (Tesseract) is a separate,
// third-party install this setup does not bundle (it isn't something a
// license permits silently downloading and running as part of this
// installer, and a portable/bundled copy would still need to be fetched
// from somewhere at build time). The best this installer can honestly do
// is check for it and tell the user clearly, once, before they're left
// wondering why OCR shows "Unavailable" -- rather than silently saying
// nothing. This never blocks installation: PaddleOCR (or a later manual
// Tesseract install) both work without touching this installer again.
function TesseractFound(): Boolean;
begin
  Result := FileExists(ExpandConstant('{pf}\Tesseract-OCR\tesseract.exe'))
    or FileExists(ExpandConstant('{pf32}\Tesseract-OCR\tesseract.exe'))
    or FileExists(ExpandConstant('{localappdata}\Programs\Tesseract-OCR\tesseract.exe'));
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpReady) and not TesseractFound() then
  begin
    MsgBox(
      'Tesseract OCR was not found on this computer.' + #13#10 + #13#10 +
      'InstaCore Sync uses it to read the Device ID from your videos. Setup will ' +
      'continue and the app will still run -- but OCR will show "Unavailable" in ' +
      'the app until Tesseract is installed.' + #13#10 + #13#10 +
      'After installing Tesseract, open InstaCore Sync, go to the Health Check ' +
      'page, and confirm OCR turns green (or set the tesseract.exe path in ' +
      'Settings if it was installed to a non-standard location).' + #13#10 + #13#10 +
      'Download Tesseract OCR (free) from:' + #13#10 +
      'https://github.com/UB-Mannheim/tesseract/wiki',
      mbInformation, MB_OK
    );
  end;
end;

[UninstallDelete]
; Logs are diagnostic/ops data with no reason to survive a real uninstall.
Type: filesandordirs; Name: "{localappdata}\InstacoreSync\logs"
; config/ (settings.local.yaml, credentials.json, the encrypted token.json
; + token.key) lives under {app} -- Inno Setup only auto-removes files it
; itself installed, so anything the running app wrote there later
; (credentials.json a user copied in, the token files created at sign-in)
; would otherwise survive uninstall as orphaned files inside a
; supposedly-removed Program Files folder. A clean uninstall removes them;
; a user reinstalling should keep a backup copy of credentials.json first
; if they want to skip redoing Google Cloud Console setup (see
; docs/RECOVERY_GUIDE.md).
Type: filesandordirs; Name: "{app}\config"
; The database, Processed/NeedsReview/Failed folders, and the upload
; history/audit trail in %localappdata%\InstacoreSync are deliberately
; NOT deleted here -- that is the user's actual data (every video they've
; ever processed), and losing it silently on uninstall would be a real
; foot-gun. See docs/RECOVERY_GUIDE.md for a full/manual data wipe.
