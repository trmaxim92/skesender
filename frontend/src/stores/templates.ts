import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, ApiError } from '@/api/client'
import type { ApiTemplate } from '@/api/cabinet'
import type { ChannelTransport, Template } from '@/types'

function mapTemplate(t: ApiTemplate): Template {
  return {
    id: String(t.id),
    name: t.name,
    body: t.body,
    transport: t.transport,
    kind: t.kind ?? 'appeal_closed',
    categoryId: null,
    categoryName: null,
    isMine: false,
    updatedAt: t.updated_at,
  }
}

/** System close-appeal template (single shared row). */
export const useTemplatesStore = defineStore('templates', () => {
  const closeTemplate = ref<Template | null>(null)
  const loading = ref(false)
  const error = ref('')
  const saving = ref(false)

  async function fetchCloseTemplate() {
    loading.value = true
    error.value = ''
    try {
      const row = await api<ApiTemplate>('/api/templates/close')
      closeTemplate.value = mapTemplate(row)
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить шаблон закрытия'
      closeTemplate.value = null
    } finally {
      loading.value = false
    }
  }

  async function saveCloseTemplate(payload: {
    name?: string
    body: string
    transport?: ChannelTransport | 'all'
  }) {
    saving.value = true
    error.value = ''
    try {
      const row = await api<ApiTemplate>('/api/templates/close', {
        method: 'PUT',
        json: payload,
      })
      closeTemplate.value = mapTemplate(row)
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить'
      return false
    } finally {
      saving.value = false
    }
  }

  function closeTemplateFor(transport: ChannelTransport | null | undefined) {
    const t = closeTemplate.value
    if (!t) return null
    if (t.transport === 'all' || t.transport === transport) return t
    return null
  }

  return {
    closeTemplate,
    loading,
    error,
    saving,
    fetchCloseTemplate,
    saveCloseTemplate,
    closeTemplateFor,
    /** @deprecated use fetchCloseTemplate */
    fetchTemplates: fetchCloseTemplate,
  }
})
