#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{8F6C2B4D-3A19-4C8E-9D15-7A2F4E1B9C01}
AppName=Luma-Wave
AppVersion={#AppVersion}
AppVerName=Luma-Wave {#AppVersion}
AppPublisher=Siddharth Gupta
AppPublisherURL=https://github.com/sid-gupta-007/luma-wave-v2-sid
AppSupportURL=https://github.com/sid-gupta-007/luma-wave-v2-sid/issues
AppUpdatesURL=https://github.com/sid-gupta-007/luma-wave-v2-sid/releases
DefaultDirName={localappdata}\Programs\Luma-Wave
DisableProgramGroupPage=yes
LicenseFile=LICENSE
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=LumaWave-v{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
UninstallDisplayIcon={app}\LumaWave.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\LumaWave\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Luma-Wave"; Filename: "{app}\LumaWave.exe"
Name: "{autodesktop}\Luma-Wave"; Filename: "{app}\LumaWave.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LumaWave.exe"; Description: "{cm:LaunchProgram,Luma-Wave}"; Flags: nowait postinstall skipifsilent

