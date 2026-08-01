import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  createTemplateRequest,
  deleteTemplateRequest,
  listTemplatesRequest,
  updateTemplateRequest,
  type ApiTemplate,
} from '@/api/cabinet'
import { ApiError } from '@/api/client'
import type { ChannelTransport, Template, TemplateKind } from '@/types'

function mapTemplate(t: ApiTemplate): Template {
  return {
    id: String(t.id),
    name: t.name,
    body: t.body,
    transport: t.transport,
    kind: t.kind ?? 'general',
    categoryId: null,
    categoryName: null,
    isMine: false,
    updatedAt: t.updated_at,
  }
}

/** Общие шаблоны раздела «Шаблоны». */
export const useTemplatesStore = defineStore('templates', () => {
  const templates = ref<Template[]>([])
  const loading = ref(false)
  const error = ref('')

  async function fetchTemplates() {
    loading.value = true
    error.value = ''
    try {
      const list = await listTemplatesRequest()
      templates.value = list.map(mapTemplate)
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить шаблоны'
    } finally {
      loading.value = false
    }
  }

  async function addTemplate(
    name: string,
    body: string,
    transport: ChannelTransport | 'all',
    kind: TemplateKind = 'general',
  ) {
    try {
      const created = await createTemplateRequest({ name, body, transport, kind })
      templates.value.unshift(mapTemplate(created))
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить'
      return false
    }
  }

  async function updateTemplate(
    id: string,
    payload: {
      name?: string
      body?: string
      transport?: ChannelTransport | 'all'
      kind?: TemplateKind
    },
  ) {
    try {
      const updated = await updateTemplateRequest(Number(id), payload)
      const mapped = mapTemplate(updated)
      templates.value = templates.value.map((t) => (t.id === id ? mapped : t))
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить'
      return false
    }
  }

  async function removeTemplate(id: string) {
    try {
      await deleteTemplateRequest(Number(id))
      templates.value = templates.value.filter((t) => t.id !== id)
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить'
    }
  }

  function forTransport(transport: ChannelTransport | null | undefined) {
    return templates.value.filter(
      (t) => t.kind === 'general' && (t.transport === 'all' || t.transport === transport),
    )
  }

  function closeTemplateFor(transport: ChannelTransport | null | undefined) {
    const list = templates.value.filter(
      (t) => t.kind === 'appeal_closed' && (t.transport === 'all' || t.transport === transport),
    )
    return list[0] ?? null
  }

  return {
    templates,
    loading,
    error,
    fetchTemplates,
    addTemplate,
    updateTemplate,
    removeTemplate,
    forTransport,
    closeTemplateFor,
  }
})
