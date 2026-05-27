<template>
  <div class="query-page">
    <div class="query-header">
      <h2 class="section-title">情报分析助手</h2>
      <span class="subtitle">基于自然语言理解的黑灰产情报检索系统</span>
    </div>

    <!-- 对话区域 -->
    <div class="chat-container" ref="chatContainer">
      <div v-if="messages.length === 0" class="welcome-message">
        <p>您好，我是情报分析助手。请描述您想查询的情报，例如：</p>
        <ul>
          <li>查询近三天抖音账号买卖的线索</li>
          <li>搜索涉及微信号的诈骗引流情报</li>
          <li>查看最近一周贴吧的流量作弊信息</li>
        </ul>
      </div>

      <!-- 消息列表 -->
      <div class="messages-list">
        <div
          v-for="(msg, index) in messages"
          :key="index"
          :class="['message', msg.role]"
        >
          <div class="message-avatar">
            <span v-if="msg.role === 'user'">👤</span>
            <span v-else>🤖</span>
          </div>
          <div class="message-content">
            <div class="message-text" v-html="formatMessage(msg.content)"></div>
            <div class="message-time">{{ formatTime(msg.timestamp) }}</div>
          </div>
        </div>

        <!-- 正在输入指示器 -->
        <div v-if="isTyping" class="message assistant typing">
          <div class="message-avatar">🤖</div>
          <div class="message-content">
            <div class="typing-indicator">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        </div>

        <!-- 进度显示 -->
        <div v-if="currentProgress" class="progress-indicator">
          <div class="progress-text">{{ currentProgress }}</div>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
          </div>
        </div>
      </div>

      <!-- 线索卡片列表 -->
      <div v-if="clueResults.length > 0" class="clue-results-section">
        <div class="results-header">
          <h3>检索结果 ({{ clueResults.length }} 条线索)</h3>
          <el-button size="small" text @click="clueResults = []">收起</el-button>
        </div>
        <div class="results-list">
          <div
            v-for="clue in clueResults"
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
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="input-section">
      <div class="input-wrapper">
        <el-input
          v-model="queryText"
          type="textarea"
          :rows="2"
          placeholder="请输入您想查询的情报..."
          :disabled="isProcessing"
          @keyup.enter.ctrl="handleQuery"
          @keyup.enter="handleQuery"
        />
        <div class="input-actions">
          <span class="hint-text">Ctrl+Enter 发送</span>
          <el-button
            type="primary"
            :loading="isProcessing"
            :disabled="!queryText.trim()"
            @click="handleQuery"
          >
            {{ isProcessing ? '处理中...' : '发送' }}
          </el-button>
        </div>
      </div>

      <!-- 快捷筛选 -->
      <div class="quick-filters">
        <span class="filter-label">快捷筛选：</span>
        <el-check-tag
          v-for="filter in quickFilters"
          :key="filter.label"
          :checked="filter.active"
          @change="toggleFilter(filter)"
          :disabled="isProcessing"
        >
          {{ filter.label }}
        </el-check-tag>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { queryApi } from '../api'
import { marked } from 'marked'

// 配置 marked 选项
marked.setOptions({
  breaks: true,  // 允许换行
  gfm: true     // 允许 GitHub 风格 Markdown
})

const router = useRouter()

// 对话状态
const messages = ref([])
const queryText = ref('')
const isProcessing = ref(false)
const isTyping = ref(false)
const currentProgress = ref('')
const progressPercent = ref(0)
const clueResults = ref([])
const chatContainer = ref(null)

// 快捷筛选
const quickFilters = reactive([
  { label: '账号交易', active: false, risk_label_level1: '账号交易' },
  { label: '流量作弊', active: false, risk_label_level1: '流量作弊' },
  { label: '诈骗引流', active: false, risk_label_level1: '诈骗引流' },
  { label: '黑产工具', active: false, risk_label_level1: '黑产工具' }
])

function toggleFilter(filter) {
  filter.active = !filter.active
}

async function handleQuery() {
  if (!queryText.value.trim() || isProcessing.value) return

  const text = queryText.value.trim()
  queryText.value = ''

  // 添加用户消息
  messages.value.push({
    role: 'user',
    content: text,
    timestamp: new Date()
  })

  await scrollToBottom()

  // 开始处理
  isProcessing.value = true
  isTyping.value = true
  currentProgress.value = '正在提交查询...'
  progressPercent.value = 0

  try {
    // 创建查询任务
    const options = {}
    const activeFilters = quickFilters.filter(f => f.active)
    if (activeFilters.length === 1) {
      options.risk_types = [activeFilters[0].risk_label_level1]
    }

    const res = await queryApi.create(text, options)
    const queryId = res.data?.data?.query_id

    if (!queryId) {
      throw new Error('无法创建查询任务')
    }

    // 连接SSE获取实时进度
    const eventSource = queryApi.stream(queryId)

    eventSource.onopen = () => {
      currentProgress.value = '已连接，正在分析...'
    }

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        handleSSEEvent(data)
      } catch (e) {
        console.error('SSE parse error:', e)
      }
    }

    eventSource.onerror = (error) => {
      console.error('SSE error:', error)
      isTyping.value = false
      isProcessing.value = false
      currentProgress.value = ''
    }

  } catch (e) {
    console.error('Query failed:', e)
    ElMessage.error('查询失败：' + (e.message || '未知错误'))
    isTyping.value = false
    isProcessing.value = false
    currentProgress.value = ''
  }
}

function handleSSEEvent(event) {
  switch (event.type) {
    case 'stage':
    case 'progress':
      currentProgress.value = event.content || ''
      if (event.progress !== undefined) {
        progressPercent.value = event.progress
      }
      break

    case 'content':
      // LLM生成的文本内容，流式显示
      if (event.content) {
        // 如果还在显示"正在分析"，替换为AI的第一句话
        if (isTyping.value && messages.value.length > 0) {
          const lastMsg = messages.value[messages.value.length - 1]
          if (lastMsg.role === 'assistant' && lastMsg.content.startsWith('正在')) {
            lastMsg.content = event.content
          } else {
            messages.value.push({
              role: 'assistant',
              content: event.content,
              timestamp: new Date()
            })
          }
        } else if (messages.value.length === 0 ||
                   messages.value[messages.value.length - 1].role === 'user') {
          messages.value.push({
            role: 'assistant',
            content: event.content,
            timestamp: new Date()
          })
        } else {
          // 追加到上一条消息
          messages.value[messages.value.length - 1].content += event.content
        }
        isTyping.value = false
      }
      break

    case 'clue_list':
      // 收到线索列表
      if (event.data?.items) {
        clueResults.value = event.data.items
      }
      break

    case 'complete':
      // 完成
      isTyping.value = false
      isProcessing.value = false
      currentProgress.value = '查询完成'
      progressPercent.value = 100
      break

    case 'error':
      ElMessage.error(event.content || '处理出错')
      isTyping.value = false
      isProcessing.value = false
      currentProgress.value = ''
      break

    case 'heartbeat':
      // 心跳，保持连接
      break
  }

  scrollToBottom()
}

async function scrollToBottom() {
  await nextTick()
  if (chatContainer.value) {
    chatContainer.value.scrollTop = chatContainer.value.scrollHeight
  }
}

function formatMessage(text) {
  if (!text) return ''
  // 使用 marked 渲染 Markdown
  return marked(text)
}

function formatTime(time) {
  if (!time) return ''
  const date = new Date(time)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
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
  return map[channel] || channel || '-'
}
</script>

<style scoped>
.query-page {
  max-width: 900px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  height: calc(100vh - 120px);
}

.query-header {
  padding: var(--spacing-md) 0;
  border-bottom: 1px solid var(--color-border);
}

.query-header .subtitle {
  font-size: 13px;
  color: var(--color-text-muted);
}

.chat-container {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-md) 0;
}

.welcome-message {
  text-align: center;
  color: var(--color-text-secondary);
  padding: var(--spacing-xl);
}

.welcome-message ul {
  list-style: none;
  padding: 0;
  margin-top: var(--spacing-md);
}

.welcome-message li {
  padding: var(--spacing-xs) 0;
  color: var(--color-primary);
}

.messages-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.message {
  display: flex;
  gap: var(--spacing-sm);
  align-items: flex-start;
}

.message.user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--color-primary-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.message-content {
  max-width: 70%;
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
}

.message.user .message-content {
  background: var(--color-primary);
  color: white;
  border-color: var(--color-primary);
}

.message-text {
  line-height: 1.6;
  word-break: break-word;
}

/* Markdown 渲染样式 */
.message-text :deep(h1),
.message-text :deep(h2),
.message-text :deep(h3) {
  margin: 0.5em 0;
  font-weight: 600;
}

.message-text :deep(h1) { font-size: 1.4em; }
.message-text :deep(h2) { font-size: 1.2em; }
.message-text :deep(h3) { font-size: 1.1em; }

.message-text :deep(p) {
  margin: 0.5em 0;
}

.message-text :deep(ul),
.message-text :deep(ol) {
  margin: 0.5em 0;
  padding-left: 1.5em;
}

.message-text :deep(li) {
  margin: 0.25em 0;
}

.message-text :deep(table) {
  border-collapse: collapse;
  margin: 0.5em 0;
  width: 100%;
  font-size: 0.9em;
}

.message-text :deep(th),
.message-text :deep(td) {
  border: 1px solid var(--color-border);
  padding: 0.4em 0.6em;
  text-align: left;
}

.message-text :deep(th) {
  background: var(--color-primary-subtle);
  font-weight: 600;
}

.message-text :deep(code) {
  background: var(--color-primary-subtle);
  padding: 0.1em 0.3em;
  border-radius: 3px;
  font-size: 0.9em;
}

.message-text :deep(pre) {
  background: var(--color-primary-subtle);
  padding: 0.6em;
  border-radius: var(--radius-sm);
  overflow-x: auto;
  margin: 0.5em 0;
}

.message-text :deep(pre code) {
  background: none;
  padding: 0;
}

.message-text :deep(blockquote) {
  border-left: 3px solid var(--color-primary);
  margin: 0.5em 0;
  padding-left: 0.8em;
  color: var(--color-text-secondary);
}

.message-text :deep(hr) {
  border: none;
  border-top: 1px solid var(--color-border);
  margin: 0.8em 0;
}

.message-text :deep(strong) {
  font-weight: 600;
}

.message-text :deep(a) {
  color: var(--color-primary);
  text-decoration: underline;
}

.message-time {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: var(--spacing-xxs);
}

.message.user .message-time {
  color: rgba(255, 255, 255, 0.7);
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: var(--spacing-xs);
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-text-muted);
  animation: typing 1.4s infinite;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-4px); }
}

.progress-indicator {
  padding: var(--spacing-sm) var(--spacing-md);
  background: var(--color-surface);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-primary-subtle);
}

.progress-text {
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-bottom: var(--spacing-xs);
}

.progress-bar {
  height: 4px;
  background: var(--color-border);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--color-primary);
  transition: width 0.3s ease;
}

.clue-results-section {
  margin-top: var(--spacing-lg);
  padding: var(--spacing-md);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-md);
}

.results-header h3 {
  font-size: 14px;
  font-weight: 500;
}

.results-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  max-height: 400px;
  overflow-y: auto;
}

.clue-card {
  padding: var(--spacing-sm);
  border: 1px solid var(--color-border);
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
  font-size: 13px;
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
  font-size: 13px;
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
  font-size: 11px;
  padding: 2px 6px;
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

.input-section {
  padding: var(--spacing-md) 0;
  border-top: 1px solid var(--color-border);
}

.input-wrapper {
  background: var(--color-surface);
  border: 1px solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-sm);
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: var(--spacing-sm);
}

.hint-text {
  font-size: 12px;
  color: var(--color-text-muted);
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
</style>