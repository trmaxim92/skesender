/** Authenticated media URLs without putting JWT in query strings. */

const blobCache = new Map<string, string>()
const inflight = new Map<string, Promise<string>>()

function cleanPath(path: string): string {
  const bare = path.split('?')[0] || path
  return bare
}

export function attachmentPath(path: string): string {
  return cleanPath(path)
}

export async function resolveAuthMediaUrl(path: string): Promise<string> {
  const key = cleanPath(path)
  const cached = blobCache.get(key)
  if (cached) return cached

  const pending = inflight.get(key)
  if (pending) return pending

  const job = (async () => {
    const token = localStorage.getItem('oe_access_token')
    const headers = new Headers()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const response = await fetch(key, { headers })
    if (!response.ok) {
      throw new Error(`Media HTTP ${response.status}`)
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    blobCache.set(key, url)
    return url
  })()

  inflight.set(key, job)
  try {
    return await job
  } finally {
    inflight.delete(key)
  }
}

export function revokeAuthMediaUrl(path: string) {
  const key = cleanPath(path)
  const url = blobCache.get(key)
  if (url) {
    URL.revokeObjectURL(url)
    blobCache.delete(key)
  }
}

export async function downloadAuthFile(path: string, fileName?: string) {
  const url = await resolveAuthMediaUrl(path)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName || 'file'
  a.target = '_blank'
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}
