import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { PermissionCode } from '@/types'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { guest: true },
    },
    {
      path: '/',
      component: () => import('@/layouts/CabinetLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        { path: '', redirect: '/chats' },
        {
          path: 'chats',
          name: 'chats',
          component: () => import('@/views/ChatsView.vue'),
          meta: { permission: 'section.chats' },
        },
        {
          path: 'appeals',
          name: 'appeals',
          component: () => import('@/views/AppealsView.vue'),
          meta: { permission: 'section.appeals' },
        },
        {
          path: 'appeals/:appealId',
          name: 'appeal-detail',
          component: () => import('@/views/AppealDetailView.vue'),
          meta: { permission: 'section.appeals' },
        },
        {
          path: 'mailing',
          name: 'mailing',
          component: () => import('@/views/MailingView.vue'),
          meta: { permission: 'section.mailing' },
        },
        {
          path: 'channels',
          name: 'channels',
          component: () => import('@/views/ChannelsView.vue'),
          meta: { permission: 'section.channels' },
        },
        {
          path: 'employees',
          redirect: '/users',
        },
        {
          path: 'users',
          name: 'users',
          component: () => import('@/views/UsersView.vue'),
          meta: { permission: 'section.employees' },
        },
        {
          path: 'roles',
          name: 'roles',
          component: () => import('@/views/RolesView.vue'),
          meta: { permission: 'section.employees' },
        },
        {
          path: 'departments',
          name: 'departments',
          component: () => import('@/views/settings/DepartmentsView.vue'),
          meta: { permission: 'section.employees' },
        },
        {
          path: 'settings/departments',
          redirect: '/departments',
        },
        {
          path: 'templates',
          redirect: '/profile/templates',
        },
        {
          path: 'settings/close-template',
          name: 'close-template',
          component: () => import('@/views/settings/CloseTemplateView.vue'),
          meta: { permission: 'section.settings' },
        },
        {
          path: 'profile/templates',
          name: 'profile-templates',
          component: () => import('@/views/profile/MyTemplatesView.vue'),
        },
        {
          path: 'webhooks',
          name: 'webhooks',
          component: () => import('@/views/WebhooksView.vue'),
          meta: { permission: 'section.webhooks' },
        },
        {
          path: 'settings/appeal-fields',
          name: 'settings-appeal-fields',
          component: () => import('@/views/settings/AppealFieldsView.vue'),
          meta: { permission: 'section.settings' },
        },
        {
          path: 'settings/client-fields',
          name: 'settings-client-fields',
          component: () => import('@/views/settings/ClientFieldsView.vue'),
          meta: { permission: 'section.settings' },
        },
      ],
    },
  ],
})

let hydrated = false

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!hydrated) {
    hydrated = true
    await auth.hydrate()
  }
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.guest && auth.isAuthenticated) {
    return auth.firstAllowedPath()
  }
  if (auth.isAuthenticated) {
    const perm = to.meta.permission as PermissionCode | undefined
    if (perm && !auth.can(perm)) {
      return auth.firstAllowedPath()
    }
  }
  return true
})

export default router
