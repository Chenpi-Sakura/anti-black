# AntiBlack System

黑灰产情报分析Agent系统 - 后端服务

## 项目结构

```
antiblack/
├── api/                    # API服务
│   └── server.py          # Flask服务器入口
├── config/                 # 配置管理
│   └── __init__.py        # 配置加载器
├── models/                 # 数据模型
│   └── __init__.py        # MongoDB集合模型
├── pipeline/               # 处理流水线
│   ├── collector.py       # 数据采集模块
│   ├── cleaner.py         # 数据清洗模块
│   ├── classifier.py      # 意图分类模块
│   ├── extractor.py       # 实体抽取模块
│   ├── router.py          # 分流决策模块
│   └── slang_learning.py   # 黑话学习模块
├── routes/                 # API路由
│   ├── queries.py         # 查询接口
│   ├── clues.py          # 线索接口
│   ├── entities.py        # 实体接口
│   ├── feedback.py       # 反馈接口
│   ├── system.py         # 系统状态接口
│   ├── taxonomy.py      # 分类体系接口
│   ├── evolution.py     # 自进化接口
│   ├── export.py        # 导出接口
│   ├── channels.py      # 渠道接口
│   ├── metrics.py       # 监控接口
│   └── seed_words.py    # 种子词接口
├── services/              # 服务层
│   ├── database.py      # MongoDB服务
│   ├── kafka_service.py # Kafka服务
│   └── lightrag_service.py  # LightRAG服务
├── tests/                # 单元测试
│   └── test_pipeline.py # 测试用例
├── utils/                # 工具函数
│   └── __init__.py      # 工具函数
├── docs/                 # 文档
├── LightRAG/             # LightRAG库（克隆）
├── RAG-anything/         # RAG-anything库（克隆）
├── config.yaml          # 配置文件
├── main.py              # 主入口
└── requirements.txt     # 依赖列表
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config.yaml` 配置MongoDB、Kafka、LightRAG等连接参数。

### 3. 运行

```bash
python main.py
```

API服务将在 http://127.0.0.1:8000 启动。

### 4. 测试

```bash
pytest tests/ -v
```

## API端点

- `POST /api/v1/queries` - 发起自然语言查询
- `GET /api/v1/queries/{query_id}` - 查询任务状态
- `GET /api/v1/clues` - 获取线索列表
- `GET /api/v1/clues/{clue_id}` - 获取线索详情
- `GET /api/v1/entities/{entity_id}/profile` - 获取实体画像
- `POST /api/v1/feedback` - 提交纠错反馈
- `GET /api/v1/system/ready` - 获取系统就绪状态
- `GET /api/v1/system/pipeline-status` - 获取后台巡逻状态
- `GET /api/v1/taxonomy` - 获取分类体系
- `GET /api/v1/evolution/status` - 获取自进化状态
- `GET /api/v1/evolution/proposals` - 获取规则提案列表
- `POST /api/v1/evolution/proposals/{proposal_id}/approve` - 审批规则提案
- `POST /api/v1/exports` - 创建导出任务
- `GET /api/v1/exports/{export_id}` - 查询导出任务状态
- `GET /api/v1/metrics/overview` - 获取监控概览
- `GET /api/v1/channels` - 获取渠道列表
- `GET /api/v1/channels/{platform}/status` - 获取指定渠道状态
- `POST /api/v1/channels/{platform}/config` - 配置渠道采集任务
- `GET /api/v1/channels/{platform}/stats` - 获取渠道采集统计
- `GET /api/v1/seed-words` - 获取种子词库状态
- `POST /api/v1/seed-words/{word}/promote` - 手动晋升种子词

## 架构说明

系统采用多Agent协作架构：
- 主控Agent负责任务编排和分流决策
- 采集Agent负责从多源渠道采集情报
- 清洗Agent负责数据标准化和去重
- 分类Agent负责风险意图分类
- 抽取Agent负责实体抽取（轻量通道）
- 深度分析Agent（图谱构建通道）负责使用LightRAG构建知识图谱