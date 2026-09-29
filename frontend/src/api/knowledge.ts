import { api } from '@/api/client'
import type { KbArticle, KbArticleSummary, KbFolderNode } from '@/types'

type ApiArticleSummary = {
  id: number
  folder_id: number
  title: string
  slug: string
  is_published: boolean
  updated_at: string
}

type ApiFolderNode = {
  id: number
  parent_id: number | null
  title: string
  icon: string | null
  sort_order: number
  articles: ApiArticleSummary[]
  children: ApiFolderNode[]
}

type ApiTree = { folders: ApiFolderNode[] }

type ApiArticle = {
  id: number
  folder_id: number
  title: string
  slug: string
  body_html: string
  is_published: boolean
  created_by_id: number | null
  created_by_name: string | null
  updated_by_id: number | null
  updated_by_name: string | null
  created_at: string
  updated_at: string
}

function mapSummary(a: ApiArticleSummary): KbArticleSummary {
  return {
    id: a.id,
    folderId: a.folder_id,
    title: a.title,
    slug: a.slug,
    isPublished: a.is_published,
    updatedAt: a.updated_at,
  }
}

function mapFolder(f: ApiFolderNode): KbFolderNode {
  return {
    id: f.id,
    parentId: f.parent_id,
    title: f.title,
    icon: f.icon,
    sortOrder: f.sort_order,
    articles: (f.articles ?? []).map(mapSummary),
    children: (f.children ?? []).map(mapFolder),
  }
}

function mapArticle(a: ApiArticle): KbArticle {
  return {
    id: a.id,
    folderId: a.folder_id,
    title: a.title,
    slug: a.slug,
    bodyHtml: a.body_html ?? '',
    isPublished: a.is_published,
    createdById: a.created_by_id,
    createdByName: a.created_by_name,
    updatedById: a.updated_by_id,
    updatedByName: a.updated_by_name,
    createdAt: a.created_at,
    updatedAt: a.updated_at,
  }
}

export async function fetchKnowledgeTree(): Promise<KbFolderNode[]> {
  const data = await api<ApiTree>('/api/knowledge/tree')
  return (data.folders ?? []).map(mapFolder)
}

export async function fetchKnowledgeArticle(id: number): Promise<KbArticle> {
  const data = await api<ApiArticle>(`/api/knowledge/articles/${id}`)
  return mapArticle(data)
}

export async function createKnowledgeFolder(payload: {
  title: string
  parentId?: number | null
  icon?: string | null
  sortOrder?: number
}): Promise<KbFolderNode> {
  const data = await api<ApiFolderNode>('/api/knowledge/folders', {
    method: 'POST',
    json: {
      title: payload.title,
      parent_id: payload.parentId ?? null,
      icon: payload.icon ?? null,
      sort_order: payload.sortOrder ?? 0,
    },
  })
  return mapFolder(data)
}

export async function updateKnowledgeFolder(
  id: number,
  payload: {
    title?: string
    parentId?: number | null
    icon?: string | null
    sortOrder?: number
  },
): Promise<KbFolderNode> {
  const body: Record<string, unknown> = {}
  if (payload.title !== undefined) body.title = payload.title
  if (payload.parentId !== undefined) body.parent_id = payload.parentId
  if (payload.icon !== undefined) body.icon = payload.icon
  if (payload.sortOrder !== undefined) body.sort_order = payload.sortOrder
  const data = await api<ApiFolderNode>(`/api/knowledge/folders/${id}`, {
    method: 'PATCH',
    json: body,
  })
  return mapFolder(data)
}

export async function deleteKnowledgeFolder(id: number): Promise<void> {
  await api(`/api/knowledge/folders/${id}`, { method: 'DELETE' })
}

export async function createKnowledgeArticle(payload: {
  folderId: number
  title: string
  bodyHtml?: string
  isPublished?: boolean
}): Promise<KbArticle> {
  const data = await api<ApiArticle>('/api/knowledge/articles', {
    method: 'POST',
    json: {
      folder_id: payload.folderId,
      title: payload.title,
      body_html: payload.bodyHtml ?? '',
      is_published: payload.isPublished ?? true,
    },
  })
  return mapArticle(data)
}

export async function updateKnowledgeArticle(
  id: number,
  payload: {
    folderId?: number
    title?: string
    bodyHtml?: string
    isPublished?: boolean
  },
): Promise<KbArticle> {
  const body: Record<string, unknown> = {}
  if (payload.folderId !== undefined) body.folder_id = payload.folderId
  if (payload.title !== undefined) body.title = payload.title
  if (payload.bodyHtml !== undefined) body.body_html = payload.bodyHtml
  if (payload.isPublished !== undefined) body.is_published = payload.isPublished
  const data = await api<ApiArticle>(`/api/knowledge/articles/${id}`, {
    method: 'PATCH',
    json: body,
  })
  return mapArticle(data)
}

export async function deleteKnowledgeArticle(id: number): Promise<void> {
  await api(`/api/knowledge/articles/${id}`, { method: 'DELETE' })
}

export async function reorderKnowledgeFolders(
  items: { id: number; parentId: number | null; sortOrder: number }[],
): Promise<KbFolderNode[]> {
  const data = await api<ApiTree>('/api/knowledge/folders/reorder', {
    method: 'POST',
    json: {
      items: items.map((i) => ({
        id: i.id,
        parent_id: i.parentId,
        sort_order: i.sortOrder,
      })),
    },
  })
  return (data.folders ?? []).map(mapFolder)
}

export type KbSearchHit = {
  id: number
  folderId: number
  title: string
  snippet: string
  isPublished: boolean
  updatedAt: string
}

export async function searchKnowledgeArticles(q: string): Promise<KbSearchHit[]> {
  const data = await api<{
    items: {
      id: number
      folder_id: number
      title: string
      snippet: string
      is_published: boolean
      updated_at: string
    }[]
  }>(`/api/knowledge/search?q=${encodeURIComponent(q)}`)
  return (data.items ?? []).map((i) => ({
    id: i.id,
    folderId: i.folder_id,
    title: i.title,
    snippet: i.snippet ?? '',
    isPublished: i.is_published,
    updatedAt: i.updated_at,
  }))
}

export async function uploadKnowledgeImage(file: File): Promise<{ url: string; fileName: string }> {
  const form = new FormData()
  form.append('file', file)
  const token = localStorage.getItem('oe_access_token')
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch('/api/knowledge/images', { method: 'POST', headers, body: form })
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
    const detail =
      typeof data === 'object' && data && 'detail' in data
        ? String((data as { detail: unknown }).detail)
        : `HTTP ${response.status}`
    throw new Error(detail)
  }
  const parsed = data as { url: string; file_name: string }
  return { url: parsed.url, fileName: parsed.file_name }
}
