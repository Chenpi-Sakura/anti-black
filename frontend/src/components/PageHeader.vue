<template>
  <div class="page-header">
    <div class="header-text">
      <h2 v-if="title" class="page-title">{{ title }}</h2>
      <slot name="title-extra" />
      <p v-if="subtitle" class="page-subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="header-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' }
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: var(--spacing-md);
  padding-bottom: var(--spacing-sm);
  border-bottom: var(--border-thin) solid var(--color-divider);
}

.header-text {
  flex: 1;
  min-width: 0;
}

.page-title {
  font-size: 22px;
  font-weight: 500;
  color: var(--color-text-primary);
  margin: 0 0 var(--spacing-xxs) 0;
}

.page-subtitle {
  font-size: 13px;
  color: var(--color-text-muted);
  margin: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  flex-shrink: 0;
}
</style>
