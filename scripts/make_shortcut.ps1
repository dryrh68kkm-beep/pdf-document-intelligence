# Creates the "Store Suite" Desktop shortcut (hidden window + own icon). ASCII only.
$app = Split-Path -Parent $PSScriptRoot
$b64 = Join-Path $app 'assets\suite_icon.ico.b64'
$ico = Join-Path $app 'assets\suite_icon.ico'
if (Test-Path $b64) {  # always rewrite: an older icon may be on disk
  [IO.File]::WriteAllBytes($ico, [Convert]::FromBase64String([IO.File]::ReadAllText($b64)))
}
$w = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$s = $w.CreateShortcut((Join-Path $desktop 'Store Suite.lnk'))
# Starts StoreSuite.bat directly (normal window): works where Windows Script Host is blocked,
# and any error stays visible instead of vanishing.
$s.TargetPath = (Join-Path $app 'StoreSuite.bat')
$s.WindowStyle = 1
$s.WorkingDirectory = $app
if (Test-Path $ico) { $s.IconLocation = $ico + ',0' }
$s.Description = 'Store Suite'
$s.Save()
Write-Host "Shortcut created on: $desktop"
