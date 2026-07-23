Option Explicit

' Silent source launcher for JARVIS on this Windows installation.
' It deliberately uses python.exe (not pythonw.exe): the Qt GUI is reliable
' through python.exe, while WScript keeps the console window hidden.
Dim shell, fileSystem, projectDir, pythonExe, command

Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
projectDir = fileSystem.GetParentFolderName(WScript.ScriptFullName)
pythonExe = shell.ExpandEnvironmentStrings("%LocalAppData%") & _
    "\Programs\Python\Python312\python.exe"

If Not fileSystem.FileExists(pythonExe) Then
    MsgBox "JARVIS could not find the verified Python 3.12 runtime at:" & vbCrLf & pythonExe, _
        vbCritical, "JARVIS launch error"
    WScript.Quit 1
End If

command = Chr(34) & pythonExe & Chr(34) & " -u " & _
    Chr(34) & projectDir & "\desktop_main.py" & Chr(34)
shell.Run command, 0, False
