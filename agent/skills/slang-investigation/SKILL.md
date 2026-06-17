---
name: slang-investigation
description: "黑话与暗语调查：输入黑话/暗语/Emoji/TODO 等模糊标识，输出词典释义、分类场景、使用分布与相关线索。"
triggers: ["黑话", "暗语", "啥意思", "什么意思", "啥", "chuhao", "缩写", "emoji", "黑产术语"]
tools: ["search_slang", "search_clues", "kg_query"]
plan_template: ["查询黑话词典", "拉取使用线索", "挖掘关联场景", "生成解读报告"]
---

# Slang Investigation Skill

## 何时使用
用户问"chuhao 是啥意思"、"最近有谁在用这个"、"XX是什么黑话"。

## 强制工作流（按顺序执行）
1. **第一步调 `search_slang`**（`slang_term` 用用户输入的词）
   - 从 slang_mappings 表中获取含义 + 分类
2. **第二步调 `search_clues`**（`query` 用用户输入的词）
   - 拉最近的使用线索，看分布在什么场景和平台
3. **第三步按需调 `kg_query`**
   - 如果该黑话关联了特定实体/关系网络
4. **生成报告**

## 无追问规则（继承 CORE）
- 黑话不明确时（如"最近有啥新的"、"帮我看下黑话"），默认用 search_slang(limit=20) 展示最近黑话
- 不追问"你具体问哪个"
- 如果用户只说了一个词（如"chuhao"），就当 slang_term 查询

## 输出结构（强制 Markdown 排版）
一、**黑话释义**：黑话 | 含义 | 分类 | 示例
二、**使用分布**：按平台和时间的分布
三、**相关线索与典型案例**
四、**关联场景与实体**
五、**综合研判**

## 错误兜底
- search_slang 返回空 → 报告说明"未收录该黑话"; 发起 search_clues 看是否在 text 中作为普通词出现
- search_clues 返回空 → "暂未发现使用记录"
- 全空 → "暂无该黑话相关信息"
