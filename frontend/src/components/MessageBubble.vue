<template>
  <div :class="['message', role]">
    <div class="message-avatar">
      <span v-if="role === 'user'">👤</span>
      <span v-else>🤖</span>
    </div>
    <div class="message-content" :class="{ 'has-reasoning': role === 'assistant' && message.reasoning?.length }">
      <!-- ReasoningBlock：AI 执行过程（折叠在回复上方） -->
      <div v-if="role === 'assistant' && message.reasoning?.length" class="reasoning-block">
        <div class="reasoning-header" @click="message._reasoningExpanded = !message._reasoningExpanded">
          <span class="reasoning-toggle">{{ message._reasoningExpanded ? '▼' : '▶' }}</span>
          <span class="reasoning-summary">推理过程（{{ message.reasoning.length }} 步）</span>
          <span v-if="message.reasoningDuration" class="reasoning-duration">{{ message.reasoningDuration }}</span>
        </div>
        <div v-if="message._reasoningExpanded" class="reasoning-steps">
          <div v-for="(step, i) in message.reasoning" :key="i" class="reasoning-step" :class="stepClass(step)">
            <span class="step-dot" :class="stepDotClass(step)"></span>
            <span class="step-label">{{ step.content || getStageLabel(step.stage) }}</span>
            <span v-if="step.tool_name && !['skill_selecting','skill_selected','plan'].includes(step.stage)" :class="['step-tool', `tool-${step.tool_name}`]">{{ step.tool_name }}</span>
            <span v-if="step.elapsed_ms !== undefined" class="step-ms">{{ step.elapsed_ms }}ms</span>
            <span v-if="step.iteration" class="step-iter">#{{ step.iteration }}</span>
          </div>
        </div>
      </div>
      <!-- 消息正文 -->
      <div class="message-body">
        <div class="message-text" v-html="renderedContent"></div>
      </div>
      <div class="message-time">{{ formatTime(message.timestamp) }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import python from 'highlight.js/lib/languages/python'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import sql from 'highlight.js/lib/languages/sql'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import yaml from 'highlight.js/lib/languages/yaml'

// Register only the languages we actually see in LLM output (SQL/JSON/bash
// dominate). Full hljs bundle is ~1MB; core + 8 langs is ~40KB.
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('py', python)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('sh', bash)
hljs.registerLanguage('shell', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('css', css)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('yml', yaml)

const props = defineProps({
  message: { type: Object, required: true },
  role: { type: String, default: 'assistant' }
})

const marked = new Marked(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      // hljs.getLanguage is the source of truth — if the language isn't
      // registered, fall back to HTML-escaped raw text. Calling
      // hljs.highlight with an unregistered name throws (Unknown language).
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
      }
      return code
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
    }
  })
)
marked.setOptions({
  gfm: true,
  breaks: true,
  // No pedantic: tolerate slightly-malformed LLM output without throwing.
})

// Render the LLM's markdown output directly. The previous regex-based
// "newline repair" is gone: the real culprit was services/orchestrator.py
// _chunk_text() calling .strip() on each SSE chunk, which erased the
// leading/trailing newlines the LLM emits. Now fixed at the source — we
// trust the markdown and let marked parse it as-is.
const renderedContent = computed(() => {
  const text = props.message.content
  if (!text) return ''
  return marked.parse(text)
})

function getStageLabel(stage) {
  const labels = {
    'parsing': '理解用户意图',
    'retrieving': '调用 LightRAG 检索',
    'retrieved': '知识图谱查询完成',
    'analyzing': '生成分析报告',
    'results': '整理情报结果',
    'complete': '处理完成',
    'reasoning': 'LLM 推理过程',
    'skill_selecting': '正在分析意图…选择 Skill',
    'skill_selected': 'Skill 已选择',
    'plan': '计划已生成',
    'thinking': 'LLM 推理中',
    'tool_started': '工具开始执行',
    'tool_completed': '工具执行完成',
    'tool_failed': '工具执行失败',
  }
  return labels[stage] || stage
}

function stepClass(step) {
  if (step.stage === 'thinking') return 'step-thinking'
  if (step.stage === 'tool_started') return 'step-tool-active'
  if (step.stage === 'tool_failed') return 'step-tool-failed'
  if (['skill_selecting', 'skill_selected', 'plan'].includes(step.stage)) return 'step-skill'
  return ''
}

function stepDotClass(step) {
  if (step.stage === 'thinking') return 'dot-thinking'
  if (step.stage === 'tool_started') return 'dot-active'
  if (step.stage === 'tool_failed') return 'dot-failed'
  if (['skill_selecting', 'skill_selected', 'plan'].includes(step.stage)) return 'dot-skill'
  return ''
}

function formatTime(time) {
  if (!time) return ''
  return new Date(time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.message {
  display: flex;
  gap: var(--spacing-sm);
  align-items: flex-start;
  animation: fadeSlideIn var(--duration-standard) var(--ease-out-quint);
}

.message.user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--color-primary-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-lg);
  flex-shrink: 0;
}

.message-content {
  max-width: 80%;
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: 8px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  overflow: visible;
}

.message-content.has-reasoning {
  padding-top: 0;
}

.message.user .message-content {
  background: var(--color-primary);
  color: white;
  border-color: var(--color-primary);
}

.message-body { width: 100%; }

.message-text {
  line-height: 1.7;
  word-break: break-word;
  font-size: var(--font-size-sm);
  overflow: visible;
  width: 100%;
}

.message-text :deep(p) { margin: 0.6em 0; line-height: 1.7; }
.message-text :deep(p:first-child) { margin-top: 0; }
.message-text :deep(p:last-child) { margin-bottom: 0; }
.message-text :deep(h1), .message-text :deep(h2),
.message-text :deep(h3), .message-text :deep(h4) {
  margin: 0.8em 0 0.4em; font-weight: 600; line-height: 1.4;
}
.message-text :deep(h1) { font-size: 1.35em; }
.message-text :deep(h2) { font-size: 1.2em; }
.message-text :deep(h3) { font-size: 1.1em; }
.message-text :deep(h4) { font-size: 1em; }
.message-text :deep(ul), .message-text :deep(ol) {
  margin: 0.6em 0; padding-left: 1.5em;
}
.message-text :deep(ul) { list-style-type: disc; }
.message-text :deep(ol) { list-style-type: decimal; }
.message-text :deep(li) { margin: 0.35em 0; line-height: 1.6; }
.message-text :deep(li > ul), .message-text :deep(li > ol) { margin: 0.25em 0; }
.message-text :deep(table) {
  border-collapse: collapse; width: 100%; margin: 1em 0; font-size: var(--font-size-sm);
  overflow: visible; border: 1px solid #dfe2e5;
}
.message-text :deep(table th), .message-text :deep(table td) {
  border: 1px solid #dfe2e5; padding: 8px 12px; text-align: left;
}
.message-text :deep(table th) { background: #f6f8fa; font-weight: 600; }
.message-text :deep(table tr:nth-child(even) td) { background: #fafbfc; }
.message-text :deep(pre) {
  background: #1e1e2e; padding: 12px 16px; border-radius: 6px;
  overflow-x: auto; margin: 0.8em 0; border: 1px solid #2a2a3a;
}
.message-text :deep(pre code) {
  background: none; padding: 0; color: #cdd6f4;
  font-size: var(--font-size-sm); font-family: var(--font-mono);
}
/* highlight.js token colors — Catppuccin Mocha-inspired palette, designed
   for dark backgrounds. Inline `code` (no <pre>) keeps the original light
   styling; only block code uses these. */
.message-text :deep(.hljs-keyword),
.message-text :deep(.hljs-selector-tag),
.message-text :deep(.hljs-built_in) { color: #cba6f7; }
.message-text :deep(.hljs-string),
.message-text :deep(.hljs-attr),
.message-text :deep(.hljs-title.class_) { color: #a6e3a1; }
.message-text :deep(.hljs-number),
.message-text :deep(.hljs-literal) { color: #fab387; }
.message-text :deep(.hljs-comment),
.message-text :deep(.hljs-quote) { color: #6c7086; font-style: italic; }
.message-text :deep(.hljs-variable),
.message-text :deep(.hljs-template-variable),
.message-text :deep(.hljs-name) { color: #f38ba8; }
.message-text :deep(.hljs-function),
.message-text :deep(.hljs-title.function_) { color: #89b4fa; }
.message-text :deep(.hljs-type),
.message-text :deep(.hljs-class .hljs-title) { color: #f9e2af; }
.message-text :deep(.hljs-tag),
.message-text :deep(.hljs-meta) { color: #f5c2e7; }
.message-text :deep(blockquote) {
  border-left: 3px solid var(--color-primary); margin: 0.8em 0;
  padding: 8px 16px; color: var(--color-text-secondary);
  background: var(--color-primary-subtle); border-radius: 0 4px 4px 0;
}
.message-text :deep(strong) { font-weight: 700; }
.message.user .message-text :deep(strong) { color: rgba(255, 255, 255, 0.95); }
.message-text :deep(a) { color: var(--color-primary); text-decoration: underline; text-underline-offset: 2px; }
.message-text :deep(hr) { border: none; border-top: 1px solid var(--color-border); margin: 1em 0; }
.message-text :deep(code) {
  background: rgba(0, 0, 255, 0.06); padding: 2px 6px; border-radius: 3px;
  font-size: 0.9em; font-family: var(--font-mono); color: #d63384;
}

.message-time {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-top: 4px;
}

.message.user .message-time { color: rgba(255, 255, 255, 0.7); }

.reasoning-block {
  margin-bottom: var(--spacing-sm);
  border-bottom: 1px solid var(--color-divider);
  padding-bottom: var(--spacing-sm);
}

.reasoning-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  cursor: pointer;
  user-select: none;
  padding: 4px 0;
}

.reasoning-toggle {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.reasoning-summary { flex: 1; }

.reasoning-duration {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  background: var(--color-divider);
  padding: 1px 6px;
  border-radius: 3px;
}

.reasoning-steps {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin-top: 4px;
}

.reasoning-step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0 4px 4px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.step-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-border);
  flex-shrink: 0;
}

.step-label { flex: 1; }

.step-tool {
  font-size: var(--font-size-xs);
  padding: 1px 6px;
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  border-radius: 3px;
  white-space: nowrap;
}

/* Per-tool color coding.  Each tool name maps to a distinct hue so the
   user can scan the reasoning block and tell at a glance which tools
   the agent picked.  Color is hue-only (no brightness) so the
   primary-blue chrome stays consistent. */
.step-tool.tool-search_clues,
.step-tool.tool-get_recent_clues {
  background: rgba(0, 0, 255, 0.12);
  color: #0000a0;
}
.step-tool.tool-kg_query {
  background: rgba(128, 0, 255, 0.14);
  color: #5b21b6;
}
.step-tool.tool-search_entities {
  background: rgba(0, 153, 76, 0.14);
  color: #15803d;
}
.step-tool.tool-get_clue_detail {
  background: rgba(255, 140, 0, 0.16);
  color: #b45309;
}
.step-tool.tool-search_slang {
  background: rgba(234, 179, 8, 0.18);
  color: #92400e;
}

@keyframes fadeSlideIn {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Step status colors for skill/thinking/tool events */
.step-skill { background: rgba(0, 150, 255, 0.08); border-radius: 4px; }
.step-tool-active .step-dot { background: #2563eb; animation: pulse-blue 1.2s ease-in-out infinite; }
.step-tool-failed .step-dot { background: #dc2626; }
.step-thinking .step-dot { background: #7c3aed; }
.step-skill .step-dot { background: #0284c7; }
.dot-active { background: #2563eb; animation: pulse-blue 1.2s ease-in-out infinite; }
.dot-failed { background: #dc2626; }
.dot-thinking { background: #7c3aed; }
.dot-skill { background: #0284c7; }

.step-ms {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  background: var(--color-divider);
  padding: 1px 5px;
  border-radius: 3px;
  white-space: nowrap;
}
.step-iter {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
}

@keyframes pulse-blue {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

</style>
