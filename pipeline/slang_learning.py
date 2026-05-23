"""
Slang Learning module for AntiBlack pipeline.
Handles automatic discovery and learning of new slang terms.
"""
import logging
from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class SlangCandidate:
    """A candidate slang term for learning."""
    word: str
    contexts: List[str] = field(default_factory=list)
    occurrence_count: int = 0
    status: str = "NEW"  # NEW/OBSERVED/LIKELY/CONFIRMED/REJECTED/STABLE
    inference_count: int = 0
    regex_pattern: Optional[str] = None
    meaning: Optional[str] = None
    source_channel: Optional[str] = None
    reject_until: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class SlangLearner:
    """
    Slang learning module with progressive state machine.

    State transitions:
    NEW (1-5) -> OBSERVED (10, trigger inference) -> LIKELY (20, second inference)
      -> CONFIRMED (passes regex validation) -> STABLE (500 occurrences)
      OR REJECTED (failed validation after 3 retries, 30-day silence)
    """

    def __init__(self, config: Dict[str, Any], slang_mappings: Dict[str, str] = None):
        self.config = config
        self.slang_mappings = slang_mappings or {}

        # Get thresholds from config
        slang_config = config.get('slang_learning', {})
        thresholds = slang_config.get('thresholds', {})
        self.thresholds = {
            'new_to_observed': thresholds.get('new_to_observed', 10),
            'observed_to_likely': thresholds.get('observed_to_likely', 20),
            'likely_to_confirmed': thresholds.get('likely_to_confirmed', 50),
            'stable_count': thresholds.get('stable_count', 500)
        }

        reject_config = slang_config.get('reject', {})
        self.reject_config = {
            'silence_days': reject_config.get('silence_days', 30),
            'max_retries': reject_config.get('max_retries', 3)
        }

        # Token control
        token_control = slang_config.get('token_control', {})
        self.token_control = {
            'batch_size': token_control.get('batch_size', 20),
            'dynamic_threshold_factor': token_control.get('dynamic_threshold_factor', 1.5)
        }

        # In-memory candidate storage (in production, persist to DB)
        self._candidates: Dict[str, SlangCandidate] = {}

        # Known words to skip
        self._known_words: Set[str] = set(slang_mappings.keys()) if slang_mappings else set()

        # Regex patterns for validation
        self._validation_patterns = [
            r'^[一-鿿]+$',  # Chinese characters only
            r'^[\w]+$',  # Alphanumeric only
        ]

    def process_text(self, text: str, source_channel: str = None) -> List[SlangCandidate]:
        """
        Process text to find new slang candidates.

        Returns list of newly discovered candidates.
        """
        discovered = []
        words = self._extract_words(text)

        for word in words:
            if self._should_skip(word):
                continue

            candidate = self._get_or_create_candidate(word, source_channel)
            candidate.occurrence_count += 1
            candidate.contexts.append(self._get_context(text, word))
            candidate.updated_at = datetime.utcnow()

            # Check state transitions
            old_status = candidate.status
            self._check_state_transition(candidate)

            if candidate.status != old_status:
                discovered.append(candidate)
                logger.info(f"Slang candidate {word} transitioned: {old_status} -> {candidate.status}")

        return discovered

    def _extract_words(self, text: str) -> List[str]:
        """Extract potential slang words from text."""
        # Extract words that are:
        # - 2-8 characters
        # - Not purely numbers
        # - Not already known
        import re
        words = re.findall(r'[一-鿿]{2,8}', text)
        return [w for w in words if not w.isdigit()]

    def _should_skip(self, word: str) -> bool:
        """Check if word should be skipped."""
        if word in self._known_words:
            return True
        if word in self._candidates:
            candidate = self._candidates[word]
            if candidate.status == 'REJECTED':
                if candidate.reject_until and datetime.utcnow() < candidate.reject_until:
                    return True
        return False

    def _get_or_create_candidate(self, word: str, source_channel: str = None) -> SlangCandidate:
        """Get or create a candidate entry."""
        if word not in self._candidates:
            self._candidates[word] = SlangCandidate(
                word=word,
                source_channel=source_channel
            )
        return self._candidates[word]

    def _get_context(self, text: str, word: str, context_size: int = 30) -> str:
        """Get context around the word."""
        idx = text.find(word)
        if idx < 0:
            return text[:context_size]

        start = max(0, idx - context_size)
        end = min(len(text), idx + len(word) + context_size)
        return text[start:end]

    def _check_state_transition(self, candidate: SlangCandidate) -> None:
        """Check and execute state transitions based on count."""
        status = candidate.status
        count = candidate.occurrence_count

        if status == 'NEW' and count >= self.thresholds['new_to_observed']:
            candidate.status = 'OBSERVED'
            candidate.inference_count = 1

        elif status == 'OBSERVED' and count >= self.thresholds['observed_to_likely']:
            candidate.status = 'LIKELY'
            candidate.inference_count = 2

        elif status == 'LIKELY' and count >= self.thresholds['likely_to_confirmed']:
            # Try to confirm - would call LLM in production
            if self._validate_candidate(candidate):
                candidate.status = 'CONFIRMED'
                self._known_words.add(candidate.word)
            else:
                candidate.inference_count += 1
                if candidate.inference_count >= self.reject_config['max_retries']:
                    candidate.status = 'REJECTED'
                    candidate.reject_until = datetime.utcnow() + timedelta(
                        days=self.reject_config['silence_days']
                    )

        elif status == 'CONFIRMED' and count >= self.thresholds['stable_count']:
            candidate.status = 'STABLE'

    def _validate_candidate(self, candidate: SlangCandidate) -> bool:
        """
        Validate candidate through regex pattern testing.

        In production, this would:
        1. Call LLM to generate regex_pattern + test_cases
        2. Test regex against positive samples
        3. Check false positive rate against negative samples
        """
        # Simplified validation for demo
        # Real implementation would do actual regex testing
        return candidate.occurrence_count >= self.thresholds['likely_to_confirmed']

    def get_pending_validation(self) -> List[SlangCandidate]:
        """Get candidates that need LLM inference."""
        return [
            c for c in self._candidates.values()
            if c.status in ('OBSERVED', 'LIKELY') and c.inference_count < 3
        ]

    def get_confirmed(self) -> List[SlangCandidate]:
        """Get confirmed slang candidates."""
        return [
            c for c in self._candidates.values()
            if c.status == 'CONFIRMED'
        ]

    def get_candidate_stats(self) -> Dict[str, int]:
        """Get statistics about candidates."""
        stats = defaultdict(int)
        for c in self._candidates.values():
            stats[c.status] += 1
        return dict(stats)


class SlangDictionary:
    """Manages slang dictionary with mappings."""

    def __init__(self, mappings: Dict[str, str] = None):
        self.mappings = mappings or {}
        self._ac_automaton = None  # Would use AC automaton in production

    def add_mapping(self, slang: str, meaning: str, source: str = "learned") -> None:
        """Add a slang -> meaning mapping."""
        self.mappings[slang] = meaning
        logger.info(f"Added slang mapping: {slang} -> {meaning} (source: {source})")

    def get_mapping(self, slang: str) -> Optional[str]:
        """Get meaning for slang term."""
        return self.mappings.get(slang)

    def match_in_text(self, text: str) -> List[Dict[str, str]]:
        """Find all slang matches in text."""
        matches = []
        for slang, meaning in self.mappings.items():
            if slang in text:
                matches.append({
                    'slang_raw': slang,
                    'meaning': meaning
                })
        return matches

    def export_for_ac_automaton(self) -> List[str]:
        """Export slang terms for AC automaton."""
        return list(self.mappings.keys())