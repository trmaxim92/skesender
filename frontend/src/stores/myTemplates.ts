import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  createMyTemplateCategoryRequest,
  createMyTemplateRequest,
  deleteMyTemplateCategoryRequest,
  deleteMyTemplateRequest,
  listMyTemplateCategoriesRequest,
  listMyTemplatesRequest,
  updateMyTemplateCategoryRequest,
  updateMyTemplateRequest,
  type ApiTemplate,
  type ApiTemplateCategory,
} from '@/api/cabinet'
import { ApiError } from '@/api/client'
import type {
  ChannelTransport,
  Template,
  TemplateCategory,
  TemplateGroup,
  TemplateKind,
} from '@/types'

function mapCategory(c: ApiTemplateCategory): TemplateCategory {
  return {
    id: String(c.id),
    name: c.name,
    sortOrder: c.sort_order,
    updatedAt: c.updated_at,
  }
}

function mapTemplate(t: ApiTemplate): Template {
  return {
    id: String(t.id),
    name: t.name,
    body: t.body,
    transport: t.transport,
    kind: t.kind ?? 'general',
    categoryId: t.category_id != null ? String(t.category_id) : null,
    categoryName: t.category_name ?? null,
    hasMedia: Boolean(t.has_media),
    mediaName: t.media_name ?? null,
    isMine: true,
    updatedAt: t.updated_at,
  }
}

/** Личные шаблоны менеджера (профиль). */
export const useMyTemplatesStore = defineStore('myTemplates', () => {
  const templates = ref<Template[]>([])
  const categories = ref<TemplateCategory[]>([])
  const loading = ref(false)
  const error = ref('')

  async function fetchAll() {
    loading.value = true
    error.value = ''
    try {
      const [tplList, catList] = await Promise.all([
        listMyTemplatesRequest(),
        listMyTemplateCategoriesRequest(),
      ])
      templates.value = tplList.map(mapTemplate)
      categories.value = catList.map(mapCategory)
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить шаблоны'
    } finally {
      loading.value = false
    }
  }

  async function addCategory(name: string) {
    try {
      const created = await createMyTemplateCategoryRequest({ name })
      const mapped = mapCategory(created)
      categories.value.push(mapped)
      categories.value.sort(
        (a, b) => a.sortOrder - b.sortOrder || a.name.localeCompare(b.name, 'ru'),
      )
      return mapped
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось создать категорию'
      return null
    }
  }

  async function renameCategory(id: string, name: string) {
    try {
      const updated = await updateMyTemplateCategoryRequest(Number(id), { name })
      const mapped = mapCategory(updated)
      categories.value = categories.value.map((c) => (c.id === id ? mapped : c))
      templates.value = templates.value.map((t) =>
        t.categoryId === id ? { ...t, categoryName: mapped.name } : t,
      )
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось обновить категорию'
      return false
    }
  }

  async function removeCategory(id: string) {
    try {
      await deleteMyTemplateCategoryRequest(Number(id))
      categories.value = categories.value.filter((c) => c.id !== id)
      templates.value = templates.value.map((t) =>
        t.categoryId === id ? { ...t, categoryId: null, categoryName: null } : t,
      )
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить категорию'
      return false
    }
  }

  async function addTemplate(payload: {
    name: string
    body: string
    transport: ChannelTransport | 'all'
    kind?: TemplateKind
    categoryId?: string | null
    media?: File | null
  }) {
    try {
      const form = new FormData()
      form.append('name', payload.name)
      form.append('body', payload.body)
      form.append('transport', payload.transport)
      form.append('kind', payload.kind ?? 'general')
      if (payload.categoryId) form.append('category_id', payload.categoryId)
      if (payload.media) form.append('media', payload.media)
      const created = await createMyTemplateRequest(form)
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
      name: string
      body: string
      transport: ChannelTransport | 'all'
      kind?: TemplateKind
      categoryId?: string | null
      media?: File | null
      clearMedia?: boolean
    },
  ) {
    try {
      const form = new FormData()
      form.append('name', payload.name)
      form.append('body', payload.body)
      form.append('transport', payload.transport)
      form.append('kind', payload.kind ?? 'general')
      form.append('category_id', payload.categoryId ?? '')
      if (payload.clearMedia) form.append('clear_media', 'true')
      if (payload.media) form.append('media', payload.media)
      const updated = await updateMyTemplateRequest(Number(id), form)
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
      await deleteMyTemplateRequest(Number(id))
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

  function forTransportGrouped(transport: ChannelTransport | null | undefined): TemplateGroup[] {
    const list = forTransport(transport)
    const byCat = new Map<string | null, Template[]>()
    for (const t of list) {
      const key = t.categoryId
      const arr = byCat.get(key) ?? []
      arr.push(t)
      byCat.set(key, arr)
    }

    const groups: TemplateGroup[] = []
    const orderedCats = [...categories.value].sort(
      (a, b) => a.sortOrder - b.sortOrder || a.name.localeCompare(b.name, 'ru'),
    )
    for (const cat of orderedCats) {
      const items = byCat.get(cat.id)
      if (items?.length) {
        groups.push({ categoryId: cat.id, categoryName: cat.name, templates: items })
        byCat.delete(cat.id)
      }
    }
    for (const [catId, items] of byCat) {
      if (!items.length) continue
      const name =
        catId == null ? 'Без категории' : items[0]?.categoryName || 'Без категории'
      groups.push({ categoryId: catId, categoryName: name, templates: items })
    }
    return groups
  }

  return {
    templates,
    categories,
    loading,
    error,
    fetchAll,
    addCategory,
    renameCategory,
    removeCategory,
    addTemplate,
    updateTemplate,
    removeTemplate,
    forTransport,
    forTransportGrouped,
  }
})
