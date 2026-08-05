import { api, ApiError } from '@/api/client'
import type {
  AccessRole,
  ChannelTransport,
  PermissionCatalogItem,
  PermissionCode,
  Role,
  User,
} from '@/types'

export interface ApiUser {
  id: number
  email: string
  name: string
  role: Role
  is_active?: boolean
  access_role_id?: number | null
  role_name?: string | null
  permissions?: string[]
  all_channels?: boolean
  channel_ids?: number[]
  department_ids?: number[]
}

export interface ApiAccessRole {
  id: number
  name: string
  slug: string
  is_system: boolean
  all_channels: boolean
  permissions: string[]
  channel_ids?: number[]
  created_at: string
}

export interface ApiTemplateCategory {
  id: number
  name: string
  sort_order: number
  created_at: string
  updated_at: string
}

export interface ApiTemplate {
  id: number
  name: string
  body: string
  transport: ChannelTransport | 'all'
  kind?: 'general' | 'appeal_closed'
  category_id?: number | null
  category_name?: string | null
  media_kind?: string | null
  media_name?: string | null
  mime_type?: string | null
  has_media?: boolean
  created_by_id?: number | null
  is_mine?: boolean
  created_at: string
  updated_at: string
}

export interface ApiWebhook {
  id: number
  url: string
  events: string[]
  active: boolean
  has_secret?: boolean
  created_at: string
}

export async function listUsersRequest(includeInactive = false) {
  const q = includeInactive ? '?include_inactive=true' : ''
  return api<ApiUser[]>(`/api/users${q}`)
}

export async function createUserRequest(payload: {
  name: string
  email: string
  password: string
  role?: Role
  access_role_id?: number | null
  channel_ids?: number[]
  department_ids?: number[]
}) {
  return api<ApiUser>('/api/users', { method: 'POST', json: payload })
}

export async function updateUserRequest(
  id: number,
  payload: {
    name?: string
    email?: string
    role?: Role
    access_role_id?: number | null
    channel_ids?: number[]
    department_ids?: number[]
    is_active?: boolean
    password?: string
  },
) {
  return api<ApiUser>(`/api/users/${id}`, { method: 'PATCH', json: payload })
}

export async function deleteUserRequest(id: number) {
  return api<void>(`/api/users/${id}`, { method: 'DELETE' })
}

export async function listRolesRequest() {
  return api<ApiAccessRole[]>('/api/roles')
}

export async function listPermissionCatalogRequest() {
  return api<Array<{ code: string; label: string }>>('/api/roles/permissions')
}

export async function createRoleRequest(payload: {
  name: string
  permissions: string[]
  all_channels: boolean
  channel_ids?: number[]
}) {
  return api<ApiAccessRole>('/api/roles', { method: 'POST', json: payload })
}

export async function updateRoleRequest(
  id: number,
  payload: {
    name?: string
    permissions?: string[]
    all_channels?: boolean
    channel_ids?: number[]
  },
) {
  return api<ApiAccessRole>(`/api/roles/${id}`, { method: 'PATCH', json: payload })
}

export async function deleteRoleRequest(id: number) {
  return api<void>(`/api/roles/${id}`, { method: 'DELETE' })
}

export async function listMyTemplateCategoriesRequest() {
  return api<ApiTemplateCategory[]>('/api/me/template-categories')
}

export async function createMyTemplateCategoryRequest(payload: {
  name: string
  sort_order?: number
}) {
  return api<ApiTemplateCategory>('/api/me/template-categories', {
    method: 'POST',
    json: payload,
  })
}

export async function updateMyTemplateCategoryRequest(
  id: number,
  payload: { name?: string; sort_order?: number },
) {
  return api<ApiTemplateCategory>(`/api/me/template-categories/${id}`, {
    method: 'PATCH',
    json: payload,
  })
}

export async function deleteMyTemplateCategoryRequest(id: number) {
  return api<void>(`/api/me/template-categories/${id}`, { method: 'DELETE' })
}

export async function listMyTemplatesRequest() {
  return api<ApiTemplate[]>('/api/me/templates')
}

export async function createMyTemplateRequest(form: FormData) {
  return api<ApiTemplate>('/api/me/templates', { method: 'POST', body: form })
}

export async function updateMyTemplateRequest(id: number, form: FormData) {
  return api<ApiTemplate>(`/api/me/templates/${id}`, { method: 'PATCH', body: form })
}

export async function deleteMyTemplateRequest(id: number) {
  return api<void>(`/api/me/templates/${id}`, { method: 'DELETE' })
}

export async function fetchMyTemplateMediaBlob(id: number): Promise<Blob> {
  const token = localStorage.getItem('oe_access_token')
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const base = import.meta.env.VITE_API_URL ?? ''
  const response = await fetch(`${base}/api/me/templates/${id}/media`, { headers })
  if (!response.ok) {
    throw new ApiError(response.status, `HTTP ${response.status}`)
  }
  return response.blob()
}

export async function listTemplatesRequest() {
  return api<ApiTemplate[]>('/api/templates')
}

export async function createTemplateRequest(payload: {
  name: string
  body: string
  transport: ChannelTransport | 'all'
  kind?: 'general' | 'appeal_closed'
}) {
  return api<ApiTemplate>('/api/templates', { method: 'POST', json: payload })
}

export async function updateTemplateRequest(
  id: number,
  payload: {
    name?: string
    body?: string
    transport?: ChannelTransport | 'all'
    kind?: 'general' | 'appeal_closed'
  },
) {
  return api<ApiTemplate>(`/api/templates/${id}`, { method: 'PATCH', json: payload })
}

export async function deleteTemplateRequest(id: number) {
  return api<void>(`/api/templates/${id}`, { method: 'DELETE' })
}

export async function listWebhooksRequest() {
  return api<ApiWebhook[]>('/api/webhooks')
}

export async function createWebhookRequest(payload: { url: string; events: string[]; secret?: string }) {
  return api<ApiWebhook>('/api/webhooks', { method: 'POST', json: payload })
}

export async function updateWebhookRequest(
  id: number,
  payload: { url?: string; events?: string[]; active?: boolean; secret?: string },
) {
  return api<ApiWebhook>(`/api/webhooks/${id}`, { method: 'PATCH', json: payload })
}

export async function deleteWebhookRequest(id: number) {
  return api<void>(`/api/webhooks/${id}`, { method: 'DELETE' })
}

export function mapApiUser(u: ApiUser): User {
  return {
    id: u.id,
    email: u.email,
    name: u.name,
    role: u.role,
    accessRoleId: u.access_role_id ?? null,
    roleName: u.role_name ?? null,
    permissions: (u.permissions ?? []) as PermissionCode[],
    allChannels: !!u.all_channels,
    channelIds: u.channel_ids ?? [],
    departmentIds: u.department_ids ?? [],
    isActive: u.is_active,
  }
}

export function mapApiRole(r: ApiAccessRole): AccessRole {
  return {
    id: r.id,
    name: r.name,
    slug: r.slug,
    isSystem: r.is_system,
    allChannels: r.all_channels,
    permissions: r.permissions as PermissionCode[],
    channelIds: r.channel_ids ?? [],
    createdAt: r.created_at,
  }
}

export function mapPermissionCatalog(items: Array<{ code: string; label: string }>): PermissionCatalogItem[] {
  return items.map((i) => ({ code: i.code as PermissionCode, label: i.label }))
}
