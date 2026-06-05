# Daemon 分类流程优化方案

## 状态: ✅ 已实现 V2（2026-06-05）

---

## 当前状态：三级漏斗 + 拒识 + 归一化

```
输入文本
    ↓
┌─────────────────────────────────────────────┐
│ Stage 1: 规则匹配（regex / 关键词）          │
│   • 命中且 confidence >= 0.7 → 直接返回    │
│   • confidence 默认 0.9-0.95                │
│   • 零 Token                                │
└─────────────────────────────────────────────┘
    ↓ (未命中)
┌─────────────────────────────────────────────┐
│ Stage 2: Embedding 分类器（Ollama bge-m3）  │
│   • 1024 维向量 + sklearn LogisticRegression│
│   • threshold: confidence >= 0.6            │
│   • 拒识（FR-CLF-07）:                       │
│       max_proba < 0.45 → 拒识              │
│       margin (top1-top2) < 0.12 → 拒识     │
│   • 拒识时 source='embedding_uncertain'     │
│   • 满足阈值 → 直接返回 ★                   │
│   • 拒识 → 强制 fallback 到 LLM            │
└─────────────────────────────────────────────┘
    ↓ (拒识或未满足阈值)
┌─────────────────────────────────────────────┐
│ Stage 3: LLM 兜底                            │
│   • 调用 LLMClient（多 provider 链）         │
│   • 输出归一化（FR-CLF-06）                 │
│   • 零 Token 的 embedding 路径无效时唯一兜底 │
└─────────────────────────────────────────────┘
    ↓
[归一化] 所有出口经过 _normalize_level1_label
    ↓
clues.risk_label_level1 ∈ {5 个标准值}
```

### 关键改进（V2 增量更新，commits `98bd93a` + `329471d`）

| 改动 | 原因 | 代码位置 |
|---|---|---|
| 修复 `_classify_by_embedding*` 中 `proba[label_idx]` 越界 bug | 训练时 LabelEncoder 编码空间断裂，predict 返回原始编码值但 proba 列索引是连续的 | `pipeline/classifier.py:281, 396` |
| 加 `_normalize_level1_label` 静态方法 | 消除 LLM prompt 标签变体（`Unknown/Other` 等）污染 clues 表 | `pipeline/classifier.py:172-198` |
| 加 embedding max_proba + margin 拒识逻辑 | 开放集分类前置，避免对明显无关内容硬给一个高置信度标签 | `pipeline/classifier.py:400-422` |
| 加 IRRELEVANT 类别（level2: 普通内容/广告/噪声） | 让模型学会拒识明显无关内容（待收集 ≥1000 负样本重训） | `config.yaml:243-252` |
| 加 slang→rule 桥接（FR-EVO-06） | CONFIRMED slang 自动反哺 Stage 1 规则 | `pipeline/slang_to_rule_bridge.py` |
| 加 unknown_discovery 端到端（UMAP+HDBSCAN+强约束 LLM） | 自动发现新型黑产类别 | `pipeline/unknown_discovery.py` |

### 效果数据（实测）

| 指标 | 修复前 | 修复后 |
|---|---|---|
| Macro F1 | 0.674 | **0.93** |
| `classification_source='embedding'` 占比 | 49 / 34,935（0.14%） | 预计数千（待 daemon 跑 1-2 天观测） |
| `risk_label_level1` 唯一值数量 | 16+ 变体 | 严格 5 个标准值 |
| `index N out of bounds` 越界 Warning | 频繁 | 不再出现 |

### 相关文件

- 核心模块：`pipeline/classifier.py`
- 工具脚本：
  - `scripts/diagnose_training_data.py` — 数据分布诊断
  - `scripts/normalize_clue_labels.py` — 历史数据清洗（事务化 + 快照回滚）
  - `scripts/trigger_retrain.py` — 手动触发重训练
  - `scripts/calibrate_embedding_thresholds.py` — 拒识阈值直方图标定

---

<details>
<summary>📜 V1 历史（rule_threshold 0.9→0.7 + 启用 Embedding）</summary>

> **问题**：Stage 2 (Embedding) 是 stub，永远返回 None，导致 rule 匹配不上的数据 100% 走 LLM。每次 polling 100 条数据，约 70 条走 LLM，非常耗 token。
>
> **优化方案 A: 降低阈值 + 启用 Embedding**
>
> | 项目 | 原来 | 现在 |
> |------|------|------|
> | rule_threshold | 0.9 | 0.7 |
> | `_classify_by_embedding()` | stub (返回 None) | 真正实现 |
>
> **优化后流程**
> ```
> Stage 1: Rule → confidence >= 0.7 → 直接返回 ★
> Stage 2: Embedding (Ollama bge-m3 + sklearn) → confidence >= 0.6 → 直接返回 ★
> Stage 3: LLM → 仅在 embedding 也不确定时调用
> ```
>
> **实现细节**
> 1. `config.yaml`: `rule_confidence_threshold: 0.9 → 0.7`
> 2. `pipeline/classifier.py`:
>    - `__init__` 中加载 sklearn 模型
>    - `_classify_by_embedding()` 调用 Ollama bge-m3 + sklearn 分类
>    - 返回 `ClassificationResult(source='embedding', ...)`
>
> **预期效果**
> - LLM 调用量降低 60-70%
> - Token 消耗降低 50%+

</details>

---

## 验证

```bash
# 1. 重启 daemon
powershell -Command "Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force"
conda run -n anti-black python scripts/run_daemon.py > logs/antiblack_daemon.log 2>&1 &

# 2. 等待一个 collection cycle (15分钟)

# 3. 检查日志
grep -E "Rule classification|Embedding classification|LLM classification" logs/antiblack_daemon.log | sort | uniq -c

# 预期: Rule/Embedding 次数增加，LLM 次数减少
```
