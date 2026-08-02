import { api } from '@/api/client'
import type { Department, FieldDefinition, FieldScope, FieldType } from '@/types'

export interface ApiDepartment {
  id: number
  name: string
  slug: string
  is_active: boolean
  member_ids: number[]
  channel_count: number
  created_at: string
}

export interface ApiFieldDefinition {
  id: number
  scope: FieldScope
  department_id: number | null
  key: string
  label: string
  field_type: FieldType
  options: string[]
  required: boolean
  sort_order: number
  is_system: boolean
  is_active: boolean
}

export function mapDepartment(d: ApiDepartment): Department {
  return {
    id: d.id,
    name: d.name,
    slug: d.slug,
    isActive: d.is_active,
    memberIds: d.member_ids ?? [],
    channelCount: d.channel_count ?? 0,
    createdAt: d.created_at,
  }
}

export function mapFieldDefinition(f: ApiFieldDefinition): FieldDefinition {
  return {
    id: f.id,
    scope: f.scope,
    departmentId: f.department_id,
    key: f.key,
    label: f.label,
    fieldType: f.field_type,
    options: f.options ?? [],
    required: f.required,
    sortOrder: f.sort_order,
    isSystem: f.is_system,
    isActive: f.is_active,
  }
}

export async function listDepartmentsRequest() {
  return api<ApiDepartment[]>('/api/departments')
}

export async function createDepartmentRequest(payload: { name: string; member_ids?: number[] }) {
  return api<ApiDepartment>('/api/departments', { method: 'POST', json: payload })
}

export async function updateDepartmentRequest(
  id: number,
  payload: { name?: string; is_active?: boolean; member_ids?: number[] },
) {
  return api<ApiDepartment>(`/api/departments/${id}`, { method: 'PATCH', json: payload })
}

export async function deleteDepartmentRequest(id: number) {
  return api<void>(`/api/departments/${id}`, { method: 'DELETE' })
}

export async function listFieldsRequest(params: {
  scope: FieldScope
  department_id?: number
  include_inactive?: boolean
}) {
  const q = new URLSearchParams({ scope: params.scope })
  if (params.department_id != null) q.set('department_id', String(params.department_id))
  if (params.include_inactive) q.set('include_inactive', 'true')
  return api<ApiFieldDefinition[]>(`/api/settings/fields?${q}`)
}

export async function createFieldRequest(payload: {
  scope: FieldScope
  department_id?: number | null
  key?: string
  label: string
  field_type: FieldType
  options?: string[]
  required?: boolean
  sort_order?: number
}) {
  return api<ApiFieldDefinition>('/api/settings/fields', { method: 'POST', json: payload })
}

export async function updateFieldRequest(
  id: number,
  payload: {
    label?: string
    field_type?: FieldType
    options?: string[]
    required?: boolean
    sort_order?: number
    is_active?: boolean
  },
) {
  return api<ApiFieldDefinition>(`/api/settings/fields/${id}`, { method: 'PATCH', json: payload })
}

export async function deleteFieldRequest(id: number) {
  return api<void>(`/api/settings/fields/${id}`, { method: 'DELETE' })
}

export async function updateChannelRequest(
  id: number,
  payload: { name?: string; department_id?: number; status?: string },
) {
  return api<{
    id: number
    name: string
    transport: string
    status: string
    identity: string
    department_id: number | null
    department_name: string | null
    connected_at: string | null
    last_error: string | null
    has_credentials: boolean
    public_key?: string | null
  }>(`/api/channels/${id}`, { method: 'PATCH', json: payload })
}
