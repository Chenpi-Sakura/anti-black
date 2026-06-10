<template>
  <div class="empty-state">
    <el-icon v-if="icon" class="empty-icon">
      <component :is="icon" />
    </el-icon>
    <p class="empty-description">{{ description }}</p>
    <div v-if="$slots.action" class="empty-action">
      <slot name="action" />
    </div>
  </div>
</template>

<script setup>
import { Box } from '@element-plus/icons-vue'

defineProps({
  description: { type: String, default: '暂无数据' },
  icon: { type: [String, Object], default: () => Box }
})
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-xl) var(--spacing-md);
  color: var(--color-text-muted);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: var(--spacing-sm);
  color: var(--color-text-muted);
  opacity: 0.5;
}

.empty-description {
  font-size: var(--font-size-sm);
  margin: 0 0 var(--spacing-sm) 0;
}

.empty-action {
  margin-top: var(--spacing-xs);
}
</style>
