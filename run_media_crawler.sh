#!/bin/bash
# MediaCrawler 启动脚本 - 抖音 + 贴吧 关键词搜索
# 使用方式: ./run_media_crawler.sh [platform]
# platform: dy (抖音) 或 tieba (贴吧)，默认两个都跑

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "===== MediaCrawler 采集启动 ====="

# 设置环境变量 - PostgreSQL (远程 VM)
export POSTGRES_DB_HOST=192.168.148.128
export POSTGRES_DB_PORT=5432
export POSTGRES_DB_USER=antiblack
export POSTGRES_DB_PWD=antiblack123
export POSTGRES_DB_NAME=antiblack

# 关键词配置 - 黑灰产相关 (从 SlangMapping 动态读取)
# 初始使用硬编码关键词，后续由 SlangLearning 自动扩展
DOUYIN_KEYWORDS="出抖号,抖音号买卖,加V,千粉,微信号,换绑,租号"
TIEBA_KEYWORDS="出抖号,抖音号买卖,加微,刷粉,接码,群控"

run_douyin() {
    echo ""
    echo "=== 启动抖音采集 ==="
    echo "PostgreSQL: $POSTGRES_DB_HOST:$POSTGRES_DB_PORT/$POSTGRES_DB_NAME"
    echo "关键词: $DOUYIN_KEYWORDS"

    cd "$SCRIPT_DIR/MediaCrawler"
    PYTHONIOENCODING=utf-8 conda run -n anti-black python main.py \
        --platform dy \
        --type search \
        --keywords "$DOUYIN_KEYWORDS" \
        --save_data_option pg \
        --get_comment true \
        --headless true
}

run_tieba() {
    echo ""
    echo "=== 启动贴吧采集 ==="
    echo "PostgreSQL: $POSTGRES_DB_HOST:$POSTGRES_DB_PORT/$POSTGRES_DB_NAME"
    echo "关键词: $TIEBA_KEYWORDS"

    cd "$SCRIPT_DIR/MediaCrawler"
    PYTHONIOENCODING=utf-8 conda run -n anti-black python main.py \
        --platform tieba \
        --type search \
        --keywords "$TIEBA_KEYWORDS" \
        --save_data_option pg \
        --get_comment true \
        --headless true
}

# 根据参数选择运行的平台
case "${1:-all}" in
    dy)
        run_douyin
        ;;
    tieba)
        run_tieba
        ;;
    all)
        run_douyin
        ;;
    *)
        echo "用法: $0 [dy|tieba|all]"
        echo "  dy    - 只采集抖音"
        echo "  tieba - 只采集贴吧"
        echo "  all   - 两个都采集 (默认)"
        exit 1
        ;;
esac

echo ""
echo "===== 采集结束 ====="