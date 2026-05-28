@echo off
chcp 65001 >nul
title AntiBlack 启动脚本

echo ================================================
echo  AntiBlack 启动脚本
echo ================================================

REM 检查 conda 环境
echo.
echo [检查] Conda 环境...
conda run -n anti-black python -c "print('anti-black OK')" 2>nul
if errorlevel 1 (
    echo [错误] Conda 环境 'anti-black' 未找到！
    echo 请先运行: conda create -n anti-black python=3.10
    pause
    exit /b 1
)
echo [OK] Conda 环境正常

REM 检查数据库连接
echo.
echo [检查] 数据库连接...
conda run -n anti-black python -c "from services.database import PostgreSQLService; PostgreSQLService.get_instance(); print('DB OK')" 2>nul
if errorlevel 1 (
    echo [警告] 数据库连接失败，请检查 PostgreSQL 服务
    echo 继续启动...
)

REM 创建日志目录
if not exist logs mkdir logs

echo.
echo ================================================
echo  启动服务...
echo ================================================

REM 启动 API Server
echo.
echo [1/3] 启动 API Server (http://localhost:8000) ...
start "AntiBlack-API" conda run -n anti-black python -m uvicorn api:app --reload --port 8000

REM 等待 API 启动
timeout /t 3 /nobreak >nul

REM 检查 API 是否启动成功
curl /s http://localhost:8000/docs >nul 2>&1
if errorlevel 1 (
    echo [警告] API Server 可能未启动成功
) else (
    echo [OK] API Server 启动成功
)

REM 启动 Frontend
echo.
echo [2/3] 启动 Frontend (http://localhost:5173) ...
cd frontend
start "AntiBlack-Frontend" npm run dev
cd ..

REM 启动 Daemon
echo.
echo [3/3] 启动 Daemon (后台守护进程) ...
start "AntiBlack-Daemon" conda run -n anti-black python scripts/run_daemon.py

echo.
echo ================================================
echo  所有服务已启动！
echo ================================================
echo.
echo  访问地址:
echo    - API 文档: http://localhost:8000/docs
echo    - Frontend:  http://localhost:5173
echo    - Daemon:    后台运行，日志在 logs/antiblack_daemon.log
echo.
echo  按任意键打开浏览器...
pause >nul

start http://localhost:8000/docs
start http://localhost:5173

echo.
echo 启动完成！所有服务已在后台运行。
echo.
echo 停止服务:
echo   - 关闭对应的命令行窗口
echo   - 或使用 taskkill /fi "windowtitle eq AntiBlack-*" /im explorer.exe
echo.
pause