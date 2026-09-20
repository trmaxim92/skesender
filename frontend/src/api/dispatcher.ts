import { api } from '@/api/client'
import type { ChannelTransport } from '@/types'

export type DispatcherCondition = {
  field: 'channel_id' | 'department_id' | 'transport'
  op: 'eq' | 'in' | 'neq'
  value: unknown
}

export type DispatcherAction = {
  type: 'send_reply'
  text: string
}

export type DispatcherRuleGroup = {
  id: number
  name: string
  active: boolean
  sortOrder: number
  rulesCount: number
  createdAt: string
  updatedAt: string
}

export type DispatcherRule = {
  id: number
  groupId: number
  name: string
  description: string
  active: boolean
  sortOrder: number
  trigger: 'appeal.opened' | string
  conditions: DispatcherCondition[]
  actions: DispatcherAction[]
  lastAppliedAt: string | null
  createdAt: string
  updatedAt: string
}

type ApiGroup = {
  id: number
  name: string
  active: boolean
  sort_order: number
  rules_count: number
  created_at: string
  updated_at: string
}

type ApiRule = {
  id: number
  group_id: number
  name: string
  description: string
  active: boolean
  sort_order: number
  trigger: string
  conditions: DispatcherCondition[]
  actions: DispatcherAction[]
  last_applied_at: string | null
  created_at: string
  updated_at: string
}

export function mapDispatcherGroup(g: ApiGroup): DispatcherRuleGroup {
  return {
    id: g.id,
    name: g.name,
    active: g.active,
    sortOrder: g.sort_order,
    rulesCount: g.rules_count,
    createdAt: g.created_at,
    updatedAt: g.updated_at,
  }
}

export function mapDispatcherRule(r: ApiRule): DispatcherRule {
  return {
    id: r.id,
    groupId: r.group_id,
    name: r.name,
    description: r.description || '',
    active: r.active,
    sortOrder: r.sort_order,
    trigger: r.trigger,
    conditions: r.conditions || [],
    actions: r.actions || [],
    lastAppliedAt: r.last_applied_at,
    createdAt: r.created_at,
    updatedAt: r.updated_at,
  }
}

export async function listDispatcherGroupsRequest() {
  return api<ApiGroup[]>('/api/dispatcher/groups')
}

export async function createDispatcherGroupRequest(body: {
  name: string
  active?: boolean
  sort_order?: number
}) {
  return api<ApiGroup>('/api/dispatcher/groups', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function updateDispatcherGroupRequest(
  id: number,
  body: { name: string; active: boolean; sort_order: number },
) {
  return api<ApiGroup>(`/api/dispatcher/groups/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function deleteDispatcherGroupRequest(id: number) {
  return api<void>(`/api/dispatcher/groups/${id}`, { method: 'DELETE' })
}

export async function listDispatcherRulesRequest(groupId?: number | null) {
  const q = groupId != null ? `?group_id=${groupId}` : ''
  return api<ApiRule[]>(`/api/dispatcher/rules${q}`)
}

export async function createDispatcherRuleRequest(body: {
  group_id: number
  name: string
  description?: string
  active?: boolean
  sort_order?: number
  trigger?: string
  conditions?: DispatcherCondition[]
  actions?: DispatcherAction[]
}) {
  return api<ApiRule>('/api/dispatcher/rules', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function updateDispatcherRuleRequest(
  id: number,
  body: {
    group_id: number
    name: string
    description?: string
    active: boolean
    sort_order: number
    trigger: string
    conditions: DispatcherCondition[]
    actions: DispatcherAction[]
  },
) {
  return api<ApiRule>(`/api/dispatcher/rules/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function deleteDispatcherRuleRequest(id: number) {
  return api<void>(`/api/dispatcher/rules/${id}`, { method: 'DELETE' })
}

export const DISPATCHER_TRIGGER_LABEL: Record<string, string> = {
  'appeal.opened': 'Новое обращение',
}

export type { ChannelTransport }
