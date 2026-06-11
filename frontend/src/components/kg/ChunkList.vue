<template>
  <div class="chunk-list">
    <div v-for="c in chunks" :key="c.chunk_id" class="chunk-item">
      <span class="chunk-meta">{{ c.file_path || '未知来源' }}</span>
      <pre class="chunk-text">{{ truncate(c.content, 300) }}</pre>
    </div>
    <div v-if="!chunks.length" class="empty-item">无分块</div>
  </div>
</template>

<script setup>
defineProps({ chunks: { type: Array, default: () => [] } })
function truncate(s, n) { return (s || '').length > n ? s.slice(0, n) + '…' : (s || '') }
</script>

<style scoped>
.chunk-list { display: flex; flex-direction: column; gap: 4px; }
.chunk-item { padding: 6px 8px; border-radius: 4px; background: var(--color-bg-tertiary, #f5f7fa); font-size: 11px; }
.chunk-meta { display: block; color: var(--color-text-muted, #999); font-size: 10px; margin-bottom: 2px; }
.chunk-text { white-space: pre-wrap; word-break: break-word; margin: 0; font-size: 11px; line-height: 1.4; max-height: 100px; overflow-y: auto; color: var(--color-text-secondary, #666); }
.empty-item { color: var(--color-text-muted, #999); font-size: 12px; padding: 12px; text-align: center; }
</style>
