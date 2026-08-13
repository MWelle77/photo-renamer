; Inno Setup script for Media File Renamer
; Requires Inno Setup 6.x — https://jrsoftware.org/isinfo.php
;
; Build the exe first:
;   python -m PyInstaller build/photo_renamer.spec --clean --noconfirm
;
; Then compile this script:
;   iscc installer\windows.iss
; Or open it in the Inno Setup GUI and click Compile.
;
; Output: installer\output\MediaFileRenamer_v1.8_Setup.exe

#define AppName      "Media File Renamer"
; NOTE: keep AppVersion in sync with version.py
#define AppVersion   "1.8"
#define AppPublisher "Michael C. Welle"
#define AppURL       "https://mcwelle.com/"
#define AppExeName   "MediaFileRenamer.exe"
#define RepoURL      "https://github.com/MWelle77/photo-renamer"

[Setup]
AppId={{6F3A2B1C-4D5E-4F60-A7B8-C9D0E1F23456}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} v{#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#RepoURL}/issues
AppUpdatesURL={#RepoURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=output
OutputBaseFilename=MediaFileRenamer_v{#AppVersion}_Setup
; Compression
Compression=lzma2/ultra64
SolidCompression=yes
; Platform
MinVersion=10.0
ArchitecturesInstallIn64BitMode=x64compatible
; Appearance
WizardStyle=modern
WizardImageFile=..\assets\installer_banner.bmp
WizardSmallImageFile=..\assets\installer_small.bmp
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
; Privileges
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Smooth upgrades — prompt to close running instances
CloseApplications=yes
; Version metadata embedded in the installer exe
VersionInfoVersion=1.8.0.0
VersionInfoDescription=Media File Renamer Setup
VersionInfoCompany=Michael C. Welle
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\MediaFileRenamer\{#AppExeName}"; DestDir: "{app}";           Flags: ignoreversion
Source: "..\dist\MediaFileRenamer\_internal\*";   DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu
Name: "{group}\{#AppName}";                      Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
; Desktop (optional task)
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up settings left behind in AppData on uninstall
Type: filesandordirs; Name: "{userappdata}\Media File Renamer"
