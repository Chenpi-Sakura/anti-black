<template>
  <div class="query-page">
    <div class="query-input-section">
      <h2 class="section-title">情报查询</h2>
      <div class="query-input-wrapper">
        <el-input
          v-model="queryText"
          type="textarea"
          :rows="3"
          placeholder="请输入您想查询的情报，例如：查询近三天抖音账号买卖的线索"
          @keyup.enter.ctrl="handleQuery"
        />
        <div class="query-hints">
          <span class="hint-label">支持：</span>
          <el-tag size="small" type="info" class="hint-tag">时间范围</el-tag>
          <el-tag size="small" type="info" class="hint-tag">风险类型</el-tag>
          <el-tag size="small" type="info" class="hint-tag">平台</el-tag>
        </div>
        <div class="query-actions">
          <el-button type="primary" :loading="loading" @click="handleQuery">
            查询
          </el-button>
          <el-button @click="clearQuery">清空</el-button>
        </div>
      </div>

      <div class="quick-filters" v-if="quickFilters.length > 0">
        <span class="filter-label">快捷筛选：</span>
        <el-check-tag
          v-for="filter in quickFilters"
          :key="filter.label"
          :checked="filter.active"
          @change="toggleQuickFilter(filter)"
          class="filter-tag"
        >
          {{ filter.label }}
        </el-check-tag>
      </div>
    </div>

    <div class="results-section" v-if="results.length > 0 || loading">
      <div class="results-header">
        <h2 class="section-title">查询结果</h2>
        <span class="results-count" v-if="!loading">{{ results.length }} 条线索</span>
      </div>

      <div v-if="loading" class="loading-state">
        <el-icon class="loading-spinner"><Loading /></el-icon>
        <span>正在检索...</span>
      </div>

      <div class="results-list" v-else>
        <div
          v-for="clue in results"
          :key="clue.clue_id"
          class="clue-card"
          @click="goToClueDetail(clue.clue_id)"
        >
          <div class="clue-header">
            <span class="clue-risk">
              {{ clue.risk_label_level1 }}
              <span class="risk-arrow">→</span>
              {{ clue.risk_label_level2 }}
            </span>
            <span class="clue-confidence">
              {{ ((clue.confidence || 0) * 100).toFixed(0) }}%
            </span>
          </div>
          <div class="clue-text">{{ clue.cleaned_text || clue.raw_text }}</div>
          <div class="clue-entities" v-if="clue.entity_list?.length">
            <span
              v-for="(entity, idx) in clue.entity_list.slice(0, 3)"
              :key="idx"
              class="entity-tag"
            >
              {{ entity.entity_type }}: {{ entity.entity_value }}
            </span>
          </div>
          <div class="clue-footer">
            <span class="clue-channel">{{ getChannelName(clue.source_channel) }}</span>
            <span class="clue-time">{{ formatTime(clue.published_at) }}</span>
          </div>
        </div>
      </div>

      <el-empty v-if="!loading && results.length === 0 && hasSearched" description="未找到匹配的线索" />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { clueApi } from '../api'

const router = useRouter()
const queryText = ref('')
const loading = ref(false)
const results = ref([])
const hasSearched = ref(false)

const quickFilters = reactive([
  { label: '账号交易', active: false, risk_label_level1: '账号交易' },
  { label: '流量作弊', active: false, risk_label_level1: '流量作弊' },
  { label: '诈骗引流', active: false, risk_label_level1: '诈骗引流' },
  { label: '黑产工具', active: false, risk_label_level1: '黑产工具' }
])

function toggleQuickFilter(filter) {
  filter.active = !filter.active
}

async function handleQuery() {
  if (!queryText.value.trim() && !quickFilters.some(f => f.active)) {
    ElMessage.warning('请输入查询条件')
    return
  }

  loading.value = true
  results.value = []
  hasSearched.value = false

  try {
    const params = {
      page_no: 1,
      page_size: 50
    }

    // Parse quick filters
    const activeFilters = quickFilters.filter(f => f.active)
    if (activeFilters.length === 1) {
      params.risk_label_level1 = activeFilters[0].risk_label_level1
    }

    // Simple keyword search via min_confidence filter to get all, then could filter client-side
    // For now, just get recent clues
    params.min_confidence = 0

    // Parse time range from query text if present
    const timeRange = parseTimeRange(queryText.value)
    if (timeRange.start_time) params.start_time = timeRange.start_time
    if (timeRange.end_time) params.end_time = timeRange.end_time

    const res = await clueApi.list(params)
    const data = res.data?.data

    if (data?.items?.length > 0) {
      // Client-side filter by query text if present
      if (queryText.value.trim()) {
        const keyword = queryText.value.toLowerCase()
        results.value = data.items.filter(item =>
          (item.cleaned_text || '').toLowerCase().includes(keyword) ||
          (item.raw_text || '').toLowerCase().includes(keyword) ||
          (item.risk_label_level1 || '').toLowerCase().includes(keyword) ||
          (item.risk_label_level2 || '').toLowerCase().includes(keyword)
        )
      } else {
        results.value = data.items
      }
    }

    hasSearched.value = true

    if (results.value.length === 0) {
      ElMessage.info('未找到匹配的线索')
    }
  } catch (e) {
    console.error('Query failed:', e)
    ElMessage.error('查询失败：' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

function parseTimeRange(text) {
  const result = {}
  const now = new Date()

  // Parse "近N天"
  const nearMatch = text.match(/近(\d+)天/)
  if (nearMatch) {
    const days = parseInt(nearMatch[1])
    const start = new Date(now)
    start.setDate(start.getDate() - days)
    result.start_time = start.toISOString()
    result.end_time = now.toISOString()
  }

  // Parse "近一周" / "近一个月"
  if (text.includes('近一周')) {
    const start = new Date(now)
    start.setDate(start.getDate() - 7)
    result.start_time = start.toISOString()
    result.end_time = now.toISOString()
  } else if (text.includes('近一个月')) {
    const start = new Date(now)
    start.setMonth(start.getMonth() - 1)
    result.start_time = start.toISOString()
    result.end_time = now.toISOString()
  } else if (text.includes('近三天')) {
    const start = new Date(now)
    start.setDate(start.getDate() - 3)
    result.start_time = start.toISOString()
    result.end_time = now.toISOString()
  }

  return result
}

function clearQuery() {
  queryText.value = ''
  results.value = []
  hasSearched.value = false
  quickFilters.forEach(f => f.active = false)
}

function goToClueDetail(clueId) {
  router.push(`/clues/${clueId}`)
}

function getChannelName(channel) {
  const map = {
    'douyin': '抖音',
    'baidu_tieba': '贴吧',
    'telegram': 'Telegram',
    'forum': '论坛'
  }
  return map[channel] || channel
}

function formatTime(timeStr) {
  if (!timeStr) return '-'
  const date = new Date(timeStr)
  return date.toLocaleString('zh-CN')
}
</script>

<style scoped>
.query-page {
  max-width: 1000px;
  margin: 0 auto;
}

.section-title {
  margin-bottom: var(--spacing-md);
}

.query-input-section {
  margin-bottom: var(--spacing-lg);
}

.query-input-wrapper {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
}

.query-hints {
  margin-top: var(--spacing-xs);
  font-size: 12px;
  color: var(--color-text-muted);
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.hint-tag {
  margin-right: var(--spacing-xxs);
}

.query-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-sm);
  margin-top: var(--spacing-sm);
}

.quick-filters {
  margin-top: var(--spacing-sm);
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  flex-wrap: wrap;
}

.filter-label {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.filter-tag {
  cursor: pointer;
}

.results-section {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-md);
}

.results-count {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-xl);
  color: var(--color-text-secondary);
}

.loading-spinner {
  font-size: 20px;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.results-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.clue-card {
  padding: var(--spacing-sm);
  border: var(--border-thin) solid var(--color-border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease-out-quint);
}

.clue-card:hover {
  border-color: var(--color-primary);
  transform: translateY(-2px);
}

.clue-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: var(--spacing-xs);
}

.clue-risk {
  font-weight: 500;
  color: var(--color-primary);
}

.risk-arrow {
  color: var(--color-text-muted);
  margin: 0 var(--spacing-xxs);
}

.clue-confidence {
  font-size: 12px;
  color: var(--color-text-secondary);
  padding: 2px 8px;
  background: var(--color-primary-subtle);
  border-radius: 2px;
}

.clue-text {
  font-size: 14px;
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clue-entities {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-xs);
}

.entity-tag {
  font-size: 12px;
  padding: 2px 8px;
  background: var(--color-primary-subtle);
  border-radius: 2px;
  color: var(--color-text-secondary);
}

.clue-footer {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>
