# AntiBlack Docker 部署指南

## 快速启动

```bash
cd docker-deploy
./start.sh
```

## 配置说明

### 1. 环境变量配置

复制 `.env.example` 为 `.env`，修改 `DB_HOST` 为本机IP：

```bash
cp .env.example .env
```

编辑 `.env`：
```env
DB_HOST=192.168.148.128  # 修改为你的局域网IP
```

### 2. 查看本机IP

```bash
# Linux/Mac
hostname -I

# Windows
ipconfig
```

### 3. 启动服务

```bash
./start.sh
```

### 4. 停止服务

```bash
./stop.sh
```

## 服务地址

| 服务 | 地址 | 默认账号 |
|------|------|----------|
| MongoDB | localhost:27017 | - |
| Kafka | localhost:9092 | - |
| Neo4j | localhost:7474 | neo4j/neo4j123 |
| PostgreSQL | localhost:5432 | antiblack/antiblack123 |
| Redis | localhost:6379 | - |

## 远程连接配置

如果要从其他机器连接这些服务：

1. 确保VM防火墙开放相应端口
2. 修改 `.env` 中的 `DB_HOST` 为VM的局域网IP
3. 重启服务：`docker compose restart`

## Docker Compose 单独命令

```bash
# 后台启动所有服务
docker compose up -d

# 查看日志
docker compose logs -f

# 查看特定服务日志
docker compose logs -f kafka

# 重启特定服务
docker compose restart kafka

# 停止所有服务
docker compose down

# 删除所有数据卷
docker compose down -v
```
