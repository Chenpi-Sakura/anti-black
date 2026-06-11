import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue')
  },
  {
    path: '/query',
    name: 'Query',
    component: () => import('../views/Query.vue')
  },
  {
    path: '/clues',
    name: 'Clues',
    component: () => import('../views/Clues.vue')
  },
  {
    path: '/clues/:id',
    name: 'ClueDetail',
    component: () => import('../views/ClueDetail.vue')
  },
  {
    path: '/entities/:id',
    name: 'EntityProfile',
    component: () => import('../views/EntityProfile.vue')
  },
  {
    path: '/feedback',
    name: 'Feedback',
    component: () => import('../views/Feedback.vue')
  },
  {
    path: '/kg',
    name: 'KnowledgeGraph',
    component: () => import('../views/KnowledgeGraph.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router