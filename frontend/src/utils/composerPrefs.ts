/** Composer send shortcut labels (preference itself lives on User.sendMode in DB). */

export type SendMode = 'enter' | 'ctrl_enter' | 'button'

export const SEND_MODE_OPTIONS: {
  id: SendMode
  label: string
  hint: string
}[] = [
  {
    id: 'ctrl_enter',
    label: 'Ctrl+Enter — отправить',
    hint: 'Enter — новая строка. На Mac: ⌘+Enter.',
  },
  {
    id: 'enter',
    label: 'Enter — отправить',
    hint: 'Shift+Enter — новая строка.',
  },
  {
    id: 'button',
    label: 'Только кнопка',
    hint: 'Enter всегда делает новую строку; отправка только кнопкой.',
  },
]

export function normalizeSendMode(raw: string | null | undefined): SendMode {
  if (raw === 'ctrl_enter' || raw === 'button' || raw === 'enter') return raw
  return 'ctrl_enter'
}
