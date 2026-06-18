# 将本机 8787 暴露为 HTTPS（需先在 ngrok.com 注册并配置 authtoken）
# 用法: powershell -ExecutionPolicy Bypass -File scripts\start_ngrok.ps1
$ngrok = Join-Path $PSScriptRoot "..\tools\ngrok\ngrok.exe" | Resolve-Path
$port = if ($env:DAILY_ATTENDANCE_REPORT_API_PORT) { $env:DAILY_ATTENDANCE_REPORT_API_PORT } else { "8787" }
Write-Host "Starting ngrok -> 127.0.0.1:$port"
Write-Host "首次使用请先执行: & '$ngrok' config add-authtoken <你的token>"
& $ngrok http $port
