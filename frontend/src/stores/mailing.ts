import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  createMailingCampaignRequest,
  createMailingTemplateRequest,
  deleteMailingTemplateRequest,
  getMailingCampaignRequest,
  listMailingCampaignsRequest,
  listMailingTemplatesRequest,
  mapMailingCampaign,
  mapMailingTemplate,
  pauseMailingCampaignRequest,
  startMailingCampaignRequest,
} from '@/api/mailing'
import { ApiError } from '@/api/client'

export type MailingTemplate = ReturnType<typeof mapMailingTemplate>
export type MailingCampaign = ReturnType<typeof mapMailingCampaign>

export const useMailingStore = defineStore('mailing', () => {
  const templates = ref<MailingTemplate[]>([])
  const campaigns = ref<MailingCampaign[]>([])
  const activeCampaign = ref<(MailingCampaign & {
    recipients: {
      id: number
      raw: string
      normalized: string
      kind: string
      status: string
      channelId: number | null
      error: string | null
      sentAt: string | null
    }[]
    recipientsTotal: number
  }) | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function fetchTemplates() {
    try {
      const list = await listMailingTemplatesRequest()
      templates.value = list.map(mapMailingTemplate)
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить шаблоны'
    }
  }

  async function fetchCampaigns() {
    loading.value = true
    error.value = ''
    try {
      const list = await listMailingCampaignsRequest()
      campaigns.value = list.map(mapMailingCampaign)
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить кампании'
    } finally {
      loading.value = false
    }
  }

  async function createTemplate(name: string, body: string, media: File | null) {
    error.value = ''
    const form = new FormData()
    form.append('name', name)
    form.append('body', body)
    if (media) form.append('media', media)
    try {
      const created = await createMailingTemplateRequest(form)
      templates.value.unshift(mapMailingTemplate(created))
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось создать шаблон'
      return false
    }
  }

  async function removeTemplate(id: number) {
    try {
      await deleteMailingTemplateRequest(id)
      templates.value = templates.value.filter((t) => t.id !== id)
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить шаблон'
    }
  }

  async function createCampaign(payload: {
    name: string
    templateId: number
    channelIds: number[]
    delaySec: number
    recipientsText: string
  }) {
    error.value = ''
    try {
      const created = await createMailingCampaignRequest({
        name: payload.name,
        template_id: payload.templateId,
        channel_ids: payload.channelIds,
        delay_sec: payload.delaySec,
        recipients_text: payload.recipientsText,
      })
      const mapped = mapMailingCampaign(created)
      campaigns.value.unshift(mapped)
      return mapped
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось создать кампанию'
      return null
    }
  }

  async function openCampaign(id: number) {
    try {
      const detail = await getMailingCampaignRequest(id)
      activeCampaign.value = {
        ...mapMailingCampaign(detail),
        recipients: detail.recipients.map((r) => ({
          id: r.id,
          raw: r.raw,
          normalized: r.normalized,
          kind: r.kind,
          status: r.status,
          channelId: r.channel_id,
          error: r.error,
          sentAt: r.sent_at,
        })),
        recipientsTotal: detail.recipients_total,
      }
      const idx = campaigns.value.findIndex((c) => c.id === id)
      if (idx >= 0) campaigns.value[idx] = mapMailingCampaign(detail)
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось открыть кампанию'
    }
  }

  async function startCampaign(id: number) {
    try {
      const updated = mapMailingCampaign(await startMailingCampaignRequest(id))
      const idx = campaigns.value.findIndex((c) => c.id === id)
      if (idx >= 0) campaigns.value[idx] = updated
      if (activeCampaign.value?.id === id) {
        activeCampaign.value = { ...activeCampaign.value, ...updated }
      }
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось запустить'
    }
  }

  async function pauseCampaign(id: number) {
    try {
      const updated = mapMailingCampaign(await pauseMailingCampaignRequest(id))
      const idx = campaigns.value.findIndex((c) => c.id === id)
      if (idx >= 0) campaigns.value[idx] = updated
      if (activeCampaign.value?.id === id) {
        activeCampaign.value = { ...activeCampaign.value, ...updated }
      }
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось поставить на паузу'
    }
  }

  return {
    templates,
    campaigns,
    activeCampaign,
    loading,
    error,
    fetchTemplates,
    fetchCampaigns,
    createTemplate,
    removeTemplate,
    createCampaign,
    openCampaign,
    startCampaign,
    pauseCampaign,
  }
})
