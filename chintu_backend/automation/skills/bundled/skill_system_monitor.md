# system monitor
Description: Show quick CPU, RAM, and disk usage on Windows.
Triggers: system monitor, system status quick, system usage
Command: powershell -NoProfile -Command "& { $os=Get-CimInstance Win32_OperatingSystem; $cpu=Get-CimInstance Win32_Processor | Select-Object -First 1; $memUsed=[math]::Round(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/1MB,2); $memTotal=[math]::Round($os.TotalVisibleMemorySize/1MB,2); $cpuLoad=$cpu.LoadPercentage; $disks=Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object { $_.DeviceID + ' ' + [math]::Round(($_.FreeSpace/1GB),1) + 'GB free / ' + [math]::Round(($_.Size/1GB),1) + 'GB' }; Write-Output ('CPU: ' + $cpuLoad + '% | RAM: ' + $memUsed + '/' + $memTotal + ' GB | Disks: ' + ($disks -join ', ')) }"
Type: shell
Requires-Bin: powershell
