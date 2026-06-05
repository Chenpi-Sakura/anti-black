"""Centralized LLM prompt templates for Phase 2 components.

All prompts follow the System-Task-Rules-Output structure to constrain LLM
generations and minimize the risk of "creative" but unsafe outputs in a
risk-control context.
"""
from typing import List, Optional


# === Common system role used by both pipelines ===
SYSTEM_ROLE_RISK_ANALYST = (
    "你是一位资深的互联网黑产对抗与风控情报分析专家。"
    "你擅长从社交媒体文本中识别黑灰产信号，并严格遵守给定的分类体系与命名规范。"
)


# === Stage 3 LLM single-text classifier (legacy path) ===
LEGACY_CLASSIFY_PROMPT = """你是一个黑灰产情报分类专家。

分析以下文本，判断它属于哪种风险类型：

风险类别：
- 账号交易 - 买卖账号、租号、换绑等
- 流量作弊 - 刷粉、刷赞、刷量等
- 诈骗引流 - 刷单、杀猪盘、投资诈骗等
- 黑产工具 - 接码平台、群控工具等
- 未知/其他 - 无法判断或无风险

文本: {text}

仅返回JSON格式的分类结果，不要包含其他内容：
{{"level1": "类别名", "level2": "子类别", "confidence": 0.0-1.0, "reason": "判断理由"}}"""


# === Step 2.2: slang -> rule bridge ===
def build_slang_to_rule_prompt(
    slang_word: str,
    slang_meaning: str,
    current_taxonomy_text: str,
) -> str:
    """LLM 评判一个 CONFIRMED slang 是否适合作为某类别的关键词。

    强约束: 只输出纯文本关键词列表, 禁正则元字符, 禁具体品牌/App名。
    """
    return f"""**任务**
判断下面这个已经被系统识别为"已确认(CONFIRMED)"的黑灰产暗语, 是否适合作为某个具体类别的【分类关键词】(用于第一级规则匹配器)。

**暗语**
- 字面: {slang_word}
- 释义: {slang_meaning}

**当前分类体系**
{current_taxonomy_text}

**分析规则(严格遵守)**
1. 【高度抽象】关键词必须指向通用类别, 禁止包含具体品牌名、App名、平台名(如"抖音"、"微信"、"王者"等)。
   - ❌ 错误: "抖音代刷点赞"、"王者账号出售"
   - ✅ 正确: "刷量互动"、"账号买卖"
2. 【纯净文本】只输出纯文本子串, 严禁输出任何正则表达式元字符(如 `*+?{{}}()[].\\|^$` 等)。
3. 【类别归属】必须明确归属于【当前分类体系】中的某个 level1 (账号交易/流量作弊/诈骗引流/黑产工具/未知/其他/无关)。
4. 【粒度合理】关键词长度建议 2-8 个字符, 不宜过长。
5. 【拒绝扩散】如果该暗语过于狭窄, 只对极少数特定场景有效 (例如只针对某个游戏副本), 判为"不适合", 不要扩散到通用分类。

**输出格式(严格 JSON, 无其他内容)**
{{
  "suitable": true/false,
  "level1": "账号交易|流量作弊|诈骗引流|黑产工具|未知/其他|无关",
  "level2": "对应的 level2 子类别 (如'账号买卖'、'刷粉'、'刷单引流'、'接码平台'等)",
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "reason": "限 50 字以内的判断理由",
  "confidence": 0.0 到 1.0
}}

**只输出 JSON, 不要任何解释。**
"""


# === Step 2.3: unknown_discovery cluster naming ===
def build_cluster_naming_prompt(
    cluster_samples_text: str,
    current_taxonomy_text: str,
    cluster_size: int,
) -> str:
    """LLM 评判一个聚类簇, 决定是归入现有类别还是提议新类别。

    强约束: 优先归类, 高度抽象, 2-6 字命名, 避免生造黑话/具体名。
    """
    return f"""**任务**
系统对一批被分类为"未知/其他"的社交媒体文本进行了聚类(共 {cluster_size} 条样本, 以下是 Top 30 最典型样本)。请你判断: 这批样本是否属于现有的违规类别, 还是形成了一种【新型黑产/违规行为】。

**当前分类体系**
{current_taxonomy_text}

**待研判样本(Top 30 中心采样)**
{cluster_samples_text}

**严格遵守的研判规则**
1. 【优先归类】首先判断这些样本是否可以归入【当前分类体系】中的某一个现存类别(即使是用词变体)。如果可以, 绝对不要生造新类别, 必须把 proposed_level2 设为现有 level2 名称。
2. 【高度抽象】如果确实是新型黑产, 你必须对其进行高度抽象。禁止使用具体的品牌名、App 名、平台名或极其具体的金额/物品。
   - ❌ 错误示例: "抖音代刷点赞评论"、"出售500元微信号"
   - ✅ 正确示例: "刷量互动"、"账号买卖"
3. 【命名规范】新类别的名称必须是简练的中文名词短语, 字数严格限制在 2 到 6 个汉字之间。
4. 【无意义判定】如果这些样本完全是普通用户的日常交流、无意义乱码、或没有任何风控价值的正常广告/营销内容, 请将类别判定为 "无关" / 普通内容。
5. 【保守提议】如果置信度不足 0.8, 请把 is_new_category 设为 false, 并把 proposed_level1/proposed_level2 设为"未知/其他/未分类"。

**输出格式(严格 JSON, 无其他内容)**
{{
  "chain_of_thought": "分析这批样本的共同特征, 以及为什么不属于现有类别的理由 (限 50 字以内)",
  "is_new_category": true/false,
  "proposed_level1": "如果属于现有分类, 填现有 level1; 如果是全新大类, 建议符合规范的 level1 (通常归入'未知/其他')",
  "proposed_level2": "现有的 level2 名称, 或者提议的全新 level2 名称",
  "confidence": 0.0 到 1.0
}}

**只输出 JSON, 不要任何解释。**
"""


# === Helper to dump taxonomy as a human-readable text block ===
def format_taxonomy_text(categories: List[dict]) -> str:
    """Format the taxonomy config block as a text listing for prompt injection."""
    lines = []
    for cat in categories:
        level1 = cat.get("level1_name", cat.get("level1_code", ""))
        lines.append(f"- {level1}")
        for item in cat.get("level2_items", []):
            level2 = item.get("level2_name", item.get("level2_code", ""))
            lines.append(f"    · {level2}")
    return "\n".join(lines)
