<template>
  <div class="clue-detail">
    <div class="detail-header">
      <el-button :icon="ArrowLeft" @click="goBack">返回</el-button>
    </div>

    <div v-if="clue" class="detail-content">
      <div class="detail-main">
        <div class="info-card">
          <div class="card-header">
            <span class="risk-label">{{ clue.risk_label_level1 }} > {{ clue.risk_label_level2 }}</span>
            <span class="confidence">置信度 {{ (clue.confidence * 100).toFixed(1) }}%</span>
          </div>

          <div class="text-section">
            <h4>原始文本</h4>
            <p class="raw-text">{{ clue.raw_text }}</p>
          </div>

          <div class="text-section" v-if="clue.cleaned_text">
            <h4>清洗后文本</h4>
            <p class="cleaned-text">{{ clue.cleaned_text }}</p>
          </div>

          <div class="meta-info">
            <span>来源: {{ getChannelName(clue.source_channel) }}</span>
            <span>时间: {{ formatTime(clue.published_at) }}</span>
            <span>分类来源: {{ clue.classification_source }}</span>
          </div>
        </div>

        <div class="entities-card" v-if="clue.entity_list?.length">
          <h3>抽取实体</h3>
          <div class="entities-list">
            <div
              v-for="(entity, idx) in clue.entity_list"
              :key="idx"
              class="entity-item"
              @click="goToEntity(entity)"
            >
              <span class="entity-type">{{ entity.entity_type }}</span>
              <span class="entity-value">{{ entity.entity_value }}</span>
              <span class="entity-source">{{ entity.source }}</span>
            </div>
          </div>
        </div>

        <div class="slang-card" v-if="clue.slang_mappings?.length">
          <h3>黑话映射</h3>
          <div class="slang-list">
            <div v-for="(mapping, idx) in clue.slang_mappings" :key="idx" class="slang-item">
              <span class="slang-raw">{{ mapping.slang }}</span>
              <span class="slang-arrow">→</span>
              <span class="slang-meaning">{{ mapping.meaning }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="detail-sidebar">
        <div class="feedback-card">
          <h3>反馈</h3>
          <div class="feedback-buttons">
            <el-button type="primary" @click="submitFeedback('helpful')">
              <el-icon><CircleCheck /></el-icon>
              有帮助
            </el-button>
            <el-button @click="showFeedbackDialog('wrong_class')">
              <el-icon><Warning /></el-icon>
              分类有误
            </el-button>
            <el-button @click="showFeedbackDialog('wrong_entity')">
              <el-icon><Location /></el-icon>
              实体错误
            </el-button>
            <el-button @click="submitFeedback('normal')">
              <el-icon><CircleCheck /></el-icon>
              正常消息
            </el-button>
          </div>
        </div>

        <div class="reason-card" v-if="clue.classification_reason">
          <h3>分类依据</h3>
          <p>{{ clue.classification_reason }}</p>
        </div>
      </div>
    </div>

    <el-empty v-else description="线索不存在" />

    <el-dialog v-model="feedbackDialogVisible" title="提交反馈" width="500px">
      <el-form :model="feedbackForm" label-width="100px">
        <el-form-item label="纠正类型">
          <el-select v-model="feedbackForm.feedback_type">
            <el-option label="分类纠正" value="wrong_class" />
            <el-option label="实体纠正" value="wrong_entity" />
            <el-option label="正常消息" value="normal" />
          </el-select>
        </el-form-item>
        <el-form-item label="正确分类" v-if="feedbackForm.feedback_type === 'wrong_class'">
          <el-cascader
            v-model="feedbackForm.correct_labels"
            :options="taxonomyOptions"
            placeholder="选择正确分类"
          />
        </el-form-item>
        <el-form-item label="补充说明">
          <el-input v-model="feedbackForm.comment" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="feedbackDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitFeedbackForm">确认提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clueApi, feedbackApi, taxonomyApi, entityApi } from '../api'
import { ArrowLeft, CircleCheck, Warning, Location } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()
const clue = ref(null)
const taxonomyOptions = ref([])
const feedbackDialogVisible = ref(false)

const feedbackForm = reactive({
  feedback_type: 'wrong_class',
  correct_labels: [],
  comment: ''
})

function goBack() {
  router.back()
}

function getChannelName(channel) {
  const map = { 'douyin': '抖音', 'baidu_tieba': '贴吧', 'telegram': 'Telegram' }
  return map[channel] || channel
}

function formatTime(timeStr) {
  if (!timeStr) return '-'
  return new Date(timeStr).toLocaleString('zh-CN')
}

function goToEntity(entity) {
  if (entity.entity_id) {
    router.push(`/entities/${entity.entity_id}`)
  }
}

function showFeedbackDialog(type) {
  feedbackForm.feedback_type = type
  feedbackDialogVisible.value = true
}

async function submitFeedback(type) {
  try {
    await feedbackApi.submit({
      clue_id: clue.value.clue_id,
      feedback_type: type
    })
    ElMessage.success('反馈提交成功')
  } catch (e) {
    ElMessage.error('反馈提交失败')
  }
}

async function submitFeedbackForm() {
  try {
    await feedbackApi.submit({
      clue_id: clue.value.clue_id,
      feedback_type: feedbackForm.feedback_type,
      correct_risk_label_level1: feedbackForm.correct_labels[0],
      correct_risk_label_level2: feedbackForm.correct_labels[1],
      comment: feedbackForm.comment
    })
    feedbackDialogVisible.value = false
    ElMessage.success('反馈提交成功')
  } catch (e) {
    ElMessage.error('反馈提交失败')
  }
}

onMounted(async () => {
  try {
    const [clueRes, taxRes] = await Promise.all([
      clueApi.detail(route.params.id),
      taxonomyApi.get()
    ])

    clue.value = clueRes.data?.data

    if (taxRes.data?.data?.categories) {
      taxonomyOptions.value = taxRes.data.data.categories.map(cat => ({
        value: cat.level1_name,
        label: cat.level1_name,
        children: cat.level2_items?.map(item => ({
          value: item.level2_name,
          label: item.level2_name
        })) || []
      }))
    }
  } catch (e) {
    console.error('Failed to load clue detail:', e)
  }
})
</script>

<style scoped>
.clue-detail {
  max-width: 1200px;
  margin: 0 auto;
}

.detail-header {
  margin-bottom: var(--spacing-md);
}

.detail-content {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: var(--spacing-lg);
}

.info-card {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-md);
  padding-bottom: var(--spacing-sm);
  border-bottom: var(--border-thin) solid var(--color-divider);
}

.risk-label {
  font-size: 18px;
  font-weight: 500;
  color: var(--color-primary);
}

.confidence {
  font-size: 14px;
  padding: 4px 12px;
  background: var(--color-primary-subtle);
  border-radius: 4px;
}

.text-section {
  margin-bottom: var(--spacing-md);
}

.text-section h4 {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin-bottom: var(--spacing-xs);
}

.raw-text, .cleaned-text {
  font-size: 14px;
  line-height: 1.8;
  padding: var(--spacing-sm);
  background: var(--color-background);
  border-radius: var(--radius-sm);
}

.meta-info {
  display: flex;
  gap: var(--spacing-md);
  font-size: 13px;
  color: var(--color-text-muted);
}

.entities-card, .slang-card {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
  margin-top: var(--spacing-md);
}

.entities-card h3, .slang-card h3 {
  margin-bottom: var(--spacing-sm);
}

.entities-list, .slang-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.entity-item, .slang-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-xs);
  background: var(--color-background);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.entity-item:hover {
  background: var(--color-primary-subtle);
}

.entity-type {
  font-size: 12px;
  padding: 2px 6px;
  background: var(--color-primary);
  color: white;
  border-radius: 2px;
}

.entity-value {
  flex: 1;
  font-size: 14px;
}

.entity-source {
  font-size: 11px;
  color: var(--color-text-muted);
}

.slang-raw {
  font-size: 14px;
  color: var(--color-primary);
}

.slang-arrow {
  color: var(--color-text-muted);
}

.slang-meaning {
  font-size: 14px;
}

.detail-sidebar {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.feedback-card, .reason-card {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
}

.feedback-card h3, .reason-card h3 {
  margin-bottom: var(--spacing-sm);
}

.feedback-buttons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--spacing-xs);
}
</style>