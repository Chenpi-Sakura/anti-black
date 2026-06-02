"""
Hardcoded slang blacklist with TTL-based resurrection (方案A).

Words in this list are absolutely NOT 黑灰产 slangs and must never reach
CONFIRMED status. They are filtered out at the candidate extraction stage
(`pipeline/slang_learning.py:_extract_words`) and the LLM validation prompt
injects this list as a hard rule.

TTL / 复活赛机制:
- Each blacklisted word has an `expires_at` timestamp, default 90 days
- After expiry, `is_blacklisted(word)` returns False
- The word re-enters the normal pipeline: _extract_words → LLM validation → 60% backtest
- If it's still a non-slang (e.g. "原创"), the LLM/backtest will reject it again on its own
- If by then it's been co-opted by 黑灰产 (e.g. "茶叶" 演变成灰产代称), the pipeline
  will re-capture it. This solves the "黑话随时间漂移" problem.

Persistence:
- Entries are persisted to `data/slang_blacklist_state.json`
- Restarting the process does NOT reset the TTL clock
- New words added via `register_blacklist()` get a fresh TTL

Source:
1. LLM audit on 2026-06-02 (scripts/audit_slang_results.json) where the
   model marked CONFIRMED candidates as `is_slang=false` with confidence >= 80
2. Manual additions: game-account-trading words (out of system scope)

Backlog (方案D, NOT in this MVP):
- Weekly double-blind audit: re-evaluate blacklisted words with fresh Kafka
  contexts, auto-remove from blacklist if LLM says is_slang=true with high confidence
- Tracked in docs/backlog.md

Categories represented:
- 内容标签: 原创/笔记/合集/搞笑/日常 ...
- 通用商务词: 合作/报价/平台/运营/安排/开通 ...
- 用户画像: 大学生/甜妹/元气少女/未成年 ...
- 文本截断碎片: 们的独一无二的微/是我们在一起的日 ...
- 平台/品牌名: DOU/DOU+/蒲公英/闲鱼/抖音/王者荣耀 ...
- 反诈宣传: 反诈骗/立案调查/春雷行动/防诈骗 ...
- 游戏账号交易（非本系统重点）: 三角洲租号/内部代下/和平精英租号 ...
- 过度泛化: 账号/手机/分钟/方式/意义 ...
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Dict, FrozenSet, List, Set

logger = logging.getLogger(__name__)

# === Static word list (immutable source of truth) ===

_HARDCODED_WORDS: FrozenSet[str] = frozenset({
    # === 内容标签 / 话题标签 ===
    "微信号教程来了",
    "官方教程请收好",
    "微信情侣",
    "花式网名",
    "合集",
    "原创",
    "真实生活分享计划",
    "我要上热门",
    "经验分享",
    "粤语",
    "搞笑",
    "亲子教育",
    "笔记",
    "#流量",
    "玩机技巧",
    "手机技巧分享",
    "日常",

    # === 通用商务 / 平台词 ===
    "平台",
    "出一个",
    "出物",
    "闲置",
    "报价",
    "出抖音号",
    "合作",
    "互粉",
    "先到先得",
    "运营",
    "海外社媒运营",
    "合规出海",
    "急需用米",
    "开通",
    "网页链接",

    # === 用户画像 ===
    "大学生",
    "卷毛",
    "靓女",
    "甜妹",
    "元气少女",
    "未成年",
    "大帅哥",

    # === 文本截断碎片 ===
    "音小店官方号的操",
    "个体抖店也可以更",
    "们的独一无二的微",
    "是我们在一起的日",
    "感微信号",
    "宝宝萌可以当做微",
    "原创圈打水印的署",
    "未注册的小众高级",
    "看抖音视频是可以",
    "万个粉丝的账号到",
    "四男子买",
    "会不会成为抖音爆",
    "#短",
    "想买的也可以在我",
    "微信号小众独特有",
    "在每个有意义的时",
    "投资买账号赚钱到",
    "都是一些个人的看",
    "的人不知道",

    # === 平台名 / 品牌名 / 官方词 ===
    "螃蟹帐号",
    "微信交流",
    "团购等",
    "音流量",
    "抖音",
    "DOU",
    "DOU+",
    "闲鱼",
    "王者荣耀",
    "蒲公英",
    "抖音号",
    "微信好友",

    # === 反诈宣传 ===
    "反诈骗",
    "立案调查",
    "春雷行动",
    "市场监管在行动",
    "诈骗",
    "万元被刑拘",
    "贩卖抖音号获利",
    "黑心耐电网收号骗",
    "不要出租出借游戏",
    "防诈骗",
    "骗局",
    "卖号盛行",

    # === 日常口语 / 语气词 ===
    "信号啦",
    "是她的名字首字母",
    "是我的名字首字母",
    "安排",
    "一个",
    "我学会了你学会了",
    "搭讪",
    "追女生",
    "了么",
    "费老鼻子劲了",
    "可以加个",
    "生日同一天的加个",
    "帮手",
    "号以后",
    "部手机",
    "我想加帅哥",
    "意义",
    "要记住",
    "谁是",
    "也可以",
    "抖音大号被封了",
    "加好友",
    "如果你也感觉不错",
    "欢迎大叔合拍",
    "年呀",
    "建议",
    "我醒了给你发消息",
    "互加好友",
    "你醒了给我打电话",
    "不行啊",
    "手机",
    "分钟",
    "主要还是怎么方便",
    "方式",
    "怎么来",
    "好了",
    "这些都是作弊器",
    "官方早就为你准备",
    "真的会害了你",
    "只是",
    "全过程",

    # === 情感 / 文艺 / 生活类 ===
    "是爱",
    "终于换上了属于我",
    "小众高级感",
    "实现梦经济自由的",
    "理想型",
    "晚风很温柔",
    "夏天的味道",
    "高级",
    "刷到了就是缘分",
    "感恩遇见",
    "爱人先爱己",

    # === 自媒体运营术语 ===
    "嵌入式",
    "万粉成长计划",
    "新人粉丝从",
    "千粉小博主是怎么",
    "小助手",
    "你也能收获",
    "用心坚持",
    "让账号动起来吧",
    "将不能再挂载橱窗",
    "媒体",
    "颜值赛道",
    "文案",
    "九宫格",
    "十五字以上",
    "海外矩阵管理系统",

    # === 游戏账号交易（非本系统重点） ===
    "三角洲租号",
    "内部代下",
    "和平精英租号",
    "账号",

    # === 其他 ===
    "楚雨悦",          # 示例性人名/ID占位符
    "桃枥",            # SEO引流随机关键词
    "信小网号",         # 微信小号/微信号的笔误
    "卖簪",            # 营销账号用户名
    "熱镀",            # 灰产服务账号ID
    "番茄肥牛卷卷",     # 普通用户昵称
    "椋椋",            # 普通网络昵称
    "哈弗币",          # 三角洲行动游戏内虚拟币
    "洞妖",            # 反诈科普自定义标签
    "商行",            # 三角洲行动游戏内交易系统
    "三角洲商行",        # 特定游戏店铺名
    "粉管",            # 牙膏产品描述
    "多问律师",         # 普法类博主名称
    "️⃣",              # Emoji符号（keycap变体）
    "侧切",            # 滑雪装备专业术语
    "电子信息",         # 高校学科术语
})


# === TTL state (mutable, persisted) ===

# Default TTL: 90 days. A word that has been "dead" for 90 days gets a chance
# to re-enter the normal pipeline. If it's still non-slang, the LLM/backtest
# filters will catch it.
DEFAULT_TTL_DAYS: int = 90

# Path to the persistence file. Using a stable on-disk JSON so the TTL clock
# does NOT reset on every process restart.
_STATE_PATH: Path = Path(__file__).resolve().parent.parent / "data" / "slang_blacklist_state.json"

# Mutable in-memory state. word -> expires_at (UTC, naive for JSON compat).
_entries: Dict[str, datetime] = {}
_loaded: bool = False
_lock = RLock()


def _ensure_loaded() -> None:
    """Lazy-load state from disk. Idempotent."""
    global _loaded
    with _lock:
        if _loaded:
            return
        if _STATE_PATH.exists():
            try:
                raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
                entries_raw = raw.get("entries", {})
                for word, iso in entries_raw.items():
                    try:
                        _entries[word] = datetime.fromisoformat(iso)
                    except (ValueError, TypeError):
                        logger.warning("Skipping malformed blacklist entry: %s=%s", word, iso)
                logger.info("Loaded %d blacklist entries from %s", len(_entries), _STATE_PATH)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load blacklist state from %s: %s — starting fresh", _STATE_PATH, e)
        # Seed any new words from the static source list that aren't in state yet
        now = datetime.utcnow()
        seeded = 0
        for word in _HARDCODED_WORDS:
            if word not in _entries:
                _entries[word] = now + timedelta(days=DEFAULT_TTL_DAYS)
                seeded += 1
        if seeded > 0:
            logger.info("Seeded %d new blacklist entries (TTL=%dd)", seeded, DEFAULT_TTL_DAYS)
            _persist_unlocked()
        _loaded = True


def _persist_unlocked() -> None:
    """Write current state to disk. Caller must hold _lock."""
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "ttl_days": DEFAULT_TTL_DAYS,
        "updated_at": datetime.utcnow().isoformat(),
        "entries": {w: dt.isoformat() for w, dt in _entries.items()},
    }
    tmp = _STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_STATE_PATH)


def is_blacklisted(word: str) -> bool:
    """Check if a word is currently blacklisted (not yet TTL-expired).

    Returns False for words whose TTL has passed — they get a chance to
    re-enter the normal pipeline and re-prove themselves via LLM validation
    and 60% backtest.
    """
    if not word:
        return False
    _ensure_loaded()
    with _lock:
        expires = _entries.get(word)
        if expires is None:
            return False
        if datetime.utcnow() >= expires:
            # Expired — do NOT delete (audit trail), just report as not-blacklisted.
            return False
        return True


def register_blacklist(words, ttl_days: int = DEFAULT_TTL_DAYS) -> int:
    """Add new words to the blacklist with a fresh TTL.

    Args:
        words: iterable of words to blacklist
        ttl_days: TTL in days from now (default 90)

    Returns:
        Number of words actually added (excluding already-active entries).
    """
    _ensure_loaded()
    now = datetime.utcnow()
    expires = now + timedelta(days=ttl_days)
    added = 0
    with _lock:
        for word in words:
            if not word or not isinstance(word, str):
                continue
            # Only add if not already in state OR already expired
            existing = _entries.get(word)
            if existing is not None and existing > now:
                continue
            _entries[word] = expires
            added += 1
        if added > 0:
            _persist_unlocked()
            logger.info("Registered %d new blacklist entries (TTL=%dd)", added, ttl_days)
    return added


def active_blacklist() -> List[str]:
    """Return the list of currently-active (non-expired) blacklisted words.

    Used by the LLM prompt to inject the hard rule list.
    """
    _ensure_loaded()
    now = datetime.utcnow()
    with _lock:
        return sorted(w for w, exp in _entries.items() if exp > now)


def active_blacklist_set() -> Set[str]:
    """Same as active_blacklist() but as a set for O(1) lookup."""
    _ensure_loaded()
    now = datetime.utcnow()
    with _lock:
        return {w for w, exp in _entries.items() if exp > now}


def get_expired_words() -> List[str]:
    """Return words whose TTL has passed. For inspection / metrics.

    These words will re-enter the normal pipeline on next candidate extraction.
    """
    _ensure_loaded()
    now = datetime.utcnow()
    with _lock:
        return sorted(w for w, exp in _entries.items() if exp <= now)


def get_state_snapshot() -> dict:
    """Return a snapshot of blacklist state for debugging / metrics."""
    _ensure_loaded()
    with _lock:
        now = datetime.utcnow()
        active = sum(1 for exp in _entries.values() if exp > now)
        expired = sum(1 for exp in _entries.values() if exp <= now)
        return {
            "total_entries": len(_entries),
            "active": active,
            "expired": expired,
            "ttl_days": DEFAULT_TTL_DAYS,
            "state_path": str(_STATE_PATH),
        }


# Backward-compat alias: callers (LLM prompt) may want the static word list.
# We keep this for documentation / static reference only — runtime checks
# MUST go through is_blacklisted() so TTL is respected.
HARDCODED_SLANG_BLACKLIST: FrozenSet[str] = _HARDCODED_WORDS
