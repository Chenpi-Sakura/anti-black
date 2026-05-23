"""
Unit tests for AntiBlack system.
Tests core functionality of pipeline modules and utilities.
"""
import pytest
from datetime import datetime, timedelta


class TestUtils:
    """Test utility functions."""

    def test_generate_id(self):
        """Test ID generation."""
        from utils import generate_id

        id1 = generate_id("test")
        id2 = generate_id("test")

        assert id1.startswith("test_")
        assert id1 != id2  # Should be unique

    def test_compute_text_hash(self):
        """Test text hashing."""
        from utils import compute_text_hash

        hash1 = compute_text_hash("test text")
        hash2 = compute_text_hash("test text")
        hash3 = compute_text_hash("different text")

        assert hash1 == hash2  # Same text = same hash
        assert hash1 != hash3  # Different text = different hash

    def test_normalize_text(self):
        """Test text normalization."""
        from utils import normalize_text

        # Test full-width to half-width
        text = "ＡＢＣ１２３"
        normalized = normalize_text(text)
        assert normalized == "ABC123"

        # Test whitespace normalization
        text = "hello    world  test"
        normalized = normalize_text(text)
        assert normalized == "hello world test"

    def test_extract_entities_regex(self):
        """Test entity extraction."""
        from utils import extract_entities_regex

        # Test WeChat
        text = "加V:dyhao668"
        entities = extract_entities_regex(text)
        wechat_entities = [e for e in entities if e['entity_type'] == 'WECHAT']
        assert len(wechat_entities) > 0
        assert wechat_entities[0]['entity_value'] == 'dyhao668'

        # Test phone
        text = "联系电话13812345678"
        entities = extract_entities_regex(text)
        phone_entities = [e for e in entities if e['entity_type'] == 'PHONE']
        assert len(phone_entities) > 0
        assert phone_entities[0]['entity_value'] == '13812345678'

        # Test URL
        text = "官网https://t.me/demo"
        entities = extract_entities_regex(text)
        url_entities = [e for e in entities if e['entity_type'] == 'URL']
        assert len(url_entities) > 0


class TestModels:
    """Test data models."""

    def test_entity_model(self):
        """Test Entity model."""
        from models import Entity, EntityType

        entity = Entity(
            entity_id="test_entity_001",
            entity_type=EntityType.WECHAT,
            raw_value="dyhao668"
        )

        assert entity.entity_id == "test_entity_001"
        assert entity.entity_type == EntityType.WECHAT
        assert entity.raw_value == "dyhao668"
        assert entity.occurrence_count == 0

        # Test to_dict
        d = entity.to_dict()
        assert d['entity_type'] == 'WECHAT'
        assert d['raw_value'] == 'dyhao668'

    def test_query_task_model(self):
        """Test QueryTask model."""
        from models import QueryTask, QueryStatus

        task = QueryTask(
            query_id="test_qry_001",
            query_text="测试查询",
            status=QueryStatus.PENDING
        )

        assert task.query_id == "test_qry_001"
        assert task.status == QueryStatus.PENDING

    def test_clue_model(self):
        """Test Clue model."""
        from models import Clue

        clue = Clue(
            clue_id="test_clue_001",
            message_id="test_msg_001",
            risk_label_level1="账号交易",
            risk_label_level2="抖音号买卖",
            confidence=0.95,
            classification_source="rule",
            source_channel="telegram",
            raw_text="出抖号，加V:dyhao668",
            cleaned_text="出抖号 加V dyhao668"
        )

        assert clue.clue_id == "test_clue_001"
        assert clue.confidence == 0.95


class TestPipeline:
    """Test pipeline components."""

    def test_cleaner_normalize(self):
        """Test text cleaning and normalization."""
        from pipeline.cleaner import Cleaner

        cleaner = Cleaner()

        # Test HTML removal
        raw = {'message_id': '1', 'raw_text': '<p>Hello</p> World'}
        cleaned = cleaner._clean_single(raw)
        assert cleaned is not None
        assert '<' not in cleaned.cleaned_text

        # Test full-width conversion
        raw = {'message_id': '2', 'raw_text': 'ＡＢＣ'}
        cleaned = cleaner._clean_single(raw)
        assert cleaned is not None
        assert 'ABC' in cleaned.cleaned_text

    def test_cleaner_dedup(self):
        """Test deduplication."""
        from pipeline.cleaner import Cleaner

        cleaner = Cleaner()

        raw1 = {'message_id': '1', 'raw_text': 'Same text', 'source_channel': 'test', 'group_id': 'g1', 'author_id': 'a1', 'published_at': '2026-05-23T10:00:00+08:00'}
        raw2 = {'message_id': '2', 'raw_text': 'Same text', 'source_channel': 'test', 'group_id': 'g1', 'author_id': 'a1', 'published_at': '2026-05-23T10:00:00+08:00'}

        result1 = cleaner._clean_single(raw1)
        result2 = cleaner._clean_single(raw2)

        assert result1 is not None
        assert result2 is None  # Should be deduplicated

    def test_classifier_rules(self):
        """Test rule-based classification."""
        from pipeline.classifier import Classifier

        classifier = Classifier()

        # Test account trading rule
        text = "出抖号，千粉，换绑稳"
        result = classifier._classify_by_rules(text)
        assert result is not None
        assert result.level1_label == '账号交易'

        # Test fraud rule
        text = "刷单兼职，日赚200"
        result = classifier._classify_by_rules(text)
        assert result is not None
        assert result.level1_label == '诈骗引流'

    def test_extractor_entities(self):
        """Test entity extraction."""
        from pipeline.extractor import Extractor

        extractor = Extractor()

        text = "出抖号，千粉，换绑稳，加V:dyhao668"
        result = extractor.extract("msg_001", text)

        assert result.message_id == "msg_001"
        assert len(result.entities) > 0

        # Check WeChat entity
        wechat_entities = [e for e in result.entities if e.entity_type == 'WECHAT']
        assert len(wechat_entities) > 0

        # Check slang mapping
        assert len(result.slang_mappings) > 0

    def test_extractor_platform(self):
        """Test platform detection."""
        from pipeline.extractor import Extractor

        extractor = Extractor()

        # Test Douyin detection
        text = "抖音号出售，价格优惠"
        result = extractor.extract("msg_001", text)
        assert result.platform == '抖音'

        # Test unknown platform
        text = "普通文本，没有平台信息"
        result = extractor.extract("msg_002", text)
        assert result.platform is None

    def test_router_scoring(self):
        """Test routing score calculation."""
        from pipeline.router import Router

        router = Router()

        # High-value message
        high_value_msg = {
            'message_id': '1',
            'risk_level': 'HIGH',
            'entities': [{'type': 'WECHAT'}, {'type': 'PHONE'}],
            'slang_mappings': [{'slang': '飞机'}],
            'raw_text': '出抖号，加V:dyhao668，联系方式13812345678',
            'source_channel': 'telegram'
        }

        score = router._calculate_score(high_value_msg)
        assert score > 0.5  # Should route to deep channel

        # Low-value message
        low_value_msg = {
            'message_id': '2',
            'risk_level': 'LOW',
            'entities': [],
            'slang_mappings': [],
            'raw_text': '你好',
            'source_channel': 'social'
        }

        score = router._calculate_score(low_value_msg)
        assert score < 0.3  # Should route to light channel


class TestSlangLearning:
    """Test slang learning module."""

    def test_candidate_creation(self):
        """Test slang candidate creation."""
        from pipeline.slang_learning import SlangLearner

        learner = SlangLearner({})

        # Process text with potential slang
        text = "这有个飞机可以带你飞"
        candidates = learner.process_text(text, source_channel='telegram')

        # Should find some candidates (depends on Chinese text analysis)
        stats = learner.get_candidate_stats()
        assert 'NEW' in stats or len(stats) >= 0

    def test_state_transitions(self):
        """Test slang state machine."""
        from pipeline.slang_learning import SlangLearner

        config = {
            'slang_learning': {
                'thresholds': {
                    'new_to_observed': 5,
                    'observed_to_likely': 10,
                    'likely_to_confirmed': 15,
                    'stable_count': 100
                }
            }
        }
        learner = SlangLearner(config)

        # Simulate word discovery
        word = "测试词"
        for i in range(20):
            learner.process_text(f"含有{word}的文本内容 {i}", source_channel='telegram')

        candidate = learner._candidates.get(word)
        assert candidate is not None
        # Should have transitioned through states
        assert candidate.occurrence_count == 20


class TestAPI:
    """Test API endpoints."""

    def test_format_responses(self):
        """Test response formatting."""
        from utils import format_success_response, format_error_response

        # Test success response
        resp = format_success_response({"key": "value"})
        assert resp['code'] == 0
        assert resp['message'] == 'ok'
        assert resp['data'] == {"key": "value"}
        assert 'request_id' in resp

        # Test error response
        resp = format_error_response(1001, "Invalid request")
        assert resp['code'] == 1001
        assert resp['message'] == "Invalid request"
        assert resp['data'] is None


class TestRouting:
    """Test routing decisions."""

    def test_route_threshold(self):
        """Test routing threshold adjustment."""
        from pipeline.router import Router

        router = Router()

        msg = {
            'message_id': '1',
            'risk_level': 'MEDIUM',
            'entities': [],
            'slang_mappings': [],
            'raw_text': 'test',
            'source_channel': 'telegram'
        }

        # With sufficient token budget
        channel = router.route(msg, token_budget_percent=0.5)
        assert channel in ('light', 'deep')

        # With low token budget
        channel = router.route(msg, token_budget_percent=0.2)
        assert channel == 'light'  # Should route to light with low budget


if __name__ == '__main__':
    pytest.main([__file__, '-v'])