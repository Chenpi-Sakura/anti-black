<template>
  <div class="kg-page">
    <PageHeader title="知识图谱可视分析">
      <template #actions>
        <el-input v-model="queryText" placeholder="输入查询文本, 如: 微信号诈骗" clearable class="kg-search" @keyup.enter="runQuery" />
        <el-select v-model="mode" class="kg-mode" size="default">
          <el-option label="mix（综合）" value="mix" />
          <el-option label="hybrid（混合）" value="hybrid" />
          <el-option label="local（实体）" value="local" />
          <el-option label="global（关系）" value="global" />
          <el-option label="naive（向量）" value="naive" />
        </el-select>
        <el-button type="primary" :loading="loading" @click="runQuery">运行</el-button>
        <el-button @click="reloadLayout">重排</el-button>
      </template>
    </PageHeader>

    <div class="kg-body">
      <div class="kg-canvas-wrap">
        <GraphCanvas
          ref="graphRef"
          :graph-data="graphData"
          :selected-node-id="selectedNodeId"
          @node-click="onNodeClick"
          @edge-click="onEdgeClick"
          @background-click="onBackgroundClick"
          @layout-end="layoutReady = true"
        />
        <LoadingMask v-if="loading" :loading="loading" :text="loadingText" />
        <EmptyState v-else-if="isNoData" :description="emptyText" />
      </div>

      <aside class="kg-side-panel">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="实体" name="entities">
            <EntityList :entities="graphData?.entities || []" :selected-id="selectedNodeId" @select="onNodeClick" />
          </el-tab-pane>
          <el-tab-pane label="关系" name="relationships">
            <RelationshipList :relationships="graphData?.relationships || []" :selected-key="selectedEdge" @select="onEdgeClick" />
          </el-tab-pane>
          <el-tab-pane label="分块" name="chunks">
            <ChunkList :chunks="graphData?.chunks || []" />
          </el-tab-pane>
          <el-tab-pane label="引用" name="references">
            <ReferenceList :references="graphData?.references || []" />
          </el-tab-pane>
        </el-tabs>

        <div v-if="nodeDetail" class="kg-detail">
          <h4 class="detail-title">{{ nodeDetail.entity_name }}</h4>
          <el-tag size="small">{{ nodeDetail.entity_type }}</el-tag>
          <p class="detail-text">{{ nodeDetail.description || '暂无描述' }}</p>
          <div class="detail-stat"><span>来源:</span> {{ (nodeDetail.file_path || '').slice(0, 40) }}</div>
          <h5 class="detail-subtitle">关联关系 ({{ adjacentRels.length }})</h5>
          <ul class="rel-list">
            <li v-for="r in adjacentRels" :key="`${r.src_id}-${r.tgt_id}`">
              <span class="rel-src">{{ r.src_id }}</span><span class="rel-arrow">→</span><span class="rel-tgt">{{ r.tgt_id }}</span>
            </li>
            <li v-if="!adjacentRels.length" class="rel-none">无</li>
          </ul>
        </div>

        <div v-else-if="edgeDetail" class="kg-detail">
          <h4 class="detail-title">{{ edgeDetail.src_id }} → {{ edgeDetail.tgt_id }}</h4>
          <div class="detail-stat"><span>权重:</span> {{ (edgeDetail.weight || 0).toFixed(2) }}</div>
          <p class="detail-text">{{ edgeDetail.description || '暂无描述' }}</p>
          <div v-if="edgeDetail.keywords" class="detail-keywords">
            <el-tag v-for="k in split(edgeDetail.keywords)" :key="k" size="small" effect="plain">{{ k }}</el-tag>
          </div>
          <h5 v-if="relChunk" class="detail-subtitle">来源分块</h5>
          <pre v-if="relChunk" class="chunk-preview">{{ truncate(relChunk.content, 600) }}</pre>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '../components/PageHeader.vue'
import LoadingMask from '../components/LoadingMask.vue'
import EmptyState from '../components/EmptyState.vue'
import GraphCanvas from '../components/GraphCanvas.vue'
import EntityList from '../components/kg/EntityList.vue'
import RelationshipList from '../components/kg/RelationshipList.vue'
import ChunkList from '../components/kg/ChunkList.vue'
import ReferenceList from '../components/kg/ReferenceList.vue'
import { kgApi } from '../api'

const route = useRoute()

const queryText = ref('')
const mode = ref('mix')
const loading = ref(false)
const graphData = ref(null)
const selectedNodeId = ref(null)
const selectedEdge = ref(null)          // [src, tgt] tuple
const activeTab = ref('entities')
const errorMessage = ref('')
const layoutReady = ref(false)          // User Feedback #1: wait for layoutstop
const graphRef = ref(null)

const isNoData = computed(() =>
  !loading.value && !graphData.value
)
const entityCount = computed(() => graphData.value?.entities?.length || 0)
const relCount = computed(() => graphData.value?.relationships?.length || 0)

const emptyText = computed(() => {
  if (errorMessage.value) return errorMessage.value
  return queryText.value
    ? `未找到与「${queryText.value}」相关的实体或关系`
    : '请输入查询文本并点击「运行」'
})

const loadingText = computed(() => errorMessage.value ? '' : '正在检索知识图谱…')

const nodeDetail = computed(() => {
  if (!selectedNodeId.value || !graphData.value) return null
  return graphData.value.entities.find(e => e.entity_name === selectedNodeId.value)
})

const edgeDetail = computed(() => {
  if (!selectedEdge.value || !graphData.value) return null
  const [s, t] = selectedEdge.value
  return graphData.value.relationships.find(r => r.src_id === s && r.tgt_id === t)
})

const adjacentRels = computed(() => {
  if (!selectedNodeId.value || !graphData.value) return []
  const id = selectedNodeId.value
  return graphData.value.relationships.filter(r => r.src_id === id || r.tgt_id === id)
})

const relChunk = computed(() => {
  if (!edgeDetail.value || !graphData.value) return null
  const refId = edgeDetail.value.reference_id
  if (refId) return graphData.value.chunks.find(c => c.reference_id === refId)
  return graphData.value.chunks.find(c => c.file_path === edgeDetail.value.file_path) || null
})

function split(s) { return (s || '').split(',').map(v => v.trim()).filter(Boolean) }
function truncate(s, n) { return (s || '').length > n ? s.slice(0, n) + '…' : (s || '') }

async function runQueryCustom(text) {
  // 允许外部传入搜索词（用于初始全量加载）
  if (text !== undefined) queryText.value = text
  runQuery()
}

async function runQuery() {
  const text = queryText.value.trim()
  if (!text && !isInitialLoad.value) return  // 用户没输入而且不是初始化，不做
  loading.value = true
  layoutReady.value = false
  errorMessage.value = ''
  selectedNodeId.value = null
  selectedEdge.value = null
  activeTab.value = 'entities'
  graphData.value = null
  try {
    // 初始全量加载: raw 模式(Neo4j 直连,端点100%对齐)
    // 用户搜索时: mix 模式(语义向量检索)
    const topK = isInitialLoad.value ? 200 : 30
    const searchText = text || ''
    const m = isInitialLoad.value ? 'raw' : (mode.value || 'mix')
    const res = await kgApi.query({ text: searchText, mode: m, top_k: topK })
    const d = res.data || {}
    if (d.status === 'failure') {
      errorMessage.value = d.message || '查询失败'
      graphData.value = null
    } else {
      graphData.value = d.data || { entities: [], relationships: [], chunks: [], references: [] }
    }
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || e.message || '请求失败'
    graphData.value = null
  } finally {
    if (errorMessage.value) loading.value = false
    isInitialLoad.value = false
  }
}

watch(() => layoutReady.value, (v) => { if (v) loading.value = false })

function reloadLayout() { graphRef.value?.reload() }

function onNodeClick(id) { selectedNodeId.value = id; selectedEdge.value = null; activeTab.value = 'entities' }
function onEdgeClick(key) { selectedEdge.value = key; selectedNodeId.value = null; activeTab.value = 'relationships' }
function onBackgroundClick() { selectedNodeId.value = null; selectedEdge.value = null }

const isInitialLoad = ref(true)

onMounted(() => {
  const t = route.query.text
  if (t) {
    queryText.value = String(t)
    isInitialLoad.value = false
    runQuery()
  } else {
    // 初始全量加载
    queryText.value = ''
    runQuery()
  }
  const m = route.query.mode
  if (m && typeof m === 'string' && ['mix', 'hybrid', 'local', 'global', 'naive'].includes(m)) {
    mode.value = m
  }
})
</script>

<style scoped>
.kg-page { display: flex; flex-direction: column; height: 100%; }
.kg-body { display: flex; flex: 1; min-height: 0; gap: 16px; padding: var(--spacing-md, 16px); }
.kg-canvas-wrap { flex: 1; position: relative; border-radius: 8px; background: #f8fbff; overflow: hidden; border: 1px solid #d9e6f2; }
.kg-side-panel { width: 340px; min-width: 300px; display: flex; flex-direction: column; overflow-y: auto; border-radius: 8px; border: 1px solid #d9e6f2; padding: var(--spacing-sm, 12px); }
.kg-side-panel :deep(.el-tabs__item.is-active) { color: #409eff; }
.kg-side-panel :deep(.el-tabs__active-bar) { background: #409eff; }
.kg-search { width: 320px; }
.kg-mode { width: 140px; }
.kg-detail { padding: 12px 4px 0; border-top: 2px solid #409eff; margin-top: 8px; }
.detail-title { margin: 0 0 6px; font-size: var(--font-size-base, 15px); font-weight: 600; color: #1a4d8f; }
.detail-text { color: var(--color-text-secondary, #666); font-size: var(--font-size-sm, 13px); line-height: 1.6; margin: 6px 0; }
.detail-stat { font-size: var(--font-size-xs, 12px); color: var(--color-text-muted, #999); }
.detail-stat span { font-weight: 600; color: #409eff; }
.detail-subtitle { margin: 10px 0 4px; font-size: var(--font-size-sm, 13px); font-weight: 600; color: #1a4d8f; }
.detail-keywords { display: flex; flex-wrap: wrap; gap: 4px; margin: 8px 0; }
.rel-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 2px; }
.rel-list li { display: flex; align-items: center; gap: 4px; font-size: 12px; padding: 2px 0; border-bottom: 1px dashed #d9e6f2; }
.rel-src { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; color: #1a4d8f; }
.rel-tgt { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; color: #1a4d8f; }
.rel-arrow { color: #409eff; flex-shrink: 0; }
.rel-none { color: var(--color-text-muted, #999); font-style: italic; }
.chunk-preview { background: #f0f6ff; padding: 8px; border-radius: 4px; font-size: 11px; white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow-y: auto; }
</style>
