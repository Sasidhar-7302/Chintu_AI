param(
  [switch]$WithVoice,
  [switch]$NoUI,
  [switch]$ForceRestart,
  [switch]$NoSplash,
  [switch]$DevUI
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Get-VenvPython {
  param([string]$Root)
  $venvPython = Join-Path $Root "venv\\Scripts\\pythonw.exe"
  if (-not (Test-Path $venvPython)) {
    $venvPython = Join-Path $Root "venv\\Scripts\\python.exe"
  }
  if (-not (Test-Path $venvPython)) {
    Write-Host "Virtual environment not found. Run: python -m venv venv"
    exit 1
  }
  return $venvPython
}

function Ensure-LogDir {
  $logDir = Join-Path $env:USERPROFILE ".chintu\\logs"
  if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
  return $logDir
}

function Test-TcpPort {
  param([string]$Host = "127.0.0.1", [int]$Port = 8765, [int]$TimeoutMs = 200)
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect($Host, $Port, $null, $null)
    if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
      $client.Close()
      return $false
    }
    $client.EndConnect($iar)
    $client.Close()
    return $true
  } catch {
    return $false
  }
}

function Start-Backend {
  param([string]$Python, [string]$Root, [string]$Stdout, [string]$Stderr)
  return Start-Process -FilePath $Python `
    -WorkingDirectory $Root `
    -ArgumentList "-u", "main.py" `
    -WindowStyle Hidden `
    -RedirectStandardOutput $Stdout `
    -RedirectStandardError $Stderr `
    -PassThru
}

function Start-UI {
  param([string]$Root, [string]$Stdout, [string]$Stderr)
  $uiExe = Join-Path $Root "chintu_ui\\build\\windows\\x64\\runner\\Debug\\chintu_ui.exe"
  if (Test-Path $uiExe) {
    return Start-Process -FilePath $uiExe `
      -WorkingDirectory (Split-Path $uiExe -Parent) `
      -WindowStyle Normal `
      -RedirectStandardOutput $Stdout `
      -RedirectStandardError $Stderr `
      -PassThru
  }
  if ($DevUI -and (Get-Command flutter -ErrorAction SilentlyContinue)) {
    return Start-Process -FilePath "powershell" `
      -WindowStyle Hidden `
      -ArgumentList "-NoProfile","-Command","Set-Location '$Root\\chintu_ui'; flutter run -d windows" `
      -RedirectStandardOutput $Stdout `
      -RedirectStandardError $Stderr `
      -PassThru
  }
  return $null
}

function Show-Splash {
  param(
    [scriptblock]$OnShown,
    [scriptblock]$IsReady,
    [scriptblock]$OnTimeout,
    [int]$TimeoutSec = 90,
    [string]$LogDir
  )

  Add-Type -AssemblyName PresentationFramework
  Add-Type -AssemblyName PresentationCore
  Add-Type -AssemblyName WindowsBase

  $xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Chintu" WindowStartupLocation="CenterScreen"
        Width="260" Height="180" ResizeMode="NoResize"
        WindowStyle="None" AllowsTransparency="True"
        Background="Transparent" Topmost="True"
        ShowInTaskbar="False">
  <Grid>
    <StackPanel HorizontalAlignment="Center" VerticalAlignment="Center">
      <Grid Width="64" Height="64">
        <Ellipse Width="64" Height="64" Stroke="#1E2635" StrokeThickness="6" Opacity="0.4"/>
        <Path Stroke="#2CE5D3" StrokeThickness="6" StrokeStartLineCap="Round" StrokeEndLineCap="Round"
              Data="M 32,4 A 28,28 0 1 1 4,32">
          <Path.RenderTransform>
            <RotateTransform x:Name="SpinnerRotate" CenterX="32" CenterY="32"/>
          </Path.RenderTransform>
        </Path>
      </Grid>
      <TextBlock x:Name="StatusText" Text="Waiting for backend..."
                 Foreground="#6DDCFF" FontSize="11" HorizontalAlignment="Center" Margin="0,10,0,0"/>
    </StackPanel>
  </Grid>
</Window>
"@

  $reader = New-Object System.Xml.XmlNodeReader ([xml]$xaml)
  $window = [Windows.Markup.XamlReader]::Load($reader)
  $statusText = $window.FindName("StatusText")

  $spin = New-Object Windows.Media.Animation.DoubleAnimation
  $spin.From = 0
  $spin.To = 360
  $spin.Duration = New-Object Windows.Duration (New-Object System.TimeSpan(0,0,0,1,150))
  $spin.RepeatBehavior = [Windows.Media.Animation.RepeatBehavior]::Forever

  $spinnerRotate = $window.FindName("SpinnerRotate")
  if ($spinnerRotate) {
    $spinnerRotate.BeginAnimation([Windows.Media.RotateTransform]::AngleProperty, $spin)
  }

  $startTime = Get-Date
  $timer = New-Object Windows.Threading.DispatcherTimer
  $timer.Interval = [TimeSpan]::FromMilliseconds(500)
  $timer.Add_Tick({
    $elapsed = (Get-Date) - $startTime
    try {
      if (& $IsReady) {
        $timer.Stop()
        $window.Close()
      }
    } catch {
    }
    if ($elapsed.TotalSeconds -ge $TimeoutSec) {
      $statusText.Text = "Backend slow... launching UI."
      if ($OnTimeout) { & $OnTimeout }
      $timer.Stop()
      $window.Close()
    }
  })

  $window.add_SourceInitialized({
    if ($OnShown) { & $OnShown }
    $timer.Start()
  })

  [void]$window.ShowDialog()
}

$venvPython = Get-VenvPython -Root $root
$logDir = Ensure-LogDir
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$launchLog = Join-Path $logDir "launch_$ts.log"
$backendStdout = Join-Path $logDir "backend_stdout_$ts.log"
$backendStderr = Join-Path $logDir "backend_stderr_$ts.log"
$uiStdout = Join-Path $logDir "ui_stdout_$ts.log"
$uiStderr = Join-Path $logDir "ui_stderr_$ts.log"

$env:CHINTU_LOG_DIR = $logDir
$env:PYTHONUNBUFFERED = "1"

Add-Content -Path $launchLog -Value "[$(Get-Date)] Launch requested."

if ($ForceRestart) {
  try {
    $existing = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existing) {
      Add-Content -Path $launchLog -Value "Stopping existing backend PID $($existing.OwningProcess)."
      Stop-Process -Id $existing.OwningProcess -Force -ErrorAction SilentlyContinue
      Start-Sleep -Seconds 1
    }
  } catch {
    Add-Content -Path $launchLog -Value "Port check skipped: $($_.Exception.Message)"
  }
}

$script:backendProc = $null
$script:uiProc = $null
$script:uiWaitForWindow = $false
$script:uiStarted = $false
$script:launchStart = Get-Date

$startBackend = {
  Add-Content -Path $launchLog -Value "Starting backend..."
  $script:backendProc = Start-Backend -Python $venvPython -Root $root -Stdout $backendStdout -Stderr $backendStderr
  Start-Sleep -Milliseconds 500

  if ($WithVoice) {
    Add-Content -Path $launchLog -Value "Starting voice client."
    Start-Process -FilePath $venvPython `
      -WorkingDirectory $root `
      -ArgumentList "run_voice_client.py" `
      -WindowStyle Hidden | Out-Null
  }
}

$startUi = {
  if ($script:uiStarted -or $NoUI) { return }
  $script:uiStarted = $true
  Add-Content -Path $launchLog -Value "Starting UI..."
  $uiExe = Join-Path $root "chintu_ui\\build\\windows\\x64\\runner\\Debug\\chintu_ui.exe"
  $script:uiWaitForWindow = (Test-Path $uiExe)
  $script:uiProc = Start-UI -Root $root -Stdout $uiStdout -Stderr $uiStderr
  if (-not $script:uiProc) {
    Add-Content -Path $launchLog -Value "UI not started (missing exe and flutter)."
  }
}

$readyCheck = {
  $backendReady = Test-TcpPort -Host "127.0.0.1" -Port 8765 -TimeoutMs 200

  if ($NoUI) {
    return $backendReady
  }

  if ($backendReady -and -not $script:uiStarted) {
    & $startUi
  }

  if ($backendReady) {
    return $true
  }

  return $false
}

if ($NoSplash) {
  & $startBackend
  if (-not $NoUI) {
    & $startUi
  }
} else {
  try {
    Show-Splash -OnShown $startBackend -IsReady $readyCheck -OnTimeout $startUi -TimeoutSec 15 -LogDir $logDir
  } catch {
    Add-Content -Path $launchLog -Value "Splash failed: $($_.Exception.Message)"
    & $startBackend
    if (-not $NoUI) {
      & $startUi
    }
  }
}

Add-Content -Path $launchLog -Value "Launch complete."
