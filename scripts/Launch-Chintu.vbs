Set WshShell = CreateObject("WScript.Shell")
script = CreateObject("Scripting.FileSystemObject").GetAbsolutePathName("Launch-Chintu.ps1")
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & script & """"
WshShell.Run cmd, 0, False
