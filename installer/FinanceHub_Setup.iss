; Finance Hub — single-file Windows installer (optional).
; Compile with Inno Setup 6 (free: https://jrsoftware.org/isinfo.php): run build_exe.bat, or open this file in Inno Setup
; and press Compile. It produces FinanceHub_<version>_Setup.exe, which unpacks the setup files to a temporary folder and
; starts the Finance Hub setup wizard (program folder, data folder, shortcuts …). Python 3.10+ must be installed.
#define AppVersion GetEnv("FH_VERSION")
#if AppVersion == ""
  #define AppVersion "1.7"
#endif

[Setup]
AppName=Finance Hub
AppVersion={#AppVersion}
AppPublisher=Finance Hub
DefaultDirName={tmp}\FinanceHubSetup
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
OutputBaseFilename=FinanceHub_{#AppVersion}_Setup
OutputDir=.
SetupIconFile=hub.ico
WizardStyle=modern
DisableWelcomePage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
Compression=lzma2
SolidCompression=yes

[Files]
Source: "setup.pyw"; DestDir: "{tmp}"; Flags: ignoreversion
Source: "Setup.cmd"; DestDir: "{tmp}"; Flags: ignoreversion
Source: "hub.ico"; DestDir: "{tmp}"; Flags: ignoreversion
Source: "FinanceHub_*.zip"; DestDir: "{tmp}"; Flags: ignoreversion

[Run]
Filename: "{cmd}"; Parameters: "/c ""{tmp}\Setup.cmd"""; Flags: waituntilterminated
