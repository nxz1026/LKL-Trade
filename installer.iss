; LKL-Trade 安装器（Inno Setup 6）
; 安装到 %LOCALAPPDATA%\LKL-Trade（免管理员），HKCU Run 开机自启托盘。

#define MyAppName "LKL-Trade"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "LKL"
#define MyAppExeName "lkl_boot.exe"

[Setup]
AppId={{8B4E2B7C-3F6A-4D2E-9A1C-LKLDTRADE01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=LKL-Trade-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
SetupLogging=yes
; 卸载也免管理员
UninstallDisplayIcon={app}\{#MyAppExeName}
; 装完不自动运行（托盘由用户/自启拉起）
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked

[Files]
; 打包产物（onedir 结构整体拷贝）
; lkl_tray.exe = windowed 托盘入口（自启/快捷方式用，无控制台黑框）；lkl_boot.exe = console CLI
Source: "dist\lkl_boot\lkl_boot.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\lkl_boot\lkl_tray.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\lkl_boot\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; config.env 与 logs 均为首启运行时自动生成（config.ensure_config / TrayManager 建目录），不随包分发

[Icons]
; 托盘/自启全部走 windowed 的 lkl_tray.exe——explorer 启动 console 程序会新建黑框窗口
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\lkl_tray.exe"; Parameters: "tray"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\lkl_tray.exe"; Parameters: "tray"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; 开机自启：HKCU Run（免管理员）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LKL-Trade"; ValueData: """{app}\lkl_tray.exe"" tray"; Flags: uninsdeletevalue

[Run]
; 安装完成后立即启动托盘（勾选则启动）
Filename: "{app}\lkl_tray.exe"; Parameters: "tray"; WorkingDir: "{app}"; Flags: nowait skipifsilent; Description: "立即启动 LKL-Trade 托盘"

[UninstallDelete]
; 卸载后清日志与运行时产物（配置 config.env 也清——卸载即彻底）
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\config.env"
Type: filesandordirs; Name: "{app}\_internal"
