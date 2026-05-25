# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AntiBlack is a 黑灰产情报分析Agent系统 (Black-market Intelligence Analysis Agent System) for detecting and analyzing illegal activity signals across multiple channels (Telegram, Twitter, forums, etc.).

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the API server
python main.py
# Server starts on http://127.0.0.1:8000

# Run tests
pytest tests/ -v

# Run single test file
pytest tests/test_classifier.py -v

# Docker deployment (infrastructure only - MongoDB, Kafka, Neo4j, PostgreSQL, Redis)
cd docker-deploy && ./start.sh
```

## Architecture

### Core Components

```
api/server.py          # Flask app factory, registers all blueprints under /api/v1
main.py                # Entry point, creates log dir and starts server
config/__init__.py    # Config singleton loading from config.yaml + .env
```

### Pipeline Flow

```
collector (采集) → cleaner (清洗) → classifier (分类) → extractor (实体抽取)
                                                              ↓
                                                      router (分流决策)
                                                         /        \
                                                light_channel  deep_channel
                                                (规则/轻量)   (LightRAG+LLM)
```

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

- **PostgreSQL**: Primary database for AntiBlack (antiblack schema) and MediaCrawler (media_crawler schema)
- **Kafka**: Message queue for pipeline (raw.messages → cleaned.messages → deep.analysis.tasks)
- **Neo4j**: Graph storage for LightRAG entity relations
- **Redis**: Caching layer
- **LLM**: MiniMax-M2.7 (primary), qwen3.6-flash (backup)
- **VLM**: DashScope qwen3.6-27b (cloud)

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
- **Twitter collector** is not yet implemented - requires Twitter API credentials
- **Telegram collector** works in mock/demo mode, needs bot_token and chat_ids to be fully functional
- LightRAG is included as a local submodule clone in `LightRAG/` directory

## User Preferences

- Always confirm before git push operations
- Use `docker compose` not `docker-compose`
- Conda environment: run commands with `conda run -n <env_name> <command>` syntax