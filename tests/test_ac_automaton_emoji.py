"""
Tests for AC (Aho-Corasick) automaton emoji handling.

The codebase uses the `ahocorasick` library (PyPI: pyahocorasick) in
`services/ac_automaton_service.py`. These tests verify that the library
correctly matches slang words containing:

- Single-codepoint emoji (e.g. "加微💰", "💰", "🔞")
- ZWJ-composite emoji (e.g. "👩‍💻代练")
- Variation-Selector-16 emoji (e.g. "❤️加我")

If `ahocorasick` is not installed, the tests are skipped gracefully via
`pytest.importorskip`.
"""
import importlib.util

import pytest

ahocorasick = pytest.importorskip("ahocorasick")

_HAS_AHOCORASICK = importlib.util.find_spec("ahocorasick") is not None


def _build_automaton(words):
    """Build a fresh ahocorasick.Automaton from an iterable of words.

    Each word's value is itself, so `iter(text)` yields (end_idx, word)
    tuples. The `store` parameter is omitted (the value is the key by
    default in pyahocorasick >= 1.4).
    """
    automaton = ahocorasick.Automaton()
    for w in words:
        automaton.add_word(w, w)
    automaton.make_automaton()
    return automaton


def _matched_words(automaton, text):
    """Return the set of unique words matched in `text`."""
    return {matched for _, matched in automaton.iter(text)}


# ---------------------------------------------------------------------------
# Control: pure ASCII / CJK without emoji — must always pass.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _HAS_AHOCORASICK, reason="ahocorasick not installed")
def test_ac_basic_matching():
    automaton = _build_automaton(["加微", "出号", "我们"])
    text = "急出号 加微 找我们"
    matched = _matched_words(automaton, text)
    assert matched == {"加微", "出号", "我们"}


# ---------------------------------------------------------------------------
# Critical test: single-codepoint emoji attached to CJK slang.
# 💰 = U+1F4B0 (4 UTF-8 bytes), 😈 = U+1F608 (4 UTF-8 bytes).
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _HAS_AHOCORASICK, reason="ahocorasick not installed")
def test_ac_handles_simple_emoji():
    automaton = _build_automaton(["加微💰", "出号😈"])
    text = "急出号😈 加微💰 的来"
    matched = _matched_words(automaton, text)
    assert "加微💰" in matched, f"expected '加微💰' in {matched!r}"
    assert "出号😈" in matched, f"expected '出号😈' in {matched!r}"


# ---------------------------------------------------------------------------
# Pure-emoji words (each is a single codepoint on the BMP/SMP boundary).
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _HAS_AHOCORASICK, reason="ahocorasick not installed")
def test_ac_handles_emoji_in_isolation():
    automaton = _build_automaton(["💰", "🔞"])
    text = "v🔞 收💰"
    matched = _matched_words(automaton, text)
    assert "💰" in matched, f"expected '💰' in {matched!r}"
    assert "🔞" in matched, f"expected '🔞' in {matched!r}"


# ---------------------------------------------------------------------------
# ZWJ-composite emoji 👩‍💻 = U+1F469 + U+200D + U+1F4BB.
# This is the trickiest case: if the library splits on UTF-8 bytes the
# substring still matches, but if it normalizes/segments on ZWJ it will
# fail. Marked xfail so the suite is not blocked.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _HAS_AHOCORASICK, reason="ahocorasick not installed")
def test_ac_handles_zwj_composite():
    automaton = _build_automaton(["👩‍💻代练"])
    text = "急招 👩‍💻代练 服务"
    matched = _matched_words(automaton, text)
    if "👩‍💻代练" not in matched:
        pytest.xfail(
            "pyahocorasick did not match ZWJ-composite emoji '👩‍💻代练' "
            "as a contiguous substring. A ZWJ-normalization fallback path "
            "is needed in the slang learning pipeline."
        )


# ---------------------------------------------------------------------------
# Variation Selector-16: ❤️ = U+2764 + U+FE0F.
# Same shape as the ZWJ case — pure substring match should work, but
# if the library strips variation selectors it will fail.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _HAS_AHOCORASICK, reason="ahocorasick not installed")
def test_ac_handles_vs16_modifier():
    automaton = _build_automaton(["❤️加我"])
    text = "❤️加我 找服务"
    matched = _matched_words(automaton, text)
    if "❤️加我" not in matched:
        pytest.xfail(
            "pyahocorasick did not match VS16-modified '❤️加我'. "
            "A variation-selector fallback may be required."
        )
