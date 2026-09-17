import { api } from '@/api/client'

export interface FleetStatus {
  configured: boolean
  clientId: string
  parkId: string
  apiKeyMasked: string
  hasApiKey: boolean
  credentialsSource: string
  syncEnabled: boolean
  intervalSec: number
  workStatuses: string
  lastStartedAt: string | null
  lastFinishedAt: string | null
  lastOk: boolean | null
  lastFetched: number
  lastCreated: number
  lastUpdated: number
  lastSkipped: number
  lastPurged: number
  lastError: string
}

export interface FleetSyncResult {
  fetched: number
  created: number
  updated: number
  skipped: number
  purged: number
  errors: string[]
}

interface ApiFleetStatus {
  configured: boolean
  client_id: string
  park_id: string
  api_key_masked: string
  has_api_key: boolean
  credentials_source: string
  sync_enabled: boolean
  interval_sec: number
  work_statuses: string
  last_started_at?: string | null
  last_finished_at?: string | null
  last_ok?: boolean | null
  last_fetched: number
  last_created: number
  last_updated: number
  last_skipped: number
  last_purged: number
  last_error?: string
}

function mapStatus(s: ApiFleetStatus): FleetStatus {
  return {
    configured: s.configured,
    clientId: s.client_id || '',
    parkId: s.park_id || '',
    apiKeyMasked: s.api_key_masked || '',
    hasApiKey: Boolean(s.has_api_key),
    credentialsSource: s.credentials_source || 'none',
    syncEnabled: s.sync_enabled,
    intervalSec: s.interval_sec,
    workStatuses: s.work_statuses || '',
    lastStartedAt: s.last_started_at ?? null,
    lastFinishedAt: s.last_finished_at ?? null,
    lastOk: s.last_ok ?? null,
    lastFetched: s.last_fetched || 0,
    lastCreated: s.last_created || 0,
    lastUpdated: s.last_updated || 0,
    lastSkipped: s.last_skipped || 0,
    lastPurged: s.last_purged || 0,
    lastError: s.last_error || '',
  }
}

export async function fleetStatusRequest() {
  const s = await api<ApiFleetStatus>('/api/fleet/status')
  return mapStatus(s)
}

export async function fleetUpdateSettingsRequest(payload: {
  sync_enabled?: boolean
  interval_sec?: number
  work_statuses?: string
  client_id?: string
  park_id?: string
  api_key?: string
}) {
  const s = await api<ApiFleetStatus>('/api/fleet/settings', {
    method: 'PATCH',
    json: payload,
  })
  return mapStatus(s)
}

export async function fleetSyncRequest(options?: { purge?: boolean }) {
  const purge = options?.purge ? 'true' : 'false'
  return api<FleetSyncResult>(`/api/fleet/sync?purge=${purge}`, { method: 'POST' })
}
