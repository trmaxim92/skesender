/** Dynamic unread count on the browser tab favicon. */

const DEFAULT_HREF = '/favicon.svg'
const DEFAULT_TYPE = 'image/svg+xml'

let basePromise: Promise<HTMLImageElement> | null = null
let lastApplied: number | null = null

function loadBaseIcon(): Promise<HTMLImageElement> {
  if (!basePromise) {
    basePromise = new Promise((resolve, reject) => {
      const img = new Image()
      img.decoding = 'async'
      img.onload = () => resolve(img)
      img.onerror = () => reject(new Error('favicon load failed'))
      img.src = DEFAULT_HREF
    }).catch((err) => {
      basePromise = null
      throw err
    })
  }
  return basePromise
}

function setIconLink(href: string, type: string) {
  if (typeof document === 'undefined') return
  const existing = document.querySelector<HTMLLinkElement>("link[rel='icon']")
  const link = document.createElement('link')
  link.rel = 'icon'
  link.type = type
  link.href = href
  if (existing) existing.replaceWith(link)
  else document.head.appendChild(link)
}

function drawBadge(count: number): Promise<string> {
  return loadBaseIcon().then((img) => {
    const size = 64
    const canvas = document.createElement('canvas')
    canvas.width = size
    canvas.height = size
    const ctx = canvas.getContext('2d')
    if (!ctx) return DEFAULT_HREF

    ctx.clearRect(0, 0, size, size)
    ctx.drawImage(img, 0, 0, size, size)

    const label = count > 99 ? '99+' : String(count)
    const radius = label.length > 2 ? 17 : label.length > 1 ? 15 : 14
    const cx = size - radius - 1
    const cy = radius + 1

    ctx.beginPath()
    ctx.arc(cx, cy, radius + 2, 0, Math.PI * 2)
    ctx.fillStyle = '#ffffff'
    ctx.fill()

    ctx.beginPath()
    ctx.arc(cx, cy, radius, 0, Math.PI * 2)
    ctx.fillStyle = '#16a34a'
    ctx.fill()

    ctx.fillStyle = '#ffffff'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    const fontSize = label.length > 2 ? 18 : label.length > 1 ? 22 : 26
    ctx.font = `700 ${fontSize}px system-ui, -apple-system, Segoe UI, sans-serif`
    ctx.fillText(label, cx, cy + 1)

    return canvas.toDataURL('image/png')
  })
}

/** Update favicon badge. Pass 0 (or less) to restore the default icon. */
export function setFaviconUnread(count: number) {
  if (typeof document === 'undefined') return
  const n = Math.max(0, Math.floor(count))
  if (n === lastApplied) return
  lastApplied = n

  if (n <= 0) {
    setIconLink(DEFAULT_HREF, DEFAULT_TYPE)
    return
  }

  void drawBadge(n)
    .then((href) => {
      if (lastApplied !== n) return
      if (href === DEFAULT_HREF) {
        setIconLink(DEFAULT_HREF, DEFAULT_TYPE)
        return
      }
      setIconLink(href, 'image/png')
    })
    .catch(() => {
      // Keep default icon if canvas/svg draw fails.
      if (lastApplied === n) setIconLink(DEFAULT_HREF, DEFAULT_TYPE)
    })
}

export function resetFavicon() {
  lastApplied = null
  setFaviconUnread(0)
}
