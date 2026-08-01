import { api } from '@/api/client'
import type { ChannelTransport } from '@/types'

export interface ApiMailingTemplate {
  id: number
  name: string
  body: string
  media_kind: 'image' | 'video' | null
  media_name: string | null
  mime_type: string | null
  has_media: boolean
  created_at: string
  updated_at: string
}

export interface ApiMailingCampaignChannel {
  channel_id: number
  channel_name: string | null
  transport: ChannelTransport | null
  identity: string | null
}

export interface ApiMailingRecipient {
  id: number
  raw: string
  normalized: string
  kind: string
  status: string
  channel_id: number | null
  error: string | null
  sent_at: string | null
}

export interface ApiMailingCampaign {
  id: number
  name: string
  template_id: number
  template_name: string | null
  status: string
  delay_sec: number
  total: number
  sent: number
  failed: number
  channels: ApiMailingCampaignChannel[]
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface ApiMailingCampaignDetail extends ApiMailingCampaign {
  recipients: ApiMailingRecipient[]
  recipients_total: number
}

export function mapMailingTemplate(t: ApiMailingTemplate) {
  return {
    id: t.id,
    name: t.name,
    body: t.body,
    mediaKind: t.media_kind,
    mediaName: t.media_name,
    mimeType: t.mime_type,
    hasMedia: t.has_media,
    createdAt: t.created_at,
    updatedAt: t.updated_at,
  }
}

export function mapMailingCampaign(c: ApiMailingCampaign) {
  return {
    id: c.id,
    name: c.name,
    templateId: c.template_id,
    templateName: c.template_name,
    status: c.status as 'draft' | 'running' | 'paused' | 'completed' | 'failed',
    delaySec: c.delay_sec,
    total: c.total,
    sent: c.sent,
    failed: c.failed,
    channels: c.channels.map((ch) => ({
      channelId: ch.channel_id,
      channelName: ch.channel_name,
      transport: ch.transport,
      identity: ch.identity,
    })),
    startedAt: c.started_at,
    finishedAt: c.finished_at,
    createdAt: c.created_at,
  }
}

export async function listMailingTemplatesRequest() {
  return api<ApiMailingTemplate[]>('/api/mailing/templates')
}

export async function createMailingTemplateRequest(form: FormData) {
  return api<ApiMailingTemplate>('/api/mailing/templates', { method: 'POST', body: form })
}

export async function deleteMailingTemplateRequest(id: number) {
  return api<void>(`/api/mailing/templates/${id}`, { method: 'DELETE' })
}

export async function listMailingCampaignsRequest() {
  return api<ApiMailingCampaign[]>('/api/mailing/campaigns')
}

export async function createMailingCampaignRequest(payload: {
  name: string
  template_id: number
  channel_ids: number[]
  delay_sec: number
  recipients_text: string
}) {
  return api<ApiMailingCampaign>('/api/mailing/campaigns', { method: 'POST', json: payload })
}

export async function getMailingCampaignRequest(id: number, limit = 50, offset = 0) {
  return api<ApiMailingCampaignDetail>(
    `/api/mailing/campaigns/${id}?limit=${limit}&offset=${offset}`,
  )
}

export async function startMailingCampaignRequest(id: number) {
  return api<ApiMailingCampaign>(`/api/mailing/campaigns/${id}/start`, { method: 'POST' })
}

export async function pauseMailingCampaignRequest(id: number) {
  return api<ApiMailingCampaign>(`/api/mailing/campaigns/${id}/pause`, { method: 'POST' })
}
