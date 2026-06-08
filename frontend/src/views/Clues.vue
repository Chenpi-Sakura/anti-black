<template>
  <div class="clues-page">
    <h2 class="page-title">线索列表</h2>

    <div class="filters-card">
      <el-form :inline="true" :model="filters">
        <el-form-item label="风险类型">
          <el-select v-model="risk_label_level1" placeholder="全部" clearable>
            <el-option
              v-for="item in riskTypeOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="来源渠道">
          <el-select v-model="source_channel" placeholder="全部" clearable>
            <el-option
              v-for="item in channelOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="loadClues">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div class="clues-list">
      <div
        v-for="clue in clues"
        :key="clue.clue_id"
        class="clue-card"
        @click="goToDetail(clue.clue_id)"
      >
        <div class="clue-header">
          <span class="clue-risk">
            {{ clue.risk_label_level1 }} > {{ clue.risk_label_level2 }}
          </span>
          <span class="clue-confidence">
            {{ (clue.confidence * 100).toFixed(0) }}%
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
          <div class="clue-actions" @click.stop>
            <el-button size="small" :icon="CircleCheck" circle title="有帮助" />
            <el-button size="small" :icon="Warning" circle title="分类有误" @click="showFeedback(clue, 'wrong_class')" />
            <el-button size="small" :icon="Location" circle title="实体错误" @click="showFeedback(clue, 'wrong_entity')" />
          </div>
        </div>
      </div>

      <el-empty v-if="clues.length === 0 && !loading" description="暂无线索数据" />
    </div>

    <div class="pagination-wrapper" v-if="total > 0">
      <el-pagination
        v-model:current-page="pagination.page_no"
        :page-size="pagination.page_size"
        :total="total"
        :pager-count="7"
        layout="prev, pager, next, jumper, total"
        background
        @current-change="loadClues"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { clueApi, taxonomyApi, channelApi } from '../api'
import { useAppStore } from '../stores/app'
import { CircleCheck, Warning, Location } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const router = useRouter()
const store = useAppStore()

// All list state lives in Pinia so ClueDetail -> back preserves page + filters
const clues = computed(() => store.clues)
const total = computed(() => store.cluesPagination.total)
const pagination = store.cluesPagination  // mutate directly; reactive ref

// Filter bindings — el-select v-model needs reactive get/set. Reading
// store.cluesFilters.X directly returns a plain primitive (untracked), so
// selecting a value re-renders the input AND writes back to the store only
// if the read goes through a computed. Use computed refs and bind them
// directly in template.
const risk_label_level1 = computed({
  get: () => store.cluesFilters.risk_label_level1,
  set: (v) => { store.cluesFilters.risk_label_level1 = v }
})
const source_channel = computed({
  get: () => store.cluesFilters.source_channel,
  set: (v) => { store.cluesFilters.source_channel = v }
})
const dateRange = computed({
  get: () => store.cluesFilters.dateRange,
  set: (v) => { store.cluesFilters.dateRange = v }
})
// el-form :model just needs a non-null object; it doesn't have to track fields.
const filters = { risk_label_level1, source_channel, dateRange }

const loading = ref(false)

// Dynamic dropdown options
const riskTypeOptions = ref([])
const channelOptions = ref([])

// Channel display name map (shared between dropdown and card footer)
const CHANNEL_NAME_MAP = {
  'douyin': '抖音',
  'baidu_tieba': '贴吧',
  'weibo': '微博',
  'xiaohongshu': '小红书',
  'kuaishou': '快手',
  'telegram': 'Telegram'
  // 'e2e' deliberately omitted: test data should not surface in UI
}

function getChannelName(channel) {
  return CHANNEL_NAME_MAP[channel] || channel || '-'
}

function formatTime(timeStr) {
  if (!timeStr) return '-'
  const date = new Date(timeStr)
  return date.toLocaleDateString('zh-CN')
}

async function loadClues() {
  loading.value = true
  try {
    const params = {
      page_no: pagination.page_no,
      page_size: pagination.page_size,
      // script-context access: these are computed refs, so read .value
      risk_label_level1: risk_label_level1.value || undefined,
      source_channel: source_channel.value || undefined
    }

    if (dateRange.value?.length === 2) {
      params.start_time = dateRange.value[0].toISOString()
      params.end_time = dateRange.value[1].toISOString()
    }

    const res = await clueApi.list(params)
    const data = res.data?.data

    if (data) {
      // Persist to store so back navigation restores the same list
      store.setClues(data.items || [], {
        page_no: data.page_no ?? pagination.page_no,
        page_size: data.page_size ?? pagination.page_size,
        total: data.total || 0
      })
    }

    if (clues.value.length === 0 && pagination.page_no > 1) {
      ElMessage.info('已翻到最后一页')
    }
  } catch (e) {
    console.error('Failed to load clues:', e)
    ElMessage.error('加载线索失败: ' + (e.response?.data?.message || e.message))
  } finally {
    loading.value = false
  }
}

async function loadDropdownOptions() {
  // Load risk types from taxonomy API
  try {
    const taxRes = await taxonomyApi.get()
    const categories = taxRes.data?.data?.categories || []
    riskTypeOptions.value = categories
      .filter(c => c.level1_name && c.level1_name !== '无关')
      .map(c => ({ label: c.level1_name, value: c.level1_name }))
  } catch (e) {
    console.error('Failed to load taxonomy:', e)
    // Fallback: hardcoded options
    riskTypeOptions.value = [
      { label: '账号交易', value: '账号交易' },
      { label: '诈骗引流', value: '诈骗引流' },
      { label: '流量作弊', value: '流量作弊' },
      { label: '黑产工具', value: '黑产工具' },
      { label: '未知/其他', value: '未知/其他' }
    ]
  }

  // Load channel options from channels API
  try {
    const chRes = await channelApi.list()
    const channels = chRes.data?.data || []
    channelOptions.value = channels
      .filter(c => c.platform && CHANNEL_NAME_MAP[c.platform])
      .map(c => ({ label: CHANNEL_NAME_MAP[c.platform], value: c.platform }))
  } catch (e) {
    console.error('Failed to load channels:', e)
    // Fallback: hardcoded options
    channelOptions.value = [
      { label: '抖音', value: 'douyin' },
      { label: '贴吧', value: 'baidu_tieba' },
      { label: '微博', value: 'weibo' },
      { label: '小红书', value: 'xiaohongshu' },
      { label: '快手', value: 'kuaishou' },
      { label: 'Telegram', value: 'telegram' }
    ]
  }
}

function resetFilters() {
  store.resetCluesFilters()
  loadClues()
}

function goToDetail(clueId) {
  router.push(`/clues/${clueId}`)
}

function showFeedback(clue, type) {
  // TODO: Implement feedback dialog
  console.log('Feedback:', clue.clue_id, type)
}

onMounted(async () => {
  await loadDropdownOptions()
  // Always reload to keep data fresh (page_no + filters preserved via Pinia)
  await loadClues()
})
</script>

<style scoped>
.clues-page {
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.page-title {
  margin-bottom: var(--spacing-lg);
  flex-shrink: 0;
}

.filters-card {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
  margin-bottom: var(--spacing-md);
  flex-shrink: 0;
}

.clues-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.clue-card {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
  cursor: pointer;
  transition: all var(--duration-standard) var(--ease-out-quint);
}

.clue-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-hover);
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

.clue-confidence {
  font-size: 12px;
  padding: 2px 8px;
  background: var(--color-primary-subtle);
  border-radius: 2px;
}

.clue-text {
  font-size: 14px;
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clue-entities {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-sm);
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
  align-items: center;
  gap: var(--spacing-md);
  font-size: 12px;
  color: var(--color-text-muted);
}

.clue-channel {
  color: var(--color-text-secondary);
}

.clue-actions {
  margin-left: auto;
  display: flex;
  gap: var(--spacing-xs);
}

.pagination-wrapper {
  display: flex;
  justify-content: center;
  margin-top: var(--spacing-md);
  flex-shrink: 0;
  padding: var(--spacing-xs) 0;
  background: var(--color-surface);
  border-top: var(--border-thin) solid var(--color-divider);
}
</style>