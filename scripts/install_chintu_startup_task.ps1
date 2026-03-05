param(
  [string]$TaskName = "ChintuAutoStart",
  [string]$LaunchScript = "",
  [string]$WorkingDirectory = "",
  [switch]$RunNow,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $WorkingDirectory) {
  $WorkingDirectory = $repoRoot
}
if (-not $LaunchScript) {
  $LaunchScript = Join-Path $PSScriptRoot "Launch-Chintu.ps1"
}

if (-not (Test-Path $LaunchScript)) {
  throw "Launch script not found: $LaunchScript"
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and -not $Force) {
  throw "Task '$TaskName' already exists. Re-run with -Force to replace it."
}
if ($existing -and $Force) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$escapedLaunch = $LaunchScript.Replace('"', '`"')
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$escapedLaunch`" -NoSplash"

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument $arguments `
  -WorkingDirectory $WorkingDirectory

$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 5)

$task = Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Principal $principal `
  -Settings $settings `
  -Description "Starts Chintu at user logon for always-on operation."

if ($RunNow) {
  Start-ScheduledTask -TaskName $TaskName
}

$result = @{
  ok = $true
  task_name = $TaskName
  launch_script = (Resolve-Path $LaunchScript).Path
  working_directory = (Resolve-Path $WorkingDirectory).Path
  user = $userId
  run_now = [bool]$RunNow
  force = [bool]$Force
  state = $task.State.ToString()
}

Write-Output ($result | ConvertTo-Json -Depth 6)
