# Daemon 分类流程优化方案

## 状态: ✅ 已实现

---

## 问题

Stage 2 (Embedding) 是 stub，永远返回 None，导致 rule 匹配不上的数据 100% 走 LLM。每次 polling 100 条数据，约 70 条走 LLM，非常耗 token。

---

## 优化方案 A: 降低阈值 + 启用 Embedding

### 改动

| 项目 | 原来 | 现在 |
|------|------|------|
| rule_threshold | 0.9 | 0.7 |
| _classify_by_embedding() | stub (返回 None) | 真正实现 |

### 优化后流程

```
Stage 1: Rule → confidence >= 0.7 → 直接返回 ★
Stage 2: Embedding (Ollama bge-m3 + sklearn) → confidence >= 0.6 → 直接返回 ★
Stage 3: LLM → 仅在 embedding 也不确定时调用
```

### 实现细节

1. **`config.yaml`**: `rule_confidence_threshold: 0.9 → 0.7`
2. **`pipeline/classifier.py`**:
   - `__init__` 中加载 sklearn 模型（从 `models/classifier_v*.pkl` 或 `models/xgboost_classifier.pkl`）
   - `_classify_by_embedding()` 调用 Ollama bge-m3 获取 embedding，然后用 sklearn 分类
   - 返回 `ClassificationResult(source='embedding', ...)`

---

## 已完成改动

### 1. config.yaml
```yaml
classification:
  rule_confidence_threshold: 0.7  # 从 0.9 改为 0.7
```

### 2. pipeline/classifier.py

- `__init__`: rule_threshold 默认 0.7，加载 sklearn 模型
- `_classify_by_embedding()`: 调用 Ollama bge-m3 + sklearn 分类

### 3. 预期效果

- LLM 调用量降低 60-70%
- Token 消耗降低 50%+

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