"""
Orchestrator Agent - 主控Agent大脑
负责自然语言理解、任务编排、SSE进度推送、LLM响应生成
"""
import os
import json
import logging
import re
import asyncio
from typing import Any, Optional

from openai import AsyncOpenAI

from api.routes.queries import put_progress
from services.database import PostgreSQLService
from config import get_config

logger = logging.getLogger(__name__)


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
                        "description": "Keyword(s) to match against clue text, e.g. account_trading, Douyin_username, WeChat"
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

SYSTEM_PROMPT = """You are a black-market intelligence analysis agent. Follow the search → drill → aggregate workflow to answer user queries.

## Tool Guide

### L1 — SEARCH (broad find)
- **search_clues**: for keyword/risk/time/platform-based clue search. Returns a list of summaries.
- **get_recent_clues**: simpler time-window variant. Use when query is about 'last N hours'.
- **search_entities**: find specific entity nodes (WeChat IDs, phones, accounts) by name or type.
- **search_slang**: look up slang dictionary. Use when user asks what a term means or wants recent slang.

### L2 — DRILL (deepen one result)
- **get_clue_detail**: fetch full content for a single clue_id (raw text, entities, slang).
- **kg_query**: knowledge-graph structured retrieval (entities/relations/chunks). Raw data, no LLM summarization.

### L3 — AGGREGATE (patterns & profiles)
- **aggregate_clue_stats**: SQL GROUP BY over 110K+ clues. Use for trends, distributions, top-N today, growth rates. NEVER guess trends from search_clues samples — call this instead.
- **get_actor_footprint**: entity activity timeline across platforms. Use for 'what else did this account do'.

## Workflow
1. Start with L1 to locate relevant data
2. If more detail is needed on a specific finding, call L2
3. If the query asks about trends/ranking/entity history, call L3

## Constraints
- Max 3 tool calls per query (system-enforced).
- Do NOT repeat the same (tool, args) — the system will skip duplicates.
- Each user-requested dimension MUST get its own tool call: slang → search_slang, relationship → kg_query, trend → aggregate_clue_stats. Do NOT substitute inline fields from search_clues results for dedicated tool calls.

## Report Structure (mix and match as needed)
Risk distribution | Platform breakdown | High-value entities | Key relationships | Trends | Slang glossary | Actor portrait.
Professional, concise tone."""


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

        # 构建消息历史
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        # 添加对话历史（如果有）
        for msg in context:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

        # 添加用户查询
        messages.append({"role": "user", "content": query_text})

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

                # 调用 unified LLM client (带工具;多 provider fallback 链)
                response = await self.llm.chat_raw(
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    max_tokens=2048,
                    temperature=0.3,
                    extra_body={"reasoning_effort": "low"},
                )

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
                        # 并行发起所有工具调用
                        async def _run_one(tc, tn, ta):
                            await self._stream_progress(query_id, "stage", f"正在调用 {tn}...", 30, tool_name=tn)
                            return tc, tn, ta, await self._execute_tool(tn, ta)

                        tasks = [_run_one(tc, tn, ta) for tc, tn, ta in pending_calls]

                        # 逐条处理完成的结果（as_completed 按完成顺序 yield）
                        for coro in asyncio.as_completed(tasks):
                            tc, tn, ta, result = await coro

                            # 将工具结果添加回消息
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps(result, ensure_ascii=False, default=str)
                            })
                            tool_calls_executed.append({
                                "name": tn,
                                "args": ta,
                                "result": result,
                                "result_count": _count_tool_result(result),
                            })

                            summary = _format_tool_result_summary(result)
                            await self._stream_progress(query_id, "retrieved", f"工具执行完成，{summary}", 50, tool_name=tn)

                    # 所有工俱全部完成 → 让 LLM 思考下一步
                    # （不额外发 SSE，工具结果已经在 retrieved 事件中显示）
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

    async def _execute_tool(self, tool_name: str, tool_args: dict) -> any:
        """执行工具调用"""
        if tool_name == "search_clues":
            return await self._search_clues(
                query=tool_args.get("query", ""),
                time_range=tool_args.get("time_range"),
                risk_types=tool_args.get("risk_types"),
                platforms=tool_args.get("platforms"),
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
        limit: int = 50
    ) -> list[dict]:
        """搜索线索的工具实现"""
        from utils import parse_platform, parse_risk_type

        where_clauses = []
        params: dict = {}

        # query: keyword search against clue text
        if query and query.strip():
            where_clauses.append(
                "(raw_text ILIKE %(query_pat)s OR cleaned_text ILIKE %(query_pat)s)"
            )
            params["query_pat"] = f"%{query.strip()}%"

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

        # 默认排除 e2e 测试数据
        where_clauses.append("source_channel IS NOT NULL AND source_channel != '' AND source_channel != 'e2e'")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        params["limit"] = limit

        # Debug: log what the LLM sent and the generated SQL
        logger.debug(
            f"[search_clues] LLM sent: query={query!r} time_range={time_range!r} "
            f"risk_types={risk_types!r} platforms={platforms!r}"
        )
        logger.debug(f"[search_clues] SQL: WHERE {where_sql} | params={ {k:v for k,v in params.items() if k != 'query_pat'} }")

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

    def _chunk_text(self, text: str, chunk_size: int = 50) -> list[str]:
        """将长文本分块，用于流式输出"""
        # 按句子或短语分块
        sentences = re.split(r'([。！？\n])', text)
        chunks = []
        current = ""

        for i in range(0, len(sentences) - 1, 2):
            sent = sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else "")
            if len(current) + len(sent) <= chunk_size:
                current += sent
            else:
                if current:
                    chunks.append(current.strip())
                current = sent

        if current.strip():
            chunks.append(current.strip())

        return chunks if chunks else [text]

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