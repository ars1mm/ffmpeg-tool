; Inno Setup script for FFmpeg Video Converter
; Wraps the PyInstaller one-folder bundle produced by build_exe.ps1
;
; To compile manually:
;   iscc installer.iss
;
; Or run build_installer.ps1 which does everything automatically.

#define AppName      "FFmpeg Video Converter"
#define AppVersion   "1.0.0"
#define AppPublisher "FFmpegConverter"
#define AppExeName   "FFmpegConverter.exe"
#define BundleDir    "dist\FFmpegConverter"

[Setup]
AppId={{A3F6B2C1-4D7E-4A9F-8E2B-1C5D6F7A8B9C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/
AppSupportURL=https://github.com/
AppUpdatesURL=https://github.com/
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
; Require admin rights so we can install to Program Files and write to
; HKLM for the uninstaller entry.
PrivilegesRequired=admin
OutputDir=installer_output
OutputBaseFilename=FFmpegConverter-Setup
SetupIconFile=
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Minimum OS: Windows 10
MinVersion=10.0
; Architecture: 64-bit only (matches the Python/FFmpeg builds)
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";  Description: "{cm:CreateDesktopIcon}";  GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main application executable
Source: "{#BundleDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; All other files in the bundle folder (PyInstaller support files, _internal, etc.)
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut
Name: "{group}\{#AppName}";        Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
; Desktop shortcut (optional, off by default)
Name: "{autodesktop}\{#AppName}";  Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch the app after installation finishes.
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove the run.log the app writes next to the exe.
Type: files; Name: "{app}\run.log"
