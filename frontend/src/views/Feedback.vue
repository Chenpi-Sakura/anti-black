<template>
  <div class="feedback-page">
    <PageHeader
      title="反馈管理"
      subtitle="用户对线索的反馈记录与铂金样本追踪"
    />

    <div class="feedback-stats">
      <BaseMetricCard title="今日反馈" :value="stats.today" hint="最近 24h" />
      <BaseMetricCard title="待处理" :value="stats.pending" hint="未被模型采纳" />
      <BaseMetricCard title="已采纳" :value="stats.applied" hint="已参与模型训练" />
      <BaseMetricCard title="铂金样本" :value="stats.platinum" hint="高权重样本" />
    </div>

    <BaseCard title="反馈列表" no-padding>
      <div class="feedback-table-wrapper">
        <el-table
          v-loading="loading"
          :data="feedbacks"
          style="width: 100%"
          empty-text="暂无反馈数据"
        >
          <el-table-column prop="created_at" label="时间" width="180">
            <template #default="{ row }">
              {{ formatTime(row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column prop="clue_id" label="线索ID" width="200" show-overflow-tooltip />
          <el-table-column prop="feedback_type" label="反馈类型" width="120">
            <template #default="{ row }">
              <el-tag :type="getFeedbackTypeTag(row.feedback_type)">
                {{ getFeedbackTypeText(row.feedback_type) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="纠正分类" min-width="180">
            <template #default="{ row }">
              <span v-if="row.correct_risk_label_level1 || row.correct_risk_label_level2">
                {{ row.correct_risk_label_level1 || '-' }}
                <span v-if="row.correct_risk_label_level2"> / {{ row.correct_risk_label_level2 }}</span>
              </span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="platinum_enrolled" label="铂金样本" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.platinum_enrolled" type="warning">是</el-tag>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="model_update_status" label="模型更新" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.model_update_status && row.model_update_status !== 'IDLE'" size="small">
                {{ row.model_update_status }}
              </el-tag>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="comment" label="备注" min-width="150" show-overflow-tooltip />
        </el-table>

        <div v-if="total > 0" class="pagination-wrapper">
          <el-pagination
            v-model:current-page="pagination.page_no"
            :page-size="pagination.page_size"
            :total="total"
            layout="prev, pager, next, total"
            @current-change="loadFeedbacks"
          />
        </div>
      </div>
    </BaseCard>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { feedbackApi } from '../api'
import PageHeader from '../components/PageHeader.vue'
import BaseMetricCard from '../components/BaseMetricCard.vue'
import BaseCard from '../components/BaseCard.vue'

const feedbacks = ref([])
const total = ref(0)
const loading = ref(false)
const pagination = reactive({
  page_no: 1,
  page_size: 20
})

// Client-side stats aggregation from the current page's items
const stats = reactive({
  today: 0,
  pending: 0,
  applied: 0,
  platinum: 0
})

function formatTime(timeStr) {
  if (!timeStr) return '-'
  return new Date(timeStr).toLocaleString('zh-CN')
}

function getFeedbackTypeText(type) {
  const map = {
    'helpful': '有帮助',
    'wrong_class': '分类有误',
    'wrong_entity': '实体错误',
    'normal': '正常消息',
    'correction': '纠错'
  }
  return map[type] || type
}

function getFeedbackTypeTag(type) {
  const map = {
    'helpful': 'success',
    'wrong_class': 'warning',
    'wrong_entity': 'danger',
    'normal': 'info',
    'correction': ''
  }
  return map[type] || ''
}

function computeStats(items) {
  const now = Date.now()
  const oneDayMs = 24 * 60 * 60 * 1000
  stats.today = items.filter(i => {
    if (!i.created_at) return false
    return (now - new Date(i.created_at).getTime()) <= oneDayMs
  }).length
  stats.pending = items.filter(i =>
    i.model_update_status === 'IDLE' || !i.model_update_status
  ).length
  stats.applied = items.filter(i =>
    i.model_update_status && i.model_update_status !== 'IDLE'
  ).length
  stats.platinum = items.filter(i => i.platinum_enrolled).length
}

async function loadFeedbacks() {
  loading.value = true
  try {
    const res = await feedbackApi.list({
      page_no: pagination.page_no,
      page_size: pagination.page_size,
      sort_by: 'created_at',
      sort_order: -1
    })
    const data = res.data?.data
    if (data) {
      feedbacks.value = data.items || []
      total.value = data.total || 0
      computeStats(feedbacks.value)
    }
  } catch (e) {
    console.error('Failed to load feedbacks:', e)
    feedbacks.value = []
    total.value = 0
    computeStats([])
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadFeedbacks()
})
</script>

<style scoped>
.feedback-page {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.feedback-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
}

.feedback-table-wrapper {
  padding: var(--spacing-md);
}

.pagination-wrapper {
  display: flex;
  justify-content: center;
  margin-top: var(--spacing-md);
}

.muted {
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}

@media (max-width: 1024px) {
  .feedback-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
