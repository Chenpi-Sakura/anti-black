"""
Orchestrator Agent - 主控Agent大脑
负责自然语言理解、任务编排、SSE进度推送、LLM响应生成
"""
import os
import json
import logging
import re
import asyncio
import time as _time
from typing import Any, Optional

from agent.tools import get_tools_by_names, invoke_tool
from agent.skills.registry import (
    match_skill_by_keywords,
    get_skill,
    get_skill_body,
)

from openai import AsyncOpenAI

from api.routes.queries import put_progress
from services.database import PostgreSQLService
from config import get_config

logger = logging.getLogger(__name__)


# 中文同义词字典 — 当 LLM 发出某个关键词时，自动展开为所有同义变体，
# 大幅提升召回率（避免 LLM 选词不精准导致的 0 结果）。
# 字典 key 是常见"主词"，value 是 clue raw_text 里实际出现的同义写法。
# 数据来源：diagnose_search_clues.py 实证（7d fraud_leads 数据集）。
SYNONYM_DICT: dict[str, list[str]] = {
    "微信号":  ["微信号", "微信", "卫星", "加微", "vx", "V信", "薇信"],
    "微信":    ["微信", "微信号", "卫星", "加微", "vx", "V信"],
    "手机":    ["手机", "电话", "联系方式", "手机号"],
    "诈骗":    ["诈骗", "杀猪盘", "刷单", "兼职", "引流"],
    "诈骗引流": ["诈骗引流", "诈骗", "杀猪盘", "刷单", "兼职", "引流"],
    "刷量":    ["刷量", "刷粉", "刷赞", "刷评", "涨粉", "刷播放"],
    "账号交易": ["账号交易", "卖号", "出号", "租号", "账号买卖", "换绑"],
    "黑产工具": ["黑产工具", "接码", "群控", "脚本"],
}


def _expand_query_synonyms(tokens: list[str]) -> list[str]:
    """对每个 token 在 SYNONYM_DICT 里查找同义词，union 去重后返回展开列表。

    - 匹配方式：token == key 或 token in value → 用 key 对应的 value 展开
    - 不在字典里的 token 原样保留
    - 去重保序，避免重复 pattern 撑大 SQL 数组
    """
    seen: set[str] = set()
    expanded: list[str] = []
    for t in tokens:
        variants: list[str] = []
        if t in SYNONYM_DICT:
            variants = SYNONYM_DICT[t]
        else:
            # 反向匹配：token 是某字典项 value 里的同义写法
            for key, values in SYNONYM_DICT.items():
                if t in values:
                    variants = values
                    break
        if not variants:
            variants = [t]
        for v in variants:
            if v not in seen:
                seen.add(v)
                expanded.append(v)
    return expanded


# 工具定义 — 三层工作流：search → drill → aggregate
# Each tool description is written for the LLM, not for humans.
# Descriptions are imperative: when to call, what it returns, edge cases.
TOOLS = [
    # =========================== L1: SEARCH ===========================
    {
        "type": "function",
        "function": {
            "name": "search_clues",
            "description": "Search clues by keyword / risk_type / time / platform. Returns a LIST of clue summaries (no full text). Use for broad queries like 'find recent clue text about X'. For single-clue detail use get_clue_detail. Supports multi-value filters via array params.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "**MUST be Chinese keyword(s)** to match against clue text, e.g. '微信号', '诈骗', '刷粉', '账号交易'. raw_text / cleaned_text are stored in Chinese only — English keywords like 'WeChat' / 'fraud' will return 0 results. If user mentions an English term, translate to the Chinese equivalent (WeChat→微信号/卫星, fraud→诈骗/杀猪盘, account trading→账号交易)."
                    },
                    "entity_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["WECHAT", "PHONE", "QQ", "ACCOUNT"]
                        },
                        "description": "Optional strong-signal filter on extracted entities. Filters by entity_list JSONB column using GIN-indexed @> containment. Use when the user query explicitly references a contact channel (微信号/手机号/QQ) — combine with a Chinese query for the strongest lock (e.g. user='涉及微信号的诈骗' → query='诈骗', entity_types=['WECHAT'])."
                    },
                    "time_range": {
                        "type": "object",
                        "description": "Time window as {amount, unit}. E.g. {amount:1, unit:'day'} = last 1 day, {amount:7, unit:'day'} = last 7 days, omit = search all-time (no time filter).",
                        "properties": {
                            "amount": {"type": "integer", "description": "How many units back, e.g. 1, 7, 30"},
                            "unit": {"type": "string", "description": "Time unit: 'day', 'hour', 'week', 'month'"}
                        }
                    },
                    "risk_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Risk level1 filter: account_trading, fraud_leads, traffic_cheating, black_tools, money_laundering, unknown, irrelevant. Supply as array — multi-value supported."
                    },
                    "platforms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Platform filter: douyin, baidu_tieba, weibo, xiaohongshu, kuaishou, telegram. Multi-value supported."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return. 50 by default.",
                        "default": 50
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_clues",
            "description": "Simpler time-window alternative to search_clues. Parameters: hours (int, default 24), risk_label_level1, platform. Use when user asks 'last N hours' without needing keyword/or-platform-list filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "integer",
                        "description": "Look-back window in hours. Default 24 (last 24h).",
                        "default": 24
                    },
                    "risk_label_level1": {
                        "type": "string",
                        "description": "Single risk type filter (optional): account_trading, fraud_leads, traffic_cheating, black_tools, money_laundering, unknown, irrelevant. Only one allowed."
                    },
                    "platform": {
                        "type": "string",
                        "description": "Single platform filter (optional): douyin, baidu_tieba, weibo, xiaohongshu, kuaishou."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results. Default 20.",
                        "default": 20
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_entities",
            "description": "Search entity DB (WeChat IDs, phone numbers, QQ, accounts) by name or type. Returns matching entity nodes with metadata. Use when user mentions a specific identifier or wants to find known entities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {
                        "type": "string",
                        "description": "Entity name keyword, e.g. 'WeChat', 'account', or a specific ID"
                    },
                    "entity_type": {
                        "type": "string",
                        "description": "Entity type filter: WeChat, phone, QQ, account. Optional."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results. Default 20.",
                        "default": 20
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_slang",
            "description": "Look up slang terms in the slang dictionary (slang_mappings table). Matches against slang_raw or meaning column. Call when user asks 'what does XX mean' or wants to see recent slang. For comprehensive slang coverage use this tool — search_clues only has sampled slang_mappings on its results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slang_term": {
                        "type": "string",
                        "description": "Slang keyword or description, e.g. 'chuhao' (account selling), 'shuafen' (fake followers). Long sentences are auto-split into 2-gram keywords."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results. Default 20.",
                        "default": 20
                    }
                }
            }
        }
    },
    # =========================== L2: DRILL ===========================
    {
        "type": "function",
        "function": {
            "name": "get_clue_detail",
            "description": "Fetch a single clue's full content by clue_id. Returns raw_text, entity_list, slang_mappings, graph_relations. Call AFTER search_clues when a specific clue_id needs deeper inspection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clue_id": {
                        "type": "string",
                        "description": "The clue_id, e.g. 'clue_20260608_063205_d5d63ebb'. Required."
                    }
                },
                "required": ["clue_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kg_query",
            "description": "Knowledge-graph structured retrieval (entities ↔ relationships ↔ chunks). Returns raw structured data — NO LLM summarization. Use for 'who is connected to whom', 'entity relationship network', or 'find related entities around X'. Returns a dict with entities/relationships/chunks/references.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Query text, e.g. 'Douyin account trading relationships', 'WeChat fraud connections'"
                    },
                    "mode": {
                        "type": "string",
                        "description": "Search mode: local (entity-first), global (relationship-first), hybrid (balanced), mix (entity + relation + vector chunks, best for comprehensive retrieval), naive (pure vector)",
                        "default": "hybrid"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max entities/relationships/chunks to return per category. 10 by default.",
                        "default": 10
                    }
                }
            }
        }
    },
    # =========================== L3: AGGREGATE ===========================
    {
        "type": "function",
        "function": {
            "name": "aggregate_clue_stats",
            "description": "AGGREGATE (not search). SQL GROUP BY on 110K+ clues — count distribution by risk_type, platform, or cross-dimension. Use for 'trend', 'today breakdown', 'top 3', 'growth rate', 'change over time' queries. NOT a search tool — does NOT return individual clue text. When user asks about trends/ranking/distribution, ALWAYS call this first instead of guessing from search_clues samples.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_range": {
                        "type": "object",
                        "description": "Time window as {amount, unit}. E.g. {amount:1, unit:'day'} = today, {amount:30, unit:'day'} = this month. Omit or set amount=0 for all-time.",
                        "properties": {
                            "amount": {"type": "integer", "description": "How many units back, e.g. 1, 7, 30"},
                            "unit": {"type": "string", "description": "Time unit: 'day', 'hour', 'week', 'month'"}
                        }
                    },
                    "group_by": {
                        "type": "string",
                        "description": "Aggregation dimension: 'risk_type' (by risk only), 'platform' (by channel only, same as 'channel'), 'risk_platform' (cross by risk+platform). Default: risk_platform.",
                        "default": "risk_platform"
                    },
                    "risk_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional risk type filter for the aggregation scope: account_trading, fraud_leads, traffic_cheating, black_tools, money_laundering, unknown, irrelevant."
                    },
                    "platforms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional platform filter: douyin, baidu_tieba, weibo, xiaohongshu, kuaishou."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_actor_footprint",
            "description": "Entity activity timeline across platforms. Input a WeChat ID / phone / QQ, returns: timeline by date+channel, risk label history, recent clues, entity metadata. Use for 'what else did this account do', 'actor profile/portrait', 'track record across channels'. entity_type is optional but helps precision when known.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_value": {
                        "type": "string",
                        "description": "Entity identifier: WeChat ID, phone number, QQ number, or any source_author_id. Required."
                    },
                    "entity_type": {
                        "type": "string",
                        "description": "Entity type hint (optional, narrows entity-table search): 'WeChat', 'phone', 'QQ', 'account'."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max recent clues to return. Default 50.",
                        "default": 50
                    }
                },
                "required": ["entity_value"]
            }
        }
    }
]

SYSTEM_PROMPT_V1_DEPRECATED = """你是一个黑灰产情报分析专家（Orchestrator Agent 大脑），负责自然语言理解、任务编排、调用工具检索数据，并生成专业的态势分析报告。

【核心工作流：根据意图选择模式】
1. 宏观态势与趋势分析（例如"近期XX有什么趋势"、"大盘情况"、"全面分析XX"）：
   - 必须调用 L3 `aggregate_clue_stats` 获取准确的统计与分布数据（严禁用 search_clues 的抽样数据自己估算）。
   - 必须调用 L2 `kg_query` 挖掘涉案的核心实体与关联网络。
   - 必须调用 L1 `search_slang` 获取专属黑话词典。
2. 实体与团伙溯源（例如"分析某个微信号"、"某人的活动轨迹"、"溯源"）：
   - 必须调用 L3 `get_actor_footprint` 获取跨平台活动时间线与历史记录。
   - 必须调用 L2 `kg_query` 查找其上下游关联节点。
3. 专项与细节查询（例如"XX是什么意思"、"看下某条线索详情"、"找几条XX的线索"）：
   - 按需调用 L1 (search_clues/search_slang) 或 L2 (get_clue_detail)，获取到目标信息即刻停止。

【工具使用强约束（不可违反）】
- 中文关键词强制要求：`search_clues.query` 必须使用中文。若用户使用英文（如 fraud, WeChat, account trading），必须翻译为对应的黑产中文词汇（如 诈骗/杀猪盘, 微信号, 账号交易）。
- 实体类型强锁（GIN索引）：当用户明确查询具体通联渠道（微信号、手机号、QQ、账号）时，必须在 `search_clues` 中同时传入对应的 `entity_types`（如 ['WECHAT']），以实现底层精准加速过滤。
- 独立维度独立调用：用户要求的每个维度必须调用专属工具。绝对禁止用 `search_clues` 的结果捏造聚合趋势（必须用 aggregate_clue_stats），或代替完整的黑话词典（必须用 search_slang）。
- 限制与兜底：单次最多 3 轮工具调用。禁止使用相同参数重复调用同一工具。若某维度无数据，在报告中客观说明即可，切勿捏造。

【Markdown 排版与渲染严格规范（极其重要）】
为了确保前端解析器完美渲染，你的输出必须严格遵循标准 Markdown 语法，**绝对禁止将不同区块压缩在同一行或省略必要空行**：
1. 区块间必须保留空行：在任何标题（#）、表格（|...|）、无序列表（-）、有序列表（1.）以及引用块（>）、分割线（---）的**上方和下方，必须至少保留一个空白行`\n\n`（两个`\n`）**。绝对禁止普通段落文本紧贴在表格或列表首尾。
2. 表格严格换行与标准格式：表格的每一行结束必须有标准的换行符，绝对禁止出现 `||` 连在一起不换行的情况。表头和数据行之间必须有如 `|---|---|` 的标准分隔行。
3. 列表规范：每个列表项必须独占一行。若列表项内有换行，需保持正确缩进。
4. 分割线规范：只使用原生的 `---` 作为分割线，且上下必须有空行。

【态势报告结构规范】
遇到宏观态势、趋势分析或溯源时，必须严格采用以下结构化排版（Markdown）：
一、大盘数据与风险分布：使用 aggregate_clue_stats 的数据，说明时间窗口、总数。用**表格**呈现（风险子类 | 数量/占比 | 典型特征）。
二、跨平台活跃特征：基于统计或线索结果，使用无序列表提炼各大平台（如抖音、贴吧、微博等）的违规内容特征。
三、高价值涉案实体：用**表格**归纳图谱或线索中发现的实体（实体名称 | 类型 | 描述），建议分为"核心实体"与"关键意图实体"。
四、核心关系网络与关键发现：
    - 关系链使用**文本层级树（如 ├─→ / └─→）**直观展现（基于 kg_query 结果）。
    - 在树状图下方总结"重要发现"（如警方行动、引流手法升级等）。
五、黑话与暗语解读：用**表格**展示（黑话/emoji | 含义 | 应用场景）。
六、实体活动时间线（仅限溯源场景）：使用时间线列表格式，展示实体（get_actor_footprint）的历史动作。
七、综合研判：以安全专家视角总结核心载体、手法演变及重点防范场景。
"""

# SYSTEM_PROMPT_CORE replaces SYSTEM_PROMPT_V1_DEPRECATED. The old version
# is retained as a fallback for A/B switching during the 4-week dual-track
# migration and will be removed in a future commit.
SYSTEM_PROMPT_CORE = """你是 AntiBlack 黑灰产情报分析 Agent 的核心大脑。

# 你的工作方式
1. **理解意图**：分析用户问题，识别属于哪个场景（溯源 / 趋势 / 黑话调查 / 通用检索）。
2. **调用工具**：每个场景有专属的工具集和强制工作流。系统会告诉你当前激活的 Skill（如果有）。
3. **生成报告**：严格按规范的结构化 Markdown 输出。

# 无追问硬约束（极其重要）
- 严禁向用户反问："请提供 X"、"你具体指什么"等任何要求补充信息的回复。
- 严禁返回"信息不足"或"需要更多细节"作为最终输出。
- 必须基于合理假设推进查询：当用户问题模糊时（如"分析一下"），自动选择最可能的解读方向。
- 假设必须在最终报告中显式说明（"基于以下假设推进：xxx"），让用户能看到你的判断依据。
- 缺数据时客观说明"未发现"或"暂无数据"，**不允许阻塞**。

# Markdown 渲染规范（不可违反）
- 区块间保留空行：标题/表格/列表/分割线上下必须有 `\\n\\n`
- 表格格式严格：表头分隔行 `|---|---|` 必须有，每行 `\\n` 结尾
- 列表每项独占一行
- 关系链用 `├─→ / └─→` 树状图

# 输出原则
- 严禁捏造：没有的工具结果不能编造。无数据时客观说明"未发现"。
- 引用工具结果：所有数字必须来自工具返回，不要凭印象。
- 控制在 3 轮工具调用内。
- 每次回复必须包含实质性分析内容（不能是空回复或"已收到"）。
"""

# Active prompt — swap to SYSTEM_PROMPT_V1_DEPRECATED if needed during dual-track.
SYSTEM_PROMPT = SYSTEM_PROMPT_CORE

def _count_tool_result(result: Any) -> int:
    """Return a human-meaningful count for a tool's return value.

    Used by the orchestrator's main loop to populate the 'found N results'
    SSE event.  Different tools return different shapes:

    - search_clues / get_recent_clues / search_entities / search_slang:
      return a list.  Use len().
    - kg_query: _kg_query wraps the integrator result as
      {content, query, mode} where content is a JSON string.  Peel it.
    - get_clue_detail: returns a single dict.  Count as 1 if found, else 0.
    - aggregate_clue_stats: dict with ``total_clues`` key.
    - get_actor_footprint: dict with ``summary.total_clues_found``.
    """
    if isinstance(result, dict):
        # aggregate_clue_stats
        tc = result.get("total_clues")
        if tc is not None:
            return int(tc)
        # get_actor_footprint
        sm = result.get("summary")
        if isinstance(sm, dict) and "total_clues_found" in sm:
            return int(sm["total_clues_found"])
        # kg_query: peel content JSON for data.entities/relationships/chunks
        data = _peel_tool_result_data(result)
        if data is not None:
            return (
                len(data.get("entities", []))
                + len(data.get("relationships", []))
                + len(data.get("chunks", []))
                + len(data.get("references", []))
            )
        # get_clue_detail / raw_response
        if "clue_id" in result or "raw_response" in result:
            return 1
    if isinstance(result, list):
        return len(result)
    return 0


def _format_tool_result_summary(result: Any) -> str:
    """Return a detailed summary string for the SSE 'retrieved' event.

    For kg_query results, shows a breakdown of entities, relationships,
    and chunks.  For aggregate_clue_stats, shows total clue count.
    For get_actor_footprint, shows channel + clue summary.
    """
    if isinstance(result, dict):
        # aggregate_clue_stats
        tc = result.get("total_clues")
        if tc is not None:
            gb = result.get("group_by", "")
            return f"共 {int(tc):,} 条线索（分组: {gb}）"

        # get_actor_footprint
        sm = result.get("summary")
        if isinstance(sm, dict):
            chs = sm.get("channels", [])
            clo = sm.get("total_clues_found", 0)
            return f"实体 在 {len(chs)} 个渠道共 {int(clo)} 条活跃记录"

        # kg_query: peel content JSON
        data = _peel_tool_result_data(result)
        if data is not None:
            ents = len(data.get("entities", []))
            rels = len(data.get("relationships", []))
            chks = len(data.get("chunks", []))
            parts = []
            if ents:
                parts.append(f"{ents} 个实体")
            if rels:
                parts.append(f"{rels} 个关系")
            if chks:
                parts.append(f"{chks} 个文本块")
            total = ents + rels + chks
            return f"找到 {', '.join(parts)}（共 {total} 条）"

        # get_clue_detail
        if "clue_id" in result:
            return "获取到 1 条线索详情"

    if isinstance(result, list):
        return f"找到 {len(result)} 条结果"
    return "执行完成"


def _peel_tool_result_data(result: Any) -> dict | None:
    """Extract the structured {entities, relationships, chunks, references}
    dict from a tool result, regardless of whether it's wrapped under
    ``{content: json_str, ...}`` (kg_query) or ``{data: {...}}``."""
    if not isinstance(result, dict):
        return None
    # _kg_query wraps under "content" as JSON str
    content = result.get("content")
    if isinstance(content, str) and content.startswith("{"):
        try:
            import json
            parsed = json.loads(content)
            d = parsed.get("data")
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    # Direct {data: {...}} path
    d = result.get("data")
    if isinstance(d, dict):
        return d
    return None


def _parse_time_window(time_range: Any) -> tuple[Optional[str], Optional[str]]:
    """Convert structured time_range ``{amount: N, unit: 'day'|'hour'|'week'|'month'}``
    to (start_iso, end_iso) in Asia/Shanghai timezone.

    Returns (None, None) when time_range is None, empty, or malformed
    (meaning the caller should apply no time filter).
    """
    from datetime import datetime, timedelta, timezone as dt_timezone

    if not isinstance(time_range, dict):
        return (None, None)

    amount = time_range.get("amount", 0)
    unit = time_range.get("unit", "day")
    if not amount or amount <= 0:
        return (None, None)

    unit_map = {
        "hour": timedelta(hours=1),
        "day": timedelta(days=1),
        "week": timedelta(weeks=1),
        "month": timedelta(days=30),
    }
    delta = unit_map.get(unit)
    if delta is None:
        return (None, None)

    now = datetime.now(dt_timezone(timedelta(hours=8)))
    start = (now - delta * amount).isoformat()
    end = now.isoformat()
    return (start, end)


class Orchestrator:
    """
    Agent大脑，协调LLM + Pipeline + 知识图谱

    职责：
    1. LLM意图理解 + 工具调用
    2. 执行工具获取线索
    3. 生成自然语言回复
    4. 通过SSE推送进度
    """

    def __init__(self, config: dict = None):
        self.config = config or get_config()

        from models.clients.llm import LLMClient
        self.llm = LLMClient(timeout=60)
        # Backward-compat alias for any code that still references these names
        self.llm_client = self.llm  # legacy attribute (used to be AsyncOpenAI)
        self.model = self.llm.providers[0]["model"] if self.llm.providers else None

        self.db = PostgreSQLService.get_instance()

    async def process_query(
        self,
        query_id: str,
        query_text: str,
        context: list[dict] = None,  # 多轮对话历史
        realtime_fetch: bool = False,
        channels: list[str] = None,
        time_range: dict = None,
        risk_types: list[str] = None,
        platforms: list[str] = None
    ) -> None:
        """
        处理用户查询，流式产出SSE事件

        Args:
            query_id: 查询任务ID
            query_text: 用户查询文本
            context: 对话历史（[{role, content}]）
            realtime_fetch: 是否实时采集
            channels: 目标渠道
            time_range: 时间范围
            risk_types: 风险类型
            platforms: 目标平台

        Yields:
            SSE事件 dict
        """
        context = context or []

        await self._stream_progress(query_id, "parsing", "正在理解用户意图...", 10)

        # ============================
        # Phase 0: Skill 选择（Hybrid 关键词 + LLM confirm）
        # ============================
        await self._stream_progress(query_id, "skill_selecting", "正在分析意图…选择 Skill", None, data={
            "stage": "analyzing_intent",
            "candidates_count": 0,
        })

        candidates = match_skill_by_keywords(query_text)
        active_skill = None

        if candidates:
            await self._stream_progress(query_id, "skill_selecting", None, None, data={
                "stage": "candidates_found",
                "candidates_count": len(candidates),
                "candidates": [{"name": s.name, "description": s.description} for s in candidates[:3]],
            })

            # LLM confirm — 一次小调用确定最匹配的 Skill
            candidate_lines = "\n".join(
                f"- {s.name}: {s.description}" for s in candidates
            )
            try:
                confirm = await self.llm.chat_raw(messages=[{
                    "role": "user",
                    "content": (
                        f"用户问题：{query_text}\n\n"
                        f"候选 Skill：\n{candidate_lines}\n\n"
                        f"请从候选中选最匹配的一个，回 JSON："
                        f'{{"skill": "name_or_null", "reason": "..."}}\n'
                        f"规则：必须从候选中选一个（最接近的），"
                        f"除非所有候选都明显不相关才回 null。"
                    ),
                }], max_tokens=200, temperature=0.0,
                    response_format={"type": "json_object"})
                chosen = json.loads(confirm.choices[0].message.content)
                skill_name = chosen.get("skill")
                if skill_name and get_skill(skill_name):
                    active_skill = get_skill(skill_name)
            except Exception:
                pass  # fall through to baseline

        if active_skill:
            await self._stream_progress(query_id, "skill_selected", None, 15, data={
                "skill": active_skill.name,
                "description": active_skill.description,
            })
        else:
            await self._stream_progress(query_id, "skill_selected", None, 15, data={"skill": None})

        # ============================
        # 构建 messages + tools
        # ============================
        if active_skill:
            plan_str = "\n".join(
                f"{i+1}. {step}" for i, step in enumerate(active_skill.plan_template)
            )
            skill_body = get_skill_body(active_skill.name) or ""
            messages = [
                {"role": "system",
                 "content": SYSTEM_PROMPT + "\n\n# 当前激活的 Skill\n" + skill_body},
                {"role": "user",
                 "content": (
                     f"我的计划：\n{plan_str}\n\n"
                     f"请按上述计划逐步执行。先完成步骤 1，"
                     f"根据结果决定步骤 2 是否继续。\n\n"
                     f"用户问题：{query_text}"
                 )},
            ]
            # Plan stepper
            await self._stream_progress(query_id, "plan", None, 20, data={
                "skill": active_skill.name,
                "steps": active_skill.plan_template,
            })
            # Add conversation history (future: multi-turn support)
            for msg in context:
                messages.append({"role": msg.get("role", "user"),
                                 "content": msg.get("content", "")})
            tools_for_llm = get_tools_by_names(active_skill.tools)
        else:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query_text},
            ]
            # Add conversation history if any
            for msg in context:
                messages.append({"role": msg.get("role", "user"),
                                 "content": msg.get("content", "")})
            tools_for_llm = TOOLS

        # LLM 对话循环（支持工具调用）
        assistant_message = None
        tool_calls_executed = []
        recent_signatures: list[tuple[str, str]] = []  # 防止重复调用
        MAX_TOOL_ITERATIONS = 3
        DEDUP_WINDOW = 2  # 最近 2 步内若已调过相同 (tool, args) 则跳过

        iteration = 0
        while True:
            try:
                iteration += 1

                # === 推 SSE: thinking（开始） ===
                thinking_start = _time.time()
                await self._stream_progress(query_id, "thinking", None, None, data={
                    "iteration": iteration,
                    "status": "started",
                })

                # 调用 unified LLM client (带工具;多 provider fallback 链)
                response = await self.llm.chat_raw(
                    messages=messages,
                    tools=tools_for_llm,
                    tool_choice="auto",
                    max_tokens=2048,
                    temperature=0.3,
                    extra_body={"reasoning_effort": "low"},
                )

                # === 推 SSE: thinking（完成） ===
                thinking_elapsed = int((_time.time() - thinking_start) * 1000)
                await self._stream_progress(query_id, "thinking", None, None, data={
                    "iteration": iteration,
                    "status": "completed",
                    "elapsed_ms": thinking_elapsed,
                })

                choice = response.choices[0]
                finish_reason = choice.finish_reason

                # 获取 assistant 消息
                assistant_message = choice.message
                messages.append(assistant_message)

                # 检查是否需要调用工具（finish_reason 为 tool_calls 或消息有 tool_calls）
                needs_tool_call = finish_reason == "tool_calls" or (
                    hasattr(assistant_message, 'tool_calls') and assistant_message.tool_calls
                )

                if needs_tool_call and hasattr(assistant_message, 'tool_calls') and assistant_message.tool_calls:
                    # Loop guard: hit iteration cap → nudge LLM to summarize
                    if len(recent_signatures) >= MAX_TOOL_ITERATIONS:
                        messages.append({
                            "role": "user",
                            "content": "[系统] 工具调用已达上限，请基于已有结果直接生成最终报告，不要再调用工具。"
                        })
                        continue

                    # 并行执行工具调用
                    # 收集所有非重复的 tool calls
                    pending_calls = []  # list of (tool_call, tool_name, tool_args)
                    for tool_call in assistant_message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)
                        sig = (tool_name, json.dumps(tool_args, sort_keys=True, ensure_ascii=False))

                        # Dedup: skip if same (tool, args) was called in the last DEDUP_WINDOW steps
                        if sig in recent_signatures[-DEDUP_WINDOW:]:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": json.dumps(
                                    {"skipped": True, "reason": "duplicate_call"},
                                    ensure_ascii=False
                                )
                            })
                            continue

                        recent_signatures.append(sig)
                        pending_calls.append((tool_call, tool_name, tool_args))

                    if pending_calls:
                        # 并行发起所有工具调用 — 每个 tool 有独立的 progress 事件
                        async def _run_one_with_progress(tc, tn, ta, qid, step_index):
                            start = _time.time()
                            # === 推 SSE: tool_started ===
                            await self._stream_progress(qid, "tool_started", None, None, data={
                                "tool_name": tn,
                                "iteration": step_index,
                                "status": "running",
                            })
                            try:
                                result = await invoke_tool(tn, self, **ta)
                                elapsed_ms = int((_time.time() - start) * 1000)
                                # === 推 SSE: tool_completed ===
                                await self._stream_progress(qid, "tool_completed", None, None, data={
                                    "tool_name": tn,
                                    "iteration": step_index,
                                    "status": "done",
                                    "result_count": _count_tool_result(result),
                                    "elapsed_ms": elapsed_ms,
                                })
                                return (tc.id, tn, result)
                            except Exception as e:
                                await self._stream_progress(qid, "tool_failed", None, None, data={
                                    "tool_name": tn,
                                    "iteration": step_index,
                                    "status": "failed",
                                    "error": str(e),
                                })
                                return (tc.id, tn, {"error": str(e)})

                        tasks = [_run_one_with_progress(tc, tn, ta, query_id, iteration)
                                 for tc, tn, ta in pending_calls]

                        # 逐条处理完成的结果（as_completed 按完成顺序 yield）
                        for coro in asyncio.as_completed(tasks):
                            tc_id, tn, result = await coro

                            # 将工具结果添加回消息
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": json.dumps(result, ensure_ascii=False, default=str)
                            })
                            tool_calls_executed.append({
                                "name": tn,
                                "result": result,
                                "result_count": _count_tool_result(result),
                            })

                            summary = _format_tool_result_summary(result)
                            await self._stream_progress(query_id, "retrieved", f"工具执行完成，{summary}", 50, tool_name=tn)

                    # 所有工具全部完成 → 让 LLM 思考下一步
                    continue

                elif finish_reason == "stop" or finish_reason == "completed":
                    # LLM 完成，生成最终回复
                    response_text = assistant_message.content or ""

                    # 提取 thinking tags 内容
                    thinking_matches = re.findall(r'<think>(.*?)</think>', response_text, re.DOTALL)
                    thinking_content = "\n".join(thinking_matches).strip() if thinking_matches else ""

                    # 去除 thinking tags
                    response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()

                    if not response_text:
                        response_text = "处理完成，未生成有效回复。"

                    await self._stream_progress(query_id, "analyzing", "正在生成分析报告...", 60)

                    # 如果有 thinking 内容，先发送推理过程
                    if thinking_content:
                        await self._stream_progress(query_id, "reasoning", thinking_content, None)

                    # 流式输出 LLM 生成的文本
                    for chunk in self._chunk_text(response_text):
                        await self._stream_progress(query_id, "content", chunk, None)
                        await asyncio.sleep(0.05)

                    # 如果有工具调用结果，输出线索列表
                    if tool_calls_executed:
                        try:
                            last_tool = tool_calls_executed[-1]
                            last_result = last_tool.get("result", [])
                        except (IndexError, AttributeError):
                            last_result = None

                        if last_result and isinstance(last_result, list):
                            await self._stream_progress(query_id, "results", f"共找到 {len(last_result)} 条相关线索", 90)
                            clue_summary = self._format_clues_for_display(last_result)
                            await self._stream_progress(query_id, "clue_list", None, None, data=clue_summary)

                    # 完成
                    await self._stream_progress(query_id, "complete", "查询完成", 100)
                    break

                else:
                    # 未知 finish_reason，尝试获取内容
                    response_text = assistant_message.content or "处理完成。"
                    for chunk in self._chunk_text(response_text):
                        await self._stream_progress(query_id, "content", chunk, None)
                        await asyncio.sleep(0.05)
                    await self._stream_progress(query_id, "complete", "查询完成", 100)
                    break

            except Exception as e:
                error_msg = f"处理失败: {str(e)}"
                print(f"Orchestrator error: {e}")
                await self._stream_progress(query_id, "error", error_msg, None)
                break

    # DEPRECATED: replaced by invoke_tool() from agent.tools.registry. Keep for backward compat (remove in Phase 5).
    async def _execute_tool(self, tool_name: str, tool_args: dict) -> any:
        """执行工具调用"""
        if tool_name == "search_clues":
            return await self._search_clues(
                query=tool_args.get("query", ""),
                time_range=tool_args.get("time_range"),
                risk_types=tool_args.get("risk_types"),
                platforms=tool_args.get("platforms"),
                entity_types=tool_args.get("entity_types"),
                limit=tool_args.get("limit", 50)
            )
        elif tool_name == "kg_query":
            return await self._kg_query(
                query=tool_args.get("query", ""),
                mode=tool_args.get("mode", "hybrid"),
                limit=tool_args.get("limit", 10)
            )
        elif tool_name == "search_entities":
            return await self._search_entities(
                entity_name=tool_args.get("entity_name", ""),
                entity_type=tool_args.get("entity_type"),
                limit=tool_args.get("limit", 20)
            )
        elif tool_name == "get_clue_detail":
            return await self._get_clue_detail(
                clue_id=tool_args.get("clue_id", "")
            )
        elif tool_name == "get_recent_clues":
            return await self._get_recent_clues(
                hours=tool_args.get("hours", 24),
                risk_label_level1=tool_args.get("risk_label_level1"),
                platform=tool_args.get("platform"),
                limit=tool_args.get("limit", 20)
            )
        elif tool_name == "search_slang":
            return await self._search_slang(
                slang_term=tool_args.get("slang_term", ""),
                limit=tool_args.get("limit", 20)
            )
        elif tool_name == "aggregate_clue_stats":
            return await self._aggregate_clue_stats(
                time_range=tool_args.get("time_range", "today"),
                group_by=tool_args.get("group_by", "risk_platform"),
                risk_types=tool_args.get("risk_types"),
                platforms=tool_args.get("platforms"),
            )
        elif tool_name == "get_actor_footprint":
            return await self._get_actor_footprint(
                entity_value=tool_args.get("entity_value", ""),
                entity_type=tool_args.get("entity_type"),
                limit=tool_args.get("limit", 50)
            )
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _search_clues(
        self,
        query: str = "",
        time_range: dict = None,
        risk_types: list = None,
        platforms: list = None,
        entity_types: list = None,
        limit: int = 50
    ) -> list[dict]:
        """搜索线索的工具实现"""
        from utils import parse_platform, parse_risk_type

        where_clauses = []
        params: dict = {}

        # query: keyword search against clue text. Split on whitespace and
        # match each token independently (OR-of-ILIKE) so multi-keyword
        # queries like '微信号 诈骗' don't require a single record to
        # contain ALL tokens in literal order. A record matches if it
        # contains ANY of the tokens.
        #
        # Cap token count at MAX_QUERY_TOKENS to bound the SQL array size —
        # a query with 1000 whitespace-separated words would issue
        # `ILIKE ANY(<1000 patterns>)` against 110K+ rows, a DoS.
        # _search_slang uses an analogous cap of [:8] for the same reason.
        MAX_QUERY_TOKENS = 8
        if query and query.strip():
            tokens = query.split()[:MAX_QUERY_TOKENS]
            tokens = _expand_query_synonyms(tokens)[:MAX_QUERY_TOKENS]
            patterns = [f"%{t}%" for t in tokens]
            where_clauses.append(
                "(raw_text ILIKE ANY(%(query_pats)s) OR cleaned_text ILIKE ANY(%(query_pats)s))"
            )
            params["query_pats"] = patterns

        # time_range: structured {amount, unit} dict from LLM
        if time_range:
            start_time, end_time = _parse_time_window(time_range)
            if start_time:
                where_clauses.append("published_at >= %(start_time)s")
                params["start_time"] = start_time
            if end_time:
                where_clauses.append("published_at <= %(end_time)s")
                params["end_time"] = end_time

        # 解析 risk_types（支持多值，英文→DB 中文映射）
        if risk_types and isinstance(risk_types, list):
            _risk_type_map = {
                "account_trading": "账号交易",
                "fraud_leads": "诈骗引流",
                "traffic_cheating": "流量作弊",
                "black_tools": "黑产工具",
                "money_laundering": "灰产洗钱",
                "unknown": "未知/其他",
                "irrelevant": "无关",
            }
            mapped_risks = []
            for rt in risk_types:
                mapped_risks.append(_risk_type_map.get(rt, rt))
            mapped_risks = [r for r in mapped_risks if r]
            if mapped_risks:
                where_clauses.append("risk_label_level1 = ANY(%(risk_types)s)")
                params["risk_types"] = mapped_risks

        # 解析 platforms（支持多值，做中文→DB 名映射）
        if platforms and isinstance(platforms, list):
            platform_map = {
                "抖音": "douyin",
                "贴吧": "baidu_tieba",
                "微博": "weibo",
                "小红书": "xiaohongshu",
                "快手": "kuaishou",
                "Telegram": "telegram",
            }
            mapped = []
            for p in platforms:
                if p in platform_map:
                    mapped.append(platform_map[p])
                else:
                    mapped.append(p)
            if mapped:
                where_clauses.append("source_channel = ANY(%(platforms)s)")
                params["platforms"] = mapped

        # entity_types: 强信号实体类型过滤（JSONB @> 走 GIN 索引）
        # 把 LLM 传的 ['WECHAT', 'PHONE'] 转成 [ '[{"entity_type":"WECHAT"}]',
        # '[{"entity_type":"PHONE"}]' ] 的 JSON 字符串数组，匹配 entity_list 列
        # 中至少包含其中一个 JSON object 的记录。
        # Guard against (a) non-string entries (LLM schema drift), (b) values
        # containing JSON-breaking chars ('"' '\' newline), and (c) values
        # that aren't legal entity_type enum tokens. Without these guards a
        # single bad token breaks the whole query (PG throws invalid json on
        # parse, returns 500 to the agent).
        if entity_types and isinstance(entity_types, list):
            entity_type_filter = []
            for et in entity_types:
                if not isinstance(et, str) or not et:
                    logger.warning(f"[search_clues] entity_types non-string/empty: {et!r}; skipping")
                    continue
                if not et.replace("_", "").isalnum() or not et.isupper():
                    logger.warning(f"[search_clues] entity_types not a valid enum token: {et!r}; skipping")
                    continue
                entity_type_filter.append(json.dumps([{"entity_type": et}]))
            if entity_type_filter:
                where_clauses.append("entity_list @> ANY(%(entity_types_filter)s::jsonb[])")
                params["entity_types_filter"] = entity_type_filter

        # 默认排除 e2e 测试数据
        where_clauses.append("source_channel IS NOT NULL AND source_channel != '' AND source_channel != 'e2e'")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        params["limit"] = limit

        # Log what the LLM sent and the generated SQL (INFO so it's visible
        # at default level — DEBUG would be filtered out by uvicorn defaults).
        logger.info(
            f"[search_clues] LLM sent: query={query!r} time_range={time_range!r} "
            f"risk_types={risk_types!r} platforms={platforms!r} entity_types={entity_types!r}"
        )
        # log params excluding the bulky pattern lists (just show count for transparency)
        log_params = {k: v for k, v in params.items() if k not in ("query_pat", "query_pats", "entity_types_filter")}
        log_params["query_pats"] = f"<{len(params.get('query_pats', []))} patterns>"
        log_params["entity_types_filter"] = f"<{len(params.get('entity_types_filter', []))} filters>"
        logger.info(f"[search_clues] SQL: WHERE {where_sql} | params={log_params}")

        with self.db._get_cursor() as cur:
            cur.execute(f"""
                SELECT clue_id, risk_label_level1, risk_label_level2, confidence,
                       raw_text, cleaned_text, source_channel, published_at,
                       entity_list, slang_mappings, classification_reason
                FROM antiblack.clues
                WHERE {where_sql}
                ORDER BY published_at DESC
                LIMIT %(limit)s
            """, params)

            rows = cur.fetchall()
            logger.info(f"[search_clues] SQL returned {len(rows)} rows (LIMIT {limit})")
            result = [dict(row) for row in rows]

            # JSON 序列化前处理 datetime
            def handle_datetime(obj):
                if hasattr(obj, 'isoformat'):
                    return obj.isoformat()
                elif isinstance(obj, dict):
                    return {k: handle_datetime(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [handle_datetime(i) for i in obj]
                return obj

            return handle_datetime(result)

    async def _kg_query(
        self,
        query: str = "",
        mode: str = "hybrid",
        limit: int = 10
    ) -> dict:
        """知识图谱查询工具实现。

        LightRAG 是一个非常重的对象（Neo4j + PG + Ollama 嵌入 + 大量内存），
        每次工具调用都构造会浪费资源。改用 lightrag_service 的进程内
        singleton，第一次访问时初始化，后续直接复用。
        """
        from services.lightrag_service import get_lightrag_integrator

        try:
            config = self.config or get_config()
            integrator = await get_lightrag_integrator(config._config)

            result = await integrator.query(query, mode=mode, top_k=limit)

            # result is always a dict (status / data / metadata / ...).
            # Serialise as compact JSON so the orchestrator LLM receives
            # a structured payload it can cite entities/relations by name.
            return {
                "content": json.dumps(result, ensure_ascii=False, default=str),
                "query": query,
                "mode": mode,
            }
        except Exception as e:
            return {"error": f"知识图谱查询失败: {str(e)}", "query": query}

    async def _search_entities(
        self,
        entity_name: str = "",
        entity_type: str = None,
        limit: int = 20
    ) -> list[dict]:
        """搜索实体工具实现"""
        with self.db._get_cursor() as cur:
            where_clauses = ["1=1"]
            values = []

            if entity_name:
                # entity_name is often NULL in this table; fall back to
                # raw_value + normalized_value to make search useful.
                where_clauses.append(
                    "(entity_name ILIKE %s OR raw_value ILIKE %s OR normalized_value ILIKE %s)"
                )
                like_pat = f"%{entity_name}%"
                values.extend([like_pat, like_pat, like_pat])

            if entity_type:
                where_clauses.append("entity_type = %s")
                values.append(entity_type)

            where_sql = " AND ".join(where_clauses)

            cur.execute(f"""
                SELECT entity_id, entity_name, entity_type, raw_value,
                       description, source_channel, first_seen, last_seen
                FROM antiblack.entities
                WHERE {where_sql}
                ORDER BY occurrence_count DESC NULLS LAST, last_seen DESC NULLS LAST
                LIMIT %s
            """, values + [limit])

            rows = cur.fetchall()
            result = [dict(row) for row in rows]

            def handle_datetime(obj):
                if hasattr(obj, 'isoformat'):
                    return obj.isoformat()
                elif isinstance(obj, dict):
                    return {k: handle_datetime(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [handle_datetime(i) for i in obj]
                return obj

            return handle_datetime(result)

    async def _get_clue_detail(
        self,
        clue_id: str = ""
    ) -> dict:
        """获取线索详情工具实现"""
        if not clue_id:
            return {"error": "clue_id is required"}

        with self.db._get_cursor() as cur:
            cur.execute("""
                SELECT clue_id, risk_label_level1, risk_label_level2, confidence,
                       raw_text, cleaned_text, source_channel, published_at,
                       entity_list, slang_mappings, classification_reason,
                       graph_relations
                FROM antiblack.clues
                WHERE clue_id = %s
            """, (clue_id,))

            row = cur.fetchone()
            if not row:
                return {"error": f"Clue not found: {clue_id}"}

            result = dict(row)

            def handle_datetime(obj):
                if hasattr(obj, 'isoformat'):
                    return obj.isoformat()
                elif isinstance(obj, dict):
                    return {k: handle_datetime(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [handle_datetime(i) for i in obj]
                return obj

            return handle_datetime(result)

    async def _get_recent_clues(
        self,
        hours: int = 24,
        risk_label_level1: str = None,
        platform: str = None,
        limit: int = 20
    ) -> list[dict]:
        """按时间窗口检索最新线索。"""
        from datetime import datetime, timedelta, timezone

        conditions = ["created_at > NOW() - (%(hours)s || ' hours')::INTERVAL"]
        params = {"hours": str(hours), "limit": limit}

        # Exclude e2e + orphans by default (mirror get_clues default)
        conditions.append("source_channel IS NOT NULL AND source_channel != '' AND source_channel != 'e2e'")

        if risk_label_level1:
            conditions.append("risk_label_level1 = %(risk_label_level1)s")
            params["risk_label_level1"] = risk_label_level1
        if platform:
            conditions.append("source_channel = %(platform)s")
            params["platform"] = platform

        where_clause = " AND ".join(conditions)

        with self.db._get_cursor() as cur:
            cur.execute(f"""
                SELECT clue_id, risk_label_level1, risk_label_level2, confidence,
                       raw_text, cleaned_text, source_channel, published_at
                FROM antiblack.clues
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT %(limit)s
            """, params)
            rows = cur.fetchall()

        return [dict(r) for r in rows]

    async def _aggregate_clue_stats(
        self,
        time_range: dict = None,
        group_by: str = "risk_platform",
        risk_types: list = None,
        platforms: list = None,
    ) -> dict:
        """线索聚合统计工具实现。

        将计算下推给 DB（SQL GROUP BY），避免 LLM 从 search_clues 抽样来推算趋势。
        支持 110K+ 条历史数据的多维度聚合。
        time_range: structured {amount, unit} dict from LLM.
        """
        group_dimensions = {
            "risk_type": ["risk_label_level1"],
            "platform": ["source_channel"],
            "channel": ["source_channel"],        # alias for platform
            "risk_platform": ["risk_label_level1", "source_channel"],
        }
        group_cols = group_dimensions.get(group_by, group_dimensions["risk_platform"])
        group_sql = ", ".join(group_cols)

        conditions = []
        params = {}

        # Exclude e2e test data
        conditions.append("source_channel IS NOT NULL AND source_channel != '' AND source_channel != 'e2e'")

        if time_range:
            start_time, end_time = _parse_time_window(time_range)
            if start_time:
                conditions.append("created_at >= %(start_time)s")
                params["start_time"] = start_time
            if end_time:
                conditions.append("created_at <= %(end_time)s")
                params["end_time"] = end_time

        if risk_types and isinstance(risk_types, list):
            _risk_type_map = {
                "account_trading": "账号交易",
                "fraud_leads": "诈骗引流",
                "traffic_cheating": "流量作弊",
                "black_tools": "黑产工具",
                "money_laundering": "灰产洗钱",
                "unknown": "未知/其他",
                "irrelevant": "无关",
            }
            mapped_risks = []
            for rt in risk_types:
                mapped_risks.append(_risk_type_map.get(rt, rt))
            mapped_risks = [r for r in mapped_risks if r]
            if mapped_risks:
                conditions.append("risk_label_level1 = ANY(%(risk_types)s)")
                params["risk_types"] = mapped_risks

        if platforms and isinstance(platforms, list):
            conditions.append("source_channel = ANY(%(platforms)s)")
            params["platforms"] = platforms

        where_clause = " AND ".join(conditions)

        with self.db._get_cursor() as cur:
            cur.execute(f"""
                SELECT {group_sql}, COUNT(*) AS cnt
                FROM antiblack.clues
                WHERE {where_clause}
                GROUP BY {group_sql}
                ORDER BY cnt DESC
            """, params)
            rows = cur.fetchall()

        # Build structured response for distinct dimensions
        distributions = {}
        for col in group_cols:
            dist = {}
            for row in rows:
                val = row.get(col)
                if val:
                    dist[val] = dist.get(val, 0) + row["cnt"]
            distributions[col] = {"items": dist, "total": sum(dist.values())}

        return {
            "data": distributions,
            "group_by": group_by,
            "total_clues": sum(r["cnt"] for r in rows),
            "time_range": time_range,
        }

    async def _get_actor_footprint(
        self,
        entity_value: str = "",
        entity_type: str = None,
        limit: int = 50
    ) -> dict:
        """实体活动轨迹时间线工具实现。

        跨 clues + entities 表聚合，返回该实体的完整活动画像：
        - 活动时间线（按日/按渠道分组）
        - 风险标签变化
        - 关联线索摘要
        """
        if not entity_value:
            return {"error": "entity_value is required"}

        from datetime import datetime

        result = {
            "entity_value": entity_value,
            "entity_type": entity_type or "auto",
            "timeline": [],
            "risk_history": {},
            "channel_activity": {},
            "recent_clues": [],
            "summary": {},
        }

        # 1. Active timeline: clues by this actor, grouped by date + channel
        with self.db._get_cursor() as cur:
            cur.execute("""
                SELECT DATE(published_at) AS activity_date,
                       source_channel,
                       risk_label_level1,
                       COUNT(*) AS cnt
                FROM antiblack.clues
                WHERE source_author_id = %(entity_value)s
                   OR source_author_id ILIKE %(like_val)s
                GROUP BY activity_date, source_channel, risk_label_level1
                ORDER BY activity_date DESC
                LIMIT 200
            """, {"entity_value": entity_value, "like_val": f"%{entity_value}%"})
            timeline_rows = cur.fetchall()

        # Group by date + channel
        daily = {}
        channel_set = set()
        for row in timeline_rows:
            day = str(row["activity_date"]) if row["activity_date"] else "unknown"
            ch = row["source_channel"] or "unknown"
            risk = row["risk_label_level1"] or "unknown"
            cnt = row["cnt"]
            channel_set.add(ch)

            key = f"{day}|{ch}"
            if key not in daily:
                daily[key] = {"date": day, "channel": ch, "total": 0, "risk_labels": {}}
            daily[key]["total"] += cnt
            daily[key]["risk_labels"][risk] = daily[key]["risk_labels"].get(risk, 0) + cnt

        result["timeline"] = sorted(daily.values(), key=lambda x: x["date"], reverse=True)[:90]
        result["channel_activity"] = {ch: len([t for t in result["timeline"] if t["channel"] == ch]) for ch in sorted(channel_set)}

        # 2. Risk distribution across all clues for this actor
        with self.db._get_cursor() as cur:
            cur.execute("""
                SELECT risk_label_level1, COUNT(*) AS cnt
                FROM antiblack.clues
                WHERE source_author_id = %(entity_value)s
                   OR source_author_id ILIKE %(like_val)s
                GROUP BY risk_label_level1
                ORDER BY cnt DESC
            """, {"entity_value": entity_value, "like_val": f"%{entity_value}%"})
            result["risk_history"] = [dict(r) for r in cur.fetchall()]

        # 3. Recent clues (top N)
        with self.db._get_cursor() as cur:
            cur.execute("""
                SELECT clue_id, risk_label_level1, risk_label_level2,
                       raw_text, source_channel, published_at
                FROM antiblack.clues
                WHERE source_author_id = %(entity_value)s
                   OR source_author_id ILIKE %(like_val)s
                ORDER BY published_at DESC NULLS LAST
                LIMIT %(limit)s
            """, {"entity_value": entity_value, "like_val": f"%{entity_value}%", "limit": limit})
            rows = cur.fetchall()
            result["recent_clues"] = [dict(r) for r in rows]

        # 4. Entity record from entities table
        with self.db._get_cursor() as cur:
            entity_where = ["raw_value ILIKE %(like_val)s OR entity_name ILIKE %(like_val)s"]
            entity_params: dict = {"like_val": f"%{entity_value}%"}
            if entity_type:
                entity_where.append("entity_type = %(entity_type)s")
                entity_params["entity_type"] = entity_type
            cur.execute(f"""
                SELECT raw_value, entity_type, first_seen, last_seen,
                       occurrence_count, source_channel
                FROM antiblack.entities
                WHERE {" AND ".join(entity_where)}
                ORDER BY occurrence_count DESC NULLS LAST
                LIMIT 10
            """, entity_params)
            entity_rows = cur.fetchall()

        result["entity_records"] = [dict(r) for r in entity_rows]

        # 5. Summary
        total_clues = sum(r["cnt"] for r in result.get("risk_history", []))
        first_date = result["timeline"][-1]["date"] if result["timeline"] else None
        last_date = result["timeline"][0]["date"] if result["timeline"] else None
        result["summary"] = {
            "total_clues_found": total_clues,
            "first_active": first_date,
            "last_active": last_date,
            "channels": list(sorted(channel_set)),
            "entity_records_found": len(entity_rows),
        }

        # Datetime serialization
        def _handle_dt(obj):
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: _handle_dt(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_handle_dt(i) for i in obj]
            return obj

        return _handle_dt(result)

    async def _search_slang(
        self,
        slang_term: str = "",
        limit: int = 20
    ) -> list[dict]:
        """在 slang_mappings 表里按 slang_raw 或 meaning 模糊匹配。

        Schema: mapping_id, slang_raw, meaning, regex_pattern, source,
        verified, confidence, created_at, updated_at.

        LLM 通常会把整句查询塞进 slang_term（如"近三天涉及微信号的诈骗引流"），
        所以我们按空格/标点拆成短词，构造 OR 条件匹配，提高召回率。
        """
        if not slang_term:
            return []

        # Extract short keywords from the slang_term.
        # LLM often passes the full query (e.g. "近三天涉及微信号的诈骗引流"),
        # so we slide a 2-char window over the Chinese characters to capture
        # meaningful fragments like "微信", "诈骗", "引流" etc.
        import re as _re
        # 1) Extract all CJK runs from the input
        cjk_runs = _re.findall(r'[一-鿿]+', slang_term)
        raw = "".join(cjk_runs)

        words = set()
        # 2-gram sliding window over CJK text
        for i in range(len(raw) - 1):
            bigram = raw[i:i + 2]
            if bigram.strip():
                words.add(bigram)
        # Also keep any 3+ char runs that contain no CJK (numbers, ASCII, etc.)
        for token in _re.split(r'[\s,，。；;：:!！?？、/\\]+', slang_term):
            cleaned = token.strip()
            if cleaned and not any('一' <= c <= '鿿' for c in cleaned) and len(cleaned) >= 2:
                words.add(cleaned)

        # Limit to at most 8 keywords (safety cap)
        words = sorted(words)[:8]

        if not words:
            # No valid keywords after split — fall back to the raw term
            words = [slang_term]

        # Build OR conditions — each word matches slang_raw or meaning
        conditions = []
        params: dict = {}
        for i, w in enumerate(words):
            key = f"p{i}"
            conditions.append(f"(slang_raw ILIKE %({key})s OR meaning ILIKE %({key})s)")
            params[key] = f"%{w}%"

        where_clause = " OR ".join(conditions)
        params["limit"] = limit

        with self.db._get_cursor() as cur:
            cur.execute(f"""
                SELECT slang_raw, meaning, verified, confidence, source,
                       created_at, updated_at
                FROM antiblack.slang_mappings
                WHERE {where_clause}
                ORDER BY verified DESC, confidence DESC NULLS LAST,
                         updated_at DESC NULLS LAST
                LIMIT %(limit)s
            """, params)
            rows = cur.fetchall()

        result = []
        for r in rows:
            d = dict(r)
            for k in ("created_at", "updated_at"):
                if d.get(k) and hasattr(d[k], "isoformat"):
                    d[k] = d[k].isoformat()
            result.append(d)
        return result

    async def _stream_progress(
        self,
        query_id: str,
        stage: str,
        content: str = None,
        progress: int = None,
        data: dict = None,
        tool_name: str = None
    ):
        """推送SSE进度事件"""
        event = {
            "type": stage if stage in ("content", "complete") else "stage",
            "stage": stage,
            "content": content,
        }
        if progress is not None:
            event["progress"] = progress
        if data is not None:
            event["data"] = data
        if tool_name is not None:
            event["tool_name"] = tool_name

        put_progress(query_id, event)

    def _chunk_text(self, text: str, chunk_size: int = 200) -> list[str]:
        """按逻辑行切分文本并合并为 chunk，保留所有换行符和空格。

        防止 Markdown 渲染（表格、列表、代码块）在 SSE 流式传输中因
        丢失 `\\n` 而崩溃。早期版本用 `.strip()` / `.rstrip()` 在 chunk
        边界删掉 trailing newline，导致 GFM 表格行被挤成一行、列表项
        黏在一起、标题和段落混成一段。

        策略：
        1. `splitlines(keepends=True)` —— 每个 line 自带尾部 `\\n`，
           完美保留 LLM 的 intentional whitespace（含嵌套列表的 2 空格
           缩进、表格分隔行等）
        2. 贪心 pack 整行进 window —— 绝不在 line 中间断，保证 `\\n`
           分隔符完整
        3. `chunk_size=200`（默认从 50 提升）—— 一个典型表格行 /
           段落能装下，减少 SSE 事件数同时保留流式观感
        4. **完全无 `strip()` / `rstrip()`** —— LLM 输出的 whitespace
           是 markdown 的一部分
        """
        if not text:
            return []

        lines = text.splitlines(keepends=True)
        chunks = []
        current_chunk = ""

        for line in lines:
            if len(current_chunk) + len(line) > chunk_size and current_chunk:
                chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk += line

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _format_clues_for_display(self, clues: list[dict]) -> dict:
        """将线索格式化为前端展示格式"""
        items = []
        for clue in clues[:20]:  # 最多20条
            published_at = clue.get("published_at")
            if hasattr(published_at, 'isoformat'):
                published_at = published_at.isoformat()
            elif published_at and not isinstance(published_at, str):
                published_at = str(published_at)
            else:
                published_at = None

            entity_list = clue.get("entity_list") or []
            if entity_list and not isinstance(entity_list, list):
                entity_list = []

            items.append({
                "clue_id": clue.get("clue_id"),
                "risk_label_level1": clue.get("risk_label_level1"),
                "risk_label_level2": clue.get("risk_label_level2"),
                "confidence": float(clue.get("confidence", 0)) if clue.get("confidence") else 0,
                "raw_text": str(clue.get("raw_text", ""))[:100],
                "cleaned_text": str(clue.get("cleaned_text", "")),
                "source_channel": clue.get("source_channel"),
                "published_at": published_at,
                "entity_list": entity_list,
                "slang_mappings": clue.get("slang_mappings") or []
            })

        return {
            "items": items,
            "total": len(clues)
        }