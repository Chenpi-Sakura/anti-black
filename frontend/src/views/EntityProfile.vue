<template>
  <div class="entity-profile">
    <div class="detail-header">
      <el-button :icon="ArrowLeft" @click="goBack">返回</el-button>
    </div>

    <div v-if="profile" class="profile-content">
      <div class="profile-main">
        <div class="info-card">
          <div class="entity-header">
            <span class="entity-type-badge">{{ profile.entity_type }}</span>
            <span class="entity-value">{{ profile.raw_value }}</span>
          </div>

          <div class="entity-stats">
            <div class="stat-item">
              <span class="stat-value">{{ profile.occurrence_count }}</span>
              <span class="stat-label">出现次数</span>
            </div>
            <div class="stat-item">
              <span class="stat-value">{{ formatTime(profile.first_seen) }}</span>
              <span class="stat-label">首次发现</span>
            </div>
            <div class="stat-item">
              <span class="stat-value">{{ formatTime(profile.last_seen) }}</span>
              <span class="stat-label">最近活跃</span>
            </div>
          </div>
        </div>

        <div class="risk-dist-card" v-if="profile.risk_distribution?.length">
          <h3>风险分布</h3>
          <div class="risk-list">
            <div
              v-for="(risk, idx) in profile.risk_distribution"
              :key="idx"
              class="risk-item"
            >
              <span class="risk-label">{{ risk.risk_label }}</span>
              <span class="risk-count">{{ risk.count }}</span>
            </div>
          </div>
        </div>

        <div class="related-card" v-if="profile.related_entities?.length">
          <h3>关联实体</h3>
          <div class="related-list">
            <div
              v-for="entity in profile.related_entities"
              :key="entity.entity_id"
              class="related-item"
              @click="goToEntity(entity.entity_id)"
            >
              <span class="entity-type">{{ entity.entity_type }}</span>
              <span class="entity-value">{{ entity.raw_value }}</span>
            </div>
          </div>
        </div>

        <div class="evidence-card" v-if="profile.recent_evidence?.length">
          <h3>最近证据</h3>
          <div class="evidence-list">
            <div
              v-for="evidence in profile.recent_evidence"
              :key="evidence.clue_id"
              class="evidence-item"
              @click="goToClue(evidence.clue_id)"
            >
              <span class="evidence-time">{{ formatTime(evidence.published_at) }}</span>
              <span class="evidence-snippet">{{ evidence.snippet }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-empty v-else description="实体不存在" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { entityApi } from '../api'
import { ArrowLeft } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const profile = ref(null)

function goBack() {
  router.back()
}

function formatTime(timeStr) {
  if (!timeStr) return '-'
  const date = new Date(timeStr)
  return date.toLocaleDateString('zh-CN')
}

function goToEntity(entityId) {
  router.push(`/entities/${entityId}`)
}

function goToClue(clueId) {
  router.push(`/clues/${clueId}`)
}

onMounted(async () => {
  try {
    const res = await entityApi.profile(route.params.id)
    profile.value = res.data?.data
  } catch (e) {
    console.error('Failed to load entity profile:', e)
  }
})
</script>

<style scoped>
.entity-profile {
  max-width: 1200px;
  margin: 0 auto;
}

.detail-header {
  margin-bottom: var(--spacing-md);
}

.profile-content {
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

.entity-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-md);
}

.entity-type-badge {
  font-size: var(--font-size-xs);
  padding: 4px 12px;
  background: var(--color-primary);
  color: white;
  border-radius: 4px;
}

.entity-value {
  font-size: var(--font-size-xl);
  font-weight: 500;
}

.entity-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--spacing-md);
  padding-top: var(--spacing-md);
  border-top: var(--border-thin) solid var(--color-divider);
}

.stat-item {
  text-align: center;
}

.stat-value {
  display: block;
  font-size: var(--font-size-lg);
  font-weight: 500;
  color: var(--color-primary);
}

.stat-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.risk-dist-card, .related-card, .evidence-card {
  background: var(--color-surface);
  border: var(--border-thin) solid var(--color-primary-subtle);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
  margin-top: var(--spacing-md);
}

.risk-dist-card h3, .related-card h3, .evidence-card h3 {
  margin-bottom: var(--spacing-sm);
}

.risk-list, .related-list, .evidence-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.risk-item {
  display: flex;
  justify-content: space-between;
  padding: var(--spacing-xs);
  background: var(--color-background);
  border-radius: var(--radius-sm);
}

.risk-label {
  font-size: var(--font-size-sm);
}

.risk-count {
  font-size: var(--font-size-sm);
  color: var(--color-primary);
  font-weight: 500;
}

.related-item, .evidence-item {
  display: flex;
  gap: var(--spacing-sm);
  padding: var(--spacing-xs);
  background: var(--color-background);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.related-item:hover, .evidence-item:hover {
  background: var(--color-primary-subtle);
}

.entity-type {
  font-size: var(--font-size-xs);
  padding: 2px 6px;
  background: var(--color-primary);
  color: white;
  border-radius: 2px;
}

.entity-value {
  font-size: var(--font-size-sm);
}

.evidence-time {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
}

.evidence-snippet {
  font-size: var(--font-size-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>