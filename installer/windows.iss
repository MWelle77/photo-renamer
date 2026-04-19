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
; Output: installer\output\MediaFileRenamer_v1.2_Setup.exe

#define AppName      "Media File Renamer"
; NOTE: keep AppVersion in sync with version.py
#define AppVersion   "1.3"
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
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Allow per-user install (no admin required), but offer all-users if run as admin
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu
Name: "{group}\{#AppName}";                      Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
; Desktop (optional task)
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
