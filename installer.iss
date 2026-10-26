; Inno Setup script for PDF Studio.
; Not required — the portable zip works on its own. Build with:
;   iscc /DAppDir=...\dist\PDF Studio /DOutDir=...\dist /DIconFile=...\pdfstudio.ico installer.iss
; build_app.py passes those automatically when Inno Setup is installed.

#define MyAppName "PDF Studio"
#define MyAppVersion "1.0"
#define MyAppExe "PDF Studio.exe"

[Setup]
AppId={{8E2C4F41-6B7A-4D19-9C3E-PDFSTUDIO001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Adaptiv
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#OutDir}
OutputBaseFilename=PDFStudio-Setup
SetupIconFile={#IconFile}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user install by default: no administrator rights needed, which makes
; rollout to laptops that IT does not control much simpler.
PrivilegesRequiredOverridesAllowed=dialog
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExe}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Start {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Leftover state: the window profile and log. User files are never stored here.
Type: filesandordirs; Name: "{localappdata}\PDFStudio"
