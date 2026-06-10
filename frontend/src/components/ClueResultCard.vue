<template>
  <div class="clue-card" @click="emit('click', clue.clue_id)">
    <div class="clue-header">
      <span class="clue-risk">
        {{ clue.risk_label_level1 }}
        <span class="risk-arrow">→</span>
        {{ clue.risk_label_level2 }}
      </span>
      <span class="clue-confidence">
        {{ ((clue.confidence || 0) * 100).toFixed(0) }}%
      </span>
    </div>
    <div class="clue-text">{{ clue.cleaned_text || clue.raw_text }}</div>
    <div v-if="clue.entity_list?.length" class="clue-entities">
      <span
        v-for="(entity, idx) in clue.entity_list.slice(0, 3)"
        :key="idx"
        class="entity-tag"
      >
        {{ entity.entity_type }}: {{ entity.entity_value }}
      </span>
    </div>
    <div class="clue-footer">
      <span class="clue-channel">{{ getChannelName(clue.source_channel) }}</span>
      <span class="clue-time">{{ formatTime(clue.published_at) }}</span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  clue: { type: Object, required: true }
})

const emit = defineEmits(['click'])

const CHANNEL_NAME_MAP = {
  'douyin': '抖音',
  'baidu_tieba': '贴吧',
  'weibo': '微博',
  'xiaohongshu': '小红书',
  'kuaishou': '快手',
  'telegram': 'Telegram',
  'e2e': '测试'
}

function getChannelName(channel) {
  return CHANNEL_NAME_MAP[channel] || channel || '-'
}

function formatTime(timeStr) {
  if (!timeStr) return '-'
  return new Date(timeStr).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.clue-card {
  padding: var(--spacing-sm);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease-out-quint);
}

.clue-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-hover);
  transform: translateY(-1px);
}

.clue-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: var(--spacing-xs);
}

.clue-risk {
  font-weight: 500;
  color: var(--color-primary);
  font-size: var(--font-size-sm);
}

.risk-arrow {
  color: var(--color-text-muted);
  margin: 0 var(--spacing-xxs);
}

.clue-confidence {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  padding: 2px 8px;
  background: var(--color-primary-subtle);
  border-radius: 3px;
}

.clue-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clue-entities {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-xs);
}

.entity-tag {
  font-size: var(--font-size-xs);
  padding: 2px 6px;
  background: var(--color-primary-subtle);
  border-radius: 3px;
  color: var(--color-text-secondary);
}

.clue-footer {
  display: flex;
  justify-content: space-between;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}
</style>
