#!/bin/bash
# AntiBlack Docker 一键启动脚本

set -e

echo "===== AntiBlack 一键部署 ====="

# 检查Docker
if ! command -v docker &> /dev/null; then
    echo "错误: Docker 未安装"
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    echo "错误: docker compose 未安装"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 启动服务
echo "启动数据库服务..."
docker compose up -d

echo ""
echo "===== 服务启动中 ====="

# 等待函数
wait_for_service() {
    local name=$1
    local cmd=$2
    echo -n "$name"
    for i in {1..60}; do
        if eval "$cmd" &> /dev/null; then
            echo " OK"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    echo " 失败"
    return 1
}

# 等待各服务就绪
wait_for_service "MongoDB" "docker exec antiblack-mongodb mongosh --quiet --eval \"db.adminCommand('ping')\""
wait_for_service "Kafka" "docker exec antiblack-kafka kafka-broker-api-versions.sh --bootstrap-server localhost:9092"
wait_for_service "Neo4j" "curl -s http://localhost:7474"
wait_for_service "PostgreSQL" "docker exec antiblack-postgres pg_isready -U antiblack"
wait_for_service "Redis" "docker exec antiblack-redis redis-cli ping"

echo ""
echo "===== 部署完成 ====="
echo ""
echo "服务地址:"
echo "  MongoDB:     localhost:27017"
echo "  Kafka:       localhost:9092"
echo "  Neo4j:       http://localhost:7474 (neo4j/neo4j123)"
echo "  PostgreSQL:  localhost:5432 (antiblack/antiblack123)"
echo "  Redis:       localhost:6379"
echo ""
echo "下一步:"
echo "  1. 编辑 config.yaml 确认数据库连接配置"
echo "  2. 运行: conda activate anti-black && python main.py"
echo ""
echo "停止服务: docker compose down"
echo "查看日志: docker compose logs -f [service]"