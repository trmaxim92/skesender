import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  listNotificationsRequest,
  mapNotification,
  markNotificationsReadRequest,
  unreadNotificationsCountRequest,
  type AppNotification,
} from '@/api/notifications'
import { ApiError } from '@/api/client'

export const useNotificationsStore = defineStore('notifications', () => {
  const items = ref<AppNotification[]>([])
  const unreadCount = ref(0)
  const loading = ref(false)
  const error = ref('')

  const hasUnread = computed(() => unreadCount.value > 0)

  async function fetchUnreadCount() {
    try {
      const data = await unreadNotificationsCountRequest()
      unreadCount.value = data.unread_count
    } catch {
      // ignore — bell is non-critical
    }
  }

  async function fetchList() {
    loading.value = true
    error.value = ''
    try {
      const data = await listNotificationsRequest()
      items.value = data.items.map(mapNotification)
      unreadCount.value = data.unread_count
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить оповещения'
    } finally {
      loading.value = false
    }
  }

  async function markRead(ids?: string[]) {
    await markNotificationsReadRequest(ids)
    if (!ids || ids.length === 0) {
      items.value = items.value.map((n) => ({ ...n, read: true }))
      unreadCount.value = 0
      return
    }
    const set = new Set(ids)
    items.value = items.value.map((n) => (set.has(n.id) ? { ...n, read: true } : n))
    unreadCount.value = items.value.filter((n) => !n.read).length
  }

  async function markAllRead() {
    await markRead()
  }

  return {
    items,
    unreadCount,
    loading,
    error,
    hasUnread,
    fetchUnreadCount,
    fetchList,
    markRead,
    markAllRead,
  }
})
