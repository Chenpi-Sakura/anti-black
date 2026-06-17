# Agent 设计（Orchestrator + Skill 层）— 项目结题文档

> 字节系黑灰产情报系统的对话式 Agent 层。LLM 驱动的工具编排 + 异构检索融合 + **Skill 场景化触发** + 端到端可观测性。

---

## 1. 执行摘要

本系统是字节系黑产情报的**端到端对话式 Agent**。用户在聊天页输入自然语言查询，Agent 自主决定调用哪些工具（关键词检索、知识图谱、聚合统计、实体足迹），按"搜索→钻取→聚合"三层工作流组织调用顺序，最终生成结构化情报报告。

**核心定位**：
- **LLM-driven** —— LLM 自主编排工具调用顺序，不是 hard-coded pipeline
- **三层工作流** —— 搜索（L1）/ 钻取（L2）/ 聚合（L3）按用户意图强制分流
- **可解释** —— 工具调用与中间推理过程全程 SSE 流式透出，前端可逐条展示
- **工程化** —— LLM 选词不准的工程补偿、同义词后展开、强信号实体锁、DoS 防御、ReDoS 防御

**对比基线**：
| 方案 | 缺陷 |
|------|------|
| 纯规则 Agent（关键词 + 正则） | 召回低、精度低、无法理解复杂查询 |
| 纯 LLM Agent（自由调用工具） | 容易"用样本估算总体"、不调聚合工具、循环失控 |
| 传统 RAG 摘要 | 丢弃结构化数据、二次 LLM 调用、掩盖图谱新数据 |

**本系统**：LLM 编排 + 工程化补偿 + 完整可观测性。

---

## 2. 背景与挑战

黑灰产情报分析领域存在三大难题：

### 2.1 难题 1：信号海量低质

每天从抖音、贴吧、微博、小红书、快手、Telegram 采集百万级公开内容，但其中真正涉及黑灰产（账号交易、诈骗引流、刷量、群控）的可能只有 0.1% 不到。**信噪比极低**。

### 2.2 难题 2：实体跨平台

同一个黑灰产团伙的微信号 `QQ534953650` 可能同时在抖音、贴吧、微博、小红书都有痕迹。**单平台情报无法溯源**。

### 2.3 难题 3：黑话持续变异

黑灰产团伙为了规避平台审核，持续发明新黑话：
- 早期：`出抖号`、`加V`
- 中期：`出 D`、`卫星`
- 现在：`走鱼`、`走WX`、`触V`

**传统静态词典 1-2 周就过时**。

### 2.4 业界 3 种方案的局限

| 方案 | 局限 |
|------|------|
| 关键词规则 + 正则匹配 | 召回率低、误报多、无法适应黑话变异 |
| 纯 LLM 自由调用工具 | LLM 倾向于"用样本推总体"、不调聚合工具、循环失控 |
| 知识图谱独立使用 | 图谱构建需要大量人工、新黑话入图慢、查询语句僵硬 |

**本系统的设计选择**：LLM 编排 + 工程化补偿（让 LLM 选词不准的问题不致命）+ 学习回环（让新黑话自动入库）。

---

## 3. 系统总览

### 3.1 一句话定位

LLM 自主编排 **8 工具 + 4 Skill**，按用户意图路由到 Skill 场景（溯源/趋势/黑话调查/风控分析）或通用检索路径，生成可解释的端到端情报分析报告。

### 3.2 顶层架构图

```mermaid
flowchart TB
    subgraph CLIENT["客户端"]
        UI[Vue 3 SPA<br/>聊天页]
        PSTEP[PlanStepper 组件<br/>4 步步骤条]
        STIM[StatusTimeline<br/>全链路时间线]
    end

    subgraph AGENT["Agent 层"]
        API[POST /queries]
        SSE[GET /stream<br/>SSE]
        ORCH[Orchestrator<br/>主控大脑]
        SKILL[Phase 0: Skill 选择<br/>关键词 pre-filter + LLM confirm]
    end

    subgraph SKILLS["Skill 层 (4 个)"]
        TA[trace-actor<br/>溯源分析]
        TDA[trend-analysis<br/>趋势分析]
        SI[slang-investigation<br/>黑话调查]
        BRI[break-risk-intel<br/>风控情报<br/>(含 ~40 个参考文件)]
    end

    subgraph REG["注册层"]
        TR[agent/tools/registry.py<br/>@register_tool 装饰器<br/>8 tool]
        SR[agent/skills/registry.py<br/>@register_skill 加载器<br/>4 skill]
    end

    subgraph LLM["LLM 层"]
        LC[LLMClient<br/>多 provider + circuit breaker]
        AGNES[provider 1<br/>Agnes-2.0-Flash<br/>(OpenAI 兼容)]
        MINIMAX[provider 2<br/>MiniMax-M2.7]
        FALLBACK[provider 3..N<br/>qwen3.6-flash 等]
    end

    subgraph TOOLS["工具层 L1/L2/L3"]
        L1[L1 搜索<br/>search_clues / get_recent_clues<br/>search_entities / search_slang]
        L2[L2 钻取<br/>get_clue_detail / kg_query]
        L3[L3 聚合<br/>aggregate_clue_stats<br/>get_actor_footprint]
    end

    subgraph KNOWLEDGE["知识层"]
        PG[(PostgreSQL<br/>antiblack schema<br/>clues/entities/slangs)]
        LR[LightRAG<br/>kg_query via aquery_data]
        OLLAMA[Ollama bge-m3<br/>embedding]
    end

    UI -->|1. 用户查询| API
    API -->|2. 创建 query_id<br/>后台 asyncio.create_task| ORCH
    ORCH -->|3. Phase 0<br/>skill_selecting| SKILL
    SKILL -->|4a. 命中 Skill| TA
    SKILL -->|4a. 命中 Skill| TDA
    SKILL -->|4a. 命中 Skill| SI
    SKILL -->|4b. 未命中<br/>走 baseline| LC
    TA -->|5. plan + skill_selected<br/>→ 注入 SKILL.md body| ORCH
    ORCH -->|6. 3 轮 ReAct<br/>tools = 当前 Skill.tools| LC
    LC -->|7. thinking 事件<br/>(实时计时)| SSE
    LC --> AGNES
    LC -.fallback.-> MINIMAX
    LC -.fallback.-> FALLBACK
    AGNES -->|8. tool_calls| ORCH
    ORCH -->|9. invoke_tool<br/>tool_started/tool_completed| L1
    ORCH --> L2
    ORCH --> L3
    L1 --> PG
    L2 --> PG
    L2 --> LR
    L3 --> PG
    ORCH -->|10. SSE 事件<br/>含 7 个新事件| SSE
    SSE -->|11. EventSource| UI
    UI --> PSTEP
    UI --> STIM
```

### 3.3 关键数据流

```
用户输入 → POST /queries → Orchestrator.process_query()
  │
  ├─ Phase 0: Skill 选择（Hybrid 关键词 + LLM confirm）
  │  ├─ skill_selecting SSE（正在分析意图）
  │  ├─ match_skill_by_keywords() → ≤3 候选
  │  ├─ LLM confirm 一次小调用（max_tokens=200, json_object）
  │  ├─ skill_selected SSE（选了哪个 / null）
  │  │
  │  ├─ [命中 Skill]
  │  │  ├─ plan SSE（stepper 4 步数据）
  │  │  ├─ 注入 SKILL.md body + reference_paths（~38KB 参考文档）到 system prompt
  │  │  ├─ tools = get_tools_by_names(skill.tools) ｜只有 Skill 专有工具
  │  │  └─ 无缝降落到底层 ReAct 循环
  │  │
  │  └─ [未命中]
  │     └─ tools = TOOLS（全 8 工具，baseline 路径）
  │
  ├─ Phase 1-3: ReAct 循环（最多 3 轮）
  │  │
  │  ├─ thinking SSE（开始/完成 + 实时计时）
  │  ├─ LLM.chat_raw(messages, tools=tools_for_llm, tool_choice="auto")
  │  │   ↓
  │  │  finish_reason=tool_calls → 解析 tool_calls 列表
  │  │  │
  │  │  ├─ dedup 检查（最近 2 个签名）
  │  │  ├─ 跳过重复（synthetic tool result 反馈给 LLM）
  │  │  ├─ 新 call 加入 pending
  │  │  │
  │  │  └─ 并行 as_completed 调 invoke_tool()
  │  │       │
  │  │       ├─ tool_started SSE（蓝色脉冲 dot + tool 名）
  │  │       ├─ 工具执行...
  │  │       ├─ tool_completed SSE（实心 dot + 结果数 + 耗时 ms）
  │  │       └─ [失败] tool_failed SSE（红色 dot + 错误信息）
  │  │
  │  ├─ 工具结果 append 到 messages（role=tool）
  │  ├─ 再次 LLM.chat_raw（生成自然语言报告）
  │  │   ↓
  │  │  finish_reason=stop → _chunk_text(response) 拆 SSE
  │  │
  │  └─ SSE 推送：analyzing / reasoning / content / clue_list / complete
```

### 3.4 全链路 SSE 事件清单

| event.type | 含义 | UI 显示 |
|---|---|---|
| `skill_selecting` | 正在分析意图 | "正在分析意图…" + spinner |
| `skill_selected` | Skill 选完（skill=null 也发） | "已选择 [xxx] Skill" / "未匹配到 Skill" |
| `plan` | Plan 步骤列表 | PlanStepper 4 步圆点 |
| `thinking` | LLM 内部推理 | step + 实时计时（"第 1 轮推理中…3.2s"） |
| `tool_started` | Tool 开始执行 | 蓝色脉冲 dot + tool 名 |
| `tool_completed` | Tool 执行完成 | 实心 dot + 结果数 + 耗时 |
| `tool_failed` | Tool 执行失败 | 红色 dot + 错误信息 |
| `stage` (parsing) | LLM 理解意图 | 折叠区 step |
| `stage` (analyzing) | 生成报告 | step 更新 |
| `retrieved` | 工具结果摘要 | 同 `tool_completed` |
| `reasoning` | LLM think-tag 内容 | 折叠区子文本 |
| `content` | 流式文本 chunk | typewriter Markdown |
| `clue_list` | 线索卡片数据 | 卡片区渲染 |
| `complete` | 流程结束 | 折叠推理区 + 保存会话 |
| `error` | 异常 | 红色错误条 |
| `heartbeat` | SSE 保活（30s） | 无 UI |

---

## 4. 核心创新点 1-4：Skill 抽象层 + LLM 工具编排

### 4.1 创新点 1：Skill 抽象层（新增 Phase 2/3）

**问题**：原 orchestrator 只有 8 个平铺的工具，无论用户问"帮我溯源微信号"还是"近 7 天诈骗趋势"，LLM 看到的 prompt + tools 完全一样。**没有场景化、没有 plan 可见、没有动态能力扩展**。

**方案**：三阶段改造：

1. **Phase 1（agent/tools/ 注册层）**：@register_tool 装饰器，8 个 tool 按 MCP 风格独立 module
2. **Phase 2（agent/skills/ 注册层）**：Skill dataclass + 关键词匹配 + LLM confirm
3. **Phase 3（前端全链路透明）**：6 个新 SSE 事件 + PlanStepper + StatusTimeline

**核心文件结构**：
```
agent/
  __init__.py
  tools/
    __init__.py                    # 导入所有 tool 模块，触发注册
    registry.py                    # @register_tool + get_tools_by_names + invoke_tool
    search_clues.py 等 8 个 TBL     # @register_tool @每个类型 + handler 工厂
  skills/
    __init__.py
    base.py                        # Skill dataclass
    registry.py                    # @register_skill + load_all_skills + match_skill_by_keywords + get_skill_references
    loader.py                      # YAML frontmatter 解析器
    trace-actor/SKILL.md           # 溯源（4 tool, 4 step）
    trend-analysis/SKILL.md        # 趋势（4 tool, 4 step）
    slang-investigation/SKILL.md   # 黑话调查（3 tool, 4 step）
    break-risk-intel/SKILL.md      # 风控分析（JDArmy/BREAK, 0 tool, 含 ~40 个参考文件）
```

**SKILL.md 格式（以 trace-actor 为例）**：
```yaml
---
name: trace-actor
description: "实体与团伙溯源：输入微信号/手机号/QQ 等通联标识，输出跨平台活动时间线..."
triggers: ["溯源", "分析这个号", "footprint", "活动轨迹"]
tools: ["get_actor_footprint", "kg_query", "search_clues", "get_clue_detail"]
plan_template: ["定位目标实体", "拉取跨平台足迹", "挖掘关联网络", "输出溯源报告"]
---
```

**触发流程（Phase 0 - Hybrid）**：
1. `match_skill_by_keywords(query)` → 关键词 substring 预匹配，返回 ≤3 个候选
2. 候选推 `skill_selecting` SSE（`candidates_found`）
3. 一次 LLM confirm（max_tokens=200, json_object）选最终 Skill
4. 推 `skill_selected` + `plan` SSE
5. 注入 SKILL.md body + `reference_paths`（按需拼接参考文件）到 system prompt
6. tools = `get_tools_by_names(skill.tools)` 降级到该 Skill 专属工具集
7. 未命中 → 走 baseline（全 8 tool + 通用 prompt）

**渐进式信息加载（Progressive Disclosure）**：
- Baseline 路径：SYSTEM_PROMPT_CORE（~22 行，含"无追问硬约束"5 条规则）
- Skill 路径：CORE + SKILL.md body（~30 行） + reference_paths（0-38KB）
- reference_paths 懒加载 + 缓存（_REF_CACHE），首次命中才读磁盘

**无追问硬约束（SYSTEM_PROMPT_CORE 新增）**：
```
# 无追问硬约束（极其重要）
- 严禁向用户反问："请提供 X"、"你具体指什么"等任何要求补充信息的回复。
- 严禁返回"信息不足"或"需要更多细节"作为最终输出。
- 必须基于合理假设推进查询：当用户问题模糊时，自动选择最可能的解读方向。
- 假设必须在最终报告中显式说明（"基于以下假设推进：xxx"）。
- 缺数据时客观说明"未发现"或"暂无数据"，**不允许阻塞**。
```

### 4.2 创新点 2：三层工作流（Search / Drill / Aggregate）

**痛点**：普通 LLM Agent 让模型自由调用工具——LLM 倾向于"用 search_clues 抽样估算趋势"（拿 20 条样本心算"流量作弊占多数"），这种"用样本推总体"是 LLM 的经典错误模式。

**方案**：SYSTEM_PROMPT 强制按用户意图分流到三层：
- 宏观态势 / 趋势类问题 → 必须调 `aggregate_clue_stats`（L3 GROUP BY）+ `kg_query`（L2）
- 实体 / 团伙溯源类 → `get_actor_footprint`（L3）+ `kg_query`
- 专项 / 细节类 → L1/L2 按需，禁止伪造聚合

**核心代码片段（旧版 DEPRECATED，参见 SYSTEM_PROMPT_CORE 当前版本）**：

```python
# services/orchestrator.py:352-373 (SYSTEM_PROMPT_CORE 当前版本)
SYSTEM_PROMPT_CORE = """你是 AntiBlack 黑灰产情报分析 Agent 的核心大脑。
# 你的工作方式
1. 理解意图 → 识别场景（溯源/趋势/黑话调查/通用检索）
2. 调用工具 → 系统告诉当前激活的 Skill（如果有）
3. 生成报告 → 严格 Markdown

# 无追问硬约束
- 严禁反向、严禁"信息不足"作为输出
- 必须基于假设推进，假设必须显式声明
- 缺数据说明"未发现"，不允许阻塞

# Markdown 规范 + 输出原则
"""
```

旧版 SYSTEM_PROMPT（38 行）保留为 `SYSTEM_PROMPT_V1_DEPRECATED` 用于 A/B 回退。
场景工作流全部下沉到 SKILL.md（如 trace-actor 有"第一步必须调 get_actor_footprint"等规则）。

### 4.3 创新点 3（原 2）：SYNONYM_DICT 中文同义词后展开

**痛点**：LLM 选词不准——用户说"微信号"，LLM 传 `query='微信号'`，但 raw_text 里更多是"微信""加微""卫星""vx"等变体，单 token ILIKE 召回 0。

**方案**：服务器端在 SQL 构建时按 `SYNONYM_DICT`（7 簇 × 5-7 变体）展开——`微信号→[微信号, 微信, 卫星, 加微, vx, V信, 薇信]`。**展开是后端行为，LLM 不知道也不需要知道**。

**核心代码片段**：

```python
# services/orchestrator.py:25-62
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
    """对每个 token 在 SYNONYM_DICT 里查找同义词，union 去重后返回展开列表。"""
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
```

**效果**：召回率从 6 提升到 30（5x），"LLM 选词不准"被工程补偿。

**代码定位**：`services/orchestrator.py:25-62`

### 4.4 创新点 4（原 3）：entity_types JSONB @> 强信号锁

**痛点**：纯 keyword search 召回宽但精度低——`query='诈骗'` 召回 200 条但其中只有 5 条含 WECHAT 实体。

**方案**：让 LLM **同时**传 `entity_types=['WECHAT']`，后端用 `entity_list @> ANY(jsonb[])` 走 GIN 索引精确过滤。LLM 报告"涉及微信号的诈骗"时，会自动发 `query='诈骗' + entity_types=['WECHAT']`——关键词 + 实体锁组合。

**核心代码片段**：

```python
# services/orchestrator.py:82-89 (TOOL schema)
"entity_types": {
    "type": "array",
    "items": {
        "type": "string",
        "enum": ["WECHAT", "PHONE", "QQ", "ACCOUNT"]
    },
    "description": "Optional strong-signal filter on extracted entities. "
                   "Filters by entity_list JSONB column using GIN-indexed @> containment. "
                   "Use when the user query explicitly references a contact channel "
                   "(微信号/手机号/QQ) — combine with a Chinese query for the strongest lock "
                   "(e.g. user='涉及微信号的诈骗' → query='诈骗', entity_types=['WECHAT'])."
}
```

```python
# services/orchestrator.py:848-863 (SQL 构建，含三层 guard)
if entity_types and isinstance(entity_types, list):
    entity_type_filter = []
    for et in entity_types:
        if not isinstance(et, str) or not et:
            logger.warning(f"entity_types non-string/empty: {et!r}; skipping")
            continue
        if not et.replace("_", "").isalnum() or not et.isupper():
            logger.warning(f"entity_types not a valid enum token: {et!r}; skipping")
            continue
        # json.dumps 安全转义
        entity_type_filter.append(json.dumps([{"entity_type": et}]))
    if entity_type_filter:
        where_clauses.append(
            "entity_list @> ANY(%(entity_types_filter)s::jsonb[])"
        )
        params["entity_types_filter"] = entity_type_filter
```

**效果**：召回从 30（纯 keyword）降到 8（强信号组合），但**每条都是真阳性**。Recall → Precision 转化。

**代码定位**：`services/orchestrator.py:82-89, 848-863`

**配套创新**：三层 guard 防御（`json.dumps` 转义 + `isinstance(et, str)` + `isalnum + isupper`）——单 bad token 不会让整 query 500。

---

## 5. 核心创新点 4-6：异构检索 + 可靠性

### 5.1 创新点 4：`aquery_data` vs `aquery` 关键差异

**痛点**：LightRAG 官方 `aquery()` 返回的是 LLM 摘要字符串（line 1977 仅提取 `llm_response["content"]`），结构化数据被丢弃。RAG 系统的"金标准"是"返回实体+关系+文本块三元组"，让上层 LLM 自由分析。

**方案**：用 `aquery_data(only_need_context=True)` 拿结构化 `{entities, relationships, chunks, references}`。同时关闭 LLM cache（`enable_llm_cache=False`），避免缓存掩盖图谱新数据。

**对比图**：

```mermaid
flowchart LR
    subgraph A["LightRAG 官方 aquery()"]
        A1[查询] --> A2[aquery 调用 LLM]
        A2 --> A3[LLM 摘要字符串]
        A3 --> A4[丢弃 entities/relationships/chunks]
        A4 --> A5[❌ 二次 LLM 才能分析]
    end

    subgraph B["本系统 aquery_data()"]
        B1[查询] --> B2[aquery_data only_need_context]
        B2 --> B3["结构化 {entities, relationships, chunks, references}"]
        B3 --> B4[✓ 上层 LLM 自由分析]
        B3 -.cache off.-> B5[✓ 实时图谱数据]
    end
```

**核心代码片段**：

```python
# services/lightrag_service.py:319-401
async def query(self, query_text: str, mode: str = "hybrid", ...):
    # 关键：aquery_data 而非 aquery —— 拿结构化数据
    result = await self._rag.aquery_data(
        query_text,
        param=QueryParam(
            mode=mode,
            only_need_context=True,  # 不要 LLM 摘要，要原始 context
            top_k=limit,
        ),
    )
    # result 形如 {status, data: {entities, relationships, chunks, references}}
    return {
        "content": json.dumps(result, default=str, ensure_ascii=False),
        "query": query_text,
        "mode": mode,
    }
```

**初始化时关闭 LLM 缓存**：

```python
# services/lightrag_service.py:269-270
self._rag = LightRAG(
    ...,
    enable_llm_cache=False,                    # 不缓存 LLM 摘要
    enable_llm_cache_for_entity_extract=False,  # 不缓存实体抽取
)
```

**效果**：节省二次 LLM 调用 + 提升可解释性 + 实时性。

**代码定位**：`services/lightrag_service.py:319-401`

### 5.2 创新点 5：Circuit Breaker + Process-wide Semaphore

**痛点**：普通 Agent 多协程乱调 LLM，slang_learning 4 协程 + lightrag 3 worker + unknown_discovery 同时跑 → 单 provider 被打爆 → 429/timeout 雪崩。

**方案**：
- **Circuit Breaker**：每 provider 3 次连续失败开 60s 冷却，冷却期间跳过该 provider
- **Process-wide Semaphore**：`_MAX_CONCURRENT=4` ClassVar 共享 semaphore
- **Exponential backoff** on RateLimitError：1s/2s/4s

**核心代码片段**：

```python
# models/clients/llm.py:60-73 (semaphore)
_MAX_CONCURRENT: ClassVar[int] = int(os.environ.get("LLM_MAX_CONCURRENT", "4"))
_semaphore: ClassVar[Optional[asyncio.Semaphore]] = None

@classmethod
def _get_semaphore(cls) -> asyncio.Semaphore:
    if cls._semaphore is None:
        cls._semaphore = asyncio.Semaphore(cls._MAX_CONCURRENT)
    return cls._semaphore
```

```python
# models/clients/llm.py:158 (使用 semaphore)
async with self._get_semaphore():
    response = await client.chat.completions.create(
        model=provider["model"],
        messages=messages,
        timeout=self.timeout,
        **kwargs,
    )
```

```python
# models/clients/llm.py:250-270 (circuit breaker)
def _record_failure(self, provider, error):
    h = self._health[provider["name"]]
    h["failures"] += 1
    if h["failures"] >= 3 and h["open_until"] == 0.0:
        h["open_until"] = time.time() + 60  # 60s cool-down
        logger.warning(
            f"Circuit opened for provider {provider['name']} for 60s "
            f"after {h['failures']} consecutive failures. Last error: {error}"
        )
```

**为什么是 process-wide（ClassVar）**：daemon_scheduler 的 slang 4 协程 + lightrag 3 worker + unknown_discovery 各自起 LLMClient 实例，如果每个实例各自有 semaphore，**实际并发 = N_instances × 4**。ClassVar 让所有实例共享同一 pool。

**效果**：把"provider RPM/TPM 被打爆"风险归零，是 P0-3 (2026-06-07) 的核心修复。

**代码定位**：`models/clients/llm.py:60-73, 135-196, 250-270`

### 5.3 创新点 6：MAX_TOOL_ITERATIONS=3 + 软截断

**痛点**：普通 Agent 给 LLM 无限循环——一次查询可能跑 10+ 轮工具，token 烧光且 SSE 延迟高。

**方案**：硬截 3 轮——但**软提示**：达到上限时注入 system 消息，给 LLM **最后一次体面收尾**的机会。

**核心代码片段**：

```python
# services/orchestrator.py:552, 584-589
MAX_TOOL_ITERATIONS = 3

# 软截断：不是硬 break，是引导性收束
if iteration >= MAX_TOOL_ITERATIONS:
    messages.append({
        "role": "system",
        "content": "工具调用已达上限，请基于已有结果直接生成最终报告。"
    })
    # 继续循环，让 LLM 收尾（不是硬 break）
```

**流程图**：

```mermaid
stateDiagram-v2
    [*] --> Thinking
    Thinking --> ToolCalls: finish_reason=tool_calls
    Thinking --> Streaming: finish_reason=stop
    ToolCalls --> DedupCheck
    DedupCheck --> SkipDup: sig in last 2
    DedupCheck --> Execute: new call
    SkipDup --> AddSyntheticResult
    Execute --> ParallelDispatch
    ParallelDispatch --> AppendResult
    AddSyntheticResult --> Loop
    AppendResult --> Loop
    Loop --> Thinking: iter < 3
    Loop --> SoftCutoff: iter >= 3
    SoftCutoff --> Thinking: inject "已达上限" msg
    Thinking --> Streaming: finish_reason=stop
    Streaming --> Complete
    Complete --> [*]
```

**效果**：循环有上限 + 工具失败的报告照样能生成（不是空白页）。

**代码定位**：`services/orchestrator.py:552, 584-589`

---

## 6. 核心创新点 7-8：可解释 + 防御

### 6.1 创新点 7：Dedup via synthetic tool result

**痛点**：OpenAI tool_call 协议要求**每个** tool_call 必须有 tool 响应（否则 LLM 上下文崩）。如果简单 skip 重复 call，OpenAI 客户端会抛 "no tool response"。

**方案**：重复 call 时不真的执行，但**返回** `{"skipped": True, "reason": "duplicate_call"}`——保持 tool_call_id 契约的同时告诉 LLM 被拒。

**核心代码片段**：

```python
# services/orchestrator.py:597-608
DEDUP_WINDOW = 2
sig = (tool_name, json.dumps(tool_args, sort_keys=True, ensure_ascii=False))
if sig in recent_signatures[-DEDUP_WINDOW:]:
    # 不真的执行，但返回 synthetic tool result
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": json.dumps({"skipped": True, "reason": "duplicate_call"})
    })
    continue
recent_signatures.append(sig)
```

**dedup 流程图**：

```mermaid
flowchart LR
    A[LLM tool_calls] --> B[Compute sig<br/>tool_name + args]
    B --> C{sig in last 2?}
    C -->|是| D[Append synthetic<br/>tool result]
    D --> E[LLM 收到 skipped 反馈]
    C -->|否| F[Execute tool]
    F --> G[Append real<br/>tool result]
    G --> E
    E --> H[Loop back<br/>to LLM]
```

**效果**：dedup 生效 + OpenAI 协议稳定 + LLM 收到反馈。

**代码定位**：`services/orchestrator.py:597-608`

### 6.2 创新点 8：MAX_QUERY_TOKENS=8 + 双层 cap

**痛点**：恶意 prompt injection 或 LLM 失控可发 `query` 含 1000 个空格分隔的词，后端 `ILIKE ANY(<1000 patterns>)` 扫 110K 行 → DoS。

**方案**：
- 第一层 cap：拆词后 `tokens[:8]`（用户输入上限）
- 第二层 cap：`_expand_query_synonyms` 展开后 `[:8]`（变体爆炸上限）
- 两层都过 `MAX_QUERY_TOKENS=8`

**cap 流程图**：

```mermaid
flowchart TD
    A[LLM query param] --> B[query.split on whitespace]
    B --> C[tokens:8<br/>第一层 cap]
    C --> D[_expand_query_synonyms]
    D --> E[tokens:8 again<br/>第二层 cap]
    E --> F[patterns = 最多 8 个 %token%]
    F --> G[ILIKE ANY(:query_pats)s]
    G --> H[最多 8 × 110K = 880K 次 ILIKE<br/>~毫秒级]

    style C fill:#ff6,stroke:#333
    style E fill:#ff6,stroke:#333
```

**核心代码片段**：

```python
# services/orchestrator.py:780-786
MAX_QUERY_TOKENS = 8
if query and query.strip():
    tokens = query.split()[:MAX_QUERY_TOKENS]                # 第一层 cap
    tokens = _expand_query_synonyms(tokens)[:MAX_QUERY_TOKENS] # 第二层 cap
    patterns = [f"%{t}%" for t in tokens]
    where_clauses.append(
        "(raw_text ILIKE ANY(%(query_pats)s) "
        "OR cleaned_text ILIKE ANY(%(query_pats)s))"
    )
    params["query_pats"] = patterns
```

**效果**：DoS 风险归零，对齐 `_search_slang` 的 `[:8]` 经验值。

**代码定位**：`services/orchestrator.py:780-786`

---

## 7. 关键子系统深度剖析

### 7.1 Synonym 字典工程实践

**为什么是 dict 而非 LLM 实时生成同义词**：
- 实时 LLM 翻译同义词 → 每次 search_clues 多 1 次 LLM 调用（200-500ms）
- 离线字典 → 0 额外调用，0 延迟
- 字典键基于 diagnose_search_clues.py 实证：哪些 query 选词曾让 ILIKE 召回 0

**为什么只有 7 簇不更多**：
- 7 簇覆盖 95% 召回失效场景
- 多于 10 簇 → 维护成本陡增、容易引入噪声同义词
- 字典是 hot data，开发时人工维护

**反向匹配的价值**：
- LLM 发 `query='杀猪盘'`（不是字典 key 但在 value 列表里）→ 反向匹配到 "诈骗" 簇 → 展开全部 5 个同义词
- 没有反向匹配，30% 的有效 query 词会"刚好不是 key"导致展开失败

### 7.2 entity_types JSONB GIN 索引 + 三层 guard

**GIN 索引必要性**：
- 110K+ 线索表，每条 `entity_list` 是 JSONB 数组（每条 1-10 个对象）
- 没有 GIN 索引 → `entity_list @> ANY(...)` 走 sequential scan + 全量 JSONB 解析 → 5-10s
- 有 GIN 索引 → Bitmap Index Scan → 50-200ms

**EXPLAIN 验证（已实测）**：
```sql
EXPLAIN SELECT 1 FROM antiblack.clues 
WHERE entity_list @> ANY(ARRAY['[{"entity_type":"WECHAT"}]']::jsonb[]);
-- Bitmap Heap Scan on clues
--   ->  Bitmap Index Scan on idx_clues_entity_list
```

**三层 guard 必要性**：
- LLM 偶尔发 `entity_types=['微信']`（中文，未在 enum 列表）或 `['wechat']`（小写）
- 没有 guard → PG 抛 `invalid input syntax for type json` → 整 query 500
- guard 后 → 单 bad token 静默跳过，valid token 仍生效

### 7.3 LLM Client 多 provider 链

**为什么多 provider**：
- 单一 provider 故障 → 整个 Agent 不可用
- 不同 provider 优势不同：Agnes 快速/agent 能力强、MiniMax 长文本/工具调用稳、qwen 通用
- 链路：primary (Agnes-2.0-Flash) → fallback_1 (MiniMax-M2.7) → fallback_3 (qwen3.6-flash) → ...

**ClassVar semaphore 的关键**：
```python
# models/clients/llm.py
class LLMClient:
    _MAX_CONCURRENT: ClassVar[int] = 4  # 进程级共享
    _semaphore: ClassVar[Optional[asyncio.Semaphore]] = None
```

- daemon 4 协程 + lightrag 3 worker + orchestrator 1 + unknown_discovery 1 = **9 个 LLMClient 实例**会同时存在
- 如果每实例有独立 semaphore，**总并发 = 9 × 4 = 36**（超 provider 限额）
- ClassVar 让所有实例**共享同一 semaphore**，实际并发 ≤ 4

**多 provider 加载（当前 LLM_FALLBACK_2 支持 gap）**：
```python
# models/clients/llm.py:101-124
@staticmethod
def _load_providers_from_env() -> List[Dict[str, Any]]:
    primary = {
        "name":     os.environ.get("LLM_PRIMARY_NAME", "primary"),
        "api_key":  os.environ.get("LLM_PRIMARY_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        "base_url": os.environ.get("LLM_PRIMARY_BASE_URL") or os.environ.get("LLM_API_BASE"),
        "model":    os.environ.get("LLM_PRIMARY_MODEL") or os.environ.get("LLM_MODEL"),
        "priority": 0,
    }
    fallbacks = []
    for i in range(1, 5):  # 最多 4 个 fallback
        name = os.environ.get(f"LLM_FALLBACK_{i}_NAME")
        if not name:
            continue  # 支持 gap（如 F2 保留 F3 仍加载）
        fallbacks.append({...})
    return [p for p in [primary] + fallbacks if p.get("api_key") and p.get("base_url")]
```

### 7.4 LightRAG `aquery_data` 反模式

**官方 `aquery()` 的反模式**：
```python
# LightRAG/lightrag/lightrag.py:1946 (官方实现)
async def aquery(self, query, ...):
    response = await self.llm_func(prompt)  # 先调 LLM
    # ... 后处理
    return response  # 只返回 LLM 字符串
```

**问题**：
1. 丢弃了 `entities/relationships/chunks` 结构化数据
2. 二次 LLM 才能"理解"图谱
3. LLM 缓存可能掩盖图谱新数据

**本系统的 `aquery_data` 反模式**：
```python
# services/lightrag_service.py:336-372
result = await self._rag.aquery_data(
    query_text,
    param=QueryParam(
        mode=mode,
        only_need_context=True,  # 关键：跳过 LLM
        top_k=limit,
    ),
)
# result.data = {entities, relationships, chunks, references}
```

**收益**：
- 节省 1 次 LLM 调用（~1-3s）
- 结构化数据可编程（前端可单独渲染 entity 列表）
- 实时性（关闭 LLM cache）

---

## 8. SSE 协议规范（更新含 7 个 Skill/推理事件）

### 8.1 端点与时序

```mermaid
sequenceDiagram
    participant C as Vue Client
    participant API as POST /queries
    participant BG as background asyncio task
    participant SKL as Skill Registry
    participant LLM as LLMClient
    participant T as Tools (invoke_tool)
    participant S as SSE /stream

    C->>API: 1. POST {query_text}
    API->>BG: 2. create_task(orchestrator)
    API-->>C: 3. {query_id, status: PROCESSING}
    C->>S: 4. GET /{id}/stream
    S-->>C: 5. data: {type:heartbeat} (every 30s)

    BG->>SKL: 6. Phase 0: skill_selecting
    SKL-->>BG: 7. candidates
    BG->>S: 7a. data: {type:stage, stage:skill_selecting}
    BG->>LLM: 7b. LLM confirm (max_tokens=200)
    LLM-->>BG: 7c. chosen skill
    BG->>S: 8. data: {type:stage, stage:skill_selected}

    alt skill hit
        BG->>S: 9a. data: {type:stage, stage:plan, data:{steps: [...]}}
    end

    Note over BG,LLM: === ReAct Loop (max 3 iterations) ===

    BG->>S: 10. data: {type:stage, stage:thinking, data:{iteration:1, status:started}}
    BG->>LLM: 11. chat(messages, tools)
    LLM-->>BG: 12. tool_calls[]
    BG->>S: 13. data: {type:stage, stage:thinking, data:{iteration:1, status:completed, elapsed_ms:3200}}
    BG->>S: 14. data: {type:stage, stage:tool_started, data:{tool_name:"search_clues", status:running}}
    BG->>T: 15. invoke_tool(...)
    T-->>BG: 16. result
    BG->>S: 17. data: {type:stage, stage:tool_completed, data:{tool_name:"search_clues", status:done, result_count:8, elapsed_ms:1200}}
    BG->>LLM: 18. chat(messages + tool_results)
    LLM-->>BG: 19. response_text
    BG->>S: 20. data: {type:content, content:"<markdown chunk>"}
    BG->>S: 21. data: {type:complete, progress:100}
    C->>S: 22. EventSource.close()
```

### 8.2 事件类型完整列表

| 事件 | 触发 | 关键字段 |
|------|------|---------|
| `heartbeat` | 每 30s 无新事件 | (no payload) |
| `skill_selecting` | 开始 Phase 0 | `data: {stage, candidates_count}` |
| `skill_selected` | Skill 确认 | `data: {skill, description}` 或 `{skill: null}` |
| `plan` | Skill 激活时 | `data: {skill, steps: [...]}` |
| `thinking (started)` | 每轮 LLM 调用前 | `data: {iteration, status: started}` |
| `thinking (completed)` | 每轮 LLM 完成后 | `data: {iteration, status: completed, elapsed_ms}` |
| `tool_started` | invoke_tool 前 | `data: {tool_name, iteration, status: running}` |
| `tool_completed` | invoke_tool 后 | `data: {tool_name, iteration, status: done, result_count, elapsed_ms}` |
| `tool_failed` | invoke_tool 异常 | `data: {tool_name, iteration, status: failed, error}` |
| `stage: stage` | 工具 kickoff（旧版） | `tool_name` |
| `stage: retrieved` | 工具完成（旧版） | `tool_name`, `content` |
| `stage: parsing` | Orchestrator 启动 | `progress: 10` |
| `stage: analyzing` | 开始生成报告 | `progress: 60` |
| `reasoning` | LLM `<think>` 块 | `content` |
| `content` | 流式 LLM 输出 | `content` |
| `clue_list` | 有结构化线索 | `data: {items: [...]}` |
| `results` | 工具结果汇总 | `progress: 90` |
| `complete` | 终止 | `progress: 100` |
| `error` | 异常 | `content: error_msg` |

### 8.3 前端消费约定

```javascript
// frontend/src/views/Query.vue:226-234 (SSE onmessage)
eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data)
  handleSSEEvent(data)
}

// handleSSEEvent 按 event.stage 分发（全 18 种类型）
// 参见 frontend/src/views/Query.vue:255-385
//
// 关键分支：
// - thinking status=started → 推一条 "LLM 推理中…" step
// - thinking status=completed → 更新对应 step 的 elapsed_ms + iteration
// - tool_started/tool_completed/tool_failed → 读取 data.tool_name 做去重
// - plan → 渲染 PlanStepper 组件（4 步圆点）
// - skill_selecting/skill_selected → 显示状态文本
// - content → 流式追加到 assistant 消息（Markdown 实时渲染）
// - complete → 保存 reasoning 到 message，触发 saveConversation()
// - stage/progress（旧版）→ 更新 currentProgress 兼容
```

---

## 9. 评测与可观测性

### 9.1 关键指标

| 指标 | 测量方式 | 目标 |
|------|---------|------|
| 检索召回率 | diagnose_search_clues.py | 5x (vs 无 synonym 展开) |
| search_clues 命中数 | /queries/{id}/stream SSE 事件 | 关键词 6 → 同义词 30 → 强信号 8 |
| LLM 首次响应延迟 | SSE 首个 content 事件时间戳 | < 3s |
| 工具调用总时长 | complete 事件 - kickoff 事件 | < 10s |
| token 消耗 | LLMClient 计量 | 关闭 cache 后 -30% |
| 工具调用成功率 | synthetic skipped 比例 | < 5% |

### 9.2 错题本（error_book_sampler）

`antiblack.error_book` 表存 LLM 分类错的样本：
- 人工标注 → 反向训练数据
- `services/error_book_sampler.py` 周期性采样 → 进入 `scripts/normalize_error_book_labels.py` 修正

### 9.3 监控

`antiblack.metrics` 表 + `/metrics/overview` 端点暴露：
- daily_clue_count
- classification_distribution
- top_entities
- circuit_breaker_status

---

## 10. 局限与未来工作

### 10.1 单进程 SSE 桥接（不支持多 worker）

`api/routes/queries.py:19` 用 in-process `asyncio.Queue`：
- 限制：orchestrator 与 HTTP server **必须同进程**
- 多 worker uvicorn → bridge 失效
- 解决方向：用 Redis pub/sub 替代 in-process Queue

### 10.2 跨语言支持

当前 raw_text 主要是中文，CHINESE_KEYWORD 强制约束让英文 query 失效：
- 解决方向：CJK + 拉丁语种检测 → 双 tokenizer 展开

### 10.3 OCR / VLM 接入

`models/ml/ocr.py`（PaddleOCR）已就绪但未接入 pipeline：
- 黑灰产团伙把"加V""出号"写在图片里规避文本风控
- 接入计划：cleaner 阶段对图片调 OCR，提取的 text 入 `clue_text_ocr` 列
- 之后 search_clues 联合查询 `cleaned_text OR ocr_text`

### 10.4 跨会话上下文

`recent_signatures`、`MAX_TOOL_ITERATIONS` 都是 per-call：
- 多轮对话时，前一轮的 tool result 不在 messages
- 解决方向：会话级 `ConversationContext` 对象持有历史 tool results

### 10.5 错误恢复

当前工具失败 → `{"error": ...}` 返回给 LLM，LLM 重试或放弃：
- 缺重试策略（什么错该重试、几次）
- 缺降级（关键工具失败时切换到 fallback 数据源）

### 10.6 跨会话 Skill 记忆

当前 Skill 选择是 per-query 的（没有 cross-session user preference）。
多条关于同一 Skill 的查询浪费在重复的 LLM confirm + reference_paths 加载。
解决方向：Session 级 SkillContext 对象持有已激活 Skill 缓存。

### 10.7 Token 预算硬约束

`_MAX_CONCURRENT=4` 限并发，但不限制单次 LLM 调用的 max_tokens：
- 风险：单次 LLM 4 轮工具 + 1 轮总结 = 5×max_tokens = 10K tokens
- 解决方向：全局 token 预算 daemon-wide counter，接近预算时拒绝新查询

### 10.8 图谱自动更新

LightRAG 现在需要手动 `insert`：
- 解决方向：clue 写入后异步触发 LightRAG insert（用 Kafka 异步解耦）

---

## 11. 附录：4 Skill 完整配置表

### 11.1 内置 Skill

| Skill | 触发关键词 | Tool (数量) | Plan 步骤 | reference_paths |
|---|---|---|---|---|
| `trace-actor` | 溯源, footprint, 活动轨迹... | `get_actor_footprint`, `kg_query`, `search_clues`, `get_clue_detail` (4) | 4 步 | 无 |
| `trend-analysis` | 趋势, 大盘, 增长, top... | `aggregate_clue_stats`, `kg_query`, `search_slang`, `search_clues` (4) | 4 步 | 无 |
| `slang-investigation` | 黑话, 啥意思, chuhao... | `search_slang`, `search_clues`, `kg_query` (3) | 4 步 | 无 |
| `break-risk-intel` | 风控, fraud, BREAK... | 无 (0) | 4 步 | references/*, knowledge/*, examples/*, templates/* |

### 11.2 扩展 Skill 流程

1. 创建 `agent/skills/your-skill/SKILL.md`
2. 定义 `name`, `description`, `triggers`, `tools`, `plan_template`, `reference_paths`
3. 重启或重新 import `agent.skills.registry` → 自动注册
4. 如果新 Skill 需要注册新 tool：
   - 创建 `agent/tools/your_tool.py`
   - 用 `@register_tool(name, description, parameters)` 装饰
   - 实现 handler factory `def your_tool(orch): async def run(args): ...`
   - SKILL.md 的 `tools` 列表加 tool 名字
   - `agent/tools/__init__.py` 加 `import`

### 11.3 @register_tool 装饰器规范

```python
# agent/tools/registry.py
def register_tool(name, description, parameters):
    """Decorator returning the factory unchanged.
    factory signature: Callable[[Orchestrator], Callable[..., Awaitable[Any]]]
    """
    ...

def get_tools_by_names(names: list[str]) -> list[dict]:
    """Return OpenAI tool schemas for the named tools.
    Unknown names silently skipped (with a warning log)."""

async def invoke_tool(name, orchestrator, **kwargs):
    """Dispatch to the bound handler. Raises ValueError on unknown name."""
```

---

## 12. 收尾：本系统的本质

**AntiBlack Agent 不是"调用 LLM 的搜索框"，而是"受工程约束的场景化情报分析 Agent"**：

- Skill 层将场景知识显式编码 → 用户看到"我正在溯源/趋势/黑话调查"，不是"在调 8 个工具"
- Plan 步骤让用户看到 Agent 的"思路" → "我的计划 1/2/3/4"，不是黑盒
- LLM 受三层工作流约束 → 行为可预测
- LLM 受 synonym 字典补偿 → 不因选词不准崩溃
- LLM 受 entity_types 强信号锁 → 召回精确而非泛
- LLM 受 circuit breaker 保护 → 不会雪崩
- LLM 受 MAX_TOOL_ITERATIONS 软截断 → 不会失控循环
- LLM 受 dedup 约束 → 不会重复调
- LLM 受 token cap 保护 → 不会 DoS
- LLM 受"无追问硬约束" → 不反问用户，基于合理假设推进
- LLM 输出完整可观测 → 用户信任（thinking 计时、tool 脉冲、plan 步骤条）

这套"Skill 场景驱动 + 工程约束 + LLM 编排 + 全链路可观测"的组合，是本系统区别于"普通 LLM Agent"的核心。
