import { api, ApiError, AUTH_EXPIRED_EVENT } from '@/api/client'
import type { ChannelTransport, Role } from '@/types'

export interface ApiAttachment {
  id: number
  kind: 'image' | 'video' | 'audio' | 'file'
  file_name: string
  mime_type: string | null
  size_bytes: number | null
  url: string
}

export interface ApiDialog {
  id: number
  channel_id: number
  contact_name: string
  contact_phone: string | null
  contact_username: string | null
  contact_avatar_url?: string | null
  last_message: string
  last_at: string
  last_direction?: 'in' | 'out' | null
  last_status?: 'sent' | 'delivered' | 'read' | 'failed' | null
  unread: number
  assignee_id: number | null
  transport: ChannelTransport | null
  appeal_id?: number | null
  appeal_number?: number | null
  appeal_status?: 'open' | 'closed' | null
  department_id?: number | null
}

export interface ApiAppeal {
  id: number
  dialog_id: number
  number: number
  status: 'open' | 'closed'
  opened_at: string
  closed_at: string | null
  closed_by_id: number | null
  closed_by_name: string | null
}

export interface ApiDialogSidebar {
  client: {
    contact_name: string
    contact_username: string | null
    contact_avatar_url?: string | null
    contact_external_id: string | null
    contact_phone: string | null
    channel_id: number
    transport: ChannelTransport | null
    channel_name: string | null
    dialog_created_at: string
    appeals_count: number
    assignee_id?: number | null
    assignee_name?: string | null
    department_id?: number | null
  }
  current_appeal: ApiAppeal | null
  appeals: ApiAppeal[]
  client_fields?: Array<{
    id: number
    scope: 'client' | 'appeal'
    department_id: number | null
    key: string
    label: string
    field_type: string
    options: string[]
    required: boolean
    sort_order: number
    is_system: boolean
    is_active: boolean
  }>
  appeal_fields?: ApiDialogSidebar['client_fields']
  client_values?: Record<string, string>
  appeal_values?: Record<string, string>
}

export interface ApiMessage {
  id: number
  dialog_id: number
  direction: 'in' | 'out'
  text: string
  status: 'sent' | 'delivered' | 'read' | 'failed'
  operator_name: string | null
  created_at: string
  edited_at?: string | null
  deleted_at?: string | null
  is_internal?: boolean
  appeal_id?: number | null
  attachments?: ApiAttachment[]
  reply_to?: {
    id: number
    text: string
    direction: 'in' | 'out'
    operator_name: string | null
  } | null
}

export async function listDialogsRequest(
  filter: 'new' | 'mine' | 'others' | 'all' = 'new',
  q: string = '',
  opts: { limit?: number; offset?: number; channelId?: number | null } = {},
) {
  const params = new URLSearchParams({ filter, appeal_status: 'open' })
  const needle = q.trim()
  if (needle) params.set('q', needle)
  if (opts.channelId != null) params.set('channel_id', String(opts.channelId))
  params.set('limit', String(opts.limit ?? 50))
  params.set('offset', String(opts.offset ?? 0))
  return api<{ items: ApiDialog[]; has_more: boolean; limit: number; offset: number }>(
    `/api/chats/dialogs?${params}`,
  )
}

export async function unreadSummaryRequest() {
  return api<{ new: number; mine: number; others: number }>('/api/chats/unread-summary')
}

export async function listMessagesRequest(
  dialogId: number,
  opts: { limit?: number; beforeId?: number; appealId?: number | null } = {},
) {
  const params = new URLSearchParams()
  params.set('limit', String(opts.limit ?? 50))
  if (opts.beforeId != null) params.set('before_id', String(opts.beforeId))
  if (opts.appealId != null) params.set('appeal_id', String(opts.appealId))
  return api<{ items: ApiMessage[]; has_more: boolean }>(
    `/api/chats/dialogs/${dialogId}/messages?${params}`,
  )
}

export async function listDialogAppealsRequest(dialogId: number) {
  return api<ApiAppeal[]>(`/api/chats/dialogs/${dialogId}/appeals`)
}

export async function sendMessageRequest(
  dialogId: number,
  text: string,
  files: File[] = [],
  replyToMessageId?: number | null,
): Promise<{ message: ApiMessage; warning?: string }> {
  const form = new FormData()
  form.append('text', text)
  if (replyToMessageId != null) {
    form.append('reply_to_message_id', String(replyToMessageId))
  }
  for (const file of files) {
    form.append('files', file)
  }
  const token = localStorage.getItem('oe_access_token')
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`/api/chats/dialogs/${dialogId}/messages`, {
    method: 'POST',
    headers,
    body: form,
  })
  const raw = await response.text()
  let data: unknown = null
  if (raw) {
    try {
      data = JSON.parse(raw)
    } catch {
      data = raw
    }
  }
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT))
    }
    const detail =
      typeof data === 'object' && data && 'detail' in data
        ? String((data as { detail: unknown }).detail)
        : `HTTP ${response.status}`
    throw new ApiError(response.status, detail)
  }
  const warning = response.headers.get('X-SkySender-Warning') || undefined
  return { message: data as ApiMessage, warning }
}

export async function createNoteRequest(
  dialogId: number,
  text: string,
  appealId?: number | null,
) {
  return api<ApiMessage>(`/api/chats/dialogs/${dialogId}/notes`, {
    method: 'POST',
    json: {
      text,
      ...(appealId != null ? { appeal_id: appealId } : {}),
    },
  })
}

export async function startChatRequest(payload: {
  channel_id: number
  recipient: string
  text: string
}) {
  return api<{ dialog: ApiDialog; message: ApiMessage }>('/api/chats/start', {
    method: 'POST',
    json: payload,
  })
}

export async function editMessageRequest(dialogId: number, messageId: number, text: string) {
  return api<ApiMessage>(`/api/chats/dialogs/${dialogId}/messages/${messageId}`, {
    method: 'PATCH',
    json: { text },
  })
}

export async function deleteMessageRequest(dialogId: number, messageId: number) {
  return api<ApiMessage>(`/api/chats/dialogs/${dialogId}/messages/${messageId}`, {
    method: 'DELETE',
  })
}

export async function assignDialogRequest(dialogId: number, assigneeId: number | null) {
  return api<ApiDialog>(`/api/chats/dialogs/${dialogId}/assign`, {
    method: 'PATCH',
    json: { assignee_id: assigneeId },
  })
}

export async function markDialogReadRequest(dialogId: number) {
  return api<ApiDialog>(`/api/chats/dialogs/${dialogId}/read`, { method: 'POST' })
}

export async function closeDialogRequest(
  dialogId: number,
  withReply = true,
): Promise<{ dialog: ApiDialog; warning?: string }> {
  const params = new URLSearchParams({ with_reply: withReply ? 'true' : 'false' })
  const token = localStorage.getItem('oe_access_token')
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`/api/chats/dialogs/${dialogId}/close?${params}`, {
    method: 'POST',
    headers,
  })
  const raw = await response.text()
  let data: unknown = null
  if (raw) {
    try {
      data = JSON.parse(raw)
    } catch {
      data = raw
    }
  }
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT))
    }
    const detail =
      typeof data === 'object' && data && 'detail' in data
        ? String((data as { detail: unknown }).detail)
        : `HTTP ${response.status}`
    throw new ApiError(response.status, detail)
  }
  const warning = response.headers.get('X-SkySender-Warning') || undefined
  return { dialog: data as ApiDialog, warning }
}

export async function fetchSidebarRequest(dialogId: number) {
  return api<ApiDialogSidebar>(`/api/chats/dialogs/${dialogId}/sidebar`)
}

export async function updateClientFieldsRequest(
  dialogId: number,
  payload: {
    full_name?: string | null
    phone?: string | null
    external_id?: string | null
    values?: Array<{ key: string; value: string }>
  },
) {
  return api<ApiDialogSidebar>(`/api/chats/dialogs/${dialogId}/client-fields`, {
    method: 'PATCH',
    json: payload,
  })
}

export async function updateAppealFieldsRequest(
  appealId: number,
  payload: { values: Array<{ key: string; value: string }> },
) {
  return api<ApiDialogSidebar>(`/api/chats/appeals/${appealId}/fields`, {
    method: 'PATCH',
    json: payload,
  })
}

export async function listUsersRequest() {
  return api<
    Array<{
      id: number
      email: string
      name: string
      role: Role
      department_ids?: number[]
      all_channels?: boolean
    }>
  >('/api/users')
}

export { mapApiUser } from '@/api/cabinet'

export function attachmentUrl(path: string): string {
  // Keep path only — JWT must not appear in query (img/proxy logs).
  // Use resolveAuthMediaUrl / AuthMedia for authenticated loading.
  return path.split('?')[0] || path
}
