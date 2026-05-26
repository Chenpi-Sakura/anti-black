import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000
})

// Query APIs
export const queryApi = {
  create: (queryText, options = {}) =>
    api.post('/queries', { query_text: queryText, ...options }),
  getStatus: (queryId) =>
    api.get(`/queries/${queryId}`)
}

// Clue APIs
export const clueApi = {
  list: (params) =>
    api.get('/clues', { params }),
  detail: (clueId) =>
    api.get(`/clues/${clueId}`)
}

// Entity APIs
export const entityApi = {
  profile: (entityId) =>
    api.get(`/entities/${entityId}/profile`),
  list: (entityType, limit = 100) =>
    api.get('/entities', { params: { entity_type: entityType, limit } })
}

// Feedback APIs
export const feedbackApi = {
  submit: (data) =>
    api.post('/feedback', data)
}

// System APIs
export const systemApi = {
  ready: () =>
    api.get('/system/ready'),
  pipelineStatus: () =>
    api.get('/system/pipeline-status')
}

// Taxonomy APIs
export const taxonomyApi = {
  get: () =>
    api.get('/taxonomy')
}

// Metrics APIs
export const metricsApi = {
  overview: () =>
    api.get('/metrics/overview')
}

// Evolution APIs
export const evolutionApi = {
  status: () =>
    api.get('/evolution/status'),
  proposals: () =>
    api.get('/evolution/proposals'),
  approve: (proposalId) =>
    api.post(`/evolution/proposals/${proposalId}/approve`)
}

// Export APIs
export const exportApi = {
  create: (data) =>
    api.post('/exports', data),
  status: (exportId) =>
    api.get(`/exports/${exportId}`)
}

// Channel APIs
export const channelApi = {
  list: () =>
    api.get('/channels'),
  status: (platform) =>
    api.get(`/channels/${platform}/status`)
}

// Seed Word APIs
export const seedWordApi = {
  list: (status) =>
    api.get('/seed-words', { params: { status } }),
  promote: (word) =>
    api.post(`/seed-words/${word}/promote`)
}

export default api