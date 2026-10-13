#define MyAppName "RedioCast Agent"
#define MyAppVersion "2.1.0"
#define MyAppPublisher "Shivang Tripathi"
#define MyAppURL "https://redio.radhakrishnajewellery.in"
#define MyAppExeName "AudioAgentUI.exe"

[Setup]
AppId={{8A1C7E7A-9E2A-4E3B-8E3F-999999999999}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\AudioAgent
DefaultGroupName=AudioAgent
OutputDir=output
OutputBaseFilename=AudioAgentSetup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
DisableProgramGroupPage=yes
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\AudioAgentUI.exe
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription="Audio Agent Installation"
VersionInfoCopyright="Copyright © {#MyAppPublisher}"
MinVersion=6.1.7601
AppComments="Cloud-based audio scheduling and playlist broadcasting system"
AppContact="support@{#MyAppPublisher}.com"

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
Name: "{commonappdata}\AudioAgent"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{commonappdata}\AudioAgent\logs"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{commonappdata}\AudioAgent\config"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{commonappdata}\AudioAgent\audio_cache"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{commonappdata}\AudioAgent\vlc"; Permissions: users-modify; Flags: uninsneveruninstall

[Files]
Source: "dist\AudioAgent\AudioAgent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\AudioAgent\AudioAgentUI.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\AudioAgent\AudioAgentService.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\AudioAgent\_internal\*"; DestDir: "{app}\_internal"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "dist\AudioAgent\_internal\vlc\*"; DestDir: "{commonappdata}\AudioAgent\vlc"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "extras\vcredist_x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "extras\AudioAgent.exe.manifest"; DestDir: "{app}"; Flags: ignoreversion
Source: "extras\AudioAgentUI.exe.manifest"; DestDir: "{app}"; Flags: ignoreversion
Source: "extras\AudioAgentService.exe.manifest"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\AudioAgent"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\AudioAgent"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{cmd}"; Parameters: "/C echo Preparing installation..."; Flags: shellexec waituntilterminated; StatusMsg: "Preparing installation..."
Filename: "taskkill.exe"; Parameters: "/F /IM AudioAgentUI.exe 2>nul"; Flags: runhidden
Filename: "{tmp}\vcredist_x64.exe"; Parameters: "/quiet /norestart"; StatusMsg: "Installing Microsoft VC++ Runtime..."; Flags: waituntilterminated; Check: ShouldInstallVC
Filename: "{app}\AudioAgentService.exe"; Parameters: "install"; StatusMsg: "Registering AudioAgent service..."; Flags: runhidden waituntilterminated
Filename: "{cmd}"; Parameters: "/C sc description AudioAgentService ""Manages scheduled audio playback and playlist streaming for AudioAgent"""; Flags: runhidden waituntilterminated
Filename: "{cmd}"; Parameters: "/C sc config AudioAgentService start= auto"; Flags: runhidden waituntilterminated

[UninstallRun]
Filename: "{app}\AudioAgentService.exe"; Parameters: "remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveService"
Filename: "{cmd}"; Parameters: "/C sc delete AudioAgentService"; Flags: runhidden waituntilterminated; RunOnceId: "ForceDeleteService"
Filename: "taskkill.exe"; Parameters: "/F /IM AudioAgent.exe 2>nul"; Flags: runhidden; RunOnceId: "KillAgent"
Filename: "taskkill.exe"; Parameters: "/F /IM AudioAgentUI.exe 2>nul"; Flags: runhidden; RunOnceId: "KillUI"
Filename: "taskkill.exe"; Parameters: "/F /IM AudioAgentService.exe 2>nul"; Flags: runhidden; RunOnceId: "KillService"

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\AudioAgent\vlc"

[Code]
// Declare Windows API GetTickCount function
function GetTickCount(): LongWord;
external 'GetTickCount@kernel32.dll stdcall';

const
  AgentServiceName = 'AudioAgentService';
  AgentWorkerImage = 'AudioAgent.exe';

  ServiceNotInstalled = -1;
  ServiceStopped      = 1;
  ServiceStartPending = 2;
  ServiceStopPending  = 3;
  ServiceRunning      = 4;

  StopTimeoutMs       = 120000;
  WorkerExitTimeoutMs = 30000;
  StartTimeoutMs      = 120000;
  PollIntervalMs      = 500;

var
  ScOutputFile: String;

procedure SetStatus(const Msg: String);
begin
  Log(Msg);
  if WizardForm.StatusLabel <> nil then
  begin
    WizardForm.StatusLabel.Caption := Msg;
    WizardForm.Refresh;
  end;
end;

function ScratchFile: String;
begin
  if ScOutputFile = '' then
    ScOutputFile := ExpandConstant('{tmp}\AudioAgent_sc_out.txt');
  Result := ScOutputFile;
end;

function ScCapture(const Params: String): Boolean;
var
  ResultCode: Integer;
  OutFile: String;
begin
  OutFile := ScratchFile;
  DelTree(OutFile, False, True, False);
  Result := Exec(ExpandConstant('{cmd}'),
    '/C sc ' + Params + ' > "' + OutFile + '" 2>&1', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function ScCommand(const Params: String): Boolean;
var
  ResultCode: Integer;
begin
  ResultCode := -1;
  Result := Exec(ExpandConstant('{cmd}'), '/C sc ' + Params, '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function LeadingInt(const S: String): Integer;
var
  I: Integer;
  C: Char;
begin
  Result := 0;
  for I := 1 to Length(S) do
  begin
    C := S[I];
    if (C >= '0') and (C <= '9') then
      Result := Result * 10 + (Ord(C) - Ord('0'))
    else if Result > 0 then
      Exit;
  end;
end;

function QueryServiceState: Integer;
var
  Lines: TArrayOfString;
  I, Code: Integer;
  Line, Tail: String;
begin
  Result := ServiceNotInstalled;
  if not ScCapture('query ' + AgentServiceName) then
    Exit;
  if not LoadStringsFromFile(ScratchFile, Lines) then
    Exit;

  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    Line := Lines[I];
    if Pos('STATE', Uppercase(Line)) > 0 then
    begin
      Code := Pos(':', Line);
      if Code > 0 then
      begin
        Tail := Trim(Copy(Line, Code + 1, MaxInt));
        Result := LeadingInt(Tail);
        Exit;
      end;
    end;
  end;
end;

function ServiceStateName(State: Integer): String;
begin
  if State = ServiceNotInstalled then Result := 'NOT INSTALLED'
  else if State = ServiceStopped then Result := 'STOPPED'
  else if State = ServiceStartPending then Result := 'START_PENDING'
  else if State = ServiceStopPending then Result := 'STOP_PENDING'
  else if State = ServiceRunning then Result := 'RUNNING'
  else Result := 'STATE ' + IntToStr(State);
end;

function WaitForServiceState(Target: Integer; TimeoutMs: Integer): Boolean;
var
  Started: LongWord;
begin
  Result := False;
  Started := GetTickCount;
  repeat
    if QueryServiceState = Target then
    begin
      Result := True;
      Exit;
    end;
    Sleep(PollIntervalMs);
  until (GetTickCount - Started) >= LongWord(TimeoutMs);
end;

function WorkerRunning: Boolean;
var
  Lines: TArrayOfString;
  ResultCode: Integer;
  I: Integer;
begin
  Result := False;
  DelTree(ScratchFile, False, True, False);
  if not Exec(ExpandConstant('{cmd}'),
       '/C tasklist /FI "IMAGENAME eq ' + AgentWorkerImage + '" /NH > "' +
       ScratchFile + '" 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Exit;
  if not LoadStringsFromFile(ScratchFile, Lines) then
    Exit;

  for I := 0 to GetArrayLength(Lines) - 1 do
    if Pos(Uppercase(AgentWorkerImage), Uppercase(Lines[I])) > 0 then
    begin
      Result := True;
      Exit;
    end;
end;

function WaitForWorkerExit(TimeoutMs: Integer): Boolean;
var
  Started: LongWord;
begin
  Result := False;
  Started := GetTickCount;
  repeat
    if not WorkerRunning then
    begin
      Result := True;
      Exit;
    end;
    Sleep(PollIntervalMs);
  until (GetTickCount - Started) >= LongWord(TimeoutMs);
end;

function StopFailureMessage: String;
begin
  Result := 'The ' + AgentServiceName + ' service could not be stopped, so its'
    + #13#10 + 'binaries cannot be replaced safely.'
    + #13#10 + #13#10 +
    'Please close the AudioAgent tray, run "sc stop ' + AgentServiceName +
    '"' + #13#10 + 'in an elevated command prompt and wait until it reports'
    + #13#10 + 'STOPPED, then run this installer again.'
    + #13#10 + #13#10 + 'Current state: ' + ServiceStateName(QueryServiceState);
end;

function StopServiceForUpgrade: Boolean;
var
  State: Integer;
begin
  Result := False;
  State := QueryServiceState;

  if State = ServiceNotInstalled then
  begin
    SetStatus('AudioAgent service is not installed - continuing.');
    Result := True;
    Exit;
  end;

  if (State = ServiceStopped) and (not WorkerRunning) then
  begin
    SetStatus('AudioAgent service is already stopped.');
    Result := True;
    Exit;
  end;

  if State <> ServiceStopped then
  begin
    SetStatus('Stopping ' + AgentServiceName + '...');
    if not ScCommand('stop ' + AgentServiceName) then
      SetStatus('sc stop did not report success - waiting for STOPPED anyway.');

    if not WaitForServiceState(ServiceStopped, StopTimeoutMs) then
    begin
      SetStatus('ERROR: service did not reach STOPPED within ' +
        IntToStr(StopTimeoutMs div 1000) + 's (state: ' +
        ServiceStateName(QueryServiceState) + ').');
      Exit;
    end;
  end;

  SetStatus('Waiting for ' + AgentWorkerImage + ' to exit...');
  if not WaitForWorkerExit(WorkerExitTimeoutMs) then
  begin
    SetStatus('ERROR: ' + AgentWorkerImage +
      ' is still running and may still be holding playback/resources.');
    Exit;
  end;

  SetStatus('AudioAgent service stopped.');
  Result := True;
end;

function StartFailureMessage: String;
begin
  Result := 'The ' + AgentServiceName + ' service was installed but could not'
    + #13#10 + 'be started.'
    + #13#10 + #13#10 +
    'Current state: ' + ServiceStateName(QueryServiceState)
    + #13#10 + #13#10 +
    'Please run "sc start ' + AgentServiceName + '" and check'
    + #13#10 + '"%ProgramData%\AudioAgent\logs\service\service.log".';
end;

function StartServiceAndVerify: Boolean;
begin
  Result := False;

  if QueryServiceState = ServiceRunning then
  begin
    SetStatus(AgentServiceName + ' is already running.');
    Result := True;
    Exit;
  end;

  SetStatus('Starting ' + AgentServiceName + '...');
  if not ScCommand('start ' + AgentServiceName) then
  begin
    SetStatus('ERROR: "sc start ' + AgentServiceName + '" failed.');
    Exit;
  end;

  if not WaitForServiceState(ServiceRunning, StartTimeoutMs) then
  begin
    SetStatus('ERROR: service did not reach RUNNING within ' +
      IntToStr(StartTimeoutMs div 1000) + 's.');
    Exit;
  end;

  SetStatus(AgentServiceName + ' is running.');
  Result := True;
end;

procedure RestoreRecoveryPolicy;
begin
  if ScCommand('failure ' + AgentServiceName + ' reset= 0 actions= restart/5000') then
    SetStatus('Failure-recovery policy restored (restart/5000).')
  else
    SetStatus('WARNING: could not set the failure-recovery policy.');
end;

function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
begin
  Result := True;
  GetWindowsVersionEx(Version);
  if Version.Major < 6 then
  begin
    MsgBox('Windows 7 or later is required.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  if not WizardSilent then
    MsgBox('RedioCast Agent will be installed to manage your scheduled and playlist audio.' + #13#10 + #13#10 +
           'This installation will:' + #13#10 +
           '• Stop the running AudioAgent service cleanly' + #13#10 +
           '• Install required components' + #13#10 +
           '• Set up the RedioCast service' + #13#10 +
           '• Preserve your existing settings and cached audio',
           mbInformation, MB_OK);

  if WizardSilent then
    if not StopServiceForUpgrade then
    begin
      MsgBox(StopFailureMessage, mbError, MB_OK);
      Result := False;
    end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpSelectDir then
    if not StopServiceForUpgrade then
      RaiseException(StopFailureMessage);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopServiceForUpgrade;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigPath: String;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    RestoreRecoveryPolicy;

    if not StartServiceAndVerify then
    begin
      RestoreRecoveryPolicy;
      RaiseException(StartFailureMessage);
    end;

    Exec(ExpandConstant('{app}\AudioAgentUI.exe'), '', '', SW_SHOWNORMAL,
      ewNoWait, ResultCode);

    ConfigPath := ExpandConstant('{commonappdata}\AudioAgent');
    if not WizardSilent then
      if MsgBox('Add AudioAgent folder to Windows Defender exclusions for better performance?',
                mbConfirmation, MB_YESNO) = IDYES then
        Exec('powershell.exe',
             '-Command "Add-MpPreference -ExclusionPath ''' + ConfigPath + '''"',
             '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

function ShouldInstallVC(): Boolean;
begin
  Result := not FileExists(ExpandConstant('{sys}\msvcp140.dll'));
end;