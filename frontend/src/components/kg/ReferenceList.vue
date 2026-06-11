<template>
  <ul class="el-list">
    <li v-for="ref in references" :key="ref.reference_id" class="ref-item">
      <span class="ref-id">{{ ref.reference_id || '-' }}</span>
      <span class="ref-path">{{ ref.file_path || '—' }}</span>
    </li>
    <li v-if="!references.length" class="empty-item">无引用</li>
  </ul>
</template>

<script setup>
defineProps({ references: { type: Array, default: () => [] } })
</script>

<style scoped>
.el-list { list-style: none; padding: 0; margin: 0; }
.ref-item { display: flex; gap: 8px; padding: 4px 8px; font-size: 12px; }
.ref-id { color: var(--color-primary, #409eff); font-weight: 600; min-width: 20px; }
.ref-path { color: var(--color-text-secondary, #666); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty-item { color: var(--color-text-muted, #999); font-size: 12px; padding: 12px; text-align: center; }
</style>
