import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  createKnowledgeArticle,
  createKnowledgeFolder,
  deleteKnowledgeArticle,
  deleteKnowledgeFolder,
  fetchKnowledgeArticle,
  fetchKnowledgeTree,
  updateKnowledgeArticle,
  updateKnowledgeFolder,
} from '@/api/knowledge'
import { ApiError } from '@/api/client'
import type { KbArticle, KbFolderNode } from '@/types'

function countArticles(nodes: KbFolderNode[]): number {
  let n = 0
  for (const f of nodes) {
    n += f.articles.length
    n += countArticles(f.children)
  }
  return n
}

export const useKnowledgeStore = defineStore('knowledge', () => {
  const folders = ref<KbFolderNode[]>([])
  const current = ref<KbArticle | null>(null)
  const loading = ref(false)
  const loadingArticle = ref(false)
  const saving = ref(false)
  const error = ref('')

  const isEmpty = computed(() => folders.value.length === 0)
  const articleCount = computed(() => countArticles(folders.value))

  async function fetchTree() {
    loading.value = true
    error.value = ''
    try {
      folders.value = await fetchKnowledgeTree()
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить базу знаний'
    } finally {
      loading.value = false
    }
  }

  async function loadArticle(id: number) {
    loadingArticle.value = true
    error.value = ''
    try {
      current.value = await fetchKnowledgeArticle(id)
      return current.value
    } catch (e) {
      current.value = null
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить статью'
      return null
    } finally {
      loadingArticle.value = false
    }
  }

  function clearArticle() {
    current.value = null
  }

  async function createFolder(title: string, parentId: number | null = null) {
    saving.value = true
    error.value = ''
    try {
      await createKnowledgeFolder({ title, parentId })
      await fetchTree()
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось создать раздел'
      return false
    } finally {
      saving.value = false
    }
  }

  async function renameFolder(id: number, title: string) {
    saving.value = true
    error.value = ''
    try {
      await updateKnowledgeFolder(id, { title })
      await fetchTree()
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось переименовать'
      return false
    } finally {
      saving.value = false
    }
  }

  async function removeFolder(id: number) {
    saving.value = true
    error.value = ''
    try {
      await deleteKnowledgeFolder(id)
      await fetchTree()
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить раздел'
      return false
    } finally {
      saving.value = false
    }
  }

  async function createArticle(folderId: number, title: string, bodyHtml = '') {
    saving.value = true
    error.value = ''
    try {
      const article = await createKnowledgeArticle({ folderId, title, bodyHtml })
      await fetchTree()
      current.value = article
      return article
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось создать статью'
      return null
    } finally {
      saving.value = false
    }
  }

  async function saveArticle(
    id: number,
    payload: { title?: string; bodyHtml?: string; isPublished?: boolean; folderId?: number },
  ) {
    saving.value = true
    error.value = ''
    try {
      const article = await updateKnowledgeArticle(id, payload)
      current.value = article
      await fetchTree()
      return article
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить статью'
      return null
    } finally {
      saving.value = false
    }
  }

  async function removeArticle(id: number) {
    saving.value = true
    error.value = ''
    try {
      await deleteKnowledgeArticle(id)
      if (current.value?.id === id) current.value = null
      await fetchTree()
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить статью'
      return false
    } finally {
      saving.value = false
    }
  }

  return {
    folders,
    current,
    loading,
    loadingArticle,
    saving,
    error,
    isEmpty,
    articleCount,
    fetchTree,
    loadArticle,
    clearArticle,
    createFolder,
    renameFolder,
    removeFolder,
    createArticle,
    saveArticle,
    removeArticle,
  }
})
