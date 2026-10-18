; Setup di RT per Windows (Inno Setup 6), compilato da scripts/build_app.py:
;   iscc /DAppVersion=4.3.0 /DAppNumericVersion=4.3.0 /DSourceDir=... /DOutputDir=... /DOutputName=... /DIconFile=... rt.iss
; Installa per l'utente corrente (niente amministratore) in %LOCALAPPDATA%\Programs\RT.
; I dati (lezioni, database, impostazioni) stanno in %USERPROFILE%\.rt e restano anche
; disinstallando l'app.
;
; Aggiornamento dall'app (rt/core/app_update.py): il setup parte con /SILENT, chiude RT,
; sostituisce i file e lo riapre con --after-update (riapre server e finestra).
; /NOLAUNCH=1 non riapre RT (prove automatiche).

#define RtCmd '""{app}\bin\rt""'

[Setup]
AppId={{5E0C2B7A-6C1D-4B8E-9C61-2D7B8F3A9E41}
AppName=RT
AppVersion={#AppVersion}
AppVerName=RT {#AppVersion}
VersionInfoVersion={#AppNumericVersion}
AppPublisher=atturk
AppPublisherURL=https://github.com/atturk/rt
AppUpdatesURL=https://github.com/atturk/rt/releases
DefaultDirName={localappdata}\Programs\RT
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\rt.ico
UninstallDisplayName=RT
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea un'icona sul desktop"; Flags: unchecked
Name: "startup"; Description: "Avvia RT all'accesso a Windows"; Flags: unchecked

[InstallDelete]
; codice e Python della versione precedente: niente file orfani dopo un aggiornamento
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\rt"
Type: filesandordirs; Name: "{app}\bin"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#IconFile}"; DestDir: "{app}"; DestName: "rt.ico"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\RT"; Filename: "{app}\python\pythonw.exe"; Parameters: "{#RtCmd} desktop"; WorkingDir: "{%USERPROFILE}"; IconFilename: "{app}\rt.ico"; AppUserModelID: "atturk.RT"; Comment: "Apre RT"
Name: "{autodesktop}\RT"; Filename: "{app}\python\pythonw.exe"; Parameters: "{#RtCmd} desktop"; WorkingDir: "{%USERPROFILE}"; IconFilename: "{app}\rt.ico"; AppUserModelID: "atturk.RT"; Tasks: desktopicon
Name: "{userstartup}\RT"; Filename: "{app}\python\pythonw.exe"; Parameters: "{#RtCmd} desktop --no-browser"; WorkingDir: "{%USERPROFILE}"; IconFilename: "{app}\rt.ico"; AppUserModelID: "atturk.RT"; Flags: runminimized; Tasks: startup

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "{#RtCmd} desktop"; WorkingDir: "{%USERPROFILE}"; Description: "Apri RT"; Flags: postinstall nowait skipifsilent
Filename: "{app}\python\pythonw.exe"; Parameters: "{#RtCmd} desktop --after-update"; WorkingDir: "{%USERPROFILE}"; Flags: nowait; Check: RelaunchAfterSilentUpdate

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function RelaunchAfterSilentUpdate(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:NOLAUNCH|0}') <> '1');
end;

{ Chiude RT (API, worker, browser delle catture) avviato da questa cartella: i file in uso
  non si potrebbero sostituire. }
procedure StopRt();
var
  ResultCode: Integer;
  Command: String;
begin
  Command := '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith(''' +
    ExpandConstant('{app}') + '\'', [System.StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force -ErrorAction SilentlyContinue"';
  Exec('powershell.exe', Command, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRt();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopRt();
end;
