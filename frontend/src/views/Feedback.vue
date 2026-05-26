<template>
  <div class="feedback-page">
    <h2 class="page-title">反馈管理</h2>

    <div class="feedback-stats">
      <div class="stat-card">
        <span class="stat-value">{{ stats.today }}</span>
        <span class="stat-label">今日反馈</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{{ stats.pending }}</span>
        <span class="stat-label">待处理</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{{ stats.applied }}</span>
        <span class="stat-label">已采纳</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{{ stats.platinum }}</span>
        <span class="stat-label">铂金样本</span>
      </div>
    </div>

    <div class="feedback-list">
      <el-table :data="feedbacks" style="width: 100%">
        <el-table-column prop="created_at" label="时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="clue_id" label="线索ID" width="200" />
        <el-table-column prop="feedback_type" label="反馈类型" width="120">
          <template #default="{ row }">
            <el-tag :type="getFeedbackTypeTag(row.feedback_type)">
              {{ getFeedbackTypeText(row.feedback_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="correct_risk_label_level1" label="纠正分类" width="180">
          <template #default="{ row }">
            {{ row.correct_risk_label_level1 || '-' }}
            {{ row.correct_risk_label_level2 || '' }}
          </template>
        </el-table-column>
        <el-table-column prop="platinum_enrolled" label="铂金样本" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.platinum_enrolled" type="warning">是</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="model_update_status" label="模型更新" width="100">
          <template #default="{ row }">
            {{ row.model_update_status || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="comment" label="备注" min-width="150" show-overflow-tooltip />
      </el-table>

      <div class="pagination-wrapper" v-if="total > 0">
        <el-pagination
          v-model:current-page="pagination.page_no"
          :page-size="pagination.page_size"
          :total="total"
          layout="prev, pager, next, total"
          @current-change="loadFeedbacks"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { feedbackApi } from '../api'

const feedbacks = ref([])
const total = ref(0)
const pagination = reactive({
  page_no: 1,
  page_size: 20
})

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

async function loadFeedbacks() {
  // TODO: Implement feedback list API
  // For now, keep empty
}

onMounted(() => {
  loadFeedbacks()
})
</script>

<style scoped>
.feedback-page {
  max-width: 1200px;
  margin: 0 auto;
}

.page-title {
  margin-bottom: var(--spacing-lg);
}

.feedback-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
}

.stat-card {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
  text-align: center;
}

.stat-value {
  display: block;
  font-size: 24px;
  font-weight: 500;
  color: var(--color-primary);
}

.stat-label {
  font-size: 12px;
  color: var(--color-text-muted);
}

.feedback-list {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
}

.pagination-wrapper {
  display: flex;
  justify-content: center;
  margin-top: var(--spacing-md);
}
</style>