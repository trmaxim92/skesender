import { api } from '@/api/client'
import type { Channel, ChannelTransport, ChannelStatus, PermissionCode, Role, User } from '@/types'

interface ApiUser {
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

interface ApiChannel {
  id: number
  name: string
  transport: ChannelTransport
  status: ChannelStatus
  identity: string
  external_id: string | null
  connected_at: string | null
  last_error: string | null
  created_at: string
  has_credentials: boolean
  department_id?: number | null
  department_name?: string | null
  public_key?: string | null
}

interface TokenResponse {
  access_token: string
  token_type: string
}

interface ChannelConnectResult {
  channel: ApiChannel
  bot: Record<string, unknown> | null
}

export function mapUser(u: ApiUser): User {
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

export function mapChannel(ch: ApiChannel): Channel {
  return {
    id: ch.id,
    name: ch.name,
    transport: ch.transport,
    status: ch.status,
    identity: ch.identity,
    unread: 0,
    connectedAt: ch.connected_at,
    lastError: ch.last_error,
    hasCredentials: ch.has_credentials,
    departmentId: ch.department_id ?? null,
    departmentName: ch.department_name ?? null,
    publicKey: ch.public_key ?? ch.external_id ?? null,
  }
}

export async function loginRequest(email: string, password: string) {
  return api<TokenResponse>('/api/auth/login', {
    method: 'POST',
    auth: false,
    json: { email, password },
  })
}

export async function meRequest() {
  return api<ApiUser>('/api/auth/me')
}

export async function updateMeRequest(name: string) {
  return api<ApiUser>('/api/auth/me', {
    method: 'PATCH',
    json: { name },
  })
}

export async function changePasswordRequest(currentPassword: string, newPassword: string) {
  return api<void>('/api/auth/me/password', {
    method: 'POST',
    json: { current_password: currentPassword, new_password: newPassword },
  })
}

export async function listChannelsRequest() {
  return api<ApiChannel[]>('/api/channels')
}

export async function connectMaxBotRequest(
  token: string,
  name?: string,
  departmentId?: number | null,
) {
  return api<ChannelConnectResult>('/api/channels/maxbot', {
    method: 'POST',
    json: { token, name: name || null, department_id: departmentId ?? null },
  })
}

export async function connectTelegramBotRequest(
  token: string,
  name?: string,
  departmentId?: number | null,
) {
  return api<ChannelConnectResult>('/api/channels/telegram', {
    method: 'POST',
    json: { token, name: name || null, department_id: departmentId ?? null },
  })
}

export async function connectWebchatRequest(name?: string, departmentId?: number | null) {
  return api<ChannelConnectResult>('/api/channels/webchat', {
    method: 'POST',
    json: { name: name || null, department_id: departmentId ?? null, allowed_origins: [] },
  })
}

export interface MaxQrStartResponse {
  channel: ApiChannel
  qr_url: string
  status: string
}

export interface MaxQrStatusResponse {
  channel_id: number
  status: string
  qr_url: string | null
  identity: string | null
  hint: string | null
  error: string | null
  channel: ApiChannel | null
}

export async function startMaxQrRequest(name?: string, departmentId?: number | null) {
  return api<MaxQrStartResponse>('/api/channels/max/qr/start', {
    method: 'POST',
    json: { name: name || null, department_id: departmentId ?? null },
  })
}

export async function startTelegramQrRequest(name?: string, departmentId?: number | null) {
  return api<MaxQrStartResponse>('/api/channels/tgapi/qr/start', {
    method: 'POST',
    json: { name: name || null, department_id: departmentId ?? null },
  })
}

export async function maxQrStatusRequest(channelId: number) {
  return api<MaxQrStatusResponse>(`/api/channels/${channelId}/qr/status`)
}

export async function maxQr2faRequest(channelId: number, password: string) {
  return api<MaxQrStatusResponse>(`/api/channels/${channelId}/qr/2fa`, {
    method: 'POST',
    json: { password },
  })
}

export async function deleteChannelRequest(id: number) {
  return api<void>(`/api/channels/${id}`, { method: 'DELETE' })
}
