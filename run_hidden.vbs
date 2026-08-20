' Starts PDF Document Intelligence with no visible console window.
' Double-click this (or a shortcut to it) instead of run.bat.
' Use stop.bat to shut the server down again, since there's no window
' left to close.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = scriptDir
shell.Run """" & scriptDir & "\run.bat""", 0, False
