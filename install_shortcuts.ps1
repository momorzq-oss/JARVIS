param()

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$launcher = Join-Path $projectRoot 'Launch JARVIS.vbs'
$icon = Join-Path $projectRoot 'jarvis.ico'

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "JARVIS launcher not found: $launcher"
}
if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) {
    throw "JARVIS icon not found: $icon"
}

function Install-JarvisShortcut {
    param([Parameter(Mandatory = $true)][string]$ShortcutPath)

    $parent = Split-Path -Parent $ShortcutPath
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
    $shortcut.Arguments = '"' + $launcher + '"'
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.IconLocation = $icon + ',0'
    $shortcut.Description = 'Launch JARVIS Desktop Intelligence silently'
    $shortcut.Save()
}

$desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'JARVIS.lnk'
$startMenuShortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'JARVIS.lnk'
Install-JarvisShortcut -ShortcutPath $desktopShortcut
Install-JarvisShortcut -ShortcutPath $startMenuShortcut

Write-Output $desktopShortcut
Write-Output $startMenuShortcut
