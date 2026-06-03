"""
黑灰产 M.O. & Toolchain / Supply & Demand 抽取器。

设计原则：
- 不自建 regex/dict 框架——让 LLM 抽
- 不走 LightRAG 默认抽取（它的 prompt 抽 person/org/location，浪费 token）
- 我们 LLM 拿结构化 JSON → ainsert_custom_kg 喂给 LightRAG Neo4j
- 同名 entity_name 走 Neo4j MERGE 自动跨消息聚合
- 跨名同义（"接码平台" vs "接码资源"）留待离线 dedup cron 处理

产出两个图谱：
  M.O. & Toolchain: TOOL / TACTIC / TARGET 三类节点
  Supply & Demand:  RESOURCE / INTENT / SCENE / PRICE 四类节点
"""
import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# 黑产 M.O. 抽取 prompt。
# 受试模型：MiniMax-M2.7（OpenAI 兼容） / 后续可切本地 Qwen2.5-32B
EXTRACTION_PROMPT = """你是黑灰产情报分析助手。请从以下黑产相关文本中提取结构化信息。

【图谱 1：作案手法与工具链 (M.O. & Toolchain)】
- 黑产工具 (entity_type=TOOL)：接码平台, 改机工具, 群控系统, 云控脚本, 秒拼软件, 打码平台, 设备伪装, IP池, 指纹浏览器, 猫池, 多开工具, 模拟器, 注册机, 群发器
- 战术动作 (entity_type=TACTIC)：养号, 截流, 爆粉, 刷屏, 刷粉, 刷赞, 刷量, 代实名, 代养, 解封, 搬号, 群控, 私信引流, 评论截流, 关注引流, 矩阵运营
- 攻击目标 (entity_type=TARGET)：抖音直播间, 本地生活评论区, 小店店铺, 短视频带货, 评论引流, 短视频评论区, 抖音粉丝群, 私信列表

【图谱 2：产业链供需 (Supply & Demand)】
- 黑产资源 (entity_type=RESOURCE)：千粉号, 万粉号, 实名号, 蓝V号, 企业号, 真人粉丝, 黑卡, IP池, 实名资料, 银行卡, 支付通道
- 交易意图 (entity_type=INTENT)：出, 收, 寻, 代办, 出售, 求购, 回收, 出租, 转让, 换绑, 售卖, 出售
- 应用场景 (entity_type=SCENE)：无人直播, 短剧推广, 海外带货, 矩阵号运营, 截流变现, 带货口碑, 私域转化, 直播切片
- 价格 (entity_type=PRICE)：100元, 1000元, 几十一百, 面议, 50-100元, 几百, 上千, 几万

【输出格式（严格 JSON，无 markdown 包裹）】
{{
  "entities": [
    {{"entity_name": "云控脚本", "entity_type": "TOOL", "description": "黑产自动化操控多账号的工具"}},
    {{"entity_name": "养号", "entity_type": "TACTIC", "description": "通过模拟正常用户行为养账号权重"}},
    {{"entity_name": "千粉号", "entity_type": "RESOURCE", "description": "1000粉丝级别的抖音账号"}}
  ],
  "relationships": [
    {{"src_id": "云控脚本", "tgt_id": "养号", "description": "云控脚本可以用于养号", "keywords": "enables", "weight": 1.0}},
    {{"src_id": "千粉号", "tgt_id": "无人直播", "description": "千粉号用于无人直播带货", "keywords": "supplies", "weight": 1.0}}
  ]
}}

要求：
- 只返回严格 JSON，不要任何 markdown 标记（不要 ```json 包裹）
- entities 列出所有识别出的黑产实体，description 简短
- relationships 描述实体间关联，keywords 限定在：enables/targets/supplies/demands/priced_at/alternative_to
- 原文中没出现任何黑产相关内容时返回 {{"entities": [], "relationships": []}}

原文：{text}"""


# 类级缓存：daemon 多轮 / 多 batch 共享同一缓存
# 黑产评论高度同质化（全网刷同一句广告），命中率应该很高
# 进程内，5 分钟 TTL，max 5000 条
# 用 cachetools.TTLCache；如未装则降级为带 TTL 的 dict（功能等价）
try:
    from cachetools import TTLCache
    _extraction_cache: Any = TTLCache(maxsize=5000, ttl=300)
except ImportError:
    # 降级实现：手动清理过期 key
    _extraction_cache: Dict[str, tuple] = {}  # {hash: (timestamp, result)}
    _CACHE_TTL = 300
    _CACHE_MAX = 5000


def _cache_get(text_hash: str) -> Optional[Dict[str, Any]]:
    """统一 cache get 接口（处理 TTLCache 与降级 dict 两种实现）。"""
    try:
        return _extraction_cache.get(text_hash)
    except Exception:
        return None


def _cache_put(text_hash: str, result: Dict[str, Any]) -> None:
    """统一 cache put 接口。降级 dict 实现需要手动清理过期和 LRU。"""
    if isinstance(_extraction_cache, dict) and not hasattr(_extraction_cache, "popitem"):
        # 降级 dict：清理过期 + LRU
        now = time.time()
        expired = [k for k, (ts, _) in _extraction_cache.items() if now - ts > _CACHE_TTL]
        for k in expired:
            _extraction_cache.pop(k, None)
        # LRU 截断
        while len(_extraction_cache) >= _CACHE_MAX:
            _extraction_cache.pop(next(iter(_extraction_cache)), None)
        _extraction_cache[text_hash] = (now, result)
    else:
        _extraction_cache[text_hash] = result


_MARKDOWN_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE | re.IGNORECASE)


def _strip_markdown_json(raw: str) -> str:
    """剔除 LLM 输出常见的 ```json ... ``` 包装。

    实测 Ollama 跑的开源模型（Qwen2.5/Mistral/Llama3）有 ~30% 概率
    在 JSON 外面套 markdown 标记，直接 json.loads 会 SyntaxError。
    粗暴但管用：去前后空白 → 去 ``` 包裹 → 去 "json" 前缀 → 再 strip。
    """
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    else:
        # 兜底正则：去除首尾 markdown 围栏
        s = _MARKDOWN_FENCE_RE.sub("", s).strip()
    return s


# LLM 调用超时（秒）+ 重试（指数退避）
LLM_TIMEOUT = 60
LLM_MAX_RETRIES = 2


async def _call_llm(prompt: str) -> str:
    """调 MiniMax LLM 拿原始返回。失败抛异常，由 caller 决定如何降级。

    复用 services/lightrag_service.py:create_minimax_complete() 实现，
    共用 OPENAI_API_KEY / LLM_API_BASE 环境变量。
    """
    from services.lightrag_service import create_minimax_complete
    from openai import APITimeoutError, APIError

    llm_complete = create_minimax_complete()
    last_err: Optional[Exception] = None
    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            return await llm_complete(
                prompt=prompt,
                system_prompt="你是黑灰产情报分析助手，输出严格 JSON。",
                history_messages=[],
            )
        except (APITimeoutError, APIError) as e:
            last_err = e
            if attempt < LLM_MAX_RETRIES:
                backoff = 2 ** attempt
                logger.warning(f"LLM call failed (attempt {attempt+1}), retry in {backoff}s: {e}")
                import asyncio
                await asyncio.sleep(backoff)
                continue
            raise
    # 不可达，类型检查器
    raise last_err if last_err else RuntimeError("LLM call exhausted retries")


class MOExtractor:
    """黑灰产 M.O. + Supply/Demand 抽取器（LLM 驱动）。

    使用方式：
        extractor = MOExtractor(config)
        result = await extractor.extract(raw_text)  # {"entities":[...], "relationships":[...]}
        kg = extractor.to_lightrag_kg(result, message_id="msg_123")
        await rag.ainsert_custom_kg(kg)
    """

    # 合法 entity_type 白名单（schema 校验，避免 LLM 自由发挥生成脏数据）
    VALID_ENTITY_TYPES = frozenset({
        "TOOL", "TACTIC", "TARGET",
        "RESOURCE", "INTENT", "SCENE", "PRICE",
    })

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        # 文本截断长度：超过 1500 字截断（防 LLM prompt 过长 + 节省 token）
        self.max_text_chars = 1500

    async def extract(self, text: str) -> Dict[str, Any]:
        """调 LLM，返回 {"entities": [...], "relationships": [...]}。

        失败/无匹配 → 返回 {"entities": [], "relationships": []} (best-effort)。
        5-min 文本哈希缓存在类变量（跨 instance 共享，黑产评论同质化命中率高）。
        """
        if not text or not text.strip():
            return {"entities": [], "relationships": []}

        # 1. 类级缓存命中
        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:16]
        cached = _cache_get(text_hash)
        if cached is not None:
            return cached

        # 2. 调 LLM
        prompt = EXTRACTION_PROMPT.format(text=text[: self.max_text_chars])
        try:
            raw = await _call_llm(prompt)
        except Exception as e:
            # 关键：不静默！监控能看到是 LLM 抽风还是真没数据
            logger.warning(f"MO LLM call failed: {e}")
            result: Dict[str, Any] = {"entities": [], "relationships": []}
            _cache_put(text_hash, result)
            return result

        # 3. 解析 JSON（含 markdown 清洗）
        try:
            cleaned = _strip_markdown_json(raw)
            result = json.loads(cleaned)
            if not isinstance(result, dict) or "entities" not in result:
                logger.warning(
                    f"MO extraction returned non-dict or missing 'entities' key, "
                    f"raw: {raw[:200]}"
                )
                result = {"entities": [], "relationships": []}
            else:
                # schema 校验：剔除非法 entity_type
                result = self._sanitize_extraction(result)
        except Exception as e:
            # 关键：不静默！监控能看到是 LLM 抽风还是真没数据
            logger.warning(f"MO JSON parse failed: {e}, raw_output: {raw[:200]}")
            result = {"entities": [], "relationships": []}

        _cache_put(text_hash, result)
        return result

    def _sanitize_extraction(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """过滤掉非法 entity_type（LLM 偶尔会输出 ENTITY/THING 等泛型）。"""
        raw_entities = result.get("entities", [])
        valid_entity_names = set()
        clean_entities = []
        for e in raw_entities:
            if not isinstance(e, dict):
                continue
            name = e.get("entity_name", "").strip()
            etype = e.get("entity_type", "").strip().upper()
            if not name or etype not in self.VALID_ENTITY_TYPES:
                continue
            clean_entities.append({
                "entity_name": name,
                "entity_type": etype,
                "description": e.get("description", "")[:300],
            })
            valid_entity_names.add(name)

        raw_rels = result.get("relationships", [])
        clean_rels = []
        for r in raw_rels:
            if not isinstance(r, dict):
                continue
            src = r.get("src_id", "").strip()
            tgt = r.get("tgt_id", "").strip()
            if not src or not tgt:
                continue
            # 只保留 src/tgt 都通过 schema 校验的边
            if src not in valid_entity_names and tgt not in valid_entity_names:
                # 边指向 schema 不认的节点时，仍保留（LightRAG 会自动创建 UNKNOWN 端点）
                pass
            clean_rels.append({
                "src_id": src,
                "tgt_id": tgt,
                "description": r.get("description", "")[:200],
                "keywords": r.get("keywords", "related")[:50],
                "weight": float(r.get("weight", 1.0) or 1.0),
            })

        return {"entities": clean_entities, "relationships": clean_rels}

    def to_lightrag_kg(
        self,
        extraction: Dict[str, Any],
        message_id: str,
    ) -> Dict[str, Any]:
        """把抽取结果转成 ainsert_custom_kg 接受的 DICT。

        DICT 格式（已读 LightRAG/lightrag/lightrag.py:1655 验证）：
          chunks:        [{"content", "source_id"}]
          entities:      [{"entity_name", "entity_type", "description", "source_id"}]
          relationships: [{"src_id", "tgt_id", "description", "keywords", "weight", "source_id"}]

        entity_name 用作 Neo4j 主键（entity_id）→ 同名自动 MERGE 跨消息聚合。
        """
        source_id = f"mo_msg_{message_id}"
        return {
            "chunks": [{
                "content": f"[M.O. extraction source: {message_id}]",
                "source_id": source_id,
            }],
            "entities": [
                {
                    "entity_name": e["entity_name"],
                    "entity_type": e["entity_type"],
                    "description": e.get("description", ""),
                    "source_id": source_id,
                }
                for e in extraction.get("entities", [])
            ],
            "relationships": [
                {
                    "src_id": r["src_id"],
                    "tgt_id": r["tgt_id"],
                    "description": r.get("description", ""),
                    "keywords": r.get("keywords", "related"),
                    "weight": float(r.get("weight", 1.0) or 1.0),
                    "source_id": source_id,
                }
                for r in extraction.get("relationships", [])
            ],
        }

    def to_pg_entity_records(
        self,
        extraction: Dict[str, Any],
        message_id: str,
        source_channel: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """把抽取结果转成 PG `entities` 表写入格式。

        供 services/database.py:upsert_entity() 调用（同一 entity_name 跨消息自增）。
        返回 list of dict：
          {"entity_id": "ent_TOOL_xxxx", "entity_type": "TOOL",
           "raw_value": "云控脚本", "source_channel": "douyin", ...}
        """
        records = []
        for e in extraction.get("entities", []):
            name = e.get("entity_name", "").strip()
            etype = e.get("entity_type", "").strip().upper()
            if not name or etype not in self.VALID_ENTITY_TYPES:
                continue
            entity_id = f"ent_{etype.lower()}_{hashlib.md5(name.encode('utf-8')).hexdigest()[:12]}"
            records.append({
                "entity_id": entity_id,
                "entity_type": etype,
                "raw_value": name,
                "normalized_value": name,
                "occurrence_count": 1,
                "source_channel": source_channel,
                "risk_labels": [],
                "metadata": {
                    "description": e.get("description", "")[:300],
                    "source_message_id": message_id,
                },
            })
        return records
