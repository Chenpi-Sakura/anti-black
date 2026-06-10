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
          <div v-for="(step, i) in message.reasoning" :key="i" class="reasoning-step">
            <span class="step-dot"></span>
            <span class="step-label">{{ step.content || getStageLabel(step.stage) }}</span>
            <span v-if="step.tool_name" :class="['step-tool', `tool-${step.tool_name}`]">{{ step.tool_name }}</span>
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
import MarkdownIt from 'markdown-it'

const props = defineProps({
  message: { type: Object, required: true },
  role: { type: String, default: 'assistant' }
})

const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: true
})

// Format raw message text and run 8 normalization regexes (table/list/heading fixes)
// to repair the LLM's occasionally-collapsed markdown output.
const renderedContent = computed(() => {
  const text = props.message.content
  if (!text) return ''
  const processed = text
    .replace(/\|\|/g, '|\n|')
    .replace(/^([ \t]*[^|\n]+?[^\s|])(\s*)(\|(?:[ \t]*[^\n|]+[ \t]*\|){2,})/gm, '$1\n\n$3')
    .replace(/([^\n|])[ \t]*\n[ \t]*(\|(?:[ \t]*[^\n|]+[ \t]*\|){2,})/g, '$1\n\n$2')
    .replace(/([^#\n])\s*(#{1,6}\s+)/g, '$1\n\n$2')
    .replace(/([^\|\-\*\#\s\n])\s*(-\s+[^\n]+)/g, '$1\n\n$2')
    .replace(/([^\|\-\*\#\s\n\[\(\{])\s*(\d+\.\s+)/g, '$1\n\n$2')
    .replace(/(\*\*)\s*(>)/g, '$1\n\n$2')
    .replace(/^[ \t]*(-{3,}|—+)[ \t]*$/gm, '\n\n---\n\n')
  return md.render(processed)
})

function getStageLabel(stage) {
  const labels = {
    'parsing': '理解用户意图',
    'retrieving': '调用 LightRAG 检索',
    'retrieved': '知识图谱查询完成',
    'analyzing': '生成分析报告',
    'results': '整理情报结果',
    'complete': '处理完成',
    'reasoning': 'LLM 推理过程'
  }
  return labels[stage] || stage
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
  background: #f6f8fa; padding: 12px 16px; border-radius: 6px;
  overflow-x: auto; margin: 0.8em 0; border: 1px solid var(--color-border);
}
.message-text :deep(pre code) { background: none; padding: 0; color: inherit; font-size: var(--font-size-sm); }
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
</style>
