import { api } from '@/api/client'
import type { AppealStatusDef } from '@/types'

export interface ApiAppealStatusDef {
  id: number
  name: string
  slug: string
  color: string
  sort_order: number
  is_system: boolean
  is_active: boolean
  is_terminal: boolean
  needs_callback: boolean
  counts_as_open: boolean
}

export function mapAppealStatusDef(s: ApiAppealStatusDef): AppealStatusDef {
  return {
    id: s.id,
    name: s.name,
    slug: s.slug,
    color: s.color,
    sortOrder: s.sort_order,
    isSystem: s.is_system,
    isActive: s.is_active,
    isTerminal: s.is_terminal,
    needsCallback: s.needs_callback,
    countsAsOpen: s.counts_as_open,
  }
}

export async function listAppealStatusesManageRequest() {
  return api<ApiAppealStatusDef[]>('/api/appeal-statuses/manage')
}

export async function listActiveAppealStatusesRequest() {
  return api<ApiAppealStatusDef[]>('/api/appeal-statuses/active')
}

export async function createAppealStatusRequest(payload: {
  name: string
  color?: string
  sort_order?: number
  is_terminal?: boolean
  needs_callback?: boolean
  counts_as_open?: boolean
  is_active?: boolean
}) {
  return api<ApiAppealStatusDef>('/api/appeal-statuses', { method: 'POST', json: payload })
}

export async function updateAppealStatusRequest(
  id: number,
  payload: {
    name?: string
    color?: string
    sort_order?: number
    is_terminal?: boolean
    needs_callback?: boolean
    counts_as_open?: boolean
    is_active?: boolean
  },
) {
  return api<ApiAppealStatusDef>(`/api/appeal-statuses/${id}`, { method: 'PATCH', json: payload })
}

export async function deleteAppealStatusRequest(id: number) {
  return api<void>(`/api/appeal-statuses/${id}`, { method: 'DELETE' })
}
