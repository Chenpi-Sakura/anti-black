"""Smoke test for config/slang_stopwords.py register_stopword API + mtime reload."""
import os
import sys
import json
import time
import tempfile
import unittest
from pathlib import Path

# Use a tempdir for data/ to avoid polluting production
TEMP_DATA = Path(tempfile.mkdtemp(prefix="stopword_test_"))

# Patch _STATE_PATH BEFORE importing the module
import config.slang_stopwords as ss
ss._STATE_PATH = TEMP_DATA / "stopword_register.json"

# Force re-init of file-load state (do NOT clear the hardcoded 450 set)
ss._loaded = False
ss._last_mtime_ns = 0


class TestStopwordAPI(unittest.TestCase):

    def test_register_and_lookup(self):
        # Use a unique word that won't collide with hardcoded set
        word = "test_zyx_unique_" + str(int(time.time()))
        self.assertFalse(ss.is_stopword(word))
        result = ss.register_stopword(word)
        self.assertTrue(result)
        self.assertTrue(ss.is_stopword(word))

    def test_idempotent(self):
        word = "test_idempotent_" + str(int(time.time()))
        self.assertTrue(ss.register_stopword(word))
        self.assertFalse(ss.register_stopword(word))  # 2nd returns False
        self.assertTrue(ss.is_stopword(word))

    def test_mtime_reload_no_restart(self):
        """Critical: simulate daemon long-running scenario.
        1. Register wordA -> is_stopword(wordA) True
        2. EXTERNAL process writes the JSON with new words
        3. is_stopword(new_word) should auto-reload via mtime check
        """
        # First register via the API
        wordA = "test_mtime_A_" + str(int(time.time()))
        ss.register_stopword(wordA)
        self.assertTrue(ss.is_stopword(wordA))

        # Simulate external write (e.g. apply_stopword_audit.py just wrote)
        wordB = "test_mtime_B_" + str(int(time.time()))
        payload = {
            "version": 1,
            "updated_at": "2026-06-08T13:00:00Z",
            "words": sorted(set([wordA, wordB]))
        }
        # Ensure file mtime differs from in-memory tracker
        time.sleep(0.05)
        ss._STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ss._STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        # Now call is_stopword with wordB - should trigger mtime reload
        self.assertTrue(ss.is_stopword(wordB),
                        "mtime check should auto-reload JSON additions")

    def test_empty_string_noop(self):
        self.assertFalse(ss.register_stopword(""))
        self.assertFalse(ss.register_stopword(None))

    def test_jieba_tokenize_3char_phrase(self):
        """Sanity check: a 3-char Chinese phrase should be a single jieba token.

        Required so is_stopword('phrase') is actually called during process_text.
        Using 'we_are_here' as a placeholder to avoid GBK issues; the test
        confirms jieba's tokenization keeps common 3-char phrases as units.
        """
        import jieba
        # Test with a known 3-char Chinese phrase that's likely in jieba dict
        # Use "大部分" which is a common 3-char phrase
        test_phrase = "大部分"  # "大部分"
        sentence = f"我是{test_phrase}人"  # "我是大部分人"
        toks = list(jieba.cut(sentence))
        joined = " ".join(toks)
        self.assertIn(test_phrase, joined,
                      f"jieba should keep 3-char phrase as unit, got: {toks}")

    def test_hardcoded_set_still_works(self):
        """Existing 450-entry set still works after mtime refactor."""
        self.assertTrue(ss.is_stopword("我"))  # hardcoded
        self.assertTrue(ss.is_stopword("努力"))  # hardcoded
        self.assertTrue(ss.is_stopword("我尝试"))  # hardcoded


if __name__ == "__main__":
    unittest.main(verbosity=2)
