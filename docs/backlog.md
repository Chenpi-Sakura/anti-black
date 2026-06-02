# AntiBlack — Backlog

未在当前迭代中实现、但已明确需要做的工程改进。按优先级粗排。

---

## Backlog-01: 黑名单双盲审计自动化复活 (方案D)

**状态**: 📋 待排期  
**来源**: 2026-06-02 slang 清理审计 (`scripts/audit_slang_results.json`)  
**前置依赖**: 方案A (TTL 复活机制) 已落地 — `config/slang_blacklist.py`  
**目标 Owner**: TBD

### 背景

方案A (`config/slang_blacklist.py`) 已经实现了"过期复活"机制：每个黑名单词有 90 天 TTL，过期后重新流入 `_extract_words` → LLM 验证 → 60% 回测流程。但 90 天是被动等，对于"已经在生产里 0 共现但被 LLM 偶然误判"的词，效率太低。

黑灰产的语言演变是动态的 —— 昨天是日常的通用词，今天可能就被黑产团伙"征用"成暗语。例：历史上"茶叶 / 喝茶 / 品茶"从日常词演变成灰产代称。如果死黑名单永远是死的，**这些动态演变的黑话** 会被我们错过。

### 方案 D：双盲审计自动化复活

**核心逻辑**：
- 每周（cron）跑 `scripts/audit_slang_quality.py` 时，**同时**把黑名单里的词也拿出来
- 给每个黑名单词，从最新的 Kafka 语料 / clues 表里取 5-10 条上下文
- 让 LLM 重新判定：is_slang=true 且 confidence >= 90？
- 如果是 → 自动踢出黑名单 + 重新激活为候选 + 走 LLM 验证 → 60% 回测 → CONFIRMED
- 如果不是 → 重置 TTL（再给 90 天）

**双盲设计**：
- 主审计: qwen3.6-flash
- 复核审计: MiniMax-M2.7 (或另一个独立 LLM)
- Diff 出"主-副不一致"的词 → 人工 final call
- 双 LLM 一致标 is_slang=true 且 conf>=95 → **无需人工**直接复活
- 双 LLM 一致标 is_slang=false → **无需人工**直接续期 TTL
- 一致但 conf<80 或不一致 → 进人工队列

### 实施步骤

1. **持久化黑名单的"历史上下文"**
   - 现状：`_extract_words` 提取后, 词直接进 `slang_candidates` 表，无历史语料
   - 需要：注册进黑名单时，把当时的 5 条上下文保留到 `blacklist_history_contexts` 表
   - SQL: `CREATE TABLE antiblack.blacklist_history_contexts (word TEXT, context TEXT, captured_at TIMESTAMPTZ)`
   - 字段: word, context_text, source_message_id, captured_at

2. **双 LLM 审计脚本**
   - 新增 `scripts/audit_blacklist_quality.py`
   - 复用 `audit_slang_quality.py` 的 LLM client 封装
   - 复用 `clues` 表的上下文检索（`db.get_clue_contexts_for_word(word, limit=10)`)
   - 输出 `scripts/audit_blacklist_results.json`，结构:
     ```json
     {
       "audit_at": "...",
       "model_primary": "qwen3.6-flash",
       "model_secondary": "...",
       "items": [
         {
           "word": "原创",
           "primary": {"is_slang": false, "confidence": 92},
           "secondary": {"is_slang": false, "confidence": 95},
           "decision": "renew_ttl",  // or "resurrect" or "human_review"
         }
       ]
     }
     ```

3. **复活执行器** `scripts/resurrect_blacklist_words.py`
   - 读取 `audit_blacklist_results.json` 里 `decision="resurrect"` 的项
   - 走完整流程: 从 `slang_candidates` 表找到原词 → 重新触发 LLM 验证 → 60% 回测
   - 复活失败的 → 续期 TTL
   - 人工队列的 → 输出 CSV 等人工处理

4. **每周 cron 任务** (基础设施侧)
   - 周日 03:00 跑 `audit_blacklist_quality.py` → 产 JSON
   - 周日 03:30 跑 `resurrect_blacklist_words.py --dry-run` → 人工 review 队列
   - 周一 10:00 跑 `resurrect_blacklist_words.py` 真跑
   - 周一 10:30 通知: `#anti-black-ops` Slack 频道

5. **监控埋点** (Grafana 看板)
   - `blacklist_active_count` gauge: 当前 active 黑名单词数
   - `blacklist_expired_7d` counter: 7 天内过期的词数
   - `blacklist_resurrected_7d` counter: 7 天内复活的词数
   - `blacklist_resurrected_to_confirmed_30d` counter: 复活后真正走到 CONFIRMED 的数

### 风险与边界

- **复活误判**: LLM 误判 is_slang=true (极小概率但不为零) → 假阳性复活
  - 缓解: 复活后必须走完 60% 回测才能 CONFIRMED, 60% 阈值是一道硬关
  - 监控: `blacklist_resurrected_to_confirmed_30d` 异常飙升则告警
- **审计成本**: 双 LLM 审计 × N 个黑名单词 × 每周 = 单次 ~$0.50
  - 缓解: 90 天未到 TTL 的词不审; 只审 TTL 已过期或即将过期 (剩余 <14d) 的词
- **历史上下文保留**: `blacklist_history_contexts` 表会持续增长
  - 缓解: 90 天前的历史上下文可清理 (CRON: `DELETE WHERE captured_at < NOW() - INTERVAL '90 days'`)
- **未在本次范围**:
  - 黑名单的"语义聚类": 多个黑名单词如果语义相近 (如 "原创" "笔记" "日常") 应该合并为"日常内容标签"这一类
  - 跨渠道黑名单同步: 抖音 / TikTok 渠道的方言黑话可能不同, 需要 per-channel TTL

### 相关记忆

- [[project-scope]] — 字节系黑产是焦点, 游戏账号交易不在范围
- [[slang-evolution]] — slang 演化机制 (待补)

---

## Backlog-02: 黑名单"语义聚类"管理

**状态**: 📋 待排期  
**依赖**: Backlog-01

把同类黑名单词聚类 (e.g. "原创 / 笔记 / 日常" → "内容标签")，维护更轻量：
- 聚类粒度更粗 → 1 个聚类代表 1 个 LLM 拒绝规则
- LLM prompt 里写"凡是内容标签类都拒" → 不需要枚举所有具体词
- 配合 Backlog-01 复活机制，复活时也是聚类粒度

---

## Backlog-03: 跨渠道黑名单差异化 TTL

**状态**: 📋 待排期  
**依赖**: Backlog-01

抖音的"原创"和 TikTok 的"original"语义不同。应该 per-channel TTL:
- `slang_blacklist_state[word].channel_overrides[channel] = expires_at`
- 默认走 global TTL; channel-specific override 在 channel 召回时优先

---

## Backlog-04: AC Automaton 接入生产 (替换 substring `in`)

**状态**: 📋 待排期  
**当前状态**: `services/ac_automaton_service.py` 已写好，但 `_ac_automaton = None`，走 substring `in` 检查

emoji 修复后，CJK 字典 + emoji 词字典的 findall 性能需要 AC Automaton 托底：
- 千词字典 + 万条/秒 throughput
- emoji (4 字节 UTF-8) 在 byte-level Trie 下的内存占用
- 单元测试已就绪: `tests/test_ac_automaton_emoji.py`

**前置**: 跑一周生产观察 substring `in` 是否真的成为瓶颈

---

## Backlog-05: emoji slang 季度语料抽查

**状态**: 📋 待排期  
**依赖**: Backlog-01 (复活机制), Backlog-04 (AC)

每季度抽 100 条含 emoji 的 slang candidate，人工 verify emoji 是否在黑话中真有隐语意义:
- 比如 "💰" / "😈" / "🔞" 在不同上下文里含义不同
- 可能有些 emoji 是营销号常用但被误判为黑话
- 季度报告里给出 emoji → 黑话含义映射表
