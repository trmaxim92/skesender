import { explainOsPushDecision, shouldShowOsPush } from './notifyGate.js'

const SOUND_KEY = 'oe_sound_enabled'
const PUSH_KEY = 'oe_push_enabled'
const DEBUG_KEY = 'oe_notify_debug'
const ICON_PATH = '/oe-notify-icon.png'
const BADGE_PATH = '/oe-badge.png'

function readFlag(key: string, fallback: boolean): boolean {
  const raw = localStorage.getItem(key)
  if (raw === null) return fallback
  return raw === '1'
}

function writeFlag(key: string, value: boolean) {
  localStorage.setItem(key, value ? '1' : '0')
}

function debugEnabled(): boolean {
  return typeof localStorage !== 'undefined' && localStorage.getItem(DEBUG_KEY) === '1'
}

function debugLog(...args: unknown[]) {
  if (debugEnabled()) console.info('[oe-notify]', ...args)
}

function absoluteAsset(path: string): string {
  if (typeof window === 'undefined') return path
  return new URL(path, window.location.origin).href
}

function truncate(text: string, max: number): string {
  const t = text.replace(/\s+/g, ' ').trim()
  if (t.length <= max) return t
  return `${t.slice(0, max - 1)}…`
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return 'OE'
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase()
  return `${parts[0]![0] ?? ''}${parts[1]![0] ?? ''}`.toUpperCase()
}

let audioCtx: AudioContext | null = null
let lastSoundAt = 0
let swRegPromise: Promise<ServiceWorkerRegistration | null> | null = null

function getCtx(): AudioContext | null {
  if (typeof window === 'undefined') return null
  const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!AC) return null
  if (!audioCtx) audioCtx = new AC()
  return audioCtx
}

/** Call from a user gesture so browsers allow subsequent beeps. */
export function unlockNotifyAudio() {
  const ctx = getCtx()
  if (!ctx) return
  if (ctx.state === 'suspended') void ctx.resume()
}

export function isSoundEnabled(): boolean {
  return readFlag(SOUND_KEY, true)
}

export function setSoundEnabled(value: boolean) {
  writeFlag(SOUND_KEY, value)
  if (value) unlockNotifyAudio()
}

export function isPushEnabled(): boolean {
  return readFlag(PUSH_KEY, false)
}

export function setPushEnabled(value: boolean) {
  writeFlag(PUSH_KEY, value)
}

export function notificationPermission(): NotificationPermission | 'unsupported' {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported'
  return Notification.permission
}

export function isPushActive(): boolean {
  return isPushEnabled() && notificationPermission() === 'granted'
}

export async function ensureNotificationPermission(): Promise<NotificationPermission | 'unsupported'> {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported'
  if (Notification.permission === 'granted' || Notification.permission === 'denied') {
    return Notification.permission
  }
  return Notification.requestPermission()
}

export function playIncomingSound() {
  if (!isSoundEnabled()) return
  const ctx = getCtx()
  if (!ctx) return
  if (ctx.state === 'suspended') void ctx.resume()

  const nowMs = Date.now()
  if (nowMs - lastSoundAt < 180) return
  lastSoundAt = nowMs

  const t0 = ctx.currentTime
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.type = 'sine'
  osc.frequency.setValueAtTime(880, t0)
  osc.frequency.setValueAtTime(1245, t0 + 0.07)
  gain.gain.setValueAtTime(0.0001, t0)
  gain.gain.exponentialRampToValueAtTime(0.14, t0 + 0.015)
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.22)
  osc.connect(gain)
  gain.connect(ctx.destination)
  osc.start(t0)
  osc.stop(t0 + 0.24)
}

export type IncomingNotifyPayload = {
  dialogId: string
  contactName: string
  text: string
  isActiveDialog?: boolean
}

export type InAppToastPayload = {
  text: string
  kind?: 'ok' | 'warn' | 'err' | 'message'
  title?: string
  dialogId?: string
  initials?: string
}

/** In-app banner — always visible even when OS swallows toasts. */
export function showInAppToast(input: string | InAppToastPayload, kind: InAppToastPayload['kind'] = 'ok') {
  if (typeof window === 'undefined') return
  const detail: InAppToastPayload =
    typeof input === 'string' ? { text: input, kind } : { kind: 'ok', ...input }
  window.dispatchEvent(new CustomEvent('oe:in-app-toast', { detail }))
}

async function ensureNotifySw(): Promise<ServiceWorkerRegistration | null> {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return null
  if (!swRegPromise) {
    swRegPromise = navigator.serviceWorker
      .register('/sw-notify.js')
      .then(async (reg) => {
        // Pick up SW edits after deploys / HMR.
        void reg.update()
        return reg
      })
      .catch((err) => {
        debugLog('sw register fail', err)
        return null
      })
  }
  return swRegPromise
}

function formatOsTitle(payload: IncomingNotifyPayload, force?: boolean): string {
  if (force) return 'Order Elite'
  const name = (payload.contactName || 'Клиент').trim()
  return name
}

function formatOsBody(payload: IncomingNotifyPayload, force?: boolean): string {
  if (force) return truncate(payload.text || 'Тестовое уведомление', 140)
  const text = truncate(payload.text || 'Новое сообщение', 140)
  return text
}

function attachClick(n: Notification, dialogId: string) {
  n.onclick = () => {
    try {
      window.focus()
    } catch {
      // ignore
    }
    window.dispatchEvent(new CustomEvent('oe:open-dialog', { detail: { dialogId } }))
    n.close()
  }
}

async function deliverOsNotification(
  payload: IncomingNotifyPayload,
  opts: { force?: boolean },
): Promise<{ ok: boolean; reason: string }> {
  const title = formatOsTitle(payload, opts.force)
  const body = formatOsBody(payload, opts.force)
  const tag = opts.force ? `oe-test-${Date.now()}` : `oe-chat-${payload.dialogId}`
  const icon = absoluteAsset(ICON_PATH)
  const badge = absoluteAsset(BADGE_PATH)

  const options: NotificationOptions & { renotify?: boolean; actions?: { action: string; title: string }[] } = {
    body,
    tag,
    renotify: true,
    icon,
    badge,
    lang: 'ru',
    data: {
      dialogId: payload.dialogId,
      contactName: payload.contactName,
    },
  }

  // Actions only work reliably via Service Worker showNotification.
  const swOptions = {
    ...options,
    actions: [
      { action: 'open', title: 'Открыть' },
      { action: 'dismiss', title: 'Скрыть' },
    ],
  }

  const reg = await ensureNotifySw()
  if (reg?.showNotification) {
    try {
      await reg.showNotification(title, swOptions)
      debugLog('sw showNotification ok', title)
      return { ok: true, reason: 'sw' }
    } catch (err) {
      debugLog('sw showNotification fail', err)
    }
  }

  try {
    const n = new Notification(title, options)
    attachClick(n, payload.dialogId)
    debugLog('Notification() ok', title)
    return { ok: true, reason: 'constructor' }
  } catch (err) {
    debugLog('Notification() throw', err)
    return { ok: false, reason: 'throw' }
  }
}

export async function showOsNotification(
  payload: IncomingNotifyPayload,
  opts: { force?: boolean } = {},
): Promise<{ ok: boolean; reason: string }> {
  const permission = notificationPermission()
  const decision = explainOsPushDecision({
    pushEnabled: isPushEnabled(),
    permission,
    force: Boolean(opts.force),
  })
  debugLog('decision', decision, {
    pushEnabled: isPushEnabled(),
    permission,
    force: opts.force,
  })

  if (!decision.show) return { ok: false, reason: decision.reason }
  if (typeof window === 'undefined' || !('Notification' in window)) {
    return { ok: false, reason: 'unsupported' }
  }

  return deliverOsNotification(payload, opts)
}

/** Fire a sample notification (must run from a click). */
export async function testOsPush(): Promise<{ ok: boolean; reason: string; permission: string }> {
  const perm = await ensureNotificationPermission()
  if (perm !== 'granted') {
    showInAppToast(
      {
        title: 'Нет доступа',
        text:
          perm === 'denied'
            ? 'Разреши уведомления для localhost в замке адресной строки'
            : 'Разрешение на уведомления не выдано',
        kind: 'err',
      },
    )
    return { ok: false, reason: `permission=${perm}`, permission: String(perm) }
  }

  if (!isPushEnabled()) setPushEnabled(true)
  await ensureNotifySw()

  const result = await showOsNotification(
    {
      dialogId: 'test',
      contactName: 'Order Elite',
      text: 'Так будут выглядеть входящие сообщения',
      isActiveDialog: false,
    },
    { force: true },
  )

  if (result.ok) {
    showInAppToast({
      title: 'Пуш отправлен',
      text: 'Системный тост и карточка в кабинете',
      kind: 'message',
      initials: 'OE',
    })
    window.setTimeout(() => {
      void showOsNotification(
        {
          dialogId: 'test',
          contactName: 'Анна Клиентова',
          text: 'Здравствуйте! Подскажите по заказу №4821',
          isActiveDialog: false,
        },
        { force: true },
      )
    }, 2000)
  } else {
    showInAppToast({
      title: 'Ошибка',
      text: `Не удалось создать уведомление: ${result.reason}`,
      kind: 'err',
    })
  }

  return { ...result, permission: String(perm) }
}

export function notifyIncomingMessage(payload: IncomingNotifyPayload) {
  playIncomingSound()
  void showOsNotification(payload).then((r) => {
    if (r.ok) return
    debugLog('incoming os skip', r.reason)
  })

  if (
    isPushActive() &&
    typeof document !== 'undefined' &&
    document.visibilityState === 'visible' &&
    !payload.isActiveDialog
  ) {
    const name = payload.contactName || 'Чат'
    showInAppToast({
      title: name,
      text: truncate(payload.text || 'Новое сообщение', 100),
      kind: 'message',
      dialogId: payload.dialogId,
      initials: initials(name),
    })
  }
}

export { shouldShowOsPush, explainOsPushDecision, initials as notifyInitials }
