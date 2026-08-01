import * as XLSX from 'xlsx'

const LOGIN_KEYS = ['login', 'username', 'user', 'логин', 'юзер', 'ник', 'nickname']
const PHONE_KEYS = ['phone', 'tel', 'mobile', 'телефон', 'номер', 'phone_number']

function normalizeHeader(value: unknown): string {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_')
}

function cellToString(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'number') {
    // Excel may store phones as numbers
    return String(Math.trunc(value))
  }
  return String(value).trim()
}

function pickField(row: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    for (const [rawKey, rawVal] of Object.entries(row)) {
      if (normalizeHeader(rawKey) === key) {
        const v = cellToString(rawVal)
        if (v) return v
      }
    }
  }
  return ''
}

/** Extract recipient lines from rows (login preferred, else phone). */
export function rowsToRecipientLines(rows: Record<string, unknown>[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()

  for (const row of rows) {
    const login = pickField(row, LOGIN_KEYS)
    const phone = pickField(row, PHONE_KEYS)

    let value = ''
    if (login) value = login.startsWith('@') ? login : login
    else if (phone) {
      const digits = phone.replace(/[^\d+]/g, '')
      value = digits.startsWith('+') ? digits : digits ? `+${digits}` : phone
    } else {
      // single-column / fallback: first non-empty cell
      for (const v of Object.values(row)) {
        const s = cellToString(v)
        if (s) {
          value = s
          break
        }
      }
    }

    value = value.trim()
    if (!value || value.startsWith('#')) continue
    const key = value.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(value)
  }
  return out
}

export async function parseRecipientsFile(file: File): Promise<string[]> {
  const name = file.name.toLowerCase()
  const buf = await file.arrayBuffer()

  if (name.endsWith('.csv') || name.endsWith('.txt')) {
    const text = new TextDecoder('utf-8').decode(buf)
    // Prefer structured parse via sheetjs so CSV headers work the same
    const wb = XLSX.read(text, { type: 'string' })
    const sheet = wb.Sheets[wb.SheetNames[0]]
    const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, { defval: '' })
    if (rows.length && hasKnownHeaders(rows[0])) {
      return rowsToRecipientLines(rows)
    }
    // plain list
    return text
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#'))
  }

  const wb = XLSX.read(buf, { type: 'array' })
  const sheet = wb.Sheets[wb.SheetNames[0]]
  const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, { defval: '' })
  return rowsToRecipientLines(rows)
}

function hasKnownHeaders(row: Record<string, unknown>): boolean {
  const keys = Object.keys(row).map(normalizeHeader)
  return keys.some((k) => LOGIN_KEYS.includes(k) || PHONE_KEYS.includes(k))
}

export function downloadRecipientsSample(format: 'csv' | 'xlsx' = 'csv') {
  const rows = [
    { login: '@example_user', phone: '' },
    { login: '', phone: '+79001234567' },
    { login: 'demo_account', phone: '+79007654321' },
  ]
  const sheet = XLSX.utils.json_to_sheet(rows)
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, sheet, 'recipients')

  if (format === 'csv') {
    const csv = XLSX.utils.sheet_to_csv(sheet)
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
    triggerDownload(blob, 'mailing_recipients_sample.csv')
    return
  }

  const out = XLSX.write(wb, { bookType: 'xlsx', type: 'array' })
  const blob = new Blob([out], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  triggerDownload(blob, 'mailing_recipients_sample.xlsx')
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
