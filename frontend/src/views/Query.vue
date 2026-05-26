<template>
  <div class="query-page">
    <div class="query-layout">
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
          <div class="query-actions">
            <el-button type="primary" :loading="loading" @click="handleQuery">
              查询
            </el-button>
            <el-button @click="clearQuery">清空</el-button>
          </div>
        </div>
      </div>

      <div class="ai-processing-section">
        <h2 class="section-title">AI 处理过程</h2>
        <div class="processing-stages">
          <div
            v-for="(stage, index) in stages"
            :key="index"
            :class="['stage-card', stage.status]"
          >
            <div class="stage-indicator">
              <span class="stage-line"></span>
              <span :class="['stage-dot', stage.status]">
                <span v-if="stage.status === 'completed'" class="stage-check">✓</span>
                <span v-else-if="stage.status === 'running'" class="stage-spin">⟳</span>
                <span v-else class="stage-waiting">⏳</span>
              </span>
            </div>
            <div class="stage-content">
              <div class="stage-header">
                <span class="stage-title">{{ stage.name }}</span>
                <span class="stage-time" v-if="stage.duration">{{ stage.duration }}s</span>
              </div>
              <div class="stage-description">{{ stage.description }}</div>
              <div class="stage-progress" v-if="stage.status === 'running'">
                <el-progress :percentage="stage.progress" :show-text="false" :stroke-width="2" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="results-section" v-if="results.length > 0">
      <h2 class="section-title">查询结果</h2>
      <div class="results-list">
        <div
          v-for="clue in results"
          :key="clue.clue_id"
          class="clue-card"
          @click="goToClueDetail(clue.clue_id)"
        >
          <div class="clue-header">
            <span class="clue-risk">{{ clue.risk_label_level1 }} > {{ clue.risk_label_level2 }}</span>
            <span class="clue-confidence">置信度 {{ clue.confidence?.toFixed(2) }}</span>
          </div>
          <div class="clue-text">{{ clue.cleaned_text || clue.raw_text }}</div>
          <div class="clue-footer">
            <span class="clue-channel">{{ clue.source_channel }}</span>
            <span class="clue-time" v-if="clue.published_at">{{ formatTime(clue.published_at) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { queryApi, clueApi } from '../api'

const router = useRouter()
const queryText = ref('')
const loading = ref(false)
const results = ref([])
const queryId = ref(null)

const stages = ref([
  { name: '数据采集', description: '从多个渠道采集情报数据', status: 'pending', progress: 0 },
  { name: '数据清洗', description: '清洗去重、标准化处理', status: 'pending', progress: 0 },
  { name: '意图分类', description: '风险分类与标签标注', status: 'pending', progress: 0 },
  { name: '实体抽取', description: '抽取关键实体信息', status: 'pending', progress: 0 },
  { name: '关联分析', description: '图谱构建与关系发现', status: 'pending', progress: 0 }
])

async function handleQuery() {
  if (!queryText.value.trim()) return

  loading.value = true
  results.value = []
  resetStages()

  try {
    // Create query task
    const createRes = await queryApi.create(queryText.value)
    queryId.value = createRes.data?.data?.query_id

    // Simulate stages progress
    await runStages()

    // Poll for results
    await pollResults()
  } catch (e) {
    console.error('Query failed:', e)
  } finally {
    loading.value = false
  }
}

function resetStages() {
  stages.value.forEach(s => {
    s.status = 'pending'
    s.progress = 0
    s.duration = null
  })
}

async function runStages() {
  const stageDelays = [2000, 1500, 1000, 800, 500]

  for (let i = 0; i < stages.value.length; i++) {
    stages.value[i].status = 'running'

    // Simulate progress
    const progressPromise = simulateProgress(i)

    await new Promise(resolve => setTimeout(resolve, stageDelays[i]))

    stages.value[i].status = 'completed'
    stages.value[i].progress = 100
    stages.value[i].duration = (stageDelays[i] / 1000).toFixed(1)

    await progressPromise
  }
}

async function simulateProgress(stageIndex) {
  for (let p = 0; p <= 100; p += 10) {
    stages.value[stageIndex].progress = p
    await new Promise(r => setTimeout(r, stageDelays[stageIndex] / 10))
  }
}

async function pollResults() {
  let attempts = 0
  while (attempts < 10) {
    try {
      const res = await clueApi.list({ query_id: queryId.value })
      const data = res.data?.data
      if (data?.items?.length > 0) {
        results.value = data.items
        break
      }
    } catch (e) {
      console.error('Poll results failed:', e)
    }
    await new Promise(r => setTimeout(r, 1000))
    attempts++
  }
}

function clearQuery() {
  queryText.value = ''
  results.value = []
  queryId.value = null
  resetStages()
}

function goToClueDetail(clueId) {
  router.push(`/clues/${clueId}`)
}

function formatTime(timeStr) {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  return date.toLocaleString('zh-CN')
}
</script>

<style scoped>
.query-page {
  max-width: 1200px;
  margin: 0 auto;
}

.query-layout {
  display: grid;
  grid-template-columns: 35% 65%;
  gap: var(--spacing-lg);
  margin-bottom: var(--spacing-lg);
}

.section-title {
  margin-bottom: var(--spacing-md);
}

.query-input-wrapper {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
}

.query-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-sm);
  margin-top: var(--spacing-sm);
}

.processing-stages {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
}

.stage-card {
  display: flex;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) 0;
  border-bottom: var(--border-thin) solid var(--color-divider);
}

.stage-card:last-child {
  border-bottom: none;
}

.stage-indicator {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 24px;
}

.stage-line {
  width: 2px;
  flex: 1;
  background: var(--color-border);
}

.stage-dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  background: var(--color-border);
  color: var(--color-text-muted);
}

.stage-dot.completed {
  background: var(--color-primary);
  color: white;
}

.stage-dot.running {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.stage-content {
  flex: 1;
}

.stage-header {
  display: flex;
  justify-content: space-between;
}

.stage-title {
  font-weight: 500;
}

.stage-time {
  font-size: 12px;
  color: var(--color-text-muted);
}

.stage-description {
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-top: var(--spacing-xxs);
}

.stage-progress {
  margin-top: var(--spacing-xs);
}

.stage-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.results-section {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
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

.clue-confidence {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.clue-text {
  font-size: 14px;
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clue-footer {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>