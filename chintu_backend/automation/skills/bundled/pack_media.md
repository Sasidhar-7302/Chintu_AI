# Media Pack

# Video Frames
Description: Extract frames from a video using ffmpeg.
Triggers: extract frames, video frames
Command: ffmpeg -i "{input}" -vf "fps=1" "{output_dir}\\frame_%04d.png"
Args: input, output_dir
Type: shell
Requires-Bin: ffmpeg

# Screenshot (native)
Description: Take a screenshot (Windows).
Triggers: screenshot, take screenshot
Command: powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; $bmp=New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); $graphics=[System.Drawing.Graphics]::FromImage($bmp); $graphics.CopyFromScreen(0,0,0,0,$bmp.Size); $path=Join-Path $env:TEMP 'chintu_screenshot.png'; $bmp.Save($path,[System.Drawing.Imaging.ImageFormat]::Png); Write-Output $path"
Type: shell
Requires-Bin: powershell
