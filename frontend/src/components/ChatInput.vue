<template>
  <div class="input-section">
    <div class="input-wrapper">
      <el-input
        :model-value="modelValue"
        type="textarea"
        :rows="2"
        :placeholder="placeholder"
        :disabled="disabled"
        @update:model-value="(v) => emit('update:modelValue', v)"
        @keyup.enter="emit('submit')"
        @keyup.enter.ctrl="emit('submit')"
      />
      <div class="input-actions">
        <span class="hint-text">Enter / Ctrl+Enter 发送</span>
        <el-button
          type="primary"
          :loading="isProcessing"
          :disabled="!modelValue || !modelValue.trim()"
          @click="emit('submit')"
        >
          {{ isProcessing ? '处理中...' : '发送' }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '请输入您想查询的情报...' },
  disabled: { type: Boolean, default: false },
  isProcessing: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'submit'])
</script>

<style scoped>
.input-section {
  padding: var(--spacing-md) 0 0 0;
  flex-shrink: 0;
}

.input-wrapper {
  background: var(--color-surface);
  border: 1px solid var(--color-primary-subtle);
  border-radius: 10px;
  padding: var(--spacing-sm);
  transition: border-color var(--duration-normal) var(--ease-out-quint);
}

.input-wrapper:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px rgba(0, 0, 255, 0.08);
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: var(--spacing-xs);
}

.hint-text {
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>
