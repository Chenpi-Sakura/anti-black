<template>
  <div class="dashboard">
    <PageHeader
      title="监控概览"
      subtitle="实时系统状态、Token 消耗、分类与渠道分布"
    />

    <div class="metrics-grid">
      <BaseMetricCard
        title="Token 消耗"
        :value="metrics.token_usage_today"
        unit=" / 1,000,000"
        :hint="`${tokenPercentage}% 已使用`"
      >
        <template #extra>
          <el-progress
            type="circle"
            :percentage="tokenPercentage"
            :color="tokenColor"
            :width="60"
          />
        </template>
      </BaseMetricCard>

      <BaseMetricCard
        title="今日处理"
        :value="metrics.messages_processed_today"
        unit="条消息"
        hint="最近 24h"
      />

      <BaseMetricCard
        title="实体总数"
        :value="metrics.total_entities"
        unit="个实体"
        :hint="`关联关系 ${metrics.total_relations || 0} 条`"
      />

      <BaseMetricCard
        title="采集成功率"
        :value="successRateText"
        :hint="`后台巡逻: ${patrolStatus}`"
      />
    </div>

    <div class="charts-row">
      <BaseCard title="分类分布">
        <div v-if="classificationDistribution.length > 0" class="distribution-list">
          <div
            v-for="(item, index) in classificationDistribution"
            :key="index"
            class="distribution-item"
          >
            <div class="distribution-label">
              <span>{{ item.risk_label_level1 || item.label }}</span>
              <span class="distribution-count">{{ item.count || item.value || 0 }} 条</span>
            </div>
            <div class="distribution-bar-container">
              <div
                class="distribution-bar"
                :style="{ width: getBarWidth(item) + '%' }"
              ></div>
            </div>
          </div>
        </div>
        <EmptyState v-else description="暂无分类数据" />
      </BaseCard>

      <BaseCard title="渠道状态">
        <div v-if="channels.length > 0" class="channel-list">
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
        <EmptyState v-else description="暂无渠道数据" />
      </BaseCard>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { metricsApi, channelApi } from '../api'
import PageHeader from '../components/PageHeader.vue'
import BaseMetricCard from '../components/BaseMetricCard.vue'
import BaseCard from '../components/BaseCard.vue'
import EmptyState from '../components/EmptyState.vue'

const metrics = ref({})
const channels = ref([])
const dailyLimit = 1000000

const tokenPercentage = computed(() => {
  const used = metrics.value.token_usage_today || 0
  return Math.min(100, Math.round((used / dailyLimit) * 100))
})

const tokenColor = computed(() => {
  const pct = tokenPercentage.value
  if (pct < 30) return 'var(--color-success)'
  if (pct < 70) return 'var(--color-warning)'
  return 'var(--color-error)'
})

const successRateText = computed(() => {
  return `${((metrics.value.collection_success_rate || 1) * 100).toFixed(1)}%`
})

const patrolStatus = computed(() => {
  const status = metrics.value.background_patrol_status
  const statusMap = {
    'IDLE': '空闲',
    'RUNNING': '运行中',
    'DEGRADED': '降级',
    'STOPPED': '停止'
  }
  return statusMap[status] || status || '未知'
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

async function loadDashboard() {
  try {
    const [metricsRes, channelsRes] = await Promise.all([
      metricsApi.overview(),
      channelApi.list()
    ])
    metrics.value = metricsRes.data?.data || {}
    channels.value = channelsRes.data?.data || []
  } catch (e) {
    console.error('Failed to load dashboard data:', e)
    metrics.value = {}
    channels.value = []
  }
}

onMounted(() => {
  loadDashboard()
})
</script>

<style scoped>
.dashboard {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
}

.charts-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--spacing-md);
}

.distribution-list,
.channel-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.distribution-item {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xxs);
}

.distribution-label {
  display: flex;
  justify-content: space-between;
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}

.distribution-count {
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
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
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}

.channel-status {
  font-size: var(--font-size-xs);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
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

.channel-status.unconfigured {
  background: var(--color-divider);
  color: var(--color-text-muted);
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
