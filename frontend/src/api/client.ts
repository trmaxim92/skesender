const API_BASE = import.meta.env.VITE_API_URL ?? ''

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

function getToken(): string | null {
  return localStorage.getItem('oe_access_token')
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem('oe_access_token', token)
  else localStorage.removeItem('oe_access_token')
}

/** Fired on authenticated 401 so the app can logout + redirect once. */
export const AUTH_EXPIRED_EVENT = 'oe:auth-expired'

export async function api<T>(
  path: string,
  options: RequestInit & { json?: unknown; auth?: boolean } = {},
): Promise<T> {
  const { json, auth = true, headers: initHeaders, ...rest } = options
  const headers = new Headers(initHeaders)
  if (json !== undefined) headers.set('Content-Type', 'application/json')
  if (auth) {
    const token = getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })

  if (response.status === 204) return undefined as T

  const text = await response.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }

  if (!response.ok) {
    if (response.status === 401 && auth) {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT))
    }
    const detail =
      typeof data === 'object' && data && 'detail' in data
        ? formatDetail((data as { detail: unknown }).detail)
        : `HTTP ${response.status}`
    throw new ApiError(response.status, detail)
  }

  return data as T
}

function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === 'object' && item && 'msg' in item) return String((item as { msg: string }).msg)
        return JSON.stringify(item)
      })
      .join('; ')
  }
  return 'Request failed'
}
