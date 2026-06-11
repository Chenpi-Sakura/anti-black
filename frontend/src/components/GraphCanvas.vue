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

// Blue-primary palette — degrees of blue for the most common entity types.
// WECHAT and PRICE/PRICE get warm accents for high-signal / value tracking.
const TYPE_COLORS = {
  PERSON: '#1e80ff', ORG: '#409eff', PHONE: '#6aaeff',
  WECHAT: '#f56c6c', ACCOUNT: '#92bfff', URL: '#2d7dd2',
  ADDRESS: '#57a0ff', WHATSAPP: '#8cbaff', TELEGRAM: '#409eff',
  QQ: '#7cb4ff',
  RESOURCE: '#409eff', INTENT: '#6aaeff', TACTIC: '#1e80ff',
  TARGET: '#2d7dd2', SCENE: '#57a0ff', TOOL: '#92bfff',
  PRICE: '#e6a23c',
  OTHER: '#c0c4cc',
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

  // Keep ALL entities (full-load mode, User Feedback #4 revised).
  // Previously we filtered out isolated nodes here, but that caused
  // edge-creation failures when a relationship referenced a non-entity
  // name (data quality). Full load is also what the user expects.
  const allRels = data.relationships || []

  const nodes = (data.entities || []).map(e => {
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

  // Only create edges whose source AND target exist in the entity list
  const entityNames = new Set((data.entities || []).map(e => e.entity_name))
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
  const dpr = window.devicePixelRatio || 1
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
          'font-size': 12,
          'font-weight': 600,
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-wrap': 'wrap',
          'text-max-width': 100,
          'text-margin-y': 6,
          'width': 'mapData(weight, 0, 10, 24, 60)',
          'height': 'mapData(weight, 0, 10, 24, 60)',
          'border-width': 2,
          'border-color': '#fff',
          'border-opacity': 0.95,
      }},
      { selector: 'edge', style: {
          'curve-style': 'bezier',
          'width': 'mapData(weight, 0, 1, 0.6, 3)',
          'line-color': '#92bfff',
          'line-opacity': 0.6,
          'target-arrow-color': '#409eff',
          'target-arrow-shape': 'triangle',
          'arrow-scale': 0.8,
      }},
      { selector: 'node:selected', style: {
          'border-color': '#409eff',
          'border-width': 4,
      }},
      { selector: 'edge:selected', style: {
          'line-color': '#409eff',
          'target-arrow-color': '#409eff',
          'width': 4,
      }},
    ],
    layout: { name: 'cose-bilkent', animate: false, randomize: true, nodeRepulsion: 20000, idealEdgeLength: 120, padding: 60, fit: true },
    minZoom: 0.15,
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
  currentLayout = cy.layout({
    name: 'cose-bilkent', animate: false, randomize: false,
    nodeRepulsion: 20000, idealEdgeLength: 120, padding: 60, fit: true,
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
  reload() { cy?.layout({ name: 'cose-bilkent', animate: true, randomize: true }).run() }
})
</script>

<style scoped>
.graph-container {
  width: 100%;
  height: 100%;
  min-height: 0;
}
</style>
