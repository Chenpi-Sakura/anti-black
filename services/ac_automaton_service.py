"""
AC Automaton Service with Double Buffering
FR-SLANG-05: 词典同步 AC 自动机，无阻塞热更新

设计原则:
- 锁内只换指针，锁外执行计算
- 查询操作无阻塞，更新操作后台原子替换
"""
import ahocorasick
import threading
import logging
from typing import Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class ACAutomatonService:
    """
    AC 自动机词典服务，支持双缓冲热更新。

    设计:
    - 查询操作使用读写锁，无阻塞
    - 更新操作在后台线程构建新 automaton，完成后原子替换
    - 最大程度减少对查询线程的阻塞
    """

    def __init__(self):
        self._automaton: ahocorasick.Automaton = ahocorasick.Automaton()
        self._word_to_meaning: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._update_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ac_update")

    def load_from_slang_mappings(self, mappings: List) -> int:
        """
        从 slang_mappings 批量加载词典。
        返回加载的词条数。
        """
        words_to_add = []
        for m in mappings:
            slang_raw = m.slang_raw if hasattr(m, 'slang_raw') else m.get('slang_raw', '')
            meaning = m.meaning if hasattr(m, 'meaning') else m.get('meaning', '')
            regex_pattern = m.regex_pattern if hasattr(m, 'regex_pattern') else m.get('regex_pattern', '')

            if slang_raw:
                words_to_add.append((slang_raw, meaning, regex_pattern))

        if not words_to_add:
            return 0

        def _build():
            new_automaton = ahocorasick.Automaton()
            new_meanings = {}

            for word, meaning, regex_pattern in words_to_add:
                key = regex_pattern if regex_pattern else word
                new_automaton.add_word(key, (key, meaning))
                new_meanings[key] = meaning

            new_automaton.make_automaton()

            with self._lock:
                self._automaton = new_automaton
                self._word_to_meaning = new_meanings

            logger.info(f"AC automaton loaded {len(words_to_add)} words")

        if len(words_to_add) > 1000:
            self._update_executor.submit(_build)
        else:
            _build()

        return len(words_to_add)

    def search(self, text: str) -> List[Tuple[str, str]]:
        """
        在文本中搜索黑话词 (彻底解除计算阻塞)

        设计: 仅在获取当前自动机引用时锁定 (< 0.1ms)，耗时的迭代在锁外执行
        返回: [(word, meaning), ...]
        """
        with self._lock:
            current_automaton = self._automaton

        results = []
        for end_idx, (word, meaning) in current_automaton.iter(text):
            results.append((word, meaning))
        return results

    def add_word(self, word: str, meaning: str, regex_pattern: str = None):
        """
        热更新添加单个词汇 (后台重建)
        """
        key = regex_pattern if regex_pattern else word

        def _rebuild():
            current_words = list(self._word_to_meaning.items())
            current_words.append((key, meaning))

            new_automaton = ahocorasick.Automaton()
            new_meanings = {}
            for w, m in current_words:
                new_automaton.add_word(w, (w, m))
                new_meanings[w] = m
            new_automaton.make_automaton()

            with self._lock:
                self._automaton = new_automaton
                self._word_to_meaning = new_meanings

            logger.info(f"AC automaton updated: added '{key}'")

        self._update_executor.submit(_rebuild)

    def remove_word(self, word: str):
        """
        热更新移除词汇 (后台重建)
        """
        def _rebuild():
            current_words = [(w, m) for w, m in self._word_to_meaning.items() if w != word]

            new_automaton = ahocorasick.Automaton()
            new_meanings = {}
            for w, m in current_words:
                new_automaton.add_word(w, (w, m))
                new_meanings[w] = m
            new_automaton.make_automaton()

            with self._lock:
                self._automaton = new_automaton
                self._word_to_meaning = new_meanings

            logger.info(f"AC automaton updated: removed '{word}'")

        self._update_executor.submit(_rebuild)

    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            return {
                'word_count': len(self._word_to_meaning),
                'automaton_type': type(self._automaton).__name__
            }


# Singleton instance
_ac_service: ACAutomatonService = None
_service_lock = threading.Lock()


def get_ac_automaton_service() -> ACAutomatonService:
    """获取 AC Automaton Service 单例"""
    global _ac_service
    if _ac_service is None:
        with _service_lock:
            if _ac_service is None:
                _ac_service = ACAutomatonService()
    return _ac_service