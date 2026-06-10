<template>
  <div class="base-card" :class="{ 'no-padding': noPadding }">
    <div v-if="title || $slots.header" class="card-header">
      <div class="header-left">
        <el-icon v-if="icon" class="header-icon">
          <component :is="icon" />
        </el-icon>
        <h3 v-if="title" class="card-title">{{ title }}</h3>
        <slot name="header" />
      </div>
      <div v-if="$slots['header-actions']" class="header-actions">
        <slot name="header-actions" />
      </div>
    </div>
    <div class="card-body">
      <slot />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  icon: { type: [String, Object], default: '' },
  noPadding: { type: Boolean, default: false }
})
</script>

<style scoped>
.base-card {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
  transition: all var(--duration-standard) var(--ease-out-quint);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-sm);
  padding-bottom: var(--spacing-xs);
  border-bottom: var(--border-thin) solid var(--color-divider);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.header-icon {
  font-size: var(--font-size-base);
  color: var(--color-primary);
}

.card-title {
  font-size: var(--font-size-base);
  font-weight: 500;
  color: var(--color-text-primary);
  margin: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.no-padding .card-body {
  padding: 0;
}
</style>
