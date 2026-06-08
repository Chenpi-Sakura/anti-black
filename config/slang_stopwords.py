"""
Hardcoded Chinese stopword set for slang candidate extraction.

PURPOSE
=======
Filter out high-frequency daily phrases that pass the length/CJK
checks in `_extract_words` but are never black-market terms.
The state-machine's 60% backtest correctly kills these phrases, but
each LLM call costs 5-15s and pollutes the LIKELY pool (~27k entries
in production are mostly daily phrases). Filtering at the extract
stage is the cheapest fix.

DESIGN vs slang_blacklist.py
============================
- `slang_blacklist.py` is **case-by-case** (each word has its own
  TTL, can be resurrected after expiry to catch semantic drift).
- `slang_stopwords.py` is a **closed set** — these words are NEVER
  black-market terms in any context, so no TTL is needed.

PERFORMANCE
===========
Backed by `Set[str]` for O(1) `in` lookup. `pipeline/slang_learning`
calls `_extract_words` per Kafka batch (5-20k times/day), so a
`set` is ~2 orders of magnitude faster than a `list`.

SOURCES (audited 2026-06-07 from 26,793 LIKELY pool)
====================================================
- Pronouns / demonstratives
- Function / grammatical particles
- High-frequency daily verbs / adverbs
- User-reported garbage phrases (我尝试, 话说, 羡慕, 你建议, 努力, etc.)
- Confirmed false-positives from scripts/_slang_report.txt
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Set

# Runtime-registered stopwords persistence (mtime-aware reload for live daemon)
_lock = threading.RLock()
_loaded: bool = False
_last_mtime_ns: int = 0
_STATE_PATH: Path = Path(__file__).resolve().parent.parent / "data" / "stopword_register.json"

# IMPORTANT: Set[str], not List[str]. O(1) lookup.
_STOPWORDS: Set[str] = {
    # Pronouns / demonstratives
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "她们", "它们",
    "自己", "大家", "某人", "别人", "人家", "本人",
    "这", "那", "这个", "那个", "这些", "那些", "这样", "那样",
    "什么", "怎么", "为什么", "怎样", "如何", "哪里", "哪个", "哪些",
    "谁", "谁的", "哪位",

    # Particles / grammar / modal
    "的", "了", "在", "是", "啊", "呢", "吧", "哦", "嗯", "哈", "呀", "嘛", "呗",
    "咯", "哇", "哎", "唉", "呸", "呕", "哼", "嘘", "耶", "嗨",
    "呵", "嘿", "咦", "兮", "欸", "哒",

    # Conjunctions / prepositions
    "和", "或", "及", "与", "而", "但", "却", "因", "为", "所", "以",
    "从", "到", "向", "往", "于", "对", "把", "被", "让", "使",
    "的", "地", "得",

    # High-frequency common verbs
    "说", "看", "想", "做", "给", "找", "用", "等", "拿", "放", "走", "来", "去",
    "吃", "喝", "打", "玩", "听", "写", "读", "买", "卖", "换", "送", "带",
    "上", "下", "进", "出", "回", "过", "起", "开", "关", "停",
    "想", "要", "能", "会", "可", "敢", "肯", "愿",
    "有", "无", "是", "非", "对", "错", "好", "坏", "真", "假",
    "是", "像", "似", "如", "比", "较", "更", "最",

    # Common adverbs / time
    "不", "也", "都", "很", "还", "又", "再", "才", "已", "已经",
    "现在", "以前", "以后", "然后", "之后", "之前", "刚才", "马上",
    "一直", "一向", "一贯", "一向", "一齐", "一起", "一同",
    "刚才", "刚", "刚要", "刚想", "刚买", "刚卖", "刚出", "刚到",
    "今晚", "今早", "今儿", "今天", "明天", "昨天", "前天", "后天",
    "早上", "中午", "下午", "晚上", "夜里", "白天",
    "年", "月", "日", "号", "点", "分", "秒",
    "刚才", "以前", "之后", "现在", "当前", "此时", "此刻",

    # Common prepositional / relative phrases
    "关于", "对于", "至于", "关于", "由于", "因为", "所以", "因此",
    "如果", "假如", "要是", "只要", "除非", "即使", "不过", "可是",
    "虽然", "尽管", "然而", "但是", "不过", "然而", "可是", "但",
    "而且", "并且", "同时", "另外", "此外", "总之", "综上",

    # High-frequency common phrases (user-reported garbage)
    "一直", "一直在", "一直以", "一直以来",
    "买手机", "卖手机", "出手机", "换手机",
    "试一下", "试过", "试试", "试了", "试过", "试过再",
    "看起来", "看上去", "听起来", "闻起来", "摸起来",
    "说起来", "讲起来", "聊起来", "说起来", "说起来也",
    "我尝试", "我打算", "我想", "我要", "我猜",
    "尝试", "打算", "尝试用",
    "话说", "话说", "话说回来", "话说上",
    "羡慕", "嫉妒", "恨", "喜欢", "讨厌",
    "你建议", "你建议", "你的建议", "你推荐",
    "努力", "勤奋", "加油", "用心",
    "合适的话我就收了", "带价格来", "找了几个人了还是",
    "评论区上面找", "合适的就", "刚买", "刚卖", "刚出",
    "合适就", "合适就出", "合适的", "合适的话",
    "我出", "我买", "我卖", "我收", "我换", "我送",
    "你出", "你买", "你卖", "你收", "你换", "你送",
    "他出", "他买", "他卖", "他收", "他换", "他送",

    # NOTE: "出号/要号/收号/号私" are real black-market slangs (account
    # trading). NOT in stopword set. They were in the 27k LIKELY pool
    # only because occurrence_count hit 50 from copy-paste, not because
    # they are noise.

    # Common quantifiers / measures
    "一个", "两个", "三个", "四个", "五个", "几个", "多个", "少个",
    "一些", "一点", "一点点", "一点也", "一些些",
    "第一", "第二", "第三", "第四", "第五",
    "一次", "两次", "三次", "多次", "反复", "重新", "再来",
    "一种", "另一种", "各种", "各种各样",

    # Common descriptors (not black-market specific)
    "大", "小", "长", "短", "高", "矮", "胖", "瘦",
    "新", "旧", "老", "年轻", "古老", "新鲜",
    "快", "慢", "早", "晚", "多", "少", "远", "近",
    "好", "坏", "美", "丑", "对", "错", "真", "假",
    "容易", "简单", "困难", "复杂", "轻松", "紧张", "开心", "难过",
    "高兴", "快乐", "幸福", "痛苦", "难受", "舒服", "难受",
    "热", "冷", "暖", "凉", "温", "烫", "冰",
    "干净", "脏", "整洁", "乱", "整齐", "整齐",
    "清楚", "模糊", "明白", "糊涂", "清晰", "清晰",

    # High-frequency prepositions / locatives
    "上", "下", "里", "外", "中", "内", "前", "后", "左", "右",
    "上边", "下边", "里边", "外边", "前边", "后边", "左边", "右边",
    "上面", "下面", "里面", "外面", "前面", "后面", "左边", "右边",
    "中间", "中间", "中间", "中央", "中心", "核心",
    "旁边", "附近", "周边", "周围", "四周",

    # More user-reported garbage (from scripts/_slang_report.txt LIKELY top-20)
    "这两个", "时赞会", "时赞会消失", "爆款公式",
    "尝试用", "用“", "“痛点", "痛感", "痛点",
    "不允许", "不允许的", "岁的", "年纪", "年龄",
    "认准近此", "认准", "找客服", "客服", "联系客服",

    # Common character-mode punctuation leftovers (junk from jieba)
    "“", "”", "‘", "’", "「", "」", "『", "』", "《", "》", "〈", "〉",
    "（", "）", "【", "】", "〔", "〕", "〖", "〗", "［", "］",
    "──", "──", "──",
}


def _ensure_loaded() -> None:
    """Lazy-load + mtime-aware auto-reload of operator-registered stopwords.

    Mirrors config/slang_blacklist.py:_ensure_loaded() (lines 265-293).
    Adds mtime check so operator apply_stopword_audit.py --apply changes
    are picked up by the running daemon WITHOUT a restart.
    Idempotent + thread-safe.
    """
    global _loaded, _last_mtime_ns
    with _lock:
        if not _STATE_PATH.exists():
            _loaded = True
            return
        try:
            current_mtime_ns = _STATE_PATH.stat().st_mtime_ns
        except OSError:
            _loaded = True
            return
        if _loaded and current_mtime_ns == _last_mtime_ns:
            return  # file unchanged, no reload needed
        try:
            raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            registered = raw.get("words", [])
            added = 0
            for w in registered:
                if isinstance(w, str) and w and w not in _STOPWORDS:
                    _STOPWORDS.add(w)
                    added += 1
            _last_mtime_ns = current_mtime_ns
            _loaded = True
            if added:
                import logging
                logging.getLogger(__name__).info(
                    "Loaded %d runtime-registered stopwords from %s (mtime check, delta=%d)",
                    added, _STATE_PATH, added
                )
        except (json.JSONDecodeError, OSError) as e:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to load stopword_register.json: %s — keeping current set", e
            )
            _loaded = True


def _persist_unlocked() -> None:
    """Write runtime-registered stopwords to disk. Caller must hold _lock.

    Bumps file mtime so _ensure_loaded() re-reads on next is_stopword() call.
    Only runtime-ADDED entries are persisted; hardcoded 450 stay in source.
    """
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: Set[str] = set()
    if _STATE_PATH.exists():
        try:
            existing = set(json.loads(_STATE_PATH.read_text(encoding="utf-8")).get("words", []))
        except (json.JSONDecodeError, OSError):
            existing = set()
    new_additions = _STOPWORDS - existing
    merged = existing | new_additions
    payload = {
        "version": 1,
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "words": sorted(merged),
    }
    tmp = _STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_STATE_PATH)  # atomic, mtime always updates


def register_stopword(word: str) -> bool:
    """Add a runtime-registered stopword. Returns True if newly added.

    Persists to data/stopword_register.json so the file's mtime changes
    and running daemons pick it up via _ensure_loaded()'s mtime check
    (no daemon restart needed).
    Thread-safe. Idempotent (returns False if already present).
    """
    if not word or not isinstance(word, str):
        return False
    with _lock:
        _ensure_loaded()
        if word in _STOPWORDS:
            return False
        _STOPWORDS.add(word)
        _persist_unlocked()
        return True


def is_stopword(w: str) -> bool:
    """Return True if `w` is a high-frequency non-slang word.

    O(1) lookup via Set. Each call checks file mtime (cheap stat()),
    auto-reloads if operator applied new stopwords since last call.
    """
    with _lock:
        _ensure_loaded()
        return w in _STOPWORDS
