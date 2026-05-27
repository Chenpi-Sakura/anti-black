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
            "description": "搜索黑灰产情报线索数据库。根据用户查询意图，搜索相关的线索条目。",
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
    }
]

SYSTEM_PROMPT = """你是一个黑灰产情报分析助手，负责根据用户的查询意图搜索相关线索，并生成专业的分析报告。

可用工具：
1. search_clues - 搜索线索数据库
2. kg_query - 知识图谱查询（实体、关系检索）
3. search_entities - 搜索实体
4. get_clue_detail - 获取线索详情

工作流程：
1. 理解用户查询意图
2. 调用适当的工具获取数据
3. 根据结果生成分析报告

注意：
- 如果搜索结果为空，告诉用户未找到匹配的线索，建议调整查询条件
- 分析报告应该包含：风险类型分布、主要涉及平台、高价值实体、关键发现
- 保持专业、简洁的语调
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

        api_key = os.environ.get("OPENAI_API_KEY")
        api_base = os.environ.get("LLM_API_BASE", "https://api.minimaxi.com/v1")
        model = os.environ.get("LLM_MODEL", "MiniMax-M2.7")

        self.llm_client = AsyncOpenAI(api_key=api_key, base_url=api_base)
        self.model = model

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

        while True:
            try:
                # 调用 LLM（带工具）
                response = await self.llm_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    max_tokens=2048,
                    temperature=0.3,
                    extra_body={"reasoning_effort": "low"}
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
                    # 执行工具调用
                    for tool_call in assistant_message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)

                        await self._stream_progress(query_id, "retrieving", "正在检索线索...", 30, tool_name=tool_name)

                        result = await self._execute_tool(tool_name, tool_args)

                        # 将工具结果添加回消息
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(result, ensure_ascii=False)
                        })
                        tool_calls_executed.append({
                            "name": tool_name,
                            "args": tool_args,
                            "result": result,
                            "result_count": len(result) if isinstance(result, list) else 0
                        })

                    # 获取最后一次工具调用的结果数量
                    last_result_count = tool_calls_executed[-1]['result_count']
                    last_tool_name = tool_calls_executed[-1]['name']
                    await self._stream_progress(query_id, "retrieved", f"工具执行完成，找到 {last_result_count} 条线索", 50, tool_name=last_tool_name)

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
                where_clauses.append("entity_name ILIKE %s")
                values.append(f"%{entity_name}%")

            if entity_type:
                where_clauses.append("entity_type = %s")
                values.append(entity_type)

            where_sql = " AND ".join(where_clauses)

            cur.execute(f"""
                SELECT entity_id, entity_name, entity_type, description,
                       source_channel, created_at
                FROM antiblack.entities
                WHERE {where_sql}
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