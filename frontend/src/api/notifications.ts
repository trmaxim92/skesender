import { api } from '@/api/client'

export type NotificationKind = 'system_news'

export type ApiNotification = {
  id: string
  kind: NotificationKind
  title: string
  body: string
  created_at: string
  read: boolean
  link: string | null
}

export type ApiNotificationsPage = {
  items: ApiNotification[]
  unread_count: number
}

export type ApiSystemNews = {
  id: number
  title: string
  body: string
  created_at: string
  published_at: string
  created_by_id: number | null
  created_by_name: string | null
  read_count: number
}

export type AppNotification = {
  id: string
  kind: NotificationKind
  title: string
  body: string
  createdAt: string
  read: boolean
  link: string | null
}

export function mapNotification(row: ApiNotification): AppNotification {
  return {
    id: row.id,
    kind: row.kind,
    title: row.title,
    body: row.body,
    createdAt: row.created_at,
    read: row.read,
    link: row.link,
  }
}

export async function listNotificationsRequest(limit = 50) {
  return api<ApiNotificationsPage>(`/api/notifications?limit=${limit}`)
}

export async function unreadNotificationsCountRequest() {
  return api<{ unread_count: number }>('/api/notifications/unread-count')
}

export async function markNotificationsReadRequest(ids?: string[]) {
  return api<void>('/api/notifications/read', {
    method: 'POST',
    json: { ids: ids ?? null },
  })
}

export async function listSystemNewsAdminRequest() {
  return api<ApiSystemNews[]>('/api/notifications/system-news')
}

export async function createSystemNewsRequest(payload: {
  title: string
  body: string
  send_push?: boolean
}) {
  return api<ApiSystemNews>('/api/notifications/system-news', {
    method: 'POST',
    json: payload,
  })
}

export async function deleteSystemNewsRequest(id: number) {
  return api<void>(`/api/notifications/system-news/${id}`, { method: 'DELETE' })
}
