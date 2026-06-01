# AntiBlack System

黑灰产情报分析Agent系统 - 后端服务

## 注意事项

本项目包含 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) 子目录，
其代码遵循 [NON-COMMERCIAL LEARNING LICENSE](MediaCrawler/LICENSE)。
请在使用时遵守其许可证条款。

## 项目状态

**全平台数据采集已成功运行！**

| 平台 | 数据量 |
|------|--------|
| dy（抖音） | 143 aweme, 1611 comment |
| tieba（贴吧） | 102 note, 905 comment |
| ks（快手） | 32 video |
| wb（微博） | 237 note, 1170 comment |
| xhs（小红书） | 197 note, 1586 comment |

**总计：751 条内容 + 5272 条评论**

## 项目结构

```
antiblack/
├── api/                    # API服务
│   └── server.py          # Flask服务器入口
├── config/                 # 配置管理
│   └── __init__.py        # 配置加载器（config.yaml + .env）
├── models/                 # 数据模型
│   └── entities.py        # 数据实体定义
├── pipeline/               # 处理流水线
│   ├── cleaner.py         # 数据清洗模块
│   ├── classifier.py      # 意图分类模块
│   ├── extractor.py       # 实体抽取模块
│   ├── router.py          # 分流决策模块
│   └── slang_learning.py  # 黑话学习模块（LLM验证）
├── scripts/               # 脚本
│   ├── run_pipeline.py    # 完整流水线脚本
│   ├── multi_crawler_scheduler.py  # 多平台采集调度器
│   ├── run_daemon.py      # 守护进程入口
│   └── start_media_crawler_api.py  # MediaCrawler API服务
├── services/              # 服务层
│   ├── database.py       # PostgreSQL服务
│   ├── daemon_scheduler.py   # 守护进程调度器
│   ├── error_book_sampler.py # LLM错题本抽检
│   ├── model_retrainer.py    # 模型重训触发
│   └── browser_automator.py  # 浏览器自动化
├── MediaCrawler/          # 数据采集模块（已定制）
├── LightRAG/             # 知识图谱库
├── docs/                 # 设计文档
├── config.yaml           # 配置文件
├── main.py              # 主入口
└── requirements.txt     # 依赖列表
```

## 快速开始

### 1. 安装依赖

```bash
conda activate anti-black
pip install -r requirements.txt
```

### 2. 配置

编辑 `config.yaml` 和 `.env` 配置数据库、LLM API、Kafka等连接参数。确保您的 Docker/VM 基础设施已启动。

### 3. 一键启动微服务集群

在 Windows 上，系统已全面升级为解耦的微服务架构。您只需要执行以下脚本，即可一键唤醒全部 5 个核心服务：

```powershell
.\scripts\start_all.ps1
```

执行后，会自动弹出 5 个带有颜色高亮和时间戳的独立控制台窗口：
1. **API 服务** (`start_api.py`)：提供数据看板和外部交互接口。
2. **爬虫底层控制台** (`start_media_crawler_api.py`)：驱动 Playwright 无头浏览器。
3. **爬虫调度器** (`multi_crawler_scheduler.py`)：定时从数据库拉取最新“黑话（Slang）”，指挥浏览器全网搜寻。
4. **数据推流端** (`media_crawler_publisher.py`)：将爬虫结果从 PostgreSQL 源源不断地推入 Kafka。
5. **处理大脑** (`run_daemon.py`)：消费 Kafka 数据，进行大模型洗稿、图谱抽取（LightRAG）和错题本自学习。

**采集结果查看：**
您可以随时查看守护进程的控制台输出，或者直接通过 API 查询系统监控状态。

### 4. 测试

```bash
pytest tests/ -v
```

## 架构说明

系统采用多Agent协作架构：

```
数据采集(MediaCrawler) → 清洗 → 分类 → 实体抽取 → 分流决策
                                                        ↓
                                              ┌─────────┴─────────┐
                                         轻量通道      深度通道(LightRAG)
                                         (规则/Regex)   (+LLM关系发现)
```

### Slang Learning 黑话学习模块

遵循设计文档 FR-SLANG-03：
- 候选词状态机：NEW → OBSERVED → LIKELY → CONFIRMED → STABLE
- LIKELY → CONFIRMED 转换需经过 LLM 验证
- **独立样本原则**：验证时排除触发消息，使用其他独立样本
- LLM 生成 regex_pattern + test_cases 进行二次验证

### 外部依赖

- **PostgreSQL**: 主数据库（192.168.148.128）
- **Neo4j**: LightRAG图存储
- **Redis**: 缓存层
- **LLM**: MiniMax-M2.7 (primary), qwen3.6-flash (backup)
- **VLM**: DashScope qwen3.6-27b (cloud)

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
