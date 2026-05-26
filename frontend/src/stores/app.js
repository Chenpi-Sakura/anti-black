import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  // System status
  const systemStatus = ref('BOOTSTRAPPING')
  const systemReady = ref(false)

  // Current user
  const user = ref(null)

  // Query state
  const currentQuery = ref(null)
  const queryResults = ref([])

  // Clues state
  const clues = ref([])
  const currentClue = ref(null)
  const cluesPagination = ref({
    page_no: 1,
    page_size: 10,
    total: 0
  })

  // Entity state
  const currentEntity = ref(null)
  const entityProfile = ref(null)

  // Loading states
  const loading = ref(false)

  // Actions
  function setSystemStatus(status) {
    systemStatus.value = status
    systemReady.value = status === 'READY'
  }

  function setCurrentQuery(query) {
    currentQuery.value = query
  }

  function setClues(clueList, pagination = null) {
    clues.value = clueList
    if (pagination) {
      cluesPagination.value = pagination
    }
  }

  function setCurrentClue(clue) {
    currentClue.value = clue
  }

  function setEntityProfile(profile) {
    entityProfile.value = profile
  }

  function setLoading(isLoading) {
    loading.value = isLoading
  }

  return {
    systemStatus,
    systemReady,
    user,
    currentQuery,
    queryResults,
    clues,
    currentClue,
    cluesPagination,
    currentEntity,
    entityProfile,
    loading,
    setSystemStatus,
    setCurrentQuery,
    setClues,
    setCurrentClue,
    setEntityProfile,
    setLoading
  }
})