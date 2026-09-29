import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  createKnowledgeArticle,
  createKnowledgeFolder,
  deleteKnowledgeArticle,
  deleteKnowledgeFolder,
  fetchKnowledgeArticle,
  fetchKnowledgeTree,
  reorderKnowledgeFolders,
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

function findFolder(nodes: KbFolderNode[], id: number): KbFolderNode | null {
  for (const n of nodes) {
    if (n.id === id) return n
    const nested = findFolder(n.children, id)
    if (nested) return nested
  }
  return null
}

function siblingsOf(nodes: KbFolderNode[], folderId: number): KbFolderNode[] | null {
  for (const n of nodes) {
    if (n.id === folderId) return nodes
    const nested = siblingsOf(n.children, folderId)
    if (nested) return nested
  }
  return null
}

function flattenFolders(
  nodes: KbFolderNode[],
  depth = 0,
): { id: number; title: string; depth: number }[] {
  const out: { id: number; title: string; depth: number }[] = []
  for (const n of nodes) {
    out.push({ id: n.id, title: n.title, depth })
    out.push(...flattenFolders(n.children, depth + 1))
  }
  return out
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
  const flatFolderOptions = computed(() => flattenFolders(folders.value))

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
      const siblings =
        parentId == null
          ? folders.value
          : (findFolder(folders.value, parentId)?.children ?? [])
      const sortOrder = siblings.length
        ? Math.max(...siblings.map((s) => s.sortOrder)) + 1
        : 0
      await createKnowledgeFolder({ title, parentId, sortOrder })
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

  async function moveFolder(id: number, direction: 'up' | 'down') {
    const siblings = siblingsOf(folders.value, id)
    if (!siblings || siblings.length < 2) return false
    const idx = siblings.findIndex((s) => s.id === id)
    if (idx < 0) return false
    const swapWith = direction === 'up' ? idx - 1 : idx + 1
    if (swapWith < 0 || swapWith >= siblings.length) return false

    saving.value = true
    error.value = ''
    try {
      const reindexed = [...siblings]
      ;[reindexed[idx], reindexed[swapWith]] = [reindexed[swapWith], reindexed[idx]]
      folders.value = await reorderKnowledgeFolders(
        reindexed.map((s, i) => ({
          id: s.id,
          parentId: s.parentId,
          sortOrder: i,
        })),
      )
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось изменить порядок'
      return false
    } finally {
      saving.value = false
    }
  }

  function canMoveFolder(id: number, direction: 'up' | 'down') {
    const siblings = siblingsOf(folders.value, id)
    if (!siblings) return false
    const idx = siblings.findIndex((s) => s.id === id)
    if (idx < 0) return false
    return direction === 'up' ? idx > 0 : idx < siblings.length - 1
  }

  async function createArticle(
    folderId: number,
    title: string,
    bodyHtml = '',
    isPublished = true,
  ) {
    saving.value = true
    error.value = ''
    try {
      const article = await createKnowledgeArticle({
        folderId,
        title,
        bodyHtml,
        isPublished,
      })
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
    flatFolderOptions,
    fetchTree,
    loadArticle,
    clearArticle,
    createFolder,
    renameFolder,
    removeFolder,
    moveFolder,
    canMoveFolder,
    createArticle,
    saveArticle,
    removeArticle,
  }
})
