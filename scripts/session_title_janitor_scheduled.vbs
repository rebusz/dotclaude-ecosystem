Option Explicit

' Run the scheduled PowerShell worker without ever creating a console window.
' Wait for completion and return its real exit code to Task Scheduler.
Dim shell, scriptPath, command, exitCode
Set shell = CreateObject("WScript.Shell")

scriptPath = shell.ExpandEnvironmentStrings( _
    "%USERPROFILE%\.claude\scripts\session_title_janitor_scheduled.ps1")
command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " _
    & Chr(34) & scriptPath & Chr(34)

exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
