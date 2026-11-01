; Reasonable Engine — установщик Windows (Inno Setup 6+)
;
; Собирается через tools/build_installer.py, который передаёт пути:
;   /DPayloadDir=<папка с готовыми файлами>
;   /DOutputDir=<куда положить setup.exe>
;   /DAppVersion=<версия>
;
; Установка выполняется для текущего пользователя в
; %LOCALAPPDATA%\Programs\Reasonable Engine, поэтому папка Projects рядом с
; движком доступна для записи без прав администратора.

#ifndef PayloadDir
  #define PayloadDir "..\dist\installer_payload"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
; Публичный лейбл релиза (RE-1.01, RE-1.02, ...) — идёт в имя установщика и в
; «Установка и удаление программ». VersionInfoVersion остаётся числовой.
#ifndef ReleaseLabel
  #define ReleaseLabel AppVersion
#endif

#define AppName "Reasonable Engine"
#define AppPublisher "Reasonable Engine"
#define AppExeName "ReasonableEngine.exe"
#define PlayerExeName "ReasonablePlayer.exe"

[Setup]
AppId={{8C0B2F8E-6D34-4A55-9C64-5B7A2D7E9F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#ReleaseLabel}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} installer
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile=EULA.txt
OutputDir={#OutputDir}
OutputBaseFilename=ReasonableEngine-Setup-{#ReleaseLabel}
SetupIconFile=..\reasonable\assets\brand\logo.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
MinVersion=10.0
ShowLanguageDialog=no
AppMutex=ReasonableEngineEditorMutex
UsePreviousAppDir=yes
UsePreviousTasks=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: checkedonce
Name: "projectsdir"; Description: "Создать папку Projects для новых проектов"; GroupDescription: "Проекты:"; Flags: checkedonce

[Dirs]
Name: "{app}\Projects"; Tasks: projectsdir

[Files]
Source: "{#PayloadDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PayloadDir}\{#PlayerExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PayloadDir}\EULA.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PayloadDir}\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PayloadDir}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PayloadDir}\runtime\python\*"; DestDir: "{app}\runtime\python"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Старая портативная среда заменяется целиком, чтобы не смешивать версии.
Type: filesandordirs; Name: "{app}\runtime\python"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Проекты пользователя не удаляются автоматически. Удаляем только кэши,
; которые создаёт сама программа.
Type: filesandordirs; Name: "{app}\runtime\python\Lib\site-packages\__pycache__"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
