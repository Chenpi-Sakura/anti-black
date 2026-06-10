"""
Classification module for AntiBlack pipeline.
Handles intent classification with rule/model/LLM三层分类.
"""
import asyncio
import concurrent.futures
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Absolute model directory — resolved once at import time so the retrain
# output lands in the right place regardless of CWD (e.g. someone running
# from scripts/ or any other directory).
_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'models', 'ml', 'assets',
)
# Also used by _load_embedding_model / _classify_by_rules etc.


# --- Layer 3: PacingSemaphore (rate-limited concurrency) ---
class _PacingSemaphore:
    """Combines a Semaphore (max concurrent) with a minimum interval between
    acquisitions. Used to throttle external LLM API calls so we don't burst
    against a rate-limited provider.

    `acquire()` waits for BOTH:
      - a free slot (semaphore)
      - the interval since the last successful acquire to elapse
    """

    def __init__(self, max_slots: int = 8, interval_sec: float = 1.0):
        self._sem = asyncio.Semaphore(max_slots)
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0
        self._interval = interval_sec

    async def __aenter__(self):
        await self._sem.acquire()
        async with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            self._next_allowed = max(now, self._next_allowed) + self._interval
        if wait > 0:
            await asyncio.sleep(wait)

    async def __aexit__(self, *exc):
        self._sem.release()


def _llm_pacing() -> _PacingSemaphore:
    """Module-level LLM pacing semaphore. Configurable via env."""
    global _pacing_sem
    if _pacing_sem is None:
        max_slots = int(os.environ.get("LLM_MAX_CONCURRENT", "8"))
        interval = float(os.environ.get("LLM_MIN_INTERVAL_SEC", "1.0"))
        _pacing_sem = _PacingSemaphore(max_slots=max_slots, interval_sec=interval)
    return _pacing_sem

_pacing_sem: Optional[_PacingSemaphore] = None


@dataclass
class ClassificationResult:
    """Classification result."""
    level1_label: str
    level2_label: str
    confidence: float
    source: str  # rule/model/llm
    reason: str


class ClassificationRule:
    """Single classification rule.

    V2 加固（防假阳性）：
    - patterns 是强词（任一出现即触发候选匹配）
    - co_occurrence_keywords 是弱词（必须至少 1 配才真正匹配）
    - 单字/双字高频日常词（私聊、加我）单独不触发，避免假阳性
    """

    def __init__(
        self,
        patterns: List[str],
        level1: str,
        level2: str,
        confidence: float = 0.9,
        co_occurrence_keywords: Optional[List[str]] = None,
        exclude_keywords: Optional[List[str]] = None,
    ):
        self.patterns = patterns
        self.level1 = level1
        self.level2 = level2
        self.confidence = confidence
        self.co_occurrence_keywords = co_occurrence_keywords or []
        self.exclude_keywords = exclude_keywords or []

    def match(self, text: str) -> bool:
        text_lower = text.lower()
        # 1) 强词必须至少 1 命中
        if not any(p in text_lower for p in self.patterns):
            return False
        # 2) 弱词必须至少 1 配
        if self.co_occurrence_keywords:
            if not any(w in text_lower for w in self.co_occurrence_keywords):
                return False
        # 3) 排除词不能出现
        if self.exclude_keywords:
            if any(e in text_lower for e in self.exclude_keywords):
                return False
        return True


class Classifier:
    """Multi-stage classifier with rule/model/LLM fallback."""

    # Predefined rules from taxonomy
    # V2 加固：高频弱词必须配对（co_occurrence_keywords），单字/双字
    # 日常词单独不触发，避免 IRRELEVANT/广告 误判。
    DEFAULT_RULES = [
        # ========== 账号交易 ==========
        ClassificationRule(
            patterns=['出号', '换绑', '租号', '抖号', '快手号', '微信号'],
            level1='账号交易',
            level2='账号买卖',
            confidence=0.95
        ),
        ClassificationRule(
            patterns=['抖音号买卖', '快手号出租', '账号转让'],
            level1='账号交易',
            level2='账号买卖',
            confidence=0.95
        ),
        ClassificationRule(
            patterns=['代实名', '代实名认证', '代过审', '实名代过'],
            level1='账号交易',
            level2='代实名服务',
            confidence=0.92
        ),

        # ========== 流量作弊 ==========
        ClassificationRule(
            patterns=['刷粉', '涨粉', '千粉', '万粉', '粉丝'],
            level1='流量作弊',
            level2='刷粉',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['刷赞', '点赞', '刷量'],
            level1='流量作弊',
            level2='刷赞',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['直播刷人气', '直播间人气', '挂人气', '直播挂'],
            level1='流量作弊',
            level2='直播刷量',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['互刷涨粉', '互关群', '互赞群', '互刷群'],
            level1='流量作弊',
            level2='互刷涨粉',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['刷评论', '刷弹幕', '刷留言'],
            level1='流量作弊',
            level2='刷评论',
            confidence=0.9
        ),

        # ========== 诈骗引流 ==========
        ClassificationRule(
            patterns=['刷单', '兼职', '佣金'],
            level1='诈骗引流',
            level2='刷单引流',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['杀猪盘', '投资', '导师'],
            level1='诈骗引流',
            level2='杀猪盘',
            confidence=0.85
        ),
        ClassificationRule(
            patterns=['兼职日结', '点赞兼职', '关注兼职', '刷单兼职'],
            level1='诈骗引流',
            level2='兼职诈骗',
            confidence=0.9
        ),
        # V2 加固：私域 + 弱词配对
        ClassificationRule(
            patterns=['私域引流', '私域变现', '引流变现', '私域运营', '私域'],
            co_occurrence_keywords=['加粉', '引粉', '拉群', '微信群', '加微'],
            level1='诈骗引流',
            level2='私域引流',
            confidence=0.88
        ),
        ClassificationRule(
            patterns=['灰产加盟', '灰产项目', '招下线', '诚邀加盟'],
            level1='诈骗引流',
            level2='灰产加盟',
            confidence=0.9
        ),

        # ========== 黑产工具 ==========
        ClassificationRule(
            patterns=['接码', '验证码', '手机号'],
            level1='黑产工具',
            level2='接码平台',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['矩阵号', '矩阵养号', '批量注册', '群控矩阵'],
            level1='黑产工具',
            level2='矩阵号',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['群控', '脚本', '自动化'],
            exclude_keywords=['矩阵号'],
            level1='黑产工具',
            level2='群控工具',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['改机工具', '改机软件', '机型伪装', '串改imei', '串号伪装'],
            level1='黑产工具',
            level2='改机工具',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['ip池', '猫池', 'ip代理', '动态ip', 'ip轮换'],
            level1='黑产工具',
            level2='IP池/猫池',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['云手机', '批量脚本', '自动化群控', '云控'],
            level1='黑产工具',
            level2='自动化脚本',
            confidence=0.88
        ),

        # ========== 灰产洗钱 ==========
        ClassificationRule(
            patterns=['跑分', '跑分平台', '跑分兼职', '跑分赚钱', '跑分日结'],
            level1='灰产洗钱',
            level2='跑分洗钱',
            confidence=0.92
        ),
        ClassificationRule(
            patterns=['四件套', '银行卡四件套', 'u盾四件套', '网银四件套'],
            level1='灰产洗钱',
            level2='四件套交易',
            confidence=0.92
        ),
        ClassificationRule(
            patterns=['代收代付', '对公账户代收', '海外代收', 'u商代收'],
            level1='灰产洗钱',
            level2='代收代付',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['口令红包', '微信口令', '抢口令', '口令'],
            level1='灰产洗钱',
            level2='口令红包',
            confidence=0.88
        ),
        ClassificationRule(
            patterns=['洗钱通道', '跑分通道', 'u商', '对公账户'],
            level1='灰产洗钱',
            level2='洗钱通道',
            confidence=0.85
        ),

        # ========== 无关（IRRELEVANT）==========
        # V2 加固：噪声强词单独即可（无歧义）
        ClassificationRule(
            patterns=['测试一下', '哈哈', '呵呵', '啊啊', '哦哦', '嘻嘻', '呵呵呵'],
            level1='无关',
            level2='噪声数据',
            confidence=0.9
        ),
        # 强词：广招代理/诚招代理/高佣 → 直接判定
        ClassificationRule(
            patterns=['广招代理', '诚招代理', '高佣', '诚邀加入'],
            co_occurrence_keywords=['加我', 'v我', '私聊', '私信'],
            level1='无关',
            level2='广告推广',
            confidence=0.85
        ),
        # 弱词配对：游戏强词但必须无黑产强词
        ClassificationRule(
            patterns=['王者荣耀开黑', '吃鸡上分', '原神开荒', 'steam联机'],
            co_occurrence_keywords=['王者荣耀', '吃鸡', '原神', 'steam'],
            exclude_keywords=['跑分', '代收', '日结', '口令', '私域', '刷粉', '万粉', '刷量', '改机', 'ip池', '矩阵', '代实名', '群控', '接码'],
            level1='无关',
            level2='不相关游戏/新闻',
            confidence=0.85
        ),
    ]

    def __init__(self, config: Dict[str, Any] = None, rules: List[ClassificationRule] = None):
        self.config = config or {}
        self.rules = rules or self.DEFAULT_RULES
        self.rule_threshold = self.config.get('classification', {}).get('rule_confidence_threshold', 0.7)
        self.embedding_threshold = self.config.get('classification', {}).get('embedding_confidence_threshold', 0.6)
        self.llm_threshold = self.config.get('classification', {}).get('llm_fallback_confidence', 0.6)

        # Load trained embedding classifier if exists
        self._embedding_clf = None
        self._embedding_le = None
        self._load_embedding_model()

    # Standard level1 labels (single source of truth)
    # V3 重构：6 有效 L1 + 未知/其他（情报有价值但分不出来）+ 无关（纯垃圾）
    # V2 命名空间对齐：全链路用中文 Name
    LEVEL1_LABELS = ('账号交易', '流量作弊', '诈骗引流', '黑产工具', '灰产洗钱', '未知/其他', '无关')

    # V4: canonical level2 names per level1 (used by reclassify_unknown.py
    # to validate LLM output and reject free-form labels).
    # Single source of truth — keep in sync with config.yaml taxonomy block.
    CANONICAL_LEVEL2 = {
        '账号交易': {'账号买卖', '账号租借', '账号转让', '代实名服务'},
        '流量作弊': {'刷粉', '刷赞', '刷播放量', '直播刷量', '互刷涨粉', '刷评论'},
        '诈骗引流': {'刷单引流', '杀猪盘', '兼职诈骗', '私域引流', '灰产加盟'},
        '黑产工具': {'接码平台', '群控工具', '改机工具', 'IP池/猫池', '矩阵号', '自动化脚本'},
        '灰产洗钱': {'跑分洗钱', '四件套交易', '代收代付', '口令红包', '洗钱通道'},
        '未知/其他': {'未分类'},
        '无关': {'噪声数据', '广告推广', '个人闲聊', '不相关游戏/新闻'},
    }

    @staticmethod
    def _normalize_level1_label(label: str) -> str:
        """Map any dirty variant of a level1 label to its canonical form.

        Handles LLM-side pollution like '账号交易 (Account Trading)' or
        'Unknown/Other' that previously leaked into the clues table and
        bloated the LabelEncoder's class space.
        """
        if not label:
            return '未知/其他'
        stripped = label.strip()
        if '账号交易' in stripped or 'Account Trading' in stripped:
            return '账号交易'
        if '流量作弊' in stripped or 'Traffic Cheating' in stripped:
            return '流量作弊'
        if '诈骗引流' in stripped or 'Fraud Leads' in stripped:
            return '诈骗引流'
        if '黑产工具' in stripped or 'Black-market Tools' in stripped:
            return '黑产工具'
        if 'Unknown' in stripped or '未分类' in stripped or stripped == '其他':
            return '未知/其他'
        if stripped in Classifier.LEVEL1_LABELS:
            return stripped
        return '未知/其他'

    def _load_embedding_model(self):
        """Load trained sklearn classifier for embedding-based classification."""
        import os
        import joblib

        # Find latest classifier model
        models_dir = _MODEL_DIR
        if not os.path.exists(models_dir):
            return

        pkl_files = [f for f in os.listdir(models_dir) if f.startswith('classifier_v') and f.endswith('.pkl')]
        if not pkl_files:
            # Fallback to xgboost models
            xgb_clf = os.path.join(_MODEL_DIR, 'xgboost_classifier.pkl')
            xgb_le = os.path.join(_MODEL_DIR, 'xgboost_classifier_label_encoder.pkl')
            if os.path.exists(xgb_clf) and os.path.exists(xgb_le):
                try:
                    self._embedding_clf = joblib.load(xgb_clf)
                    self._embedding_le = joblib.load(xgb_le)
                    logger.info("Loaded xgboost embedding classifier")
                except Exception as e:
                    logger.warning(f"Failed to load xgboost models: {e}")
            return

        # Load latest version
        pkl_files.sort(reverse=True)
        try:
            model_data = joblib.load(os.path.join(models_dir, pkl_files[0]))
            self._embedding_clf = model_data.get('model')
            self._embedding_le = model_data.get('label_encoder')
            if self._embedding_clf and self._embedding_le:
                logger.info(f"Loaded embedding classifier: {pkl_files[0]}")
        except Exception as e:
            logger.warning(f"Failed to load embedding model: {e}")

    def classify(self, text: str, context: Dict[str, Any] = None) -> ClassificationResult:
        """
        Classify text using three-stage classification.

        1. Rule-based (fast, high confidence for clear patterns)
        2. Embedding model (medium confidence)
        3. LLM fallback (low confidence or ambiguous cases)
        """
        context = context or {}

        # Stage 1: Rule classification
        result = self._classify_by_rules(text)
        if result and result.confidence >= self.rule_threshold:
            logger.debug(f"Rule classification: {result.level1_label}/{result.level2_label}")
            return self._normalize_result(result)

        # Stage 2: Embedding model (simplified for demo)
        result = self._classify_by_embedding(text, context)
        if result and result.confidence >= self.embedding_threshold:
            logger.debug(f"Embedding classification: {result.level1_label}/{result.level2_label}")
            return self._normalize_result(result)

        # Stage 3: LLM fallback (return unknown if LLM not available)
        result = self._classify_by_llm(text, context)
        if result:
            logger.debug(f"LLM classification: {result.level1_label}/{result.level2_label}")
            return self._normalize_result(result)

        # Default to unknown
        return ClassificationResult(
            level1_label='未知/其他',
            level2_label='未分类',
            confidence=0.5,
            source='rule',
            reason='未匹配到明确风险类型'
        )

    def _normalize_result(self, result: ClassificationResult) -> ClassificationResult:
        """Return a new ClassificationResult with a canonical level1 label."""
        if result.level1_label in self.LEVEL1_LABELS:
            return result
        return ClassificationResult(
            level1_label=self._normalize_level1_label(result.level1_label),
            level2_label=result.level2_label or "未分类",
            confidence=result.confidence,
            source=result.source,
            reason=result.reason,
        )

    def _classify_by_rules(self, text: str) -> Optional[ClassificationResult]:
        """Classify using predefined rules."""
        text_lower = text.lower()

        for rule in self.rules:
            if rule.match(text_lower):
                return ClassificationResult(
                    level1_label=rule.level1,
                    level2_label=rule.level2,
                    confidence=rule.confidence,
                    source='rule',
                    reason=f'命中规则: {rule.patterns}'
                )

        return None

    def _classify_by_embedding(self, text: str, context: Dict[str, Any]) -> Optional[ClassificationResult]:
        """
        Classify using embedding model (Ollama bge-m3 + sklearn classifier).
        Falls back to None if model not available or Ollama unreachable.

        Single-text path used by `classify()` (API server). For batched
        calls from the daemon hot path, use `_classify_by_embedding_batch`.
        """
        if not self._embedding_clf or not self._embedding_le:
            return None

        try:
            import httpx
            import numpy as np

            # Get embedding from Ollama
            OLLAMA_API_URL = "http://localhost:11434/api/embed"
            EMBEDDING_MODEL = "bge-m3"

            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    OLLAMA_API_URL,
                    json={"model": EMBEDDING_MODEL, "input": [text]}
                )
                response.raise_for_status()
                embeddings = response.json().get('embeddings', [])
                if not embeddings or len(embeddings) == 0:
                    return None

                embedding = np.array(embeddings[0], dtype=np.float32).reshape(1, -1)

            # Predict using sklearn classifier
            label_idx = self._embedding_clf.predict(embedding)[0]
            labels = self._embedding_le.inverse_transform([label_idx])
            label = labels[0]

            # Get confidence from probability
            proba = self._embedding_clf.predict_proba(embedding)[0]
            confidence = float(proba[label_idx])

            # Map label to level1/level2
            level1, level2 = self._map_label_to_taxonomy(label)

            return ClassificationResult(
                level1_label=level1,
                level2_label=level2,
                confidence=confidence,
                source='embedding',
                reason=f'embedding model prediction, label={label}'
            )

        except Exception as e:
            logger.debug(f"Embedding classification failed: {e}")
            return None

    async def _classify_by_embedding_batch(
        self, texts: List[str], context: Dict[str, Any]
    ) -> List[Optional[ClassificationResult]]:
        """Batched Stage 2: ONE async Ollama call for all texts.

        Replaces N sync HTTP calls (one per text in `_classify_by_embedding`)
        with 1 async HTTP call that sends the full list. Saves ~3-4s per
        20-text batch on the daemon hot path (eliminates N round-trips
        + serial event-loop blocking).

        Returns N ClassificationResults, one per input text (None for
        texts that failed embedding or predict). Caller decides whether
        to send a None-result text on to Stage 3 (LLM).

        Failure semantics differ from per-text version: if the Ollama
        call itself fails, ALL texts in the batch return None and fall
        through to LLM. Per-text failures during predict are isolated.
        """
        if not self._embedding_clf or not self._embedding_le or not texts:
            return [None] * len(texts)

        try:
            import httpx
            import numpy as np

            OLLAMA_API_URL = "http://localhost:11434/api/embed"
            EMBEDDING_MODEL = "bge-m3"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    OLLAMA_API_URL,
                    json={"model": EMBEDDING_MODEL, "input": texts}
                )
                response.raise_for_status()
                embeddings = response.json().get('embeddings', [])

            if not embeddings or len(embeddings) != len(texts):
                logger.warning(
                    f"Embedding batch: got {len(embeddings) if embeddings else 0} "
                    f"embeddings, expected {len(texts)}"
                )
                return [None] * len(texts)

            # Vectorized predict: one numpy matrix + two sklearn calls
            # for the whole batch (sklearn's C backend batches internally).
            X_emb = np.array(embeddings, dtype=np.float32)  # (N, dim)
            try:
                all_label_idxs = self._embedding_clf.predict(X_emb)
                all_probas = self._embedding_clf.predict_proba(X_emb)
                all_labels = self._embedding_le.inverse_transform(all_label_idxs)
            except Exception as e:
                logger.warning(f"Embedding batch predict failed: {e}")
                return [None] * len(texts)

            results: List[Optional[ClassificationResult]] = []
            # Phase 2 open-set: use reject/margin thresholds to flag low-confidence
            # predictions so the caller can fall back to LLM even if the raw
            # embedding confidence is above embedding_threshold.
            reject_thresh = self.config.get('classification', {}).get('embedding_reject_threshold', 0.45)
            margin_thresh = self.config.get('classification', {}).get('embedding_margin_threshold', 0.12)
            for i in range(len(texts)):
                label = all_labels[i]
                proba_row = all_probas[i]
                confidence = float(proba_row[all_label_idxs[i]])
                max_proba = float(np.max(proba_row))
                sorted_proba = np.sort(proba_row)
                margin = float(max_proba - sorted_proba[-2]) if len(sorted_proba) >= 2 else max_proba
                uncertain = max_proba < reject_thresh or margin < margin_thresh
                level1, level2 = self._map_label_to_taxonomy(label)
                results.append(ClassificationResult(
                    level1_label=level1,
                    level2_label=level2,
                    confidence=confidence,
                    source='embedding_uncertain' if uncertain else 'embedding',
                    reason=(
                        f'embedding uncertain (max_proba={max_proba:.3f} '
                        f'margin={margin:.3f}) for label={label}'
                    ) if uncertain else f'embedding model prediction, label={label}',
                ))
            return results
        except Exception as e:
            logger.warning(f"Embedding batch classification failed: {e}")
            return [None] * len(texts)

    def _map_label_to_taxonomy(self, label: str) -> Tuple[str, str]:
        """Map embedding model label to taxonomy level1/level2.

        Mirrors config.yaml taxonomy. Falls back to ('未知/其他', '未分类')
        for any label that isn't a known level1 (e.g. legacy dirty variants
        that the LabelEncoder hadn't seen yet).
        """
        label_map = {
            '账号交易': ('账号交易', '账号买卖'),
            '账号买卖': ('账号交易', '账号买卖'),
            '账号转让': ('账号交易', '账号转让'),
            '账号租借': ('账号交易', '账号租借'),
            '抖音号买卖': ('账号交易', '账号买卖'),
            '流量作弊': ('流量作弊', '刷粉刷赞'),
            '刷粉': ('流量作弊', '刷粉'),
            '刷赞': ('流量作弊', '刷赞'),
            '刷量': ('流量作弊', '刷量'),
            '刷播放量': ('流量作弊', '刷量'),
            '诈骗引流': ('诈骗引流', '刷单引流'),
            '刷单': ('诈骗引流', '刷单引流'),
            '杀猪盘': ('诈骗引流', '杀猪盘'),
            '兼职诈骗': ('诈骗引流', '兼职诈骗'),
            '黑产工具': ('黑产工具', '接码平台'),
            '接码': ('黑产工具', '接码平台'),
            '群控': ('黑产工具', '群控工具'),
            '未知/其他': ('未知/其他', '未分类'),
        }
        if label in label_map:
            return label_map[label]
        # Try to salvage dirty variants via the normalizer
        normalized = self._normalize_level1_label(label)
        return label_map.get(normalized, ('未知/其他', '未分类'))

    def _classify_by_llm(self, text: str, context: Dict[str, Any]) -> Optional[ClassificationResult]:
        """
        Classify using LLM fallback (via unified LLMClient with multi-provider chain).
        FR-EVO-01: Collect high-confidence LLM output as silver training sample.
        """
        import os
        import json
        from models.clients.llm import LLMClient, AllProvidersExhausted

        prompt = f"""你是一个黑灰产情报分类专家。本系统聚焦【字节系黑灰产】（抖音/TikTok/头条/西瓜/飞书/豆包/剪映）。

分析以下文本，判断它属于哪种风险类型。优先看"行话暗号 + 交易特征"，不要因为字面直白就否定。

【风险类别与子类】：

1. 账号交易
   - 账号买卖: 出号、换绑、租号、抖号买卖
   - 代实名服务: 代实名、代过审
2. 流量作弊
   - 刷粉: 刷粉、涨粉、千粉、万粉
   - 刷赞: 刷赞、刷量
   - 直播刷量: 直播刷人气、挂人气
   - 互刷涨粉: 互关群、互刷群
   - 刷评论: 刷评论、刷弹幕
3. 诈骗引流
   - 刷单引流: 刷单、佣金
   - 杀猪盘: 投资、导师
   - 兼职诈骗: 兼职日结、点赞兼职
   - 私域引流: 私域 + 加粉/拉群（必须配对，单字"私域"无效）
   - 灰产加盟: 招下线、诚邀加盟
4. 黑产工具
   - 接码平台: 接码、验证码
   - 群控工具: 群控、脚本
   - 改机工具: 改机、机型伪装
   - IP池/猫池: IP池、猫池、IP代理
   - 矩阵号: 矩阵号、批量注册
   - 自动化脚本: 云手机、批量脚本
5. 灰产洗钱
   - 跑分洗钱: 跑分日结、跑分兼职
   - 四件套交易: 银行卡四件套、U盾四件套
   - 代收代付: 代收代付、对公账户
   - 口令红包: 口令红包、抢口令
   - 洗钱通道: 洗钱通道、U商
6. 未知/其他 - 情报有价值但模型无法分类
7. 无关 - 纯垃圾：纯聊天、广告推广、新闻、不相关游戏

【关键判断】：
- "未知/其他" = 情报有价值但分不出来（保留供人工 review）
- "无关" = 纯垃圾（应被过滤）
- 单字/双字高频日常词（"私聊"、"加我"、"私信"）单独不构成风险判断
- 字面直白的高频交易词（"万粉号"、"出号"）在黑产语境下是有效特征

【Few-Shot 示例】：
"出抖号" → 账号交易/账号买卖
"万粉号出" → 账号交易/账号买卖
"刷粉找小妹" → 流量作弊/刷粉
"直播刷人气找我" → 流量作弊/直播刷量
"跑分日结找我" → 灰产洗钱/跑分洗钱
"四件套出售" → 灰产洗钱/四件套交易
"IP池便宜" → 黑产工具/IP池/猫池
"矩阵号群控" → 黑产工具/矩阵号
"私域加粉拉群" → 诈骗引流/私域引流
"代实名找我" → 账号交易/代实名服务
"做自媒体 活跃账号" → 无关/噪声数据
"王者荣耀开黑" → 无关/不相关游戏/新闻
"今天天气真好" → 无关/噪声数据

文本: {text}

仅返回JSON格式的分类结果，不要包含其他内容：
{{"level1": "类别名", "level2": "子类别", "confidence": 0.0-1.0, "reason": "判断理由"}}"""

        logger.info(f"[LLM Call] Triggering Classifier Fallback for text: {text[:30]}...")

        try:
            # The classify() method is sync; LLMClient is async. Use the same
            # new-event-loop-in-threadpool workaround as before, but invoke
            # the new LLMClient (which handles multi-provider fallback internally).
            import concurrent.futures
            client = LLMClient(timeout=30)
            def _call_llm_sync():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    async def fetch():
                        return await client.complete(
                            prompt=prompt,
                            max_tokens=512,
                            extra_body={"reasoning_effort": "low"},
                        )
                    return loop.run_until_complete(fetch())
                finally:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()

            with concurrent.futures.ThreadPoolExecutor() as executor:
                # LLMClient already strips <|think_start|>/<think> tags in chat()
                result_text = executor.submit(_call_llm_sync).result(timeout=60)

            # Extract JSON
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if not json_match:
                logger.warning(f"LLM classification parse failed for: {text[:50]}")
                return None

            result = json.loads(json_match.group())

            # Build ClassificationResult
            level1_label = result.get('level1', '未知/其他')
            level2_label = result.get('level2', '未分类')
            confidence = max(0.0, min(1.0, float(result.get('confidence', 0.5))))

            classification_result = ClassificationResult(
                level1_label=level1_label,
                level2_label=level2_label,
                confidence=confidence,
                source='llm',
                reason=result.get('reason', '')
            )

            # FR-EVO-01: Collect silver sample if high confidence
            if confidence >= 0.8:
                try:
                    from services.database import PostgreSQLService
                    db = PostgreSQLService.get_instance()
                    db.insert_training_sample({
                        'text': text,
                        'label': level1_label,
                        'label_source': 'silver',
                        'confidence': confidence,
                        'collection_context': 'llm_fallback'
                    })
                    logger.debug(f"Collected silver sample: {text[:50]}...")
                except Exception as e:
                    logger.warning(f"Failed to collect silver sample: {e}")

            if classification_result is not None:
                classification_result = self._normalize_result(classification_result)
            return classification_result

        except AllProvidersExhausted as e:
            logger.error(f"All LLM providers failed during classification: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM classification failed: {e}")
            return None

    async def classify_batch(self, texts: List[str], context: Dict[str, Any] = None) -> List[ClassificationResult]:
        """Classify N texts using 3-stage cascade: rule → embedding → batched LLM.

        Stage 1 (rules, fast, no network): per-text regex/keyword match.
        Stage 2 (embedding, medium confidence): one batched Ollama call for all
          texts that didn't match rules (was: per-text sync call).
        Stage 3 (LLM, rate-limited + batched): texts that need LLM are
          sent 5-10 at a time in a single LLM call, with `_llm_pacing()`
          ensuring at most `LLM_MAX_CONCURRENT` concurrent and
          `LLM_MIN_INTERVAL_SEC` minimum interval between new LLM calls.

        Returns N ClassificationResults, one per input text.
        """
        from models.clients.llm import LLMClient, AllProvidersExhausted
        n = len(texts)
        results: List[Optional[ClassificationResult]] = [None] * n

        # Stage 1: rules (fast, no network) — try each text
        for i, text in enumerate(texts):
            r = self._classify_by_rules(text)
            if r and r.confidence >= self.rule_threshold:
                results[i] = r

        # Stage 2: embedding (medium confidence) — ONE batched Ollama call
        needs_llm: List[int] = []
        needs_embedding = [i for i in range(n) if results[i] is None]
        if needs_embedding:
            embed_texts = [texts[i] for i in needs_embedding]
            embed_results = await self._classify_by_embedding_batch(embed_texts, context)
            for j, idx in enumerate(needs_embedding):
                r = embed_results[j]
                # Phase 2 open-set: if embedding flagged itself as uncertain
                # (max_proba < reject_thresh or margin < margin_thresh), force
                # fallback to LLM even if raw confidence is above the threshold.
                uncertain = r is not None and r.source == 'embedding_uncertain'
                if r and r.confidence >= self.embedding_threshold and not uncertain:
                    results[idx] = r
                else:
                    needs_llm.append(idx)

        # Stage 3: rate-limited + batched LLM for remaining
        if needs_llm:
            # timeout=120s: allow volcengine enough time for 4-text prompts.
            # max_retries=2: internal retry on transient (timeout/5xx) errors.
            # Rate limit is gated by the outer _PacingSemaphore — these are
            # independent concerns (concurrency throttle vs per-call resilience).
            client = LLMClient(timeout=120, max_retries=2)
            llm_texts = [texts[i] for i in needs_llm]
            pacing = _llm_pacing()

            async def one_chunk_call(chunk: List[str]) -> List[str]:
                """One rate-limited batched LLM call. Returns N JSON dict strings."""
                async with pacing:  # rate-limited: max N concurrent, 1s between starts
                    return await client.classify_batch(
                        chunk,
                        system_prompt=(
                            "你是一个黑灰产情报分类专家。"
                            "对每条文本独立判断它属于哪种风险类型。"
                        ),
                        batch_size=4,  # 4 texts per LLM call (was 8; smaller = faster)
                        extra_body={"reasoning_effort": "low"},
                    )

            # Split into chunks of 4 (LLM_BATCH)
            LLM_BATCH = 4
            chunked = [llm_texts[i:i + LLM_BATCH] for i in range(0, len(llm_texts), LLM_BATCH)]
            # Launch all chunks in parallel; pacing throttles the start rate
            chunk_results = await asyncio.gather(*[one_chunk_call(c) for c in chunked], return_exceptions=True)
            llm_raw_results: List[str] = []
            for cr in chunk_results:
                if isinstance(cr, Exception):
                    logger.error(f"LLM chunk failed: {cr}", exc_info=True)
                    continue
                llm_raw_results.extend(cr)

            for j, raw in enumerate(llm_raw_results):
                original_idx = needs_llm[j]
                if not raw or raw == "{}":
                    results[original_idx] = ClassificationResult(
                        level1_label="未知/其他", level2_label="未分类",
                        confidence=0.5, source="rule",
                        reason="LLM batched classify returned no result",
                    )
                    continue
                try:
                    d = json.loads(raw)
                except json.JSONDecodeError:
                    results[original_idx] = ClassificationResult(
                        level1_label="未知/其他", level2_label="未分类",
                        confidence=0.5, source="rule",
                        reason=f"LLM batched JSON parse failed: {raw[:100]!r}",
                    )
                    continue
                results[original_idx] = ClassificationResult(
                    level1_label=d.get("level1", "未知/其他") or "未知/其他",
                    level2_label=d.get("level2", "未分类") or "未分类",
                    confidence=max(0.0, min(1.0, float(d.get("confidence", 0.5) or 0.5))),
                    source="llm",
                    reason=d.get("reason", ""),
                )

        # Default for any remaining None (shouldn't happen)
        for i in range(n):
            if results[i] is None:
                results[i] = ClassificationResult(
                    level1_label="未知/其他", level2_label="未分类",
                    confidence=0.5, source="rule",
                    reason="No classification path succeeded",
                )

        # Normalize all level1 labels to canonical form (prevent dirty labels
        # from polluting the clues table and the next retrain's LabelEncoder)
        for i in range(n):
            r = results[i]
            if r is not None:
                results[i] = ClassificationResult(
                    level1_label=self._normalize_level1_label(r.level1_label),
                    level2_label=r.level2_label or "未分类",
                    confidence=r.confidence,
                    source=r.source,
                    reason=r.reason,
                )
        return results  # type: ignore

    # ========== FR-EVO-03: Model Retraining ==========

    async def _get_ollama_embeddings(self, texts: List[str], batch_size: int = 64):
        """Call Ollama API to get embeddings (bge-m3, 1024 dimensions)."""
        import httpx
        import numpy as np

        OLLAMA_API_URL = "http://localhost:11434/api/embed"
        EMBEDDING_MODEL = "bge-m3"

        all_embeddings = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i + batch_size]
                try:
                    response = await client.post(
                        OLLAMA_API_URL,
                        json={"model": EMBEDDING_MODEL, "input": batch_texts}
                    )
                    response.raise_for_status()
                    batch_embeddings = response.json().get('embeddings', [])
                    all_embeddings.extend(batch_embeddings)
                except Exception as e:
                    logger.error(f"Ollama embedding failed for batch {i}: {e}")
                    # Return zero embeddings as fallback
                    all_embeddings.extend([[0.0] * 1024 for _ in batch_texts])

        return np.array(all_embeddings, dtype=np.float32)

    async def retrain(self, train_data: Dict[str, Any]) -> Optional[str]:
        """
        Lightweight retraining: Ollama extracts features + sklearn LogisticRegression.
        FR-EVO-03: Returns new model version on success, None on failure.

        Features:
        - Ollama (bge-m3 1024-dim) instead of sentence-transformers
        - sklearn LogisticRegression natively supports sample_weight
        - Macro F1 evaluation gate: improvement < 2% means no deployment
        """
        import os
        import joblib
        from datetime import datetime
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import f1_score
        from sklearn.preprocessing import LabelEncoder
        from sklearn.linear_model import LogisticRegression

        texts = train_data['texts']
        labels = train_data['labels']
        weights = train_data.get('weights', [1.0] * len(labels))

        if len(texts) < 100:
            logger.warning("Insufficient training samples (< 100), skipping retrain")
            return None

        try:
            # 1. Get Ollama embeddings
            logger.info(f"Extracting Ollama embeddings for {len(texts)} texts...")
            embeddings = await self._get_ollama_embeddings(texts)

            # 2. Encode labels
            le = LabelEncoder()
            y = le.fit_transform(labels)

            # 3. Split data (use stratify only when every class has >= 2 members)
            import numpy as np
            unique, counts = np.unique(y, return_counts=True)
            stratify = y if counts.min() >= 2 else None
            if stratify is None:
                logger.warning(f"Some classes have < 2 members (class distribution: {dict(zip(unique.tolist(), counts.tolist()))}); using non-stratified split")
            X_train, X_test, y_train, y_test, w_train, w_test = train_test_split(
                embeddings, y, weights, test_size=0.2, stratify=stratify, random_state=42
            )

            # 4. Train sklearn LogisticRegression with sample weights
            logger.info("Training LogisticRegression classifier...")
            clf = LogisticRegression(max_iter=1000, class_weight='balanced')
            clf.fit(X_train, y_train, sample_weight=w_train)

            # 5. Macro F1 evaluation gate
            y_pred = clf.predict(X_test)
            macro_f1 = f1_score(y_test, y_pred, average='macro')

            min_improvement = self.config.get('auto_evolution', {}).get('retrain', {}).get('min_f1_improvement', 0.02)
            current_f1 = getattr(self, '_current_f1', 0.0)
            improvement = macro_f1 - current_f1

            if improvement < min_improvement:
                logger.warning(f"Macro F1 improvement ({improvement:.2%}) below threshold, skipping deploy")
                return None

            # 6. Save and hot swap
            version = datetime.now().strftime('%Y%m%d_%H%M%S')
            model_path = os.path.join(_MODEL_DIR, f"classifier_v{version}.pkl")
            os.makedirs(_MODEL_DIR, exist_ok=True)

            joblib.dump({
                'model': clf,
                'label_encoder': le,
                'macro_f1': macro_f1,
                'version': version
            }, model_path)

            self._current_f1 = macro_f1

            # 7. Update classifier model singleton if available
            try:
                from models.ml.classifier import ClassifierModel
                cm = ClassifierModel.get_instance()
                cm.hot_swap(model_path)
            except Exception as e:
                logger.warning(f"ClassifierModel hot_swap failed: {e}")

            logger.info(f"Retrain completed and hot-swapped: version={version}, Macro F1={macro_f1:.4f}")
            return version

        except Exception as e:
            logger.error(f"Retrain failed: {e}", exc_info=True)
            return None


def build_taxonomy_mapping(taxonomy_config: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Build taxonomy lookup from config."""
    mapping = {}

    for category in taxonomy_config.get('categories', []):
        level1_code = category.get('level1_code', '')
        level1_name = category.get('level1_name', '')

        for item in category.get('level2_items', []):
            level2_code = item.get('level2_code', '')
            level2_name = item.get('level2_name', '')

            mapping[level1_code] = {
                'name': level1_name,
                'level2': {
                    level2_code: level2_name
                }
            }

    return mapping


# Module-level Classifier singleton cache.
# Without this, each call to Classifier(config={}) in SlangToRuleBridge
# re-unpickles the embedding model from disk, causing redundant I/O.
import threading as _threading
_CLASSIFIER_INSTANCE: Optional[Classifier] = None
_CLASSIFIER_CONFIG: Optional[Dict[str, Any]] = None
_CLASSIFIER_LOCK = _threading.Lock()


def get_shared_classifier(config: Dict[str, Any] = None) -> Classifier:
    """Return a shared Classifier instance (cached at module level).

    CONFIG IS ONLY USED ON THE FIRST CALL. Subsequent calls with a
    different `config` argument are silently ignored — the cached
    instance from the first call is returned. Callers that genuinely
    need a different config (different rule threshold, embedding
    thresholds, etc.) must construct a fresh `Classifier(config)`
    directly without going through this helper.

    This design exists because:
      1. The embedding model pkl (50KB joblib) is the expensive part.
         Sharing it across all callers saves disk + unpickle I/O.
      2. Stage-1 rules and CANONICAL_LEVEL2 are class attributes
         (not instance), so config differences only matter for
         rule_threshold / embedding_threshold / llm_threshold — which
         are set at construction time and rarely differ between callers.

    If you pass a different config after the singleton was built, a
    warning is logged once so the silent override is at least visible.

    Double-checked locking: the inner check guards against two threads
    both passing the outer None check and each constructing a separate
    Classifier (which would unpickle the model twice).
    """
    global _CLASSIFIER_INSTANCE, _CLASSIFIER_CONFIG
    if _CLASSIFIER_INSTANCE is None:
        with _CLASSIFIER_LOCK:
            if _CLASSIFIER_INSTANCE is None:
                _CLASSIFIER_INSTANCE = Classifier(config or {})
                _CLASSIFIER_CONFIG = config or {}
    elif config and config != _CLASSIFIER_CONFIG:
        logger.warning(
            f"get_shared_classifier called with config={config!r} but "
            f"singleton was already built with config={_CLASSIFIER_CONFIG!r}; "
            f"ignoring new config. Construct a fresh Classifier() if you "
            f"need different rule/embedding/llm thresholds."
        )
    return _CLASSIFIER_INSTANCE