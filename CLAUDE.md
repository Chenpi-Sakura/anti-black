# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AntiBlack is a 黑灰产情报分析Agent系统 (Black-market Intelligence Analysis Agent System) for detecting and analyzing illegal activity signals across multiple channels (Douyin, Tieba, forums, etc.).

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the API server (FastAPI)
conda run -n anti-black python -m uvicorn api:app --reload --port 8000
# Server starts on http://127.0.0.1:8000
# API docs at http://127.0.0.1:8000/docs

# Run tests
pytest tests/ -v

# Run single test file
pytest tests/test_classifier.py -v

# Run full pipeline (data collection + processing)
./run_full_pipeline.sh

# Run processing pipeline only (no collection)
conda run -n anti-black python scripts/run_pipeline.py

# Docker deployment (infrastructure only - PostgreSQL, Kafka, Neo4j, Redis)
cd docker-deploy && ./start.sh
```

## Architecture

### Core Components

```
api/                   # FastAPI application
api/__init__.py        # FastAPI app factory
api/routes/            # FastAPI route handlers
api/schemas/           # Pydantic request/response models
api/deps.py            # Dependency injection (database)
frontend/              # Vue 3 SPA (Element Plus + Pinia)
config/__init__.py     # Config singleton loading from config.yaml + .env
```

### API Server

FastAPI with automatic OpenAPI docs at http://127.0.0.1:8000/docs

### Pipeline Flow

```
数据采集(MediaCrawler) → cleaner(清洗) → classifier(分类) → extractor(实体抽取)
                                                              ↓
                                                      router(分流决策)
                                                         /        \
                                                light_channel  deep_channel
                                                (规则/Regex)  (LightRAG+LLM)
                                                              ↓
                                                       slang_learning(进化)
```

### SSE Streaming

Query progress is streamed via Server-Sent Events (SSE) at `GET /api/v1/queries/{query_id}/stream`.

Format: `data: {"type": "stage"|"progress"|"content"|"complete", ...}\n\n`

Frontend connects via `EventSource` to receive real-time pipeline progress.

### Key Models (in models/)

| Model | Implementation | Purpose |
|-------|---------------|---------|
| EmbeddingModel | sentence-transformers (BAAI/bge-small-zh-v1.5) | Text vectorization |
| ClassificationModel | xgboost (trained classifier) | Risk classification |
| FastTextModel | lid.176.bin | Language detection |
| OCRModel | PaddleOCR | Image text extraction |
| CloudVLMClient | DashScope qwen3.6-27b | Cloud vision model |
| OllamaClient | qwen3.6 (future) | Local VLM/embedding |

### External Dependencies

- **PostgreSQL**: Primary database for AntiBlack (antiblack schema) and MediaCrawler (media_crawler schema) at 192.168.148.128
- **Kafka**: Message queue for pipeline (raw.messages → cleaned.messages → deep.analysis.tasks)
- **Neo4j**: Graph storage for LightRAG entity relations at 192.168.148.128
- **Redis**: Caching layer at 192.168.148.128
- **LLM**: MiniMax-M2.7 (primary), qwen3.6-flash (backup)
- **VLM**: DashScope qwen3.6-27b (cloud)

### Slang Learning (FR-SLANG-03)

The slang learning module (`pipeline/slang_learning.py`) implements:

- **State Machine**: NEW → OBSERVED → LIKELY → CONFIRMED → STABLE
- **Independent Sample Principle**: When validating LIKELY→CONFIRMED, the trigger message (M1) is excluded; independent samples (M2, M3...) from other messages are used
- **LLM Validation**: Generates regex_pattern + test_cases, validates with positive/negative examples
- **Retry Logic**: Max 3 retries, then REJECTED with 30-day silence period

### Data Models

All data entities are dataclasses defined in `models/entities.py`:
- `Entity`, `Clue`, `Feedback`, `QueryTask`, `SeedWord`, `Proposal`, `ExportTask`, `Channel`, `Metrics`, `AutoEvolution`
- Status enums: `SlangStatus`, `SeedWordStatus`, `QueryStatus`, `ExportStatus`, `RetrainStatus`

### Configuration

- `config.yaml`: Main configuration with environment variable interpolation (`${VAR_NAME}`)
- `.env`: Environment-specific values (API keys, database hosts, Neo4j/PostgreSQL credentials)
- Config loads `.env` automatically via `_load_env_file()` in `config/__init__.py`

## Important Notes

- **Git workflow**: Always ask before pushing to remote
- **Docker**: Use `docker compose` (space, not hyphen)
- **Environment execution**: Use `conda run -n <env> <command>` to run commands in conda environment without activating it
- **Docker services** run on VM at 192.168.148.128 (MongoDB, Kafka, Neo4j, PostgreSQL, Redis)
- **Data collection**: Uses MediaCrawler for Douyin and Tieba data collection
- **Twitter collector** is not yet implemented - requires Twitter API credentials
- **Telegram collector** works in mock/demo mode, needs bot_token and chat_ids to be fully functional
- LightRAG is included as a local submodule clone in `LightRAG/` directory
- MediaCrawler is cloned in `MediaCrawler/` directory

## User Preferences

- Always confirm before git push operations
- Use `docker compose` not `docker-compose`
- Conda environment: run commands with `conda run -n <env_name> <command>` syntax

## CDP Mode (Chrome DevTools Protocol)

The crawler uses CDP mode for anti-detection when connecting to an existing Chrome browser.

**启动方式（用户手动）：**
1. 手动启动 Chrome：`chrome --remote-debugging-port=1936`
2. 或在 Chrome 地址栏输入：`chrome://inspect/#remote-debugging`

**CDP 连接流程：**
- MediaCrawler 通过 WebSocket 连接到 `localhost:1936`
- CDP_CONNECT_EXISTING=True 时使用 `/devtools/browser` 端点
- 用户需要在浏览器弹出的确认对话框中点击"允许"

**已知问题：**
- **DouYin CDP fallback bug**：当 CDP 连接失败时，原代码会 fallback 到 Playwright 模式，但 Playwright chromium 未安装会导致误导性错误。已修复：`launch_browser_with_cdp()` 失败时直接抛异常，不再 fallback。
- **快手数据少**：Kuaishou 平台对黑灰产关键词返回数据量少，非代码问题
- **XHS Cookie 会过期**：需要定期更新登录 Cookie

## 调试经验总结

### MediaCrawler 数据库配置
- MediaCrawler 写入 `media_crawler` 数据库（public schema）
- AntiBlack 的 `MediaCrawlerAdapter` 需要在 `config.yaml` 中配置 `database: media_crawler`（不是 `antiblack`）
- 表在 `media_crawler.public` 而非 `antiblack.media_crawler`

### 成功采集的平台
| 平台 | 数据量 | 说明 |
|------|--------|------|
| dy | 143 aweme, 1611 comment | CDP模式成功 |
| tieba | 102 note, 905 comment | CDP模式成功 |
| ks | 32 video | 数据量少 |
| wb | 237 note, 1170 comment | 成功 |
| xhs | 197 note, 1586 comment | CDP模式成功，需定期更新Cookie |
