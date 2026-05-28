"""
Classification module for AntiBlack pipeline.
Handles intent classification with rule/model/LLM三层分类.
"""
import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Classification result."""
    level1_label: str
    level2_label: str
    confidence: float
    source: str  # rule/model/llm
    reason: str


class ClassificationRule:
    """Single classification rule."""

    def __init__(self, patterns: List[str], level1: str, level2: str, confidence: float = 0.9):
        self.patterns = patterns
        self.level1 = level1
        self.level2 = level2
        self.confidence = confidence

    def match(self, text: str) -> bool:
        """Check if text matches this rule."""
        for pattern in self.patterns:
            if pattern in text.lower():
                return True
        return False


class Classifier:
    """Multi-stage classifier with rule/model/LLM fallback."""

    # Predefined rules from taxonomy
    DEFAULT_RULES = [
        # Account trading rules
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
        # Traffic cheating rules
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
        # Fraud rules
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
        # Black tools rules
        ClassificationRule(
            patterns=['接码', '验证码', '手机号'],
            level1='黑产工具',
            level2='接码平台',
            confidence=0.9
        ),
        ClassificationRule(
            patterns=['群控', '脚本', '自动化'],
            level1='黑产工具',
            level2='群控工具',
            confidence=0.9
        ),
    ]

    def __init__(self, config: Dict[str, Any] = None, rules: List[ClassificationRule] = None):
        self.config = config or {}
        self.rules = rules or self.DEFAULT_RULES
        self.rule_threshold = self.config.get('classification', {}).get('rule_confidence_threshold', 0.9)
        self.embedding_threshold = self.config.get('classification', {}).get('embedding_confidence_threshold', 0.6)
        self.llm_threshold = self.config.get('classification', {}).get('llm_fallback_confidence', 0.6)

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
            return result

        # Stage 2: Embedding model (simplified for demo)
        result = self._classify_by_embedding(text, context)
        if result and result.confidence >= self.embedding_threshold:
            logger.debug(f"Embedding classification: {result.level1_label}/{result.level2_label}")
            return result

        # Stage 3: LLM fallback (return unknown if LLM not available)
        result = self._classify_by_llm(text, context)
        if result:
            logger.debug(f"LLM classification: {result.level1_label}/{result.level2_label}")
            return result

        # Default to unknown
        return ClassificationResult(
            level1_label='未知/其他',
            level2_label='未分类',
            confidence=0.5,
            source='rule',
            reason='未匹配到明确风险类型'
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
        Classify using embedding model.
        In production, this would use a trained classifier on embeddings.
        For demo, we simulate with lower confidence.
        """
        # In production: use sentence-transformers + trained classifier
        # For demo: return None to fall back to LLM
        return None

    def _classify_by_llm(self, text: str, context: Dict[str, Any]) -> Optional[ClassificationResult]:
        """
        Classify using LLM fallback.
        FR-EVO-01: Collect high-confidence LLM output as silver training sample.
        """
        import os
        import json
        from openai import AsyncOpenAI

        api_key = os.environ.get("OPENAI_API_KEY")
        api_base = os.environ.get("LLM_API_BASE", "https://api.minimaxi.com/v1")
        model = os.environ.get("LLM_MODEL", "MiniMax-M2.7")

        if not api_key:
            logger.warning("OPENAI_API_KEY not set, LLM classification skipped")
            return None

        prompt = f"""你是一个黑灰产情报分类专家。

分析以下文本，判断它属于哪种风险类型：

风险类别：
- 账号交易 (Account Trading) - 买卖账号、租号、换绑等
- 流量作弊 (Traffic Cheating) - 刷粉、刷赞、刷量等
- 诈骗引流 (Fraud Leads) - 刷单、杀猪盘、投资诈骗等
- 黑产工具 (Black-market Tools) - 接码平台、群控工具等
- 未知/其他 (Unknown/Other) - 无法判断或无风险

文本: {text}

仅返回JSON格式的分类结果，不要包含其他内容：
{{"level1": "类别名", "level2": "子类别", "confidence": 0.0-1.0, "reason": "判断理由"}}"""

        async def _call_llm():
            async_client = AsyncOpenAI(api_key=api_key, base_url=api_base)
            response = await async_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
                extra_body={"reasoning_effort": "low"},
                timeout=30
            )
            return response.choices[0].message.content

        try:
            result_text = asyncio.run(_call_llm())

            # Remove LLM thinking tags
            result_text = re.sub(r'<\|think_start\|>.*?<\|think_end\|>', '', result_text, flags=re.DOTALL).strip()

            # Extract JSON
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if not json_match:
                logger.warning(f"LLM classification parse failed for: {text[:50]}")
                return None

            result = json.loads(json_match.group())

            # Build ClassificationResult
            level1_label = result.get('level1', '未知/其他')
            level2_label = result.get('level2', '未分类')
            confidence = float(result.get('confidence', 0.5))

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
                    asyncio.run(self._collect_silver_sample(text, classification_result))
                except RuntimeError as e:
                    logger.warning(f"Failed to collect silver sample: {e}")

            return classification_result

        except Exception as e:
            logger.error(f"LLM classification failed: {e}")
            return None

    def classify_batch(self, texts: List[str], context: Dict[str, Any] = None) -> List[ClassificationResult]:
        """Classify a batch of texts."""
        return [self.classify(text, context) for text in texts]

    # ========== FR-EVO-01: Silver Sample Collection ==========

    async def _collect_silver_sample(self, text: str, result: ClassificationResult):
        """FR-EVO-01: Write LLM high-confidence output to training_samples table."""
        try:
            from services.database import PostgreSQLService
            db = PostgreSQLService.get_instance()
            db.insert_training_sample({
                'text': text,
                'label': result.level1_label,
                'label_source': 'silver',
                'confidence': result.confidence,
                'collection_context': 'llm_fallback'
            })
            logger.debug(f"Collected silver sample: {text[:50]}... -> {result.level1_label}")
        except Exception as e:
            logger.warning(f"Failed to collect silver sample: {e}")

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

            # 3. Split data
            X_train, X_test, y_train, y_test, w_train, w_test = train_test_split(
                embeddings, y, weights, test_size=0.2, stratify=y, random_state=42
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
            model_path = f"./models/classifier_v{version}.pkl"
            os.makedirs('./models', exist_ok=True)

            joblib.dump({
                'model': clf,
                'label_encoder': le,
                'macro_f1': macro_f1,
                'version': version
            }, model_path)

            self._current_f1 = macro_f1

            # 7. Update classifier model singleton if available
            try:
                from models.classifier import ClassifierModel
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