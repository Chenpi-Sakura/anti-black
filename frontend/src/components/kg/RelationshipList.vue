<template>
  <ul class="el-list">
    <li v-for="(r, i) in relationships" :key="'r-'+i"
        :class="['rel-item', { selected: selectedKey && r.src_id === selectedKey[0] && r.tgt_id === selectedKey[1] }]"
        @click="$emit('select', [r.src_id, r.tgt_id])">
      <span class="rel-pair"><strong>{{ r.src_id }}</strong> <span class="arrow">→</span> <strong>{{ r.tgt_id }}</strong></span>
      <span class="rel-desc">{{ (r.description || '').slice(0, 30) }}</span>
    </li>
    <li v-if="!relationships.length" class="empty-item">无关系</li>
  </ul>
</template>

<script setup>
defineProps({ relationships: { type: Array, default: () => [] }, selectedKey: { type: Array, default: null } })
defineEmits(['select'])
</script>

<style scoped>
.el-list { list-style: none; padding: 0; margin: 0; }
.rel-item { padding: 5px 8px; cursor: pointer; border-radius: 4px; font-size: 12px; border-bottom: 1px dashed var(--color-divider, #eee); }
.rel-item:hover { background: var(--color-primary-subtle, #ecf5ff); }
.rel-item.selected { background: var(--color-primary-light, #d9ecff); }
.rel-pair { display: block; }
.arrow { margin: 0 4px; color: var(--color-primary, #409eff); }
.rel-desc { display: block; color: var(--color-text-secondary, #666); font-size: 11px; margin-top: 2px; }
.empty-item { color: var(--color-text-muted, #999); font-size: 12px; padding: 12px; text-align: center; }
</style>
