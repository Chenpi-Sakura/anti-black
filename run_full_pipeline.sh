#!/bin/bash
# AntiBlack 完整流程 - 数据收集 + 处理 + 进化
# 包含 MediaCrawler 数据采集 + AntiBlack Pipeline 处理

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo " AntiBlack 完整流程开始"
echo "============================================"

# Step 1: 采集数据
echo ""
echo "[Step 1] 数据采集..."
echo "--------------------------------------------"

# 抖音采集
echo ""
echo "=== 抖音数据采集 ==="
POSTGRES_DB_HOST=192.168.148.128
POSTGRES_DB_PORT=5432
POSTGRES_DB_USER=antiblack
POSTGRES_DB_PWD=antiblack123
POSTGRES_DB_NAME=antiblack
export POSTGRES_DB_HOST POSTGRES_DB_PORT POSTGRES_DB_USER POSTGRES_DB_PWD POSTGRES_DB_NAME

DOUYIN_KEYWORDS="出抖号,抖音号买卖,加V,千粉,微信号,换绑,租号"

cd "$SCRIPT_DIR/MediaCrawler"
PYTHONIOENCODING=utf-8 conda run -n anti-black python main.py \
    --platform dy \
    --type search \
    --keywords "$DOUYIN_KEYWORDS" \
    --save_data_option postgres \
    --get_comment true \
    --headless true

echo "抖音采集完成"

# 贴吧采集
echo ""
echo "=== 贴吧数据采集 ==="
TIEBA_KEYWORDS="出抖号,抖音号买卖,加微,刷粉,接码,群控"

cd "$SCRIPT_DIR/MediaCrawler"
PYTHONIOENCODING=utf-8 conda run -n anti-black python main.py \
    --platform tieba \
    --type search \
    --keywords "$TIEBA_KEYWORDS" \
    --save_data_option postgres \
    --get_comment true \
    --headless true

echo "贴吧采集完成"

# Step 2: 运行 AntiBlack Pipeline
echo ""
echo "[Step 2] 数据处理..."
echo "--------------------------------------------"
cd "$SCRIPT_DIR"
conda run -n anti-black python scripts/run_pipeline.py

echo ""
echo "============================================"
echo " AntiBlack 完整流程结束"
echo "============================================"