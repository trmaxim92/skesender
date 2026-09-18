/** Composer send shortcut preference (device-local, like notify flags). */

export type SendMode = 'enter' | 'ctrl_enter' | 'button'

const KEY = 'oe_send_mode'
const EVENT = 'oe-send-mode'

export const SEND_MODE_OPTIONS: {
  id: SendMode
  label: string
  hint: string
}[] = [
  {
    id: 'enter',
    label: 'Enter — отправить',
    hint: 'Shift+Enter — новая строка. Удобно на десктопе.',
  },
  {
    id: 'ctrl_enter',
    label: 'Ctrl+Enter — отправить',
    hint: 'Enter — новая строка. На Mac: ⌘+Enter. Удобно на телефоне.',
  },
  {
    id: 'button',
    label: 'Только кнопка',
    hint: 'Enter всегда делает новую строку; отправка только кнопкой.',
  },
]

function normalize(raw: string | null): SendMode {
  if (raw === 'ctrl_enter' || raw === 'button' || raw === 'enter') return raw
  return 'enter'
}

export function getSendMode(): SendMode {
  if (typeof localStorage === 'undefined') return 'enter'
  return normalize(localStorage.getItem(KEY))
}

export function setSendMode(mode: SendMode) {
  localStorage.setItem(KEY, mode)
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(EVENT, { detail: mode }))
  }
}

export function onSendModeChange(handler: (mode: SendMode) => void): () => void {
  if (typeof window === 'undefined') return () => {}
  const onCustom = (e: Event) => {
    const detail = (e as CustomEvent<SendMode>).detail
    handler(normalize(detail ?? getSendMode()))
  }
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) handler(getSendMode())
  }
  window.addEventListener(EVENT, onCustom)
  window.addEventListener('storage', onStorage)
  return () => {
    window.removeEventListener(EVENT, onCustom)
    window.removeEventListener('storage', onStorage)
  }
}
