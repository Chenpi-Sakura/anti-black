<template>
  <div class="metric-card">
    <div class="metric-header">
      <span class="metric-title">{{ title }}</span>
      <slot name="extra" />
    </div>
    <div class="metric-body">
      <slot>
        <div class="metric-value-row">
          <span class="metric-value">{{ formattedValue }}</span>
          <span v-if="unit" class="metric-unit">{{ unit }}</span>
        </div>
        <div v-if="hint" class="metric-hint">{{ hint }}</div>
      </slot>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  value: { type: [Number, String], default: 0 },
  unit: { type: String, default: '' },
  hint: { type: String, default: '' },
  // When true, format value with toLocaleString(); set false for raw display
  format: { type: Boolean, default: true }
})

const formattedValue = computed(() => {
  if (props.value == null) return '-'
  if (typeof props.value === 'number' && props.format) {
    return props.value.toLocaleString()
  }
  return String(props.value)
})
</script>

<style scoped>
.metric-card {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
  display: flex;
  flex-direction: column;
  min-height: 110px;
}

.metric-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-sm);
}

.metric-title {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.metric-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.metric-value-row {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-xs);
}

.metric-value {
  font-size: var(--font-size-xxl);
  font-weight: 500;
  color: var(--color-text-primary);
  line-height: 1.2;
}

.metric-unit {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.metric-hint {
  margin-top: var(--spacing-xs);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}
</style>
