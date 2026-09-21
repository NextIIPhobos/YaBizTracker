Option Explicit

Dim shell, fso, baseDir, runBat
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
runBat = fso.BuildPath(baseDir, "run.bat")

shell.CurrentDirectory = baseDir
shell.Run "cmd.exe /c " & Chr(34) & runBat & Chr(34), 0, False

Set fso = Nothing
Set shell = Nothing
