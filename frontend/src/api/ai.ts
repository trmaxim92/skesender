import { api } from '@/api/client'

export type ApiAiProfile = {
  id: number | null
  department_id: number
  enabled: boolean
  mode: string
  system_prompt: string
  auto_confidence_min: number
  max_auto_replies_per_dialog: number
  gigachat_model: string
  primary_intents: string
}

export type ApiAiSuggestion = {
  id: number
  dialog_id: number
  message_id: number
  department_id: number | null
  status: string
  draft_text: string
  confidence: number
  intent: string | null
  needs_human: boolean
  sources_json: string
  auto_sent_message_id: number | null
  created_at: string
  resolved_at: string | null
}

export type ApiAiLearning = {
  id: number
  department_id: number
  dialog_id: number | null
  suggestion_id: number | null
  user_question: string
  operator_answer: string
  quality: string
  status: string
  created_at: string
  reviewed_at: string | null
}

export type ApiAiMetrics = {
  department_id: number
  suggestions_total: number
  pending: number
  accepted: number
  edited: number
  rejected: number
  auto_sent: number
  learning_pending: number
  learning_approved: number
}

export type ApiAiStatus = {
  ai_enabled: boolean
  gigachat_configured: boolean
  gigachat_ping: { ok: boolean; detail: string } | null
}

export type ApiAiGlobalSettings = {
  enabled: boolean
  client_id: string
  client_secret_set: boolean
  scope: string
  auth_url: string
  api_base: string
  default_model: string
  verify_ssl: boolean
  temperature: number
  max_tokens: number
  repetition_penalty: number
  max_reply_words: number
  require_rag_for_auto: boolean
  updated_at: string | null
}

export async function fetchAiStatus(ping = false) {
  return api<ApiAiStatus>(`/api/ai/status?ping=${ping ? 'true' : 'false'}`)
}

export async function fetchAiGlobalSettings() {
  return api<ApiAiGlobalSettings>('/api/ai/settings')
}

export async function saveAiGlobalSettings(payload: {
  enabled?: boolean
  client_id?: string
  client_secret?: string
  clear_secret?: boolean
  scope?: string
  auth_url?: string
  api_base?: string
  default_model?: string
  verify_ssl?: boolean
  temperature?: number
  max_tokens?: number
  repetition_penalty?: number
  max_reply_words?: number
  require_rag_for_auto?: boolean
}) {
  return api<ApiAiGlobalSettings>('/api/ai/settings', {
    method: 'PUT',
    json: payload,
  })
}

export async function fetchAiProfile(departmentId: number) {
  return api<ApiAiProfile>(`/api/ai/departments/${departmentId}/profile`)
}

export async function saveAiProfile(
  departmentId: number,
  payload: Partial<ApiAiProfile>,
) {
  return api<ApiAiProfile>(`/api/ai/departments/${departmentId}/profile`, {
    method: 'PUT',
    json: payload,
  })
}

export async function listDialogSuggestions(dialogId: number, status?: string) {
  const q = status ? `?status_filter=${encodeURIComponent(status)}` : ''
  return api<ApiAiSuggestion[]>(`/api/ai/dialogs/${dialogId}/suggestions${q}`)
}

export async function acceptAiSuggestion(
  suggestionId: number,
  editedText?: string,
) {
  return api<ApiAiSuggestion>(`/api/ai/suggestions/${suggestionId}/accept`, {
    method: 'POST',
    json: editedText != null ? { edited_text: editedText } : {},
  })
}

export async function rejectAiSuggestion(suggestionId: number) {
  return api<ApiAiSuggestion>(`/api/ai/suggestions/${suggestionId}/reject`, {
    method: 'POST',
  })
}

export async function listLearningExamples(
  departmentId: number,
  status = 'pending_review',
) {
  const q = status ? `?status_filter=${encodeURIComponent(status)}` : ''
  return api<ApiAiLearning[]>(`/api/ai/departments/${departmentId}/learning${q}`)
}

export async function reviewLearningExample(
  exampleId: number,
  status: 'approved' | 'rejected',
) {
  return api<ApiAiLearning>(`/api/ai/learning/${exampleId}/review`, {
    method: 'POST',
    json: { status },
  })
}

export async function fetchAiMetrics(departmentId: number) {
  return api<ApiAiMetrics>(`/api/ai/departments/${departmentId}/metrics`)
}
