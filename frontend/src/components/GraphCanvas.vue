<template>
  <div ref="containerRef" class="graph-container"></div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import cytoscape from 'cytoscape'
import coseBilkent from 'cytoscape-cose-bilkent'

cytoscape.use(coseBilkent)

const props = defineProps({
  graphData: { type: Object, default: null },
  selectedNodeId: { type: String, default: null }
})

const emit = defineEmits(['node-click', 'edge-click', 'background-click', 'layout-end'])

const containerRef = ref(null)
let cy = null
let currentLayout = null

// High-contrast palette — 10 个色相互不相邻(红/橙/黄/绿/青/蓝/紫/粉/棕/灰),
// 即使节点缩到 4-6px 也能在视觉上区分。暖色(WECHAT/PRICE/TOOL/TACTIC)对应
// 强信号,冷色(数据/标识类)对应静态信息。
const TYPE_COLORS = {
  PERSON:   '#e84545',   // 红    — 人物
  WECHAT:   '#f56c6c',   // 浅红  — 微信号(高风险)
  PRICE:    '#faad14',   // 金黄  — 价格
  TOOL:     '#a0522d',   // 棕    — 工具(灰产工具)
  TACTIC:   '#ff7a45',   // 橙    — 手法
  ORG:      '#52c41a',   // 绿    — 组织
  PHONE:    '#13c2c2',   // 青    — 手机号
  URL:      '#1d39c4',   // 深蓝  — 网址
  QQ:       '#722ed1',   // 紫    — QQ
  ACCOUNT:  '#eb2f96',   // 粉    — 账号
  WHATSAPP: '#36cfc9',   // 浅青  — WhatsApp
  TELEGRAM: '#1890ff',   // 中蓝  — Telegram
  RESOURCE: '#7cb305',   // 草绿  — 资源
  INTENT:   '#ffc53d',   // 暖黄  — 意图
  TARGET:   '#2f54eb',   // 钴蓝  — 目标
  SCENE:    '#a0d911',   // 黄绿  — 场景
  ADDRESS:  '#08979c',   // 墨青  — 地址
  OTHER:    '#8c8c8c',   // 灰    — 其他
}

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

function buildElements(data) {
  if (!data) return []

  const allRels = data.relationships || []
  const allEnts = data.entities || []

  // 孤立节点过滤:只保留至少被一条关系引用的实体
  // (上一轮决策 "Keep ALL entities" 在新反馈下被覆盖,见 plan)
  const referenced = new Set()
  for (const r of allRels) { referenced.add(r.src_id); referenced.add(r.tgt_id) }
  const entities = allEnts.filter(e => referenced.has(e.entity_name))

  const nodes = entities.map(e => {
    const type = normalizeType(e.entity_type)
    const degreeWeight = allRels
      .filter(r => r.src_id === e.entity_name || r.tgt_id === e.entity_name)
      .reduce((s, r) => s + (r.weight || 0), 0)
    return {
      group: 'nodes',
      data: {
        id: e.entity_name,
        label: e.entity_name,
        type,
        color: TYPE_COLORS[type] || TYPE_COLORS.OTHER,
        description: e.description || '',
        weight: degreeWeight,
      }
    }
  })

  // Only create edges whose source AND target exist in the (filtered) entity list
  const entityNames = new Set(entities.map(e => e.entity_name))
  const edges = allRels
    .filter(r => entityNames.has(r.src_id) && entityNames.has(r.tgt_id))
    .map((r, i) => ({
      group: 'edges',
      data: {
        id: `e-${i}-${r.src_id}-${r.tgt_id}`,
        source: r.src_id,
        target: r.tgt_id,
        weight: r.weight || 0.5,
        keywords: r.keywords || '',
        description: r.description || '',
      }
    }))

  return [...nodes, ...edges]
}

onMounted(() => {
  // High-DPI rendering fix — cytoscape defaults to CSS px which on
  // retina/4K screens looks blurry. Explicit devicePixelRatio scaling
  // matches the canvas to the actual physical resolution.
  //
  // Windows 125%/150% 缩放下 dpr ∈ {1.25, 1.5},所有 CSS px 值
  // (font-size, border-width, node width/height, edge width)
  // 都需 × SCALE 才不会在物理像素上被拉伸变糊。
  const dpr = window.devicePixelRatio || 1
  const SCALE = dpr
  cy = cytoscape({
    container: containerRef.value,
    elements: buildElements(props.graphData),
    pixelRatio: dpr,
    style: [
      { selector: 'node', style: {
          'background-color': 'data(color)',
          'background-opacity': 0.88,
          'label': 'data(label)',
          'color': '#1a4d8f',
          'font-size': 12 * SCALE,
          'font-weight': 600,
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-wrap': 'wrap',
          'text-max-width': 70 * SCALE,
          'text-margin-y': 4 * SCALE,
          // 缩小视图时字号跟着缩,避免字号 > 节点直径造成视觉重叠
          'min-zoomed-font-size': 8,
          'width': `mapData(weight, 0, 10, ${24 * SCALE}, ${60 * SCALE})`,
          'height': `mapData(weight, 0, 10, ${24 * SCALE}, ${60 * SCALE})`,
          'border-width': 2 * SCALE,
          'border-color': '#fff',
          'border-opacity': 0.95,
      }},
      { selector: 'edge', style: {
          'curve-style': 'bezier',
          'width': `mapData(weight, 0, 1, ${0.6 * SCALE}, ${3 * SCALE})`,
          'line-color': '#92bfff',
          'line-opacity': 0.6,
          'target-arrow-color': '#409eff',
          'target-arrow-shape': 'triangle',
          'arrow-scale': 0.8,
      }},
      { selector: 'node:selected', style: {
          'border-color': '#409eff',
          'border-width': 4 * SCALE,
      }},
      { selector: 'edge:selected', style: {
          'line-color': '#409eff',
          'target-arrow-color': '#409eff',
          'width': 4 * SCALE,
      }},
    ],
    // 间距三参数 + 中心引力联合调,目标:打散链式拓扑 + 节点不重叠
    // - nodeRepulsion 80000: 中等斥力,比原始 4x 不挤,但不会把全图撑到 fit 缩成点
    // - idealEdgeLength 180: 理想边长,略 > 节点直径,允许紧邻但标签不挤
    // - gravity 0.1 (默认 0.25): 中心引力减半,让图不再被拉成对角线
    // - padding 30: 画布边距小,fit 后 zoom 不被压太小(关键:否则节点会缩成点)
    layout: { name: 'cose-bilkent', animate: false, randomize: true, nodeRepulsion: 80000, idealEdgeLength: 180, gravity: 0.1, padding: 30, fit: true },
    minZoom: 0.1,
    maxZoom: 3,
  })

  // Event wiring
  cy.on('tap', 'node', evt => emit('node-click', evt.target.data('id')))
  cy.on('tap', 'edge', evt => {
    const d = evt.target.data()
    emit('edge-click', [d.source, d.target])
  })
  cy.on('tap', evt => { if (evt.target === cy) emit('background-click') })

  // Spring forces stay live after initial layout — user can drag nodes
  // and the simulation will re-settle them. This is what makes
  // force-directed graphs feel alive.
  cy.on('drag', 'node', () => {})
  cy.on('dragfree', 'node', evt => {
    // Re-anchor the dragged node so the simulation holds the new position
    // while gently re-balancing neighbours.
    evt.target.neighborhood().layout({ name: 'cose-bilkent', animate: true, randomize: false, fit: false }).run()
  })
})

onBeforeUnmount(() => {
  if (currentLayout) currentLayout.stop()
  if (cy) { cy.destroy(); cy = null }
})

watch(() => props.graphData, (newData) => {
  if (!cy) return
  if (currentLayout) currentLayout.stop()             // User Feedback #5: cleanup old layout
  cy.elements().remove()
  cy.add(buildElements(newData))
  if (cy.elements().length === 0) return               // nothing to render
  // randomize: true 重新摇随机起点,避免连续两次新图都收敛到同一条对角线
  currentLayout = cy.layout({
    name: 'cose-bilkent', animate: false, randomize: true,
    nodeRepulsion: 80000, idealEdgeLength: 180, gravity: 0.1, padding: 30, fit: true,
  })
  currentLayout.one('layoutstop', () => emit('layout-end'))
  currentLayout.run()
}, { deep: true })

watch(() => props.selectedNodeId, (id) => {
  if (!cy) return
  cy.$('node:selected').unselect()
  if (id) {
    const n = cy.getElementById(id)
    if (n.length) {
      n.select()
      cy.animate({ center: { eles: n }, zoom: 1.5 }, { duration: 300 })
    }
  }
})

// Exposed for parent to call fit/relayout
defineExpose({
  fit() { cy?.fit(undefined, 30) },
  reload() { cy?.layout({ name: 'cose-bilkent', animate: true, randomize: true, nodeRepulsion: 80000, idealEdgeLength: 180, gravity: 0.1, padding: 30, fit: true }).run() }
})
</script>

<style scoped>
.graph-container {
  width: 100%;
  height: 100%;
  min-height: 0;
  image-rendering: -webkit-optimize-contrast;
  image-rendering: crisp-edges;
}
</style>
