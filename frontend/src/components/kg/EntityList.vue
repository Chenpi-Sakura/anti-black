<template>
  <ul class="el-list">
    <li v-for="e in entities" :key="e.entity_name"
        :class="['entity-item', { selected: e.entity_name === selectedId }]"
        @click="$emit('select', e.entity_name)">
      <el-tag size="small" :type="tagType(e.entity_type)">{{ e.entity_type }}</el-tag>
      <span class="entity-name">{{ e.entity_name }}</span>
    </li>
    <li v-if="!entities.length" class="empty-item">无实体</li>
  </ul>
</template>

<script setup>
defineProps({ entities: { type: Array, default: () => [] }, selectedId: { type: String, default: null } })
defineEmits(['select'])
function tagType(t) {
  const m = { PERSON: 'primary', ORG: 'success', PHONE: 'warning', WECHAT: 'danger', ACCOUNT: 'info', URL: 'info' }
  return m[String(t).toUpperCase()] || 'info'
}
</script>

<style scoped>
.el-list { list-style: none; padding: 0; margin: 0; }
.entity-item { display: flex; align-items: center; gap: 6px; padding: 6px 8px; cursor: pointer; border-radius: 4px; font-size: 13px; }
.entity-item:hover { background: var(--color-primary-subtle, #ecf5ff); }
.entity-item.selected { background: var(--color-primary-light, #d9ecff); font-weight: 600; }
.entity-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty-item { color: var(--color-text-muted, #999); font-size: 12px; padding: 12px; text-align: center; }
</style>
