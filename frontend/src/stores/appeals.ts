import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listAppealsRequest, deleteAppealRequest, type ApiAppealListItem } from '@/api/appeals'
import { ApiError } from '@/api/client'
import type { AppealStatus, ChannelTransport } from '@/types'

export interface AppealListItem {
  id: number
  dialogId: number
  number: number
  status: AppealStatus
  openedAt: string
  closedAt: string | null
  closedById: number | null
  closedByName: string | null
  contactName: string
  contactUsername: string | null
  contactExternalId: string | null
  contactAvatarUrl: string | null
  channelId: number
  channelName: string | null
  transport: ChannelTransport | null
  assigneeId: number | null
  assigneeName: string | null
  lastMessage: string
  lastAt: string
}

function mapItem(a: ApiAppealListItem): AppealListItem {
  return {
    id: a.id,
    dialogId: a.dialog_id,
    number: a.number,
    status: a.status,
    openedAt: a.opened_at,
    closedAt: a.closed_at,
    closedById: a.closed_by_id,
    closedByName: a.closed_by_name,
    contactName: a.contact_name,
    contactUsername: a.contact_username,
    contactExternalId: a.contact_external_id,
    contactAvatarUrl: a.contact_avatar_url,
    channelId: a.channel_id,
    channelName: a.channel_name,
    transport: a.transport,
    assigneeId: a.assignee_id,
    assigneeName: a.assignee_name,
    lastMessage: a.last_message,
    lastAt: a.last_at,
  }
}

export const useAppealsStore = defineStore('appeals', () => {
  const items = ref<AppealListItem[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref('')

  const q = ref('')
  const status = ref<'all' | 'open' | 'closed'>('all')
  const dateFrom = ref('')
  const dateTo = ref('')
  const assignee = ref<'all' | 'unassigned' | 'mine'>('all')
  const limit = ref(50)
  const offset = ref(0)

  async function fetchAppeals() {
    loading.value = true
    error.value = ''
    try {
      const res = await listAppealsRequest({
        q: q.value,
        status: status.value,
        date_from: dateFrom.value || undefined,
        date_to: dateTo.value || undefined,
        assignee: assignee.value,
        limit: limit.value,
        offset: offset.value,
      })
      items.value = res.items.map(mapItem)
      total.value = res.total
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить обращения'
      items.value = []
      total.value = 0
    } finally {
      loading.value = false
    }
  }

  async function search() {
    offset.value = 0
    await fetchAppeals()
  }

  async function nextPage() {
    if (offset.value + limit.value >= total.value) return
    offset.value += limit.value
    await fetchAppeals()
  }

  async function prevPage() {
    if (offset.value <= 0) return
    offset.value = Math.max(0, offset.value - limit.value)
    await fetchAppeals()
  }

  async function removeAppeal(appealId: number) {
    error.value = ''
    try {
      await deleteAppealRequest(appealId)
      items.value = items.value.filter((a) => a.id !== appealId)
      total.value = Math.max(0, total.value - 1)
      if (!items.value.length && offset.value > 0) {
        offset.value = Math.max(0, offset.value - limit.value)
        await fetchAppeals()
      }
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить обращение'
      return false
    }
  }

  return {
    items,
    total,
    loading,
    error,
    q,
    status,
    dateFrom,
    dateTo,
    assignee,
    limit,
    offset,
    fetchAppeals,
    search,
    nextPage,
    prevPage,
    removeAppeal,
  }
})
