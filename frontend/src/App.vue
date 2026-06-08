<template>
  <div class="app-container">
    <header class="app-header">
      <div class="header-left">
        <span class="logo">::</span>
        <h1 class="system-title">黑灰产情报分析 Agent</h1>
      </div>
      <div class="header-right">
        <span :class="['status-indicator', statusClass]"></span>
        <span class="status-text">{{ statusText }}</span>
      </div>
    </header>

    <nav class="app-nav">
      <router-link to="/" class="nav-item">
        <el-icon><Monitor /></el-icon>
        <span>监控概览</span>
      </router-link>
      <router-link to="/query" class="nav-item">
        <el-icon><Search /></el-icon>
        <span>情报查询</span>
      </router-link>
      <router-link to="/clues" class="nav-item">
        <el-icon><Document /></el-icon>
        <span>线索列表</span>
      </router-link>
      <router-link to="/feedback" class="nav-item">
        <el-icon><Edit /></el-icon>
        <span>反馈管理</span>
      </router-link>
    </nav>

    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAppStore } from './stores/app'
import { systemApi } from './api'
import { Monitor, Search, Document, Edit } from '@element-plus/icons-vue'

const store = useAppStore()

const statusClass = computed(() => {
  if (store.systemReady) return 'status-online'
  if (store.systemStatus === 'BOOTSTRAPPING') return 'status-bootstrapping'
  return 'status-error'
})

const statusText = computed(() => {
  if (store.systemReady) return '在线'
  if (store.systemStatus === 'BOOTSTRAPPING') return '初始化中'
  return '异常'
})

onMounted(async () => {
  try {
    const res = await systemApi.ready()
    if (res.data?.data) {
      store.setSystemStatus(res.data.data.status)
    }
  } catch (e) {
    console.error('Failed to fetch system status:', e)
  }
})
</script>

<style scoped>
.app-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--color-background);
  overflow: hidden;
}

.app-header {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--spacing-lg);
  background: var(--color-surface);
  border-bottom: var(--border-thin) solid var(--color-primary-subtle);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.logo {
  font-size: 24px;
  color: var(--color-primary);
  font-family: var(--font-serif);
}

.system-title {
  font-size: 20px;
  font-weight: 500;
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.status-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-online {
  background: var(--color-success);
}

.status-bootstrapping {
  background: var(--color-warning);
}

.status-error {
  background: var(--color-error);
}

.status-text {
  font-size: 14px;
  color: var(--color-text-secondary);
}

.app-nav {
  display: flex;
  gap: var(--spacing-md);
  padding: var(--spacing-sm) var(--spacing-lg);
  background: var(--color-surface);
  border-bottom: var(--border-thin) solid var(--color-divider);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-xxs);
  padding: var(--spacing-xs) var(--spacing-sm);
  color: var(--color-text-secondary);
  text-decoration: none;
  font-size: 14px;
  border-radius: var(--radius-sm);
  transition: all var(--duration-normal) var(--ease-out-quint);
}

.nav-item:hover {
  color: var(--color-primary);
  background: var(--color-primary-subtle);
}

.nav-item.router-link-active {
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.app-main {
  flex: 1;
  padding: var(--spacing-sm);
  overflow: hidden;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>