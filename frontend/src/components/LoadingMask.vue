<template>
  <Teleport to="body">
    <Transition name="mask-fade">
      <div v-if="loading" class="loading-mask">
        <div class="loading-content">
          <div class="spinner"></div>
          <p v-if="text" class="loading-text">{{ text }}</p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
withDefaults(defineProps({
  loading: { type: Boolean, default: false },
  text: { type: String, default: '加载中...' }
}), {})
</script>

<style scoped>
.loading-mask {
  position: fixed;
  inset: 0;
  background: rgba(255, 255, 255, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.loading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-sm);
}

.spinner {
  width: 36px;
  height: 36px;
  border: 3px solid var(--color-primary-subtle);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.loading-text {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.mask-fade-enter-active,
.mask-fade-leave-active {
  transition: opacity var(--duration-normal) var(--ease-out-quint);
}

.mask-fade-enter-from,
.mask-fade-leave-to {
  opacity: 0;
}
</style>
