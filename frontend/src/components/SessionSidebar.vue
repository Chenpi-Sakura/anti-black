<template>
  <div class="session-sidebar" :class="{ collapsed }">
    <div class="sidebar-header">
      <h3 v-if="!collapsed">对话历史</h3>
      <el-button
        :class="['sidebar-toggle-btn', { collapsed }]"
        text
        @click="emit('toggle')"
      >
        <el-icon v-if="collapsed"><Expand /></el-icon>
        <el-icon v-else><Fold /></el-icon>
      </el-button>
    </div>
    <div v-if="!collapsed" class="sidebar-content">
      <el-button class="new-chat-btn" @click="emit('new')">
        <el-icon><Plus /></el-icon> 新建对话
      </el-button>
      <div class="conversation-list">
        <div
          v-for="conv in conversations"
          :key="conv.conversation_id"
          :class="['conversation-item', { active: conv.conversation_id === currentId }]"
          @click="emit('select', conv.conversation_id)"
        >
          <span class="conv-title">{{ conv.title || '无标题对话' }}</span>
          <span class="conv-date">{{ formatDate(conv.created_at) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Plus, Expand, Fold } from '@element-plus/icons-vue'

defineProps({
  conversations: { type: Array, default: () => [] },
  currentId: { type: String, default: null },
  collapsed: { type: Boolean, default: false }
})

const emit = defineEmits(['select', 'new', 'toggle'])

function formatDate(dateStr) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
</script>

<style scoped>
.session-sidebar {
  width: 350px;
  flex-shrink: 0;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width var(--duration-normal) var(--ease-out-quint);
}

.session-sidebar.collapsed {
  width: 48px;
  border: none;
  background: transparent;
}

.session-sidebar.collapsed .sidebar-header {
  border: none;
  padding: 0;
  justify-content: center;
  margin-top: var(--spacing-sm);
}

.sidebar-toggle-btn {
  font-size: var(--font-size-lg);
  width: 36px;
  height: 36px;
  padding: 0;
  border-radius: 8px;
  color: var(--color-text-secondary);
  transition: all var(--duration-normal) var(--ease-out-quint);
}

.sidebar-toggle-btn:hover {
  background: var(--color-primary-subtle);
  color: var(--color-primary);
}

.sidebar-toggle-btn.collapsed {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-hover);
}

.sidebar-toggle-btn.collapsed:hover {
  background: var(--color-primary-subtle);
  border-color: var(--color-primary);
  transform: translateY(-1px);
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-sm) var(--spacing-xs);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.sidebar-header h3 {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text-primary);
  letter-spacing: 0.5px;
}

.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-xs);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.new-chat-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 8px 12px;
  border: 1px dashed var(--color-primary);
  border-radius: 6px;
  color: var(--color-primary);
  background: transparent;
  font-size: var(--font-size-sm);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease-out-quint);
}

.new-chat-btn:hover {
  background: var(--color-primary-subtle);
  border-style: solid;
}

.conversation-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.conversation-item {
  padding: 10px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: var(--font-size-sm);
  display: flex;
  flex-direction: column;
  gap: 3px;
  transition: background var(--duration-normal) var(--ease-out-quint);
}

.conversation-item:hover {
  background: var(--color-primary-subtle);
}

.conversation-item.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.conversation-item.active .conv-title {
  color: var(--color-primary);
  font-weight: 500;
}

.conv-title {
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--font-size-sm);
  line-height: 1.4;
}

.conv-date {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}
</style>
