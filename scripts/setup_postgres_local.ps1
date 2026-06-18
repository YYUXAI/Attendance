# 本地 PostgreSQL 初始化：对齐 .env 密码并创建 attendance_bd
# 需以管理员运行（会短暂修改 pg_hba.conf 为 trust 后恢复）

$ErrorActionPreference = "Stop"
$PgBin = "D:\postgreSQL\bin"
$PgData = "D:\postgreSQL\data"
$PgHba = Join-Path $PgData "pg_hba.conf"
$ServiceName = "postgresql-x64-17"
$DbName = "attendance_bd"
$DbUser = "postgres"
$DbPassword = "123456789"

if (-not (Test-Path "$PgBin\psql.exe")) {
    Write-Error "未找到 $PgBin\psql.exe，请确认 PostgreSQL 安装路径。"
}

$bak = "$PgHba.bak_attendance_setup"
if (-not (Test-Path $bak)) {
    Copy-Item $PgHba $bak -Force
    Write-Host "已备份 pg_hba.conf -> $bak"
}

$hba = Get-Content $PgHba -Raw -Encoding UTF8
$trustHba = $hba -replace "scram-sha-256", "trust"
Set-Content -Path $PgHba -Value $trustHba -Encoding UTF8 -NoNewline
Write-Host "已临时启用本地 trust 认证，正在重载配置..."

& "$PgBin\pg_ctl.exe" reload -D $PgData | Out-Null
Start-Sleep -Seconds 2

$env:PGCLIENTENCODING = "UTF8"
try {
    & "$PgBin\psql.exe" -h 127.0.0.1 -U $DbUser -d postgres -v ON_ERROR_STOP=1 -c "ALTER USER postgres WITH PASSWORD '$DbPassword';"
    $exists = & "$PgBin\psql.exe" -h 127.0.0.1 -U $DbUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DbName';"
    if ($exists.Trim() -ne "1") {
        & "$PgBin\psql.exe" -h 127.0.0.1 -U $DbUser -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $DbName ENCODING 'UTF8';"
        Write-Host "已创建数据库 $DbName"
    } else {
        Write-Host "数据库 $DbName 已存在"
    }
    Write-Host "postgres 密码已设为与 .env 中 DB_PASSWORD 一致"
}
finally {
    Copy-Item $bak $PgHba -Force
    & "$PgBin\pg_ctl.exe" reload -D $PgData | Out-Null
    Write-Host "已恢复 pg_hba.conf 为 scram-sha-256"
}

$env:PGPASSWORD = $DbPassword
& "$PgBin\psql.exe" -h 127.0.0.1 -U $DbUser -d $DbName -c "SELECT version();" | Out-Host
Write-Host "完成。可运行: python main.py"
