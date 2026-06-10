"""
Orchestrator Agent - 主控Agent大脑
负责自然语言理解、任务编排、SSE进度推送、LLM响应生成
"""
import os
import json
import re
import asyncio
from typing import Optional

from openai import AsyncOpenAI

from api.routes.queries import put_progress
from services.database import PostgreSQLService
from config import get_config


# 工具定义
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_clues",
            "description": "按条件（关键词/风险类型/时间/平台）检索线索**列表**——适合『找一批』线索。不返回完整内容；想看单条请用 get_clue_detail。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如'账号买卖'、'抖音出号'等"
                    },
                    "time_range": {
                        "type": "string",
                        "description": "时间范围，如'近三天'、'近一周'、'近一个月'"
                    },
                    "risk_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "风险类型列表，可选：账号交易, 诈骗引流, 流量作弊, 黑产工具, 未知/其他"
                    },
                    "platforms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "平台列表，可选：抖音, 贴吧, Telegram, 论坛（不填则不限制平台）"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量限制，默认50条",
                        "default": 50
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kg_query",
            "description": "知识图谱查询。搜索实体、关系和文本块，支持混合检索模式。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "查询文本，如'抖音账号买卖的关系'"
                    },
                    "mode": {
                        "type": "string",
                        "description": "检索模式：local(实体优先), global(关系优先), hybrid(混合), mix(平衡), naive(纯向量)",
                        "default": "hybrid"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量限制",
                        "default": 10
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_entities",
            "description": "在知识图谱中搜索实体。查找特定名称或类型的实体节点。",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {
                        "type": "string",
                        "description": "实体名称关键词"
                    },
                    "entity_type": {
                        "type": "string",
                        "description": "实体类型筛选，如'微信号'、'账号'"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量限制",
                        "default": 20
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_clue_detail",
            "description": "获取线索的详细信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "clue_id": {
                        "type": "string",
                        "description": "线索ID"
                    }
                },
                "required": ["clue_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_clues",
            "description": "按时间窗口检索最新线索（最近 N 小时）。比 search_clues 更适合『近期/最近/最新』类查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "integer",
                        "description": "回溯的小时数，默认 24",
                        "default": 24
                    },
                    "risk_label_level1": {
                        "type": "string",
                        "description": "可选风险类型过滤：账号交易/诈骗引流/流量作弊/黑产工具/未知/其他"
                    },
                    "platform": {
                        "type": "string",
                        "description": "可选平台过滤：douyin/baidu_tieba/weibo/xiaohongshu/kuaishou"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数，默认 20",
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
            "description": "查询黑话词典（slang_mappings 表）。用户问『XX 是啥意思』或『最近新出了哪些黑话』时调用。匹配 slang_raw 或 meaning。",
            "parameters": {
                "type": "object",
                "properties": {
                    "slang_term": {
                        "type": "string",
                        "description": "黑话关键词或自然语言描述，如'出号'、'刷粉'、'加微'"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数，默认 20",
                        "default": 20
                    }
                }
            }
        }
    }
]

SYSTEM_PROMPT = """你是一个黑灰产情报分析助手，负责根据用户的查询意图选择合适的工具检索数据，并生成专业的分析报告。

可用工具（按用途选择，不要只用第一个）：
- search_clues：按条件（关键词/风险类型/时间/平台）检索**一批**线索
- get_recent_clues：按时间窗口（最近 N 小时）检索最新线索，"最近/近期/最新"类查询优先用
- kg_query：知识图谱查询，用于"谁和谁有关联"、"实体关系网"类问题
- search_entities：在实体库中查找特定名称/类型的实体
- get_clue_detail：已知 clue_id 时取单条完整内容
- search_slang：查询黑话词典，"XX 是啥意思"或"最近学到了哪些新黑话"用

工作流程（按需串联，不要一次全调）：
1. 理解用户查询意图，决定先调哪个工具（默认 search_clues / get_recent_clues）
2. 看第一个工具的结果，决定下一步是"深入"（get_clue_detail / kg_query）还是"扩展"（search_entities / search_slang）
3. 工具结果已足够时立刻停止检索并生成报告

约束：
- 单次查询最多 3 轮工具调用（系统会自动强制）
- 工具结果已足够时立刻停止检索
- 不要用相同参数重复调同一工具（系统会跳过）
- 如果搜索结果为空，告诉用户未找到匹配的线索/实体/黑话，建议调整查询条件
- **【重要】用户要求的每一个维度都必须独立调用工具获取数据。** 例如：用户要"列出实体关系和相关黑话"时，必须依次调用 kg_query 获取实体关系、**再调用 search_slang 获取黑话词典条目**。禁止仅依赖 search_clues 返回结果中内嵌的 slang_mappings 字段替代 search_slang 工具——内嵌字段只是采样，search_slang 返回的是完整的黑话词典。

报告结构（按需选用）：风险类型分布 / 主要涉及平台 / 高价值实体 / 关键发现 / 黑话解读。
保持专业、简洁的语调。
"""


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

                    # 执行工具调用
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

                        await self._stream_progress(query_id, "retrieving", f"正在调用 {tool_name}...", 30, tool_name=tool_name)

                        result = await self._execute_tool(tool_name, tool_args)

                        # 将工具结果添加回消息
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str)
                        })
                        tool_calls_executed.append({
                            "name": tool_name,
                            "args": tool_args,
                            "result": result,
                            "result_count": len(result) if isinstance(result, list) else 0
                        })

                    # 获取最后一次工具调用的结果数量
                    if tool_calls_executed:
                        last_result_count = tool_calls_executed[-1]['result_count']
                        last_tool_name = tool_calls_executed[-1]['name']
                        await self._stream_progress(query_id, "retrieved", f"工具执行完成，找到 {last_result_count} 条结果", 50, tool_name=last_tool_name)

                    # 继续对话，让 LLM 生成最终回复
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
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _search_clues(
        self,
        query: str = "",
        time_range: str = None,
        risk_types: list = None,
        platforms: list = None,
        limit: int = 50
    ) -> list[dict]:
        """搜索线索的工具实现"""
        from utils import parse_time_range, parse_platform, parse_risk_type

        params = {
            "limit": limit
        }

        # 解析 time_range
        if time_range:
            start_time, end_time = parse_time_range(time_range)
            if start_time:
                params["start_time"] = start_time
            if end_time:
                params["end_time"] = end_time

        # 解析 risk_types
        if risk_types and isinstance(risk_types, list):
            # 直接使用传入的风险类型
            params["risk_label_level1"] = risk_types[0] if len(risk_types) == 1 else None

        # 解析 platforms
        if platforms and isinstance(platforms, list):
            # 映射中文平台名到数据库值
            platform_map = {
                "抖音": "douyin",
                "贴吧": "baidu_tieba",
                "Telegram": "telegram",
                "论坛": "forum"
            }
            mapped = []
            for p in platforms:
                if p in platform_map:
                    mapped.append(platform_map[p])
                else:
                    mapped.append(p)
            if mapped:
                params["source_channel"] = mapped[0] if len(mapped) == 1 else None

        # 执行查询
        with self.db._get_cursor() as cur:
            where_clauses = ["1=1"]
            values = []

            if params.get("risk_label_level1"):
                where_clauses.append("risk_label_level1 = %s")
                values.append(params["risk_label_level1"])

            if params.get("source_channel"):
                where_clauses.append("source_channel = %s")
                values.append(params["source_channel"])

            if params.get("start_time"):
                where_clauses.append("published_at >= %s")
                values.append(params["start_time"])

            if params.get("end_time"):
                where_clauses.append("published_at <= %s")
                values.append(params["end_time"])

            where_sql = " AND ".join(where_clauses)

            cur.execute(f"""
                SELECT clue_id, risk_label_level1, risk_label_level2, confidence,
                       raw_text, cleaned_text, source_channel, published_at,
                       entity_list, slang_mappings, classification_reason
                FROM antiblack.clues
                WHERE {where_sql}
                ORDER BY published_at DESC
                LIMIT %s
            """, values + [params.get("limit", limit)])

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
        """知识图谱查询工具实现"""
        from services.lightrag_service import LightRAGIntegrator

        try:
            config = self.config or get_config()
            rag = LightRAGIntegrator(config._config)

            result = await rag.query(query, mode=mode, top_k=limit)

            if isinstance(result, str):
                return {"content": result, "query": query, "mode": mode}
            return {"content": str(result), "query": query, "mode": mode}
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