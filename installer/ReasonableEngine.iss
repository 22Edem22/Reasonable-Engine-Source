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
;
; Язык установки (русский/английский) выбирается на первой странице мастера
; и определяет язык всего интерфейса установщика. Выбор сохраняется в файл
; %APPDATA%\ReasonableEngine\installer-language.txt, который приложение при
; первом запуске переносит в settings.json (ui.language) и удаляет. Прямую
; запись в settings.json из скрипта Pascal не используем: файл может
; содержать кириллицу в UTF-8, которую AnsiString-механизмы Inno портят.

#ifndef PayloadDir
  #define PayloadDir "..\dist\installer_payload"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef AppVersion
  #define AppVersion "2.0.3"
#endif
; Публичный лейбл релиза (RE-2.01, RE-2.02, ...) — идёт в имя установщика и в
; «Установка и удаление программ». VersionInfoVersion остаётся числовой.
#ifndef ReleaseLabel
  #define ReleaseLabel "RE-2.03"
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
; Спрашиваем язык, если пользователь не передал его ключом /LANG.
ShowLanguageDialog=yes
AppMutex=ReasonableEngineEditorMutex
UsePreviousAppDir=yes
UsePreviousTasks=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
russian.ShortcutsGroup=Ярлыки:
english.ShortcutsGroup=Shortcuts:
russian.CreateDesktopIcon=Создать ярлык на рабочем столе
english.CreateDesktopIcon=Create a desktop shortcut
russian.ProjectsGroup=Проекты:
english.ProjectsGroup=Projects:
russian.CreateProjectsDir=Создать папку Projects для новых проектов
english.CreateProjectsDir=Create the Projects folder for new projects
russian.UninstallApp=Удалить %1
english.UninstallApp=Uninstall %1
russian.LaunchApp=Запустить %1
english.LaunchApp=Launch %1

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:ShortcutsGroup}"; Flags: checkedonce
Name: "projectsdir"; Description: "{cm:CreateProjectsDir}"; GroupDescription: "{cm:ProjectsGroup}"; Flags: checkedonce

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
Name: "{group}\{cm:UninstallApp,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchApp,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Проекты пользователя не удаляются автоматически. Удаляем только кэши,
; которые создаёт сама программа, и маркер языка установщика.
Type: filesandordirs; Name: "{app}\runtime\python\Lib\site-packages\__pycache__"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{userappdata}\ReasonableEngine\installer-language.txt"

[Code]
const
  LanguageMarkerFile = 'installer-language.txt';

procedure CurStepChanged(CurStep: TSetupStep);
var
  LanguageCode: string;
  MarkerPath: string;
begin
  if CurStep = ssPostInstall then
  begin
    if ActiveLanguage = 'russian' then
      LanguageCode := 'ru'
    else
      LanguageCode := 'en';
    MarkerPath := ExpandConstant('{userappdata}\ReasonableEngine\') + LanguageMarkerFile;
    ForceDirectories(ExtractFilePath(MarkerPath));
    SaveStringToFile(MarkerPath, LanguageCode, False);
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;
