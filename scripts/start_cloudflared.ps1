# 无 ngrok 浏览器拦截页，适合 Telegram Web App
# 用法: powershell -ExecutionPolicy Bypass -File scripts\start_cloudflared.ps1
$cf = Join-Path $PSScriptRoot "..\tools\cloudflared\cloudflared.exe" | Resolve-Path
$port = if ($env:DAILY_ATTENDANCE_REPORT_API_PORT) { $env:DAILY_ATTENDANCE_REPORT_API_PORT } else { "8787" }
Write-Host "Starting cloudflared -> http://127.0.0.1:$port"
Write-Host "复制输出的 https://xxxx.trycloudflare.com 到 .env 的 SHIFT_WEB_APP_PUBLIC_URL"
& $cf tunnel --url "http://127.0.0.1:$port"
