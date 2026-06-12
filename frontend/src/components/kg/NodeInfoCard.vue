<template>
  <aside
    class="node-info-card"
    :class="`mode-${mode}`"
    role="complementary"
    aria-live="polite"
    @click.stop
  >
    <!-- stats mode: 选中节点前的图谱概览 -->
    <template v-if="mode === 'stats'">
      <header class="card-header">
        <h4 class="card-title">图谱概览</h4>
        <span class="card-subtitle">未选中节点</span>
      </header>

      <div v-if="hasData" class="stats-body">
        <!-- 数据库真实总量(后端 metadata 给出) -->
        <div v-if="totalEntityCount > 0" class="stats-total">
          <div class="total-label">数据库真实总量</div>
          <div class="total-values">
            <span class="total-cell"><b>{{ totalEntityCount }}</b><em>实体</em></span>
            <span class="total-sep">·</span>
            <span class="total-cell"><b>{{ totalRelCount }}</b><em>关系</em></span>
          </div>
        </div>

        <h5 class="card-subhead">实体类型分布</h5>
        <ul class="type-list">
          <li v-for="t in topTypes" :key="t.name">
            <span class="type-swatch" :style="{ background: t.color }"></span>
            <span class="type-name">{{ t.label }}</span>
            <span class="type-count">{{ t.count }}</span>
          </li>
          <li v-if="otherCount > 0" class="type-other">
            <span class="type-swatch" :style="{ background: '#c0c4cc' }"></span>
            <span class="type-name">其他</span>
            <span class="type-count">{{ otherCount }}</span>
          </li>
        </ul>
      </div>

      <div v-else class="empty">
        <p>暂无图谱数据,请先查询</p>
      </div>
    </template>

    <!-- node mode: 选中节点 -->
    <template v-else-if="mode === 'node' && nodeDetail">
      <header class="card-header">
        <h4 class="card-title">{{ nodeDetail.entity_name }}</h4>
        <el-tag size="small" type="primary" effect="light">{{ nodeDetail.entity_type }}</el-tag>
      </header>
      <p class="detail-text">{{ nodeDetail.description || '暂无描述' }}</p>
      <div class="detail-stat"><span>来源:</span> {{ (nodeDetail.file_path || '').slice(0, 40) }}</div>
      <h5 class="card-subhead">关联关系 ({{ adjacentRels.length }})</h5>
      <ul class="rel-list">
        <li v-for="r in adjacentRels" :key="`${r.src_id}-${r.tgt_id}`">
          <span class="rel-src">{{ r.src_id }}</span><span class="rel-arrow">→</span><span class="rel-tgt">{{ r.tgt_id }}</span>
        </li>
        <li v-if="!adjacentRels.length" class="rel-none">无</li>
      </ul>
    </template>

    <!-- edge mode: 选中边 -->
    <template v-else-if="mode === 'edge' && edgeDetail">
      <header class="card-header">
        <h4 class="card-title">{{ edgeDetail.src_id }} → {{ edgeDetail.tgt_id }}</h4>
      </header>
      <div class="detail-stat"><span>权重:</span> {{ (edgeDetail.weight || 0).toFixed(2) }}</div>
      <p class="detail-text">{{ edgeDetail.description || '暂无描述' }}</p>
      <div v-if="edgeDetail.keywords" class="detail-keywords">
        <el-tag v-for="k in split(edgeDetail.keywords)" :key="k" size="small" effect="plain">{{ k }}</el-tag>
      </div>
      <h5 v-if="relChunk" class="card-subhead">来源分块</h5>
      <pre v-if="relChunk" class="chunk-preview">{{ truncate(relChunk.content, 600) }}</pre>
    </template>
  </aside>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  mode: { type: String, default: 'stats' },            // 'stats' | 'node' | 'edge'
  nodeDetail: { type: Object, default: null },
  edgeDetail: { type: Object, default: null },
  adjacentRels: { type: Array, default: () => [] },
  relChunk: { type: Object, default: null },
  entityCount: { type: Number, default: 0 },
  relCount: { type: Number, default: 0 },
  totalEntityCount: { type: Number, default: 0 },  // 数据库真实总量(后端 metadata)
  totalRelCount: { type: Number, default: 0 },
  graphData: { type: Object, default: null },
})

// 18 类型色板 — 与 GraphCanvas.vue:25-34 的 TYPE_COLORS 同步
// 取色原则:暖冷色交替,色相分散,饱和度拉满,1k 节点下仍能区分
const TYPE_COLORS = {
  PERSON:   '#e84545',
  WECHAT:   '#f56c6c',
  PRICE:    '#faad14',
  TOOL:     '#a0522d',
  TACTIC:   '#ff7a45',
  ORG:      '#52c41a',
  PHONE:    '#13c2c2',
  URL:      '#1d39c4',
  QQ:       '#722ed1',
  ACCOUNT:  '#eb2f96',
  WHATSAPP: '#36cfc9',
  TELEGRAM: '#1890ff',
  RESOURCE: '#7cb305',
  INTENT:   '#ffc53d',
  TARGET:   '#2f54eb',
  SCENE:    '#a0d911',
  ADDRESS:  '#08979c',
  OTHER:    '#8c8c8c',
}

// 中文类型映射 — 与 GraphCanvas.vue:36-39 CN_TYPE_MAP 同步
const CN_TYPE_MAP = {
  人物: 'PERSON', 组织: 'ORG', 手机号: 'PHONE', 微信号: 'WECHAT',
  账号: 'ACCOUNT', 网址: 'URL', 地址: 'ADDRESS',
}

function normalizeType(t) {
  if (!t) return 'OTHER'
  const up = String(t).toUpperCase()
  if (TYPE_COLORS[up]) return up
  return CN_TYPE_MAP[t] || 'OTHER'
}

const CN_LABEL = {
  PERSON: '人物', ORG: '组织', PHONE: '手机号', WECHAT: '微信号',
  ACCOUNT: '账号', URL: '网址', ADDRESS: '地址', WHATSAPP: 'WhatsApp',
  TELEGRAM: 'Telegram', QQ: 'QQ',
  RESOURCE: '资源', INTENT: '意图', TACTIC: '手法',
  TARGET: '目标', SCENE: '场景', TOOL: '工具',
  PRICE: '价格', OTHER: '其他',
}

function labelOf(type) {
  return CN_LABEL[type] || type
}

function split(s) { return (s || '').split(',').map(v => v.trim()).filter(Boolean) }
function truncate(s, n) { return (s || '').length > n ? s.slice(0, n) + '…' : (s || '') }

const hasData = computed(() =>
  (props.entityCount > 0) || (props.relCount > 0) ||
  (props.graphData?.entities?.length > 0)
)

const typeStats = computed(() => {
  const entities = props.graphData?.entities || []
  const m = new Map()    // type -> count
  for (const e of entities) {
    const t = normalizeType(e.entity_type)
    m.set(t, (m.get(t) || 0) + 1)
  }
  return Array.from(m.entries())
    .map(([type, count]) => ({ type, count, label: labelOf(type), color: TYPE_COLORS[type] || TYPE_COLORS.OTHER }))
    .sort((a, b) => b.count - a.count)
})

const topTypes = computed(() => typeStats.value.slice(0, 8))
const otherCount = computed(() => typeStats.value.slice(8).reduce((s, t) => s + t.count, 0))
</script>

<style scoped>
.node-info-card {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 10;
  width: 340px;
  max-height: calc(100% - 24px);
  overflow-y: auto;
  background: #ffffff;
  border: 1px solid #d9e6f2;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(31, 64, 104, 0.08);
  padding: 14px 16px;
  font-size: 13px;
  color: #1f3a5f;
  animation: cardIn .18s ease-out;
  scrollbar-width: thin;
  scrollbar-color: #d9e6f2 transparent;
}

.node-info-card::-webkit-scrollbar { width: 6px; }
.node-info-card::-webkit-scrollbar-thumb { background: #d9e6f2; border-radius: 3px; }

@keyframes cardIn {
  from { opacity: 0; transform: translateX(-8px); }
  to   { opacity: 1; transform: translateX(0); }
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.card-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #1a4d8f;
  word-break: break-all;
  flex: 1 1 auto;
  min-width: 0;
}

.card-subtitle {
  font-size: 12px;
  color: #94a8c2;
  font-weight: 400;
}

.card-subhead {
  margin: 12px 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: #1a4d8f;
}

/* stats mode */
.stats-total {
  padding: 8px 10px;
  background: #f0f6ff;
  border: 1px solid #d9e6f2;
  border-radius: 6px;
  margin-bottom: 8px;
}
.total-label {
  font-size: 11px;
  color: #94a8c2;
  margin-bottom: 4px;
  letter-spacing: 0.3px;
}
.total-values {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.total-cell b {
  font-size: 18px;
  font-weight: 700;
  color: #1a4d8f;
  font-variant-numeric: tabular-nums;
  margin-right: 2px;
}
.total-cell em {
  font-style: normal;
  font-size: 11px;
  color: #94a8c2;
}
.total-sep {
  color: #c0c4cc;
  font-weight: 400;
}

.type-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.type-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 2px 0;
}
.type-swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
  display: inline-block;
}
.type-name { flex: 1; color: #1f3a5f; }
.type-count {
  color: #409eff;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.type-other { color: #94a8c2; }

.empty {
  padding: 20px 0;
  text-align: center;
  color: #94a8c2;
  font-size: 12px;
}

/* node / edge mode shared */
.detail-text {
  color: #4a5b75;
  font-size: 13px;
  line-height: 1.6;
  margin: 6px 0;
  max-height: 120px;
  overflow-y: auto;
  word-break: break-word;
}

.detail-stat {
  font-size: 12px;
  color: #94a8c2;
  margin: 4px 0;
}
.detail-stat span {
  font-weight: 600;
  color: #409eff;
  margin-right: 4px;
}

.detail-keywords {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 8px 0;
}

.rel-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.rel-list li {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 2px 0;
  border-bottom: 1px dashed #e8f0fa;
}
.rel-src, .rel-tgt {
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: #1a4d8f;
}
.rel-arrow {
  color: #409eff;
  flex-shrink: 0;
}
.rel-none {
  color: #94a8c2;
  font-style: italic;
  border: none !important;
}

.chunk-preview {
  background: #f0f6ff;
  padding: 8px;
  border-radius: 4px;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  margin: 4px 0 0;
}
</style>
