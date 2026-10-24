' Starts Store Suite with no console window (used by the Desktop shortcut).
' Output goes to %LOCALAPPDATA%\store-suite\last-run.log. Stop with StopStoreSuite.bat.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = dir
py = dir & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(py) Then
  MsgBox "Store Suite is not installed yet. Double-click StoreSuite.bat first.", 48, "Store Suite"
Else
  shell.Run """" & py & """ """ & dir & "\scripts\run_suite.py""", 0, False
End If
