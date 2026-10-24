# Creates the "Store Suite" Desktop shortcut (hidden window + own icon). ASCII only.
$app = Split-Path -Parent $PSScriptRoot
$b64 = Join-Path $app 'assets\suite_icon.ico.b64'
$ico = Join-Path $app 'assets\suite_icon.ico'
if ((Test-Path $b64) -and -not (Test-Path $ico)) {
  [IO.File]::WriteAllBytes($ico, [Convert]::FromBase64String([IO.File]::ReadAllText($b64)))
}
$w = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$s = $w.CreateShortcut((Join-Path $desktop 'Store Suite.lnk'))
$s.TargetPath = (Join-Path $env:WINDIR 'System32\wscript.exe')
$s.Arguments = '"' + (Join-Path $app 'StoreSuite_hidden.vbs') + '"'
$s.WorkingDirectory = $app
if (Test-Path $ico) { $s.IconLocation = $ico + ',0' }
$s.Description = 'Store Suite'
$s.Save()
Write-Host "Shortcut created on: $desktop"
