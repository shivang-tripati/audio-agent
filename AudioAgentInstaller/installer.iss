#define MyAppName "AudioAgent"
#define MyAppVersion "1.4"
#define MyAppPublisher "ACS"

[Setup]
AppId={{8A1C7E7A-9E2A-4E3B-8E3F-999999999999}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\AudioAgent
DefaultGroupName=AudioAgent
OutputDir=output
OutputBaseFilename=AudioAgentSetup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
DisableProgramGroupPage=yes
SetupIconFile=icon.ico

[Dirs]

Name: "{commonappdata}\AudioAgent"; Permissions: users-modify
Name: "{commonappdata}\AudioAgent\logs"; Permissions: users-modify
Name: "{commonappdata}\AudioAgent\config"; Permissions: users-modify
Name: "{commonappdata}\AudioAgent\audio_cache"; Permissions: users-modify

[Files]

; Install FULL build folder
Source: "dist\AudioAgent\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

; VC++ runtime
Source: "extras\vcredist_x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]

Name: "{group}\AudioAgent"; Filename: "{app}\AudioAgentUI.exe"
Name: "{commondesktop}\AudioAgent"; Filename: "{app}\AudioAgentUI.exe"

[Run]

; Stop any old running agent
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM AudioAgent.exe"; Flags: runhidden

; Install VC++ runtime if missing
Filename: "{tmp}\vcredist_x64.exe"; Parameters: "/quiet /norestart"; StatusMsg: "Installing Microsoft VC++ Runtime..."; Flags: waituntilterminated; Check: ShouldInstallVC

; Install Windows Service
Filename: "{app}\AudioAgentService.exe"; Parameters: "install"; StatusMsg: "Installing AudioAgent service..."; Flags: runhidden waituntilterminated

; Set service to auto start
Filename: "{cmd}"; Parameters: "/C sc config AudioAgentService start= auto"; Flags: runhidden waituntilterminated

; Enable automatic restart if service crashes
Filename: "{cmd}"; Parameters: "/C sc failure AudioAgentService reset= 0 actions= restart/5000"; Flags: runhidden waituntilterminated

; Start service
Filename: "{app}\AudioAgentService.exe"; Parameters: "start"; StatusMsg: "Starting AudioAgent service..."; Flags: runhidden waituntilterminated

; Launch tray UI
Filename: "{app}\AudioAgentUI.exe"; Flags: nowait

[UninstallRun]

Filename: "{app}\AudioAgentService.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopService"

Filename: "{app}\AudioAgentService.exe"; Parameters: "remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveService"

Filename: "{cmd}"; Parameters: "/C taskkill /F /IM AudioAgent.exe"; Flags: runhidden; RunOnceId: "KillAgent"

[Code]

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Exec(
    'taskkill',
    '/F /IM AudioAgent.exe',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );

  Result := True;
end;

function ShouldInstallVC(): Boolean;
begin
  Result := not FileExists(
    ExpandConstant('{sys}\msvcp140.dll')
  );
end;