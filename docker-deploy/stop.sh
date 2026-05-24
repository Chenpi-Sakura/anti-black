#!/bin/bash
# AntiBlack Docker 停止脚本

echo "===== 停止 AntiBlack 服务 ====="
docker compose down
echo "服务已停止"
echo ""
echo "如需删除所有数据: docker compose down -v"