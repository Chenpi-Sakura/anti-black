<template>
  <div class="query-page">
    <SessionSidebar
      :conversations="conversationList"
      :current-id="currentConversationId"
      :collapsed="sidebarCollapsed"
      @select="loadConversation"
      @new="createNewChat"
      @toggle="sidebarCollapsed = !sidebarCollapsed"
    />

    <div class="main-content">
      <div class="query-header">
        <h2 class="section-title">情报分析助手</h2>
        <span class="subtitle">基于自然语言理解的黑灰产情报检索系统</span>
      </div>

      <div ref="chatContainer" class="chat-container">
        <!-- 欢迎语 -->
        <div v-if="messages.length === 0 && !isProcessing" class="welcome-message">
          <div class="welcome-icon">🔍</div>
          <p>您好，我是情报分析助手。请描述您想查询的情报，例如：</p>
          <div class="example-list">
            <div
              v-for="(ex, i) in examples"
              :key="i"
              class="example-item"
              @click="runExample(ex)"
            >
              {{ ex }}
            </div>
          </div>
        </div>

        <!-- 消息列表 -->
        <div class="messages-list">
          <MessageBubble
            v-for="(msg, index) in messages"
            :key="index"
            :message="msg"
            :role="msg.role"
          />

          <!-- 流式处理中的 AI 消息 -->
          <div
            v-if="isProcessing && currentReasoningSteps.length > 0 && !hasStreamingAssistantMessage"
            class="message assistant"
          >
            <div class="message-avatar">🤖</div>
            <div class="message-content">
              <div class="reasoning-block streaming">
                <div class="reasoning-header streaming">
                  <span class="reasoning-spinner"></span>
                  <span>AI 推理中...</span>
                </div>
                <div class="reasoning-steps">
                  <div v-for="(step, i) in currentReasoningSteps" :key="i" class="reasoning-step">
                    <span class="step-dot active"></span>
                    <span class="step-label">{{ step.content || step.stage }}</span>
                    <span v-if="step.tool_name" :class="['step-tool', `tool-${step.tool_name}`]">{{ step.tool_name }}</span>
                  </div>
                </div>
              </div>
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
            <ClueResultCard
              v-for="clue in clueResults"
              :key="clue.clue_id"
              :clue="clue"
              @click="goToClueDetail"
            />
          </div>
        </div>
      </div>

      <ChatInput
        v-model="queryText"
        :disabled="isProcessing"
        :is-processing="isProcessing"
        @submit="handleQuery"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { queryApi, conversationApi } from '../api'
import SessionSidebar from '../components/SessionSidebar.vue'
import MessageBubble from '../components/MessageBubble.vue'
import ClueResultCard from '../components/ClueResultCard.vue'
import ChatInput from '../components/ChatInput.vue'

const router = useRouter()

// 对话状态
const messages = ref([])
const queryText = ref('')
const isProcessing = ref(false)
const isTyping = ref(false)
const currentProgress = ref('')
const clueResults = ref([])
const chatContainer = ref(null)
const currentReasoningSteps = ref([])
const hasStreamingAssistantMessage = ref(false)

// 会话相关
const conversationList = ref([])
const currentConversationId = ref(null)
const sidebarCollapsed = ref(false)

const examples = [
  '查询近三天抖音账号买卖的线索',
  '搜索涉及微信号的诈骗引流情报',
  '查看最近一周贴吧的流量作弊信息'
]

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
      currentConversationId.value = conversationId
      messages.value = res.data.data.messages || []
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

function runExample(text) {
  queryText.value = text
  handleQuery()
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

  if (stage && stage !== 'heartbeat' && stage !== 'content' && !hasStreamingAssistantMessage.value) {
    // Deduplicate: if the last step has the same tool_name, update it in place
    // instead of appending.  The backend emits two events per tool invocation
    // (retrieving → retrieved), both with tool_name set, which would otherwise
    // render the tool tag twice.
    const prev = currentReasoningSteps.value.length > 0
      ? currentReasoningSteps.value[currentReasoningSteps.value.length - 1]
      : null
    if (prev && event.tool_name && prev.tool_name === event.tool_name) {
      prev.stage = stage
      prev.content = event.content || stage
    } else {
      currentReasoningSteps.value.push({
        stage,
        content: event.content || stage,
        tool_name: event.tool_name,
        time: new Date()
      })
    }
  }

  switch (event.type) {
    case 'stage':
    case 'progress':
      currentProgress.value = event.content || ''
      break

    case 'reasoning':
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
        if (!hasStreamingAssistantMessage.value) {
          hasStreamingAssistantMessage.value = true
          const reasoning = [...currentReasoningSteps.value]
          currentReasoningSteps.value = []
          messages.value.push({
            role: 'assistant',
            content: event.content,
            reasoning,
            _reasoningExpanded: reasoning.length > 0,
            timestamp: new Date()
          })
        } else {
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
      if (messages.value.length > 0 && currentReasoningSteps.value.length > 0) {
        const lastMsg = messages.value[messages.value.length - 1]
        if (lastMsg.role === 'assistant') {
          lastMsg.reasoning = [...currentReasoningSteps.value]
          lastMsg._reasoningExpanded = false
          lastMsg.reasoningDuration = getReasoningDuration(currentReasoningSteps.value)
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
      title,
      messages: JSON.parse(JSON.stringify(messages.value))
    }
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

function goToClueDetail(clueId) {
  router.push(`/clues/${clueId}`)
}
</script>

<style scoped>
.query-page {
  display: flex;
  flex: 1;
  gap: var(--spacing-sm);
  min-height: 0;
  overflow: hidden;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  max-height: 100%;
  /* Cap the content width so the report / input don't span the entire
     viewport. Auto margin keeps the column centered with symmetric gutters
     when the sidebar is collapsed. */
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
}

.query-header {
  padding-bottom: var(--spacing-xs);
  flex-shrink: 0;
}

.section-title {
  font-size: var(--font-size-lg);
  font-weight: 600;
  margin: 0 0 2px 0;
}

.subtitle {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.chat-container {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding: 0 var(--spacing-md);
  scroll-behavior: smooth;
}

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
  font-size: var(--font-size-sm);
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
  font-size: var(--font-size-sm);
  color: var(--color-primary);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease-out-quint);
  max-width: 400px;
}

.example-item:hover {
  background: var(--color-primary-light);
  transform: translateY(-1px);
}

.messages-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

/* Inline streaming bubble (transient, not in MessageBubble) */
.message {
  display: flex;
  gap: var(--spacing-sm);
  align-items: flex-start;
  animation: fadeSlideIn var(--duration-standard) var(--ease-out-quint);
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--color-primary-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-lg);
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

.reasoning-block.streaming {
  margin-bottom: 0;
  border-bottom: none;
  padding-bottom: 0;
}

.reasoning-header.streaming {
  cursor: default;
  color: var(--color-primary);
  font-weight: 500;
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

@keyframes reasoning-spin { to { transform: rotate(360deg); } }

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
  font-size: var(--font-size-xs);
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

.step-label { flex: 1; }

.step-tool {
  font-size: var(--font-size-xs);
  padding: 1px 6px;
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  border-radius: 3px;
  white-space: nowrap;
}

/* Per-tool color coding (see MessageBubble.vue for the canonical list) */
.step-tool.tool-search_clues,
.step-tool.tool-get_recent_clues {
  background: rgba(0, 0, 255, 0.12);
  color: #0000a0;
}
.step-tool.tool-kg_query {
  background: rgba(128, 0, 255, 0.14);
  color: #5b21b6;
}
.step-tool.tool-search_entities {
  background: rgba(0, 153, 76, 0.14);
  color: #15803d;
}
.step-tool.tool-get_clue_detail {
  background: rgba(255, 140, 0, 0.16);
  color: #b45309;
}
.step-tool.tool-search_slang {
  background: rgba(234, 179, 8, 0.18);
  color: #92400e;
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

.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-4px); }
}

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
  font-size: var(--font-size-sm);
  font-weight: 600;
}

.results-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  max-height: 400px;
  overflow-y: auto;
}

@keyframes fadeSlideIn {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
