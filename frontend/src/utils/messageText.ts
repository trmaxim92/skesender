const URL_RE = /https?:\/\/[^\s<>"']+/gi

export function normalizeMessageText(text: string): string {
  return text
    .replace(/\r\n/g, '\n')
    .replace(/[^\S\n]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export type TextPart =
  | { type: 'text'; value: string }
  | { type: 'link'; value: string; href: string }

function trimUrlTrailing(raw: string): string {
  return raw.replace(/[),.;:!?]+\s*$/g, '').replace(/[),.;:!?]+$/g, '')
}

export function splitMessageParts(text: string): TextPart[] {
  const normalized = normalizeMessageText(text)
  if (!normalized) return []

  const parts: TextPart[] = []
  let last = 0
  const re = new RegExp(URL_RE.source, 'gi')
  let match: RegExpExecArray | null
  while ((match = re.exec(normalized))) {
    const raw = match[0]
    const href = trimUrlTrailing(raw)
    const start = match.index
    const end = start + href.length
    if (start > last) {
      parts.push({ type: 'text', value: normalized.slice(last, start) })
    }
    parts.push({ type: 'link', value: href, href })
    last = end
    re.lastIndex = end
  }
  if (last < normalized.length) {
    parts.push({ type: 'text', value: normalized.slice(last) })
  }
  return parts
}

export type TicketCard = {
  title: string
  url: string
  ticketLabel: string
}

/** Compact card for “Новая заявка: + url” style bot messages. */
export function parseTicketCard(text: string): TicketCard | null {
  const normalized = normalizeMessageText(text)
  const m = normalized.match(
    /^(новая\s+заявка|new\s+ticket|новый\s+тикет)\s*:?\s*(?:\n+|[\s—–-]*)(https?:\/\/\S+)/i,
  )
  if (!m?.[2]) return null
  const url = trimUrlTrailing(m[2])
  const ticketMatch = url.match(/\/ticket\/(\d+)/i) || url.match(/[?&]id=(\d+)/i)
  const ticketLabel = ticketMatch?.[1] ? `#${ticketMatch[1]}` : 'Открыть заявку'
  const titleRaw = (m[1] || 'Новая заявка').trim()
  const title = titleRaw.charAt(0).toUpperCase() + titleRaw.slice(1).toLowerCase()
  return { title: title.replace(/\s+/g, ' '), url, ticketLabel }
}

export function shortUrlLabel(url: string, max = 42): string {
  try {
    const u = new URL(url)
    const path = `${u.host}${u.pathname}`.replace(/\/$/, '')
    if (path.length <= max) return path
    return `${path.slice(0, max - 1)}…`
  } catch {
    return url.length <= max ? url : `${url.slice(0, max - 1)}…`
  }
}
