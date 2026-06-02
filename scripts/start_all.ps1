# AntiBlack 一键启动脚本 (Windows)
# 自动打开多个 PowerShell 窗口分别运行系统的各个微服务组件

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "        AntiBlack 核心服务一键启动        " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."

# 0. 启动 Chrome CDP 授权弹窗自动点击器 (最先启动, 后续爬虫触发的弹窗都由它放行)
Write-Host "[0/5] 正在启动 CDP 弹窗自动点击器..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd `"$ProjectRoot`"; conda activate anti-black; python scripts/auto_click_cdp_dialog.py" -WindowStyle Normal

Start-Sleep -Seconds 2

# 1. 启动 AntiBlack API 服务 (提供数据看板面板)
Write-Host "[1/5] 正在启动 API 服务..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd `"$ProjectRoot`"; conda activate anti-black; python scripts/start_api.py" -WindowStyle Normal

Start-Sleep -Seconds 2

# 2. 启动底层爬虫调度器与API (驱动真实的浏览器爬取数据)
Write-Host "[2/5] 正在启动 爬虫底层 API 与 调度器..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd `"$ProjectRoot`"; conda activate anti-black; python scripts/start_media_crawler_api.py" -WindowStyle Normal
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd `"$ProjectRoot`"; conda activate anti-black; python scripts/multi_crawler_scheduler.py --daemon" -WindowStyle Normal

Start-Sleep -Seconds 3

# 3. 启动数据采集搬运工 (从数据库推向 Kafka)
Write-Host "[3/5] 正在启动 数据采集推流 (Publisher)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd `"$ProjectRoot`"; conda activate anti-black; python scripts/media_crawler_publisher.py" -WindowStyle Normal

Start-Sleep -Seconds 2

# 4. 启动后台处理总线 (消费数据并进行清洗、分类、自学习)
Write-Host "[4/5] 正在启动 核心处理引擎 (Daemon)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd `"$ProjectRoot`"; conda activate anti-black; python scripts/run_daemon.py" -WindowStyle Normal

Write-Host "`n所有服务已启动！" -ForegroundColor Yellow
Write-Host "您将看到 6 个新的 PowerShell 窗口，分别负责不同的流水线节点。" -ForegroundColor Yellow
Write-Host "您可以随时关闭不需要的窗口来终止某个具体服务。" -ForegroundColor Yellow
