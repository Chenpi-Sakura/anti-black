<template>
  <div class="dashboard">
    <h2 class="page-title">监控概览</h2>

    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-header">
          <span class="metric-title">Token 消耗</span>
        </div>
        <div class="token-gauge">
          <el-progress
            type="circle"
            :percentage="tokenPercentage"
            :color="tokenColor"
            :width="120"
          />
        </div>
        <div class="metric-detail">
          <span>{{ metrics.token_usage_today?.toLocaleString() || 0 }}</span>
          <span class="metric-unit">/ {{ dailyLimit.toLocaleString() }}</span>
        </div>
      </div>

      <div class="metric-card">
        <div class="metric-header">
          <span class="metric-title">今日处理</span>
        </div>
        <div class="metric-value">
          {{ metrics.messages_processed_today?.toLocaleString() || 0 }}
        </div>
        <div class="metric-unit">条消息</div>
      </div>

      <div class="metric-card">
        <div class="metric-header">
          <span class="metric-title">实体总数</span>
        </div>
        <div class="metric-value">
          {{ metrics.total_entities?.toLocaleString() || 0 }}
        </div>
        <div class="metric-unit">个实体</div>
      </div>

      <div class="metric-card">
        <div class="metric-header">
          <span class="metric-title">采集成功率</span>
        </div>
        <div class="metric-value">
          {{ ((metrics.collection_success_rate || 1) * 100).toFixed(1) }}%
        </div>
        <div class="metric-detail">
          <span>后台巡逻: {{ patrolStatus }}</span>
        </div>
      </div>
    </div>

    <div class="charts-row">
      <div class="chart-card">
        <h3 class="chart-title">分类分布</h3>
        <div class="chart-content">
          <div
            v-for="(item, index) in classificationDistribution"
            :key="index"
            class="distribution-item"
          >
            <div class="distribution-label">
              <span>{{ item.risk_label_level1 || item.label }}</span>
              <span>{{ item.count || item.value }} 条</span>
            </div>
            <div class="distribution-bar-container">
              <div
                class="distribution-bar"
                :style="{ width: getBarWidth(item) + '%' }"
              ></div>
            </div>
          </div>
        </div>
      </div>

      <div class="chart-card">
        <h3 class="chart-title">渠道状态</h3>
        <div class="chart-content">
          <div
            v-for="channel in channels"
            :key="channel.platform"
            class="channel-item"
          >
            <span class="channel-name">{{ channel.platform_name || channel.platform }}</span>
            <span :class="['channel-status', channel.status]">
              {{ getChannelStatusText(channel.status) }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { metricsApi, channelApi } from '../api'

const metrics = ref({})
const channels = ref([])
const dailyLimit = 1000000

const tokenPercentage = computed(() => {
  const used = metrics.value.token_usage_today || 0
  const limit = dailyLimit
  return Math.min(100, Math.round((used / limit) * 100))
})

const tokenColor = computed(() => {
  const pct = tokenPercentage.value
  if (pct < 30) return '#2D8B57'
  if (pct < 70) return '#FCA17D'
  return '#DA627D'
})

const patrolStatus = computed(() => {
  const status = metrics.value.background_patrol_status
  const statusMap = {
    'IDLE': '空闲',
    'RUNNING': '运行中',
    'DEGRADED': '降级',
    'STOPPED': '停止'
  }
  return statusMap[status] || status
})

const classificationDistribution = computed(() => {
  return metrics.value.classification_distribution || []
})

function getBarWidth(item) {
  const total = metrics.value.messages_processed_today || 1
  const count = item.count || item.value || 0
  return Math.max(5, (count / total) * 100)
}

function getChannelStatusText(status) {
  const map = {
    'healthy': '正常',
    'warning': '警告',
    'error': '异常',
    'unconfigured': '未配置'
  }
  return map[status] || status
}

onMounted(async () => {
  try {
    const [metricsRes, channelsRes] = await Promise.all([
      metricsApi.overview(),
      channelApi.list()
    ])
    metrics.value = metricsRes.data?.data || {}
    channels.value = channelsRes.data?.data || []
  } catch (e) {
    console.error('Failed to load dashboard data:', e)
  }
})
</script>

<style scoped>
.dashboard {
  max-width: 1200px;
  margin: 0 auto;
}

.page-title {
  margin-bottom: var(--spacing-lg);
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
}

.metric-card {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
  text-align: center;
}

.metric-header {
  margin-bottom: var(--spacing-sm);
}

.metric-title {
  font-size: 14px;
  color: var(--color-text-secondary);
}

.token-gauge {
  display: flex;
  justify-content: center;
  margin: var(--spacing-sm) 0;
}

.metric-value {
  font-size: 32px;
  font-weight: 500;
  color: var(--color-text-primary);
}

.metric-unit {
  font-size: 12px;
  color: var(--color-text-muted);
}

.metric-detail {
  margin-top: var(--spacing-xs);
  font-size: 13px;
  color: var(--color-text-secondary);
}

.charts-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--spacing-md);
}

.chart-card {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
}

.chart-title {
  font-size: 16px;
  margin-bottom: var(--spacing-md);
  padding-bottom: var(--spacing-xs);
  border-bottom: var(--border-thin) solid var(--color-divider);
}

.chart-content {
  min-height: 200px;
}

.distribution-item {
  margin-bottom: var(--spacing-sm);
}

.distribution-label {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  margin-bottom: var(--spacing-xxs);
}

.distribution-bar-container {
  height: 4px;
  background: var(--color-primary-subtle);
  border-radius: 2px;
  overflow: hidden;
}

.distribution-bar {
  height: 100%;
  background: var(--color-primary);
  transition: width 600ms var(--ease-out-quint);
}

.channel-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-xs) 0;
  border-bottom: var(--border-thin) solid var(--color-divider);
}

.channel-item:last-child {
  border-bottom: none;
}

.channel-name {
  font-size: 14px;
}

.channel-status {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 2px;
}

.channel-status.healthy {
  background: var(--color-primary-subtle);
  color: var(--color-success);
}

.channel-status.warning {
  background: rgba(252, 161, 125, 0.2);
  color: var(--color-warning);
}

.channel-status.error {
  background: rgba(218, 98, 125, 0.2);
  color: var(--color-error);
}

@media (max-width: 1024px) {
  .metrics-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .charts-row {
    grid-template-columns: 1fr;
  }
}
</style>