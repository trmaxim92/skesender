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
