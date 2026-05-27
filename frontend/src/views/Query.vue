<template>
  <div class="query-page">
    <!-- 对话历史侧边栏 -->
    <div class="session-sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-header">
        <h3>对话历史</h3>
        <el-button text @click="sidebarCollapsed = !sidebarCollapsed">
          {{ sidebarCollapsed ? '☰' : '×' }}
        </el-button>
      </div>
      <div class="sidebar-content" v-if="!sidebarCollapsed">
        <el-button class="new-chat-btn" @click="createNewChat">
          <el-icon><Plus /></el-icon> 新建对话
        </el-button>
        <div class="conversation-list">
          <div
            v-for="conv in conversationList"
            :key="conv.conversation_id"
            :class="['conversation-item', { active: conv.conversation_id === currentConversationId }]"
            @click="loadConversation(conv.conversation_id)"
          >
            <span class="conv-title">{{ conv.title || '无标题对话' }}</span>
            <span class="conv-date">{{ formatDate(conv.created_at) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="main-content">
      <div class="query-header">
        <h2 class="section-title">情报分析助手</h2>
        <span class="subtitle">基于自然语言理解的黑灰产情报检索系统</span>
      </div>

      <!-- 对话区域（局部滚动） -->
      <div class="chat-container" ref="chatContainer">
        <!-- 欢迎语 -->
        <div v-if="messages.length === 0 && !isProcessing" class="welcome-message">
          <div class="welcome-icon">🔍</div>
          <p>您好，我是情报分析助手。请描述您想查询的情报，例如：</p>
          <div class="example-list">
            <div class="example-item" @click="queryText = '查询近三天抖音账号买卖的线索'; handleQuery()">查询近三天抖音账号买卖的线索</div>
            <div class="example-item" @click="queryText = '搜索涉及微信号的诈骗引流情报'; handleQuery()">搜索涉及微信号的诈骗引流情报</div>
            <div class="example-item" @click="queryText = '查看最近一周贴吧的流量作弊信息'; handleQuery()">查看最近一周贴吧的流量作弊信息</div>
          </div>
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
            <div class="message-content" :class="{ 'has-reasoning': msg.role === 'assistant' && msg.reasoning?.length }">
              <!-- ReasoningBlock：AI 执行过程（折叠在回复上方） -->
              <div v-if="msg.role === 'assistant' && msg.reasoning?.length" class="reasoning-block">
                <div class="reasoning-header" @click="msg._reasoningExpanded = !msg._reasoningExpanded">
                  <span class="reasoning-toggle">{{ msg._reasoningExpanded ? '▼' : '▶' }}</span>
                  <span class="reasoning-summary">推理过程（{{ msg.reasoning.length }} 步）</span>
                  <span class="reasoning-duration" v-if="msg.reasoningDuration">{{ msg.reasoningDuration }}</span>
                </div>
                <div v-if="msg._reasoningExpanded" class="reasoning-steps">
                  <div v-for="(step, i) in msg.reasoning" :key="i" class="reasoning-step">
                    <span class="step-dot"></span>
                    <span class="step-label">{{ step.content || getStageLabel(step.stage) }}</span>
                    <span v-if="step.tool_name" class="step-tool">{{ step.tool_name }}</span>
                  </div>
                </div>
              </div>
              <!-- 消息正文 -->
              <div class="message-body">
                <div class="message-text" v-html="formatMessage(msg.content)"></div>
              </div>
              <div class="message-time">{{ formatTime(msg.timestamp) }}</div>
            </div>
          </div>

          <!-- 流式处理中的 AI 消息（统一的单个气泡） -->
          <div v-if="isProcessing && currentReasoningSteps.length > 0 && !hasStreamingAssistantMessage" class="message assistant">
            <div class="message-avatar">🤖</div>
            <div class="message-content">
              <!-- 实时推理块 -->
              <div class="reasoning-block streaming">
                <div class="reasoning-header streaming">
                  <span class="reasoning-spinner"></span>
                  <span>AI 推理中...</span>
                </div>
                <div class="reasoning-steps">
                  <div v-for="(step, i) in currentReasoningSteps" :key="i" class="reasoning-step">
                    <span class="step-dot active"></span>
                    <span class="step-label">{{ step.content || getStageLabel(step.stage) }}</span>
                    <span v-if="step.tool_name" class="step-tool">{{ step.tool_name }}</span>
                  </div>
                </div>
              </div>
              <!-- 正在输入指示器（在同一气泡内） -->
              <div class="typing-indicator">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        </div>

        <!-- 检索结果卡片 -->
        <div v-if="clueResults.length > 0" class="clue-results-section">
          <div class="results-header">
            <h3>检索结果（{{ clueResults.length }} 条线索）</h3>
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

      <!-- 输入区域（固定在底部） -->
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
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { queryApi, conversationApi } from '../api'
import MarkdownIt from 'markdown-it'

const router = useRouter()

// 对话状态
const messages = ref([])
const queryText = ref('')
const isProcessing = ref(false)
const isTyping = ref(false)
const currentProgress = ref('')
const clueResults = ref([])
const chatContainer = ref(null)

// 推理过程状态
const currentReasoningSteps = ref([])

// 会话相关状态
const conversationList = ref([])
const currentConversationId = ref(null)
const sidebarCollapsed = ref(false)

// 计算：是否有正在流式输出的 AI 消息
const hasStreamingAssistantMessage = ref(false)

onMounted(async () => {
  await loadConversationList()
})

async function loadConversationList() {
  try {
    const res = await conversationApi.list(50)
    if (res.data?.data) {
      conversationList.value = res.data.data
    }
  } catch (e) {
    console.error('Failed to load conversations:', e)
  }
}

function createNewChat() {
  messages.value = []
  clueResults.value = []
  currentConversationId.value = null
  currentProgress.value = ''
  queryText.value = ''
  currentReasoningSteps.value = []
  hasStreamingAssistantMessage.value = false
}

async function loadConversation(conversationId) {
  try {
    const res = await conversationApi.get(conversationId)
    if (res.data?.data) {
      const conv = res.data.data
      currentConversationId.value = conversationId
      messages.value = conv.messages || []
      clueResults.value = []
      currentProgress.value = ''
      currentReasoningSteps.value = []
      hasStreamingAssistantMessage.value = false
      await scrollToBottom()
    }
  } catch (e) {
    console.error('Failed to load conversation:', e)
    ElMessage.error('加载对话失败')
  }
}

async function handleQuery() {
  if (!queryText.value.trim() || isProcessing.value) return

  const text = queryText.value.trim()
  queryText.value = ''

  messages.value.push({
    role: 'user',
    content: text,
    timestamp: new Date()
  })

  await scrollToBottom()

  isProcessing.value = true
  isTyping.value = true
  hasStreamingAssistantMessage.value = false
  currentReasoningSteps.value = []
  currentProgress.value = ''

  try {
    const res = await queryApi.create(text, {})
    const queryId = res.data?.data?.query_id

    if (!queryId) {
      throw new Error('无法创建查询任务')
    }

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
  const stage = event.stage || event.type

  // 收集推理步骤（仅在 AI 消息尚未开始生成时）
  if (stage && stage !== 'heartbeat' && stage !== 'content' && !hasStreamingAssistantMessage.value) {
    const step = {
      stage: stage,
      content: event.content || getStageLabel(stage),
      tool_name: event.tool_name,
      time: new Date()
    }
    currentReasoningSteps.value.push(step)
  }

  switch (event.type) {
    case 'stage':
    case 'progress':
      currentProgress.value = event.content || ''
      break

    case 'reasoning':
      // LLM 思考过程内容，添加到推理步骤
      if (event.content) {
        currentReasoningSteps.value.push({
          stage: 'reasoning',
          content: event.content,
          tool_name: null,
          timestamp: Date.now()
        })
      }
      break

    case 'content':
      if (event.content) {
        // 首次收到内容，创建 AI 消息并拷贝推理步骤
        if (!hasStreamingAssistantMessage.value) {
          hasStreamingAssistantMessage.value = true
          const reasoning = [...currentReasoningSteps.value]
          // 立即清空 currentReasoningSteps，隐藏流式推理块
          currentReasoningSteps.value = []
          messages.value.push({
            role: 'assistant',
            content: event.content,
            reasoning: reasoning,
            _reasoningExpanded: reasoning.length > 0,
            timestamp: new Date()
          })
        } else {
          // 追加内容到已有消息
          const lastMsg = messages.value[messages.value.length - 1]
          if (lastMsg.role === 'assistant') {
            lastMsg.content += event.content
          }
        }
        isTyping.value = false
      }
      break

    case 'clue_list':
      if (event.data?.items) {
        clueResults.value = event.data.items
      }
      break

    case 'complete':
      // 确保最后一条 AI 消息的推理步骤完整
      if (messages.value.length > 0 && currentReasoningSteps.value.length > 0) {
        const lastMsg = messages.value[messages.value.length - 1]
        if (lastMsg.role === 'assistant') {
          const duration = getReasoningDuration(currentReasoningSteps.value)
          lastMsg.reasoning = [...currentReasoningSteps.value]
          lastMsg._reasoningExpanded = false
          lastMsg.reasoningDuration = duration
        }
      }
      isTyping.value = false
      isProcessing.value = false
      currentProgress.value = ''
      currentReasoningSteps.value = []
      hasStreamingAssistantMessage.value = false
      saveConversation()
      scrollToBottom()
      break
  }

  scrollToBottom()
}

function getStageLabel(stage) {
  const labels = {
    'parsing': '理解用户意图',
    'retrieving': '调用 LightRAG 检索',
    'retrieved': '知识图谱查询完成',
    'analyzing': '生成分析报告',
    'results': '整理情报结果',
    'complete': '处理完成',
    'reasoning': 'LLM 推理过程'
  }
  return labels[stage] || stage
}

function getReasoningDuration(steps) {
  if (!steps?.length) return ''
  const first = steps[0]?.time ? new Date(steps[0].time) : null
  const last = steps[steps.length - 1]?.time ? new Date(steps[steps.length - 1].time) : null
  if (first && last) {
    const ms = last - first
    if (ms < 1000) return `${ms}ms`
    return `${(ms / 1000).toFixed(1)}s`
  }
  return ''
}

async function saveConversation() {
  if (messages.value.length === 0) return

  try {
    const title = messages.value[0]?.content?.slice(0, 20) || '无标题对话'
    const conversationData = {
      title: title,
      messages: JSON.parse(JSON.stringify(messages.value))
    }

    // 清理前端临时状态
    conversationData.messages.forEach(m => {
      delete m._reasoningExpanded
      delete m.reasoningDuration
    })

    if (currentConversationId.value) {
      await conversationApi.update(currentConversationId.value, conversationData)
    } else {
      const res = await conversationApi.create(conversationData)
      if (res.data?.data?.conversation_id) {
        currentConversationId.value = res.data.data.conversation_id
        await loadConversationList()
      }
    }
  } catch (e) {
    console.error('Failed to save conversation:', e)
  }
}

async function scrollToBottom() {
  await nextTick()
  if (chatContainer.value) {
    chatContainer.value.scrollTop = chatContainer.value.scrollHeight
  }
}

const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: true
})

function formatMessage(text) {
  if (!text) return ''

  let processed = text
    // 1. 修复原有的表格跨行粘连 (解决行与行之间丢失换行，变成 "||" 的问题)
    .replace(/\|\|/g, '|\n|')

    // 2. 修复表格同行粘连 (解决 "文本| 标题1 | 标题2 |" 挤在同一行的问题)
    // 严格限制：只有当一行开头是文本，且后半部分是包含至少3个 '|' 的标准表格行时，才进行切分
    .replace(/^([ \t]*[^|\n]+?[^\s|])(\s*)(\|(?:[ \t]*[^\n|]+[ \t]*\|){2,})/gm, '$1\n\n$3')

    // 3. 修复表格跨行粘连 (解决 "文本\n| 标题1 |" 缺少安全空行的问题)
    .replace(/([^\n|])[ \t]*\n[ \t]*(\|(?:[ \t]*[^\n|]+[ \t]*\|){2,})/g, '$1\n\n$2')

    // 4. 修复标题粘连 (解决 "文本### 标题" 或 "---### 标题" 的问题)
    // 排除 # 防止破坏多级标题
    .replace(/([^#\n])\s*(#{1,6}\s+)/g, '$1\n\n$2')

    // 5. 修复无序列表粘连 (解决 "文字- 列表" 没有换行的问题)
    // 极其严格的排除：前一个字符绝不能是 |、-、*、#，完美避开表格线和加粗符号
    .replace(/([^\|\-\*\#\s\n])\s*(-\s+[^\n]+)/g, '$1\n\n$2')

    // 6. 修复有序列表粘连 (解决 "文字1. 列表" 没有换行的问题)
    // 同样严格排除，保护 "**1." 或者 "(1." 这种正常组合不被切断
    .replace(/([^\|\-\*\#\s\n\[\(\{])\s*(\d+\.\s+)/g, '$1\n\n$2')

    // 7. 修复引用块粘连 (解决 "**文本**> 引用" 的问题)
    .replace(/(\*\*)\s*(>)/g, '$1\n\n$2')

    // 8. 修复全行分割线 (---)
    .replace(/^[ \t]*(-{3,}|—+)[ \t]*$/gm, '\n\n---\n\n');

  return md.render(processed)
}

function formatTime(time) {
  if (!time) return ''
  const date = new Date(time)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
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
/* ============ 页面布局 ============ */
.query-page {
  display: flex;
  flex: 1;
  gap: var(--spacing-sm);
  min-height: 0;
  overflow: hidden;
}

/* ============ 侧边栏 ============ */
.session-sidebar {
  width: 220px;
  flex-shrink: 0;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width var(--duration-normal) var(--ease-out-quint);
}

.session-sidebar.collapsed {
  width: 40px;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-sm) var(--spacing-xs);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.sidebar-header h3 {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  letter-spacing: 0.5px;
}

.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-xs);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.new-chat-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 8px 12px;
  border: 1px dashed var(--color-primary);
  border-radius: 6px;
  color: var(--color-primary);
  background: transparent;
  font-size: 13px;
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease-out-quint);
}

.new-chat-btn:hover {
  background: var(--color-primary-subtle);
  border-style: solid;
}

.conversation-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.conversation-item {
  padding: 10px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  transition: background var(--duration-normal) var(--ease-out-quint);
}

.conversation-item:hover {
  background: var(--color-primary-subtle);
}

.conversation-item.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.conversation-item.active .conv-title {
  color: var(--color-primary);
  font-weight: 500;
}

.conv-title {
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  line-height: 1.4;
}

.conv-date {
  font-size: 11px;
  color: var(--color-text-muted);
}

/* ============ 主内容区 ============ */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  max-height: 100%;
}

.query-header {
  padding-bottom: var(--spacing-xs);
  flex-shrink: 0;
}

.query-header .section-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 2px 0;
}

.query-header .subtitle {
  font-size: 12px;
  color: var(--color-text-muted);
}

/* ============ 对话容器（核心：固定高度，局部滚动） ============ */
.chat-container {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding-right: var(--spacing-xs);
  scroll-behavior: smooth;
}

/* ============ 欢迎语 ============ */
.welcome-message {
  text-align: center;
  color: var(--color-text-secondary);
  padding: var(--spacing-xxl) var(--spacing-xl);
  animation: fadeSlideIn var(--duration-standard) var(--ease-out-quint);
}

.welcome-icon {
  font-size: 48px;
  margin-bottom: var(--spacing-md);
}

.welcome-message p {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin-bottom: var(--spacing-md);
}

.example-list {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-xs);
}

.example-item {
  padding: 10px 18px;
  background: var(--color-primary-subtle);
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-primary);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease-out-quint);
  max-width: 400px;
}

.example-item:hover {
  background: var(--color-primary-light);
  transform: translateY(-1px);
}

/* ============ 消息列表 ============ */
.messages-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.message {
  display: flex;
  gap: var(--spacing-sm);
  align-items: flex-start;
  animation: fadeSlideIn var(--duration-standard) var(--ease-out-quint);
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
  max-width: 80%;
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: 8px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  overflow: visible;
}

.message-content.has-reasoning {
  padding-top: 0;
}

.message.user .message-content {
  background: var(--color-primary);
  color: white;
  border-color: var(--color-primary);
}

/* Markdown 内容容器 */
.message-body {
  width: 100%;
}

.message-text {
  line-height: 1.7;
  word-break: break-word;
  font-size: 14px;
  overflow: visible;
  width: 100%;
}

/* Markdown 渲染样式（v-html 需要 :deep） */
.message-text :deep(p) { margin: 0.6em 0; line-height: 1.7; }
.message-text :deep(p:first-child) { margin-top: 0; }
.message-text :deep(p:last-child) { margin-bottom: 0; }

.message-text :deep(h1),
.message-text :deep(h2),
.message-text :deep(h3),
.message-text :deep(h4) {
  margin: 0.8em 0 0.4em;
  font-weight: 600;
  line-height: 1.4;
}

.message-text :deep(h1) { font-size: 1.35em; }
.message-text :deep(h2) { font-size: 1.2em; }
.message-text :deep(h3) { font-size: 1.1em; }
.message-text :deep(h4) { font-size: 1em; }

.message-text :deep(ul),
.message-text :deep(ol) {
  margin: 0.6em 0;
  padding-left: 1.5em;
}

.message-text :deep(ul) { list-style-type: disc; }
.message-text :deep(ol) { list-style-type: decimal; }

.message-text :deep(li) {
  margin: 0.35em 0;
  line-height: 1.6;
}

.message-text :deep(li > ul),
.message-text :deep(li > ol) {
  margin: 0.25em 0;
}

/* 表格 */
.message-text :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
  font-size: 13px;
  overflow: visible;
  border: 1px solid #dfe2e5;
}

.message-text :deep(table th),
.message-text :deep(table td) {
  border: 1px solid #dfe2e5;
  padding: 8px 12px;
  text-align: left;
}

.message-text :deep(table th) {
  background: #f6f8fa;
  font-weight: 600;
}

.message-text :deep(table tr:nth-child(even) td) {
  background: #fafbfc;
}

.message-text code {
  background: rgba(0, 0, 255, 0.06);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.9em;
  font-family: var(--font-mono);
  color: #d63384;
}

.message-text :deep(pre) {
  background: #f6f8fa;
  padding: 12px 16px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 0.8em 0;
  border: 1px solid var(--color-border);
}

.message-text :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
  font-size: 13px;
}

.message-text :deep(blockquote) {
  border-left: 3px solid var(--color-primary);
  margin: 0.8em 0;
  padding: 8px 16px;
  color: var(--color-text-secondary);
  background: var(--color-primary-subtle);
  border-radius: 0 4px 4px 0;
}

.message-text :deep(strong) { font-weight: 700; }
.message.user .message-text :deep(strong) { color: rgba(255, 255, 255, 0.95); }

.message-text :deep(a) {
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.message-text :deep(hr) {
  border: none;
  border-top: 1px solid var(--color-border);
  margin: 1em 0;
}

.message-time {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: 4px;
}

.message.user .message-time {
  color: rgba(255, 255, 255, 0.7);
}

/* ============ ReasoningBlock（AI 推理过程组件） ============ */
.reasoning-block {
  margin-bottom: var(--spacing-sm);
  border-bottom: 1px solid var(--color-divider);
  padding-bottom: var(--spacing-sm);
}

.reasoning-block.streaming {
  border-bottom: none;
  padding-bottom: 0;
}

.reasoning-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
  cursor: pointer;
  user-select: none;
  padding: 4px 0;
}

.reasoning-header.streaming {
  cursor: default;
  color: var(--color-primary);
  font-weight: 500;
}

.reasoning-toggle {
  font-size: 10px;
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.reasoning-summary {
  flex: 1;
}

.reasoning-duration {
  font-size: 11px;
  color: var(--color-text-muted);
  background: var(--color-divider);
  padding: 1px 6px;
  border-radius: 3px;
}

.reasoning-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid var(--color-primary-light);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: reasoning-spin 0.8s linear infinite;
  flex-shrink: 0;
}

@keyframes reasoning-spin {
  to { transform: rotate(360deg); }
}

.reasoning-steps {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin-top: 4px;
}

.reasoning-step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0 4px 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.step-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-border);
  flex-shrink: 0;
}

.step-dot.active {
  background: var(--color-primary);
  animation: pulse-dot 1.5s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.step-label {
  flex: 1;
}

.step-tool {
  font-size: 11px;
  padding: 1px 6px;
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  border-radius: 3px;
  white-space: nowrap;
}

/* ============ 打字指示器 ============ */
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

/* ============ 检索结果卡片 ============ */
.clue-results-section {
  margin-top: var(--spacing-lg);
  padding: var(--spacing-md);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-md);
}

.results-header h3 {
  font-size: 14px;
  font-weight: 600;
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
  border-radius: 6px;
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease-out-quint);
}

.clue-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-hover);
  transform: translateY(-1px);
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
  border-radius: 3px;
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
  border-radius: 3px;
  color: var(--color-text-secondary);
}

.clue-footer {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--color-text-muted);
}

/* ============ 输入区域（固定在底部） ============ */
.input-section {
  padding: var(--spacing-md) 0 0 0;
  flex-shrink: 0;
}

.input-wrapper {
  background: var(--color-surface);
  border: 1px solid var(--color-primary-subtle);
  border-radius: 10px;
  padding: var(--spacing-sm);
  transition: border-color var(--duration-normal) var(--ease-out-quint);
}

.input-wrapper:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px rgba(0, 0, 255, 0.08);
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: var(--spacing-xs);
}

.hint-text {
  font-size: 12px;
  color: var(--color-text-muted);
}

/* ============ 动画 ============ */
@keyframes fadeSlideIn {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
