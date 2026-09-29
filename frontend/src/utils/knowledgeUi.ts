import { resolveAuthMediaUrl } from '@/utils/authMedia'

const RECENT_KEY = 'oe_kb_recent'
const RECENT_MAX = 8

export type KbRecentItem = {
  id: number
  title: string
  at: number
}

export function loadKbRecent(): KbRecentItem[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as KbRecentItem[]
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((x) => x && typeof x.id === 'number' && typeof x.title === 'string')
      .slice(0, RECENT_MAX)
  } catch {
    return []
  }
}

export function pushKbRecent(id: number, title: string) {
  const next = [
    { id, title, at: Date.now() },
    ...loadKbRecent().filter((x) => x.id !== id),
  ].slice(0, RECENT_MAX)
  localStorage.setItem(RECENT_KEY, JSON.stringify(next))
}

export type KbTocItem = {
  id: string
  level: 2 | 3
  text: string
}

/** Assign ids to h2/h3 and return TOC entries. Mutates the element tree. */
export function buildKbToc(root: HTMLElement): KbTocItem[] {
  const headings = root.querySelectorAll('h2, h3')
  const items: KbTocItem[] = []
  let i = 0
  headings.forEach((el) => {
    const level = el.tagName.toLowerCase() === 'h2' ? 2 : 3
    const text = (el.textContent || '').trim()
    if (!text) return
    i += 1
    const id = el.id || `kb-h-${i}`
    el.id = id
    items.push({ id, level: level as 2 | 3, text })
  })
  return items
}

/** Persist TipTap HTML: turn blob previews back into API paths via data-kb-src. */
export function serializeKbHtml(html: string): string {
  if (typeof document === 'undefined') return html
  const wrap = document.createElement('div')
  wrap.innerHTML = html
  wrap.querySelectorAll('img').forEach((img) => {
    const original = img.getAttribute('data-kb-src')
    if (original) {
      img.setAttribute('src', original)
      img.removeAttribute('data-kb-src')
    }
  })
  return wrap.innerHTML
}

/** Resolve authenticated knowledge media into blob URLs for <img>. */
export async function hydrateKbImages(root: HTMLElement | null) {
  if (!root) return
  const imgs = Array.from(root.querySelectorAll('img'))
  await Promise.all(
    imgs.map(async (img) => {
      const apiSrc =
        img.getAttribute('data-kb-src') ||
        (img.getAttribute('src')?.startsWith('/api/knowledge/media/')
          ? img.getAttribute('src')
          : null)
      if (!apiSrc) return
      img.setAttribute('data-kb-src', apiSrc)
      try {
        const blobUrl = await resolveAuthMediaUrl(apiSrc)
        if (img.getAttribute('src') !== blobUrl) img.setAttribute('src', blobUrl)
      } catch {
        // keep original src
      }
    }),
  )
}
