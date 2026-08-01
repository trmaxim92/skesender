import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  createWebhookRequest,
  deleteWebhookRequest,
  listWebhooksRequest,
  updateWebhookRequest,
  type ApiWebhook,
} from '@/api/cabinet'
import { ApiError } from '@/api/client'
import type { WebhookEndpoint } from '@/types'

export const WEBHOOK_EVENTS = [
  'message.created',
  'dialog.updated',
  'dialog.assigned',
  'channel.status',
] as const

function mapWebhook(w: ApiWebhook): WebhookEndpoint {
  return {
    id: String(w.id),
    url: w.url,
    events: w.events,
    active: w.active,
  }
}

export const useWebhooksStore = defineStore('webhooks', () => {
  const endpoints = ref<WebhookEndpoint[]>([])
  const loading = ref(false)
  const error = ref('')

  async function fetchWebhooks() {
    loading.value = true
    error.value = ''
    try {
      const list = await listWebhooksRequest()
      endpoints.value = list.map(mapWebhook)
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить webhooks'
    } finally {
      loading.value = false
    }
  }

  async function addEndpoint(url: string, events: string[]) {
    try {
      const created = await createWebhookRequest({ url, events })
      endpoints.value.unshift(mapWebhook(created))
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось добавить'
      return false
    }
  }

  async function toggle(id: string) {
    const current = endpoints.value.find((x) => x.id === id)
    if (!current) return
    try {
      const updated = await updateWebhookRequest(Number(id), { active: !current.active })
      const mapped = mapWebhook(updated)
      const idx = endpoints.value.findIndex((x) => x.id === id)
      if (idx >= 0) endpoints.value[idx] = mapped
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось переключить'
    }
  }

  async function remove(id: string) {
    try {
      await deleteWebhookRequest(Number(id))
      endpoints.value = endpoints.value.filter((x) => x.id !== id)
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить'
    }
  }

  return { endpoints, loading, error, fetchWebhooks, addEndpoint, toggle, remove }
})
