import { api } from '@/api/client'
import { mapAppealStatusDef, type ApiAppealStatusDef } from '@/api/appealStatuses'
import { mapFieldDefinition, type ApiFieldDefinition } from '@/api/settings'
import type {
  AppealStatus,
  AppealStatusDef,
  ContactCallOutcome,
  ContactStatus,
  FieldDefinition,
} from '@/types'

export interface ApiContactComment {
  id: number
  text: string
  author_id: number
  author_name?: string | null
  created_at: string
}

export interface ApiContactCallResult {
  id: number
  outcome: string
  note?: string
  author_id: number
  author_name?: string | null
  created_at: string
}

export interface ApiContactAppeal {
  id: number
  dialog_id?: number | null
  contact_id?: number | null
  number: number
  status: AppealStatus | string
  status_id?: number | null
  status_def?: ApiAppealStatusDef | null
  opened_at: string
  closed_at?: string | null
  closed_by_id?: number | null
  closed_by_name?: string | null
}

export interface ApiContact {
  id: number
  name: string
  phone: string
  status: ContactStatus | string
  assignee_id?: number | null
  assignee_name?: string | null
  department_id?: number | null
  created_by_id?: number | null
  last_outcome?: string | null
  last_outcome_at?: string | null
  created_at: string
  updated_at: string
  comments?: ApiContactComment[]
  call_results?: ApiContactCallResult[]
  client_fields?: ApiFieldDefinition[]
  client_values?: Record<string, string>
  appeal_fields?: ApiFieldDefinition[]
  appeal_values?: Record<string, string>
  current_appeal?: ApiContactAppeal | null
  appeal_statuses?: ApiAppealStatusDef[]
}

export interface ApiContactsPage {
  items: ApiContact[]
  total: number
  limit: number
  offset: number
}

export interface ContactCallResult {
  id: number
  outcome: ContactCallOutcome | string
  note: string
  authorId: number
  authorName: string | null
  createdAt: string
}

export interface ContactAppeal {
  id: number
  dialogId: number | null
  contactId: number | null
  number: number
  status: AppealStatus | string
  statusId: number | null
  statusDef: AppealStatusDef | null
  openedAt: string
  closedAt: string | null
  closedById: number | null
  closedByName: string | null
}

export interface Contact {
  id: number
  name: string
  phone: string
  status: ContactStatus
  assigneeId: number | null
  assigneeName: string | null
  departmentId: number | null
  createdById: number | null
  lastOutcome: ContactCallOutcome | string | null
  lastOutcomeAt: string | null
  createdAt: string
  updatedAt: string
  comments: ContactComment[]
  callResults: ContactCallResult[]
  clientFields: FieldDefinition[]
  clientValues: Record<string, string>
  appealFields: FieldDefinition[]
  appealValues: Record<string, string>
  currentAppeal: ContactAppeal | null
  appealStatuses: AppealStatusDef[]
}

export interface ContactComment {
  id: number
  text: string
  authorId: number
  authorName: string | null
  createdAt: string
}

export function mapComment(c: ApiContactComment): ContactComment {
  return {
    id: c.id,
    text: c.text,
    authorId: c.author_id,
    authorName: c.author_name ?? null,
    createdAt: c.created_at,
  }
}

function mapCallResult(r: ApiContactCallResult): ContactCallResult {
  return {
    id: r.id,
    outcome: r.outcome,
    note: r.note || '',
    authorId: r.author_id,
    authorName: r.author_name ?? null,
    createdAt: r.created_at,
  }
}

function mapContactAppeal(a: ApiContactAppeal): ContactAppeal {
  return {
    id: a.id,
    dialogId: a.dialog_id ?? null,
    contactId: a.contact_id ?? null,
    number: a.number,
    status: a.status,
    statusId: a.status_id ?? null,
    statusDef: a.status_def ? mapAppealStatusDef(a.status_def) : null,
    openedAt: a.opened_at,
    closedAt: a.closed_at ?? null,
    closedById: a.closed_by_id ?? null,
    closedByName: a.closed_by_name ?? null,
  }
}

export function mapContact(c: ApiContact): Contact {
  return {
    id: c.id,
    name: c.name || '',
    phone: c.phone,
    status: (c.status as ContactStatus) || 'new',
    assigneeId: c.assignee_id ?? null,
    assigneeName: c.assignee_name ?? null,
    departmentId: c.department_id ?? null,
    createdById: c.created_by_id ?? null,
    lastOutcome: c.last_outcome ?? null,
    lastOutcomeAt: c.last_outcome_at ?? null,
    createdAt: c.created_at,
    updatedAt: c.updated_at,
    comments: (c.comments || []).map(mapComment),
    callResults: (c.call_results || []).map(mapCallResult),
    clientFields: (c.client_fields || []).map(mapFieldDefinition),
    clientValues: { ...(c.client_values || {}) },
    appealFields: (c.appeal_fields || []).map(mapFieldDefinition),
    appealValues: { ...(c.appeal_values || {}) },
    currentAppeal: c.current_appeal ? mapContactAppeal(c.current_appeal) : null,
    appealStatuses: (c.appeal_statuses || []).map(mapAppealStatusDef),
  }
}

export type ContactFilter = 'all' | 'mine' | 'callback' | 'others'

export async function listContactsRequest(params: {
  q?: string
  filter?: ContactFilter
  limit?: number
  offset?: number
}) {
  const sp = new URLSearchParams()
  if (params.q) sp.set('q', params.q)
  if (params.filter) sp.set('filter', params.filter)
  if (params.limit != null) sp.set('limit', String(params.limit))
  if (params.offset != null) sp.set('offset', String(params.offset))
  const qs = sp.toString()
  const page = await api<ApiContactsPage>(`/api/contacts${qs ? `?${qs}` : ''}`)
  return {
    items: page.items.map(mapContact),
    total: page.total,
    limit: page.limit,
    offset: page.offset,
  }
}

export async function contactsSummaryRequest() {
  return api<{ all: number; mine: number; callback: number }>('/api/contacts/summary')
}

export async function claimNextContactRequest() {
  const c = await api<ApiContact>('/api/contacts/next', { method: 'POST' })
  return mapContact(c)
}

export async function claimContactsBatchRequest(contactIds: number[]) {
  const res = await api<{
    claimed: ApiContact[]
    skipped: { id: number; reason: string }[]
  }>('/api/contacts/claim-batch', {
    method: 'POST',
    json: { contact_ids: contactIds },
  })
  return {
    claimed: res.claimed.map(mapContact),
    skipped: res.skipped || [],
  }
}

export async function getContactRequest(id: number) {
  const c = await api<ApiContact>(`/api/contacts/${id}`)
  return mapContact(c)
}

export async function createContactRequest(payload: { name: string; phone: string }) {
  const c = await api<ApiContact>('/api/contacts', { method: 'POST', json: payload })
  return mapContact(c)
}

export async function updateContactRequest(
  id: number,
  payload: { name?: string; phone?: string; status?: ContactStatus },
) {
  const c = await api<ApiContact>(`/api/contacts/${id}`, { method: 'PATCH', json: payload })
  return mapContact(c)
}

export async function updateContactFieldsRequest(
  id: number,
  payload: {
    full_name?: string
    phone?: string
    external_id?: string
    values: { key: string; value: string }[]
    appeal_values?: { key: string; value: string }[]
    department_id?: number | null
  },
) {
  const c = await api<ApiContact>(`/api/contacts/${id}/fields`, {
    method: 'PATCH',
    json: payload,
  })
  return mapContact(c)
}

export async function claimContactRequest(id: number) {
  const c = await api<ApiContact>(`/api/contacts/${id}/claim`, { method: 'POST' })
  return mapContact(c)
}

export async function setContactOutcomeRequest(
  id: number,
  payload: { outcome: ContactCallOutcome; note?: string },
) {
  const c = await api<ApiContact>(`/api/contacts/${id}/outcome`, {
    method: 'POST',
    json: payload,
  })
  return mapContact(c)
}

export async function setContactAppealStatusRequest(id: number, statusId: number) {
  const c = await api<ApiContact>(`/api/contacts/${id}/appeal/status`, {
    method: 'PATCH',
    json: { status_id: statusId },
  })
  return mapContact(c)
}

export async function openContactAppealRequest(id: number) {
  const c = await api<ApiContact>(`/api/contacts/${id}/appeal`, { method: 'POST' })
  return mapContact(c)
}

export async function addContactCommentRequest(id: number, text: string) {
  const c = await api<ApiContactComment>(`/api/contacts/${id}/comments`, {
    method: 'POST',
    json: { text },
  })
  return mapComment(c)
}

export async function importContactsRequest(file: File) {
  const form = new FormData()
  form.append('file', file)
  return api<{ created: number; skipped: number; errors: string[] }>('/api/contacts/import', {
    method: 'POST',
    body: form,
  })
}

export async function syncContactsFromFleetRequest(options?: { purge?: boolean }) {
  const purge = options?.purge ? 'true' : 'false'
  return api<{
    fetched: number
    created: number
    updated: number
    skipped: number
    purged: number
    errors: string[]
  }>(`/api/contacts/sync/fleet?purge=${purge}`, { method: 'POST' })
}

export async function sendContactMessageRequest(
  id: number,
  payload: { channel_id: number; text: string },
) {
  return api<{ dialog: { id: number }; message: { id: number } }>(`/api/contacts/${id}/message`, {
    method: 'POST',
    json: payload,
  })
}

/** Opens the OS/SIP dialer via tel: (softphones usually intercept this). */
export function telHref(phone: string): string {
  const digits = phone.replace(/[^\d+]/g, '')
  return `tel:${digits}`
}
