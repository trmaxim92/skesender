import { api } from '@/api/client'
import type { ApiUser } from '@/api/auth'
import type { PresenceEmployee, PresenceStatus } from '@/types'

export interface ApiPresenceStatus {
  id: number
  name: string
  slug: string
  color: string
  sort_order: number
  is_system: boolean
  is_active: boolean
  participates_in_routing: boolean
  can_write_chats: boolean
  on_duty: boolean
}

export interface ApiPresenceEmployee {
  id: number
  name: string
  email: string
  role_name: string | null
  department_ids: number[]
  is_active: boolean
  presence_status: ApiPresenceStatus | null
}

export function mapPresenceStatus(s: ApiPresenceStatus): PresenceStatus {
  return {
    id: s.id,
    name: s.name,
    slug: s.slug,
    color: s.color,
    sortOrder: s.sort_order,
    isSystem: s.is_system,
    isActive: s.is_active,
    participatesInRouting: s.participates_in_routing,
    canWriteChats: s.can_write_chats,
    onDuty: s.on_duty,
  }
}

export function mapPresenceEmployee(e: ApiPresenceEmployee): PresenceEmployee {
  return {
    id: e.id,
    name: e.name,
    email: e.email,
    roleName: e.role_name,
    departmentIds: e.department_ids ?? [],
    isActive: e.is_active,
    presenceStatus: e.presence_status ? mapPresenceStatus(e.presence_status) : null,
  }
}

export async function listPresenceStatusesRequest(includeInactive = false) {
  const q = includeInactive ? '?include_inactive=true' : ''
  return api<ApiPresenceStatus[]>(`/api/presence/statuses${q}`)
}

export async function listPresenceStatusesManageRequest() {
  return api<ApiPresenceStatus[]>('/api/presence/statuses/manage')
}

export async function createPresenceStatusRequest(payload: {
  name: string
  color?: string
  sort_order?: number
  participates_in_routing?: boolean
  can_write_chats?: boolean
  on_duty?: boolean
  is_active?: boolean
}) {
  return api<ApiPresenceStatus>('/api/presence/statuses', { method: 'POST', json: payload })
}

export async function updatePresenceStatusRequest(
  id: number,
  payload: {
    name?: string
    color?: string
    sort_order?: number
    participates_in_routing?: boolean
    can_write_chats?: boolean
    on_duty?: boolean
    is_active?: boolean
  },
) {
  return api<ApiPresenceStatus>(`/api/presence/statuses/${id}`, { method: 'PATCH', json: payload })
}

export async function deletePresenceStatusRequest(id: number) {
  return api<void>(`/api/presence/statuses/${id}`, { method: 'DELETE' })
}

export async function setMyPresenceRequest(presenceStatusId: number) {
  return api<ApiUser>('/api/presence/me', {
    method: 'PATCH',
    json: { presence_status_id: presenceStatusId },
  })
}

export async function listPresenceEmployeesRequest() {
  return api<ApiPresenceEmployee[]>('/api/presence/employees')
}
