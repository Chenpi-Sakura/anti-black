# AntiBlack 启动脚本
# 使用方式: 右键 -> 用 PowerShell 运行

$ErrorActionPreference = "Continue"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " AntiBlack 启动脚本" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 检查 conda 环境
Write-Host ""
Write-Host "[检查] Conda 环境..." -ForegroundColor Yellow
$null = conda run -n anti-black python -c "print('ok')" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] Conda 环境 'anti-black' 未找到！" -ForegroundColor Red
    Write-Host "请先运行: conda create -n anti-black python=3.10" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}
Write-Host "[OK] Conda 环境正常" -ForegroundColor Green

# 检查数据库连接
Write-Host ""
Write-Host "[检查] 数据库连接..." -ForegroundColor Yellow
$null = conda run -n anti-black python -c "from services.database import PostgreSQLService; PostgreSQLService.get_instance(); print('DB OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] 数据库连接正常" -ForegroundColor Green
} else {
    Write-Host "[警告] 数据库连接失败，请检查 PostgreSQL 服务" -ForegroundColor Yellow
}

# 创建日志目录
if (-not (Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" | Out-Null
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 启动服务..." -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 启动 API Server
Write-Host ""
Write-Host "[1/3] 启动 API Server (http://localhost:8000) ..." -ForegroundColor Yellow
Start-Process cmd -ArgumentList "/k title AntiBlack-API && conda run -n anti-black python -m uvicorn api:app --reload --port 8000"

# 启动 Daemon
Write-Host ""
Write-Host "[2/3] 启动 Daemon ..." -ForegroundColor Yellow
Start-Process cmd -ArgumentList "/k title AntiBlack-Daemon && conda run -n anti-black python scripts/run_daemon.py"

# 启动 Frontend
Write-Host ""
Write-Host "[3/3] 启动 Frontend (http://localhost:5173) ..." -ForegroundColor Yellow
Start-Process cmd -ArgumentList "/k title AntiBlack-Frontend && cd frontend && npm run dev"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 所有服务已启动！" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host " 访问地址:" -ForegroundColor White
Write-Host "   - API 文档: http://localhost:8000/docs" -ForegroundColor White
Write-Host "   - Frontend:  http://localhost:5173" -ForegroundColor White
Write-Host ""
Write-Host " 每个服务都在独立的 cmd 窗口中运行" -ForegroundColor Gray
Write-Host " 关闭服务: 关闭对应的 cmd 窗口" -ForegroundColor Gray
Write-Host ""

$response = Read-Host "是否打开浏览器？(Y/N)"
if ($response -eq "Y" -or $response -eq "y") {
    Start-Process -FilePath "http://localhost:8000/docs"
    Start-Process -FilePath "http://localhost:5173"
}

Write-Host ""
Write-Host "启动完成！" -ForegroundColor Green