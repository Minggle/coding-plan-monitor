; Coding Plan Monitor 安装包脚本（Inno Setup 6）
; 构建：& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss

#define MyAppName "Coding Plan Monitor"
#define MyAppNameCN "Coding Plan 用量监控"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Minggle"
#define MyAppURL "https://github.com/Minggle/coding-plan-monitor"
#define MyAppExeName "CodingPlanMonitor.exe"

[Setup]
AppId={{7E3A9C21-5B84-4D6F-9A2E-1C0D8F5B6E7A}
AppName={#MyAppNameCN}
AppVersion={#MyAppVersion}
AppVerName={#MyAppNameCN} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\CodingPlanMonitor
DefaultGroupName={#MyAppNameCN}
DisableProgramGroupPage=yes
; 输出
OutputDir=..\installer
OutputBaseFilename=CodingPlanMonitor-Setup-0.1.0
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; 权限与架构
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 体验
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#MyAppNameCN}
VersionInfoVersion=0.1.0.0
VersionInfoDescription={#MyAppNameCN} 安装程序

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："
Name: "autostart"; Description: "开机自动启动"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "..\dist\CodingPlanMonitor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 开始菜单
Name: "{group}\{#MyAppNameCN}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppNameCN}"; Filename: "{uninstallexe}"
; 桌面快捷方式（默认勾选）
Name: "{autodesktop}\{#MyAppNameCN}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; 可选的开机自启（与安装任务联动；应用内设置也可以独立控制）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "coding-plan-monitor"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppNameCN}"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
; 清理缓存快照（配置保留在 %APPDATA%，避免误删用户账号信息）
Type: filesandordirs; Name: "{app}"
