import { api } from '@/api/client'
import type { AppealStatus, ChannelTransport } from '@/types'

export interface ApiAppealListItem {
  id: number
  dialog_id: number
  number: number
  status: AppealStatus
  opened_at: string
  closed_at: string | null
  closed_by_id: number | null
  closed_by_name: string | null
  contact_name: string
  contact_username: string | null
  contact_external_id: string | null
  contact_avatar_url: string | null
  channel_id: number
  channel_name: string | null
  transport: ChannelTransport | null
  assignee_id: number | null
  assignee_name: string | null
  last_message: string
  last_at: string
}

export interface ApiAppealList {
  items: ApiAppealListItem[]
  total: number
  limit: number
  offset: number
}

export interface ApiAppealDetail extends ApiAppealListItem {
  current_appeal_id: number | null
  current_appeal_status: AppealStatus | null
  can_open_in_chats: boolean
}

export interface AppealListParams {
  q?: string
  status?: 'all' | 'open' | 'closed'
  date_from?: string
  date_to?: string
  assignee?: 'all' | 'unassigned' | 'mine'
  limit?: number
  offset?: number
}

export async function listAppealsRequest(params: AppealListParams = {}) {
  const query = new URLSearchParams()
  if (params.q?.trim()) query.set('q', params.q.trim())
  if (params.status && params.status !== 'all') query.set('status', params.status)
  if (params.date_from) query.set('date_from', params.date_from)
  if (params.date_to) query.set('date_to', params.date_to)
  if (params.assignee && params.assignee !== 'all') query.set('assignee', params.assignee)
  query.set('limit', String(params.limit ?? 50))
  query.set('offset', String(params.offset ?? 0))
  return api<ApiAppealList>(`/api/appeals?${query}`)
}

export async function getAppealRequest(appealId: number) {
  return api<ApiAppealDetail>(`/api/appeals/${appealId}`)
}

export async function deleteAppealRequest(appealId: number) {
  return api<void>(`/api/appeals/${appealId}`, { method: 'DELETE' })
}
