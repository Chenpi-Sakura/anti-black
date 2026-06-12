<template>
  <aside class="graph-legend" aria-label="图例">
    <ul class="legend-list">
      <li v-for="t in typeSwatches" :key="t.type">
        <span class="swatch" :style="{ background: t.color }"></span>
        <span class="swatch-label">{{ t.label }}</span>
      </li>
    </ul>
  </aside>
</template>

<script setup>
// 数据写死,无 props.
// 颜色与 NodeInfoCard.vue / GraphCanvas.vue 中的 TYPE_COLORS 保持一致
// 1k 节点用高对比 10 色 — 即使节点缩到 4-6px 也能区分
const typeSwatches = [
  { type: 'PERSON',  label: '人物',     color: '#e84545' },
  { type: 'WECHAT',  label: '微信号',   color: '#f56c6c' },
  { type: 'PRICE',   label: '价格',     color: '#faad14' },
  { type: 'TOOL',    label: '工具',     color: '#a0522d' },
  { type: 'TACTIC',  label: '手法',     color: '#ff7a45' },
  { type: 'ORG',     label: '组织',     color: '#52c41a' },
  { type: 'PHONE',   label: '手机号',   color: '#13c2c2' },
  { type: 'URL',     label: '网址',     color: '#1d39c4' },
  { type: 'QQ',      label: 'QQ',       color: '#722ed1' },
  { type: 'ACCOUNT', label: '账号',     color: '#eb2f96' },
  { type: 'OTHER',   label: '其他',     color: '#8c8c8c' },
]
</script>

<style scoped>
.graph-legend {
  position: absolute;
  bottom: 12px;
  left: 12px;
  z-index: 10;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  border: 1px solid #d9e6f2;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(31, 64, 104, 0.08);
  pointer-events: none;     /* 不拦截画布拖动/点击 */
  font-size: 12px;
  color: #1f3a5f;
}

.legend-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: auto auto;
  column-gap: 14px;
  row-gap: 4px;
}
.legend-list li {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
  display: inline-block;
}
.swatch-label { color: #1f3a5f; }
</style>
