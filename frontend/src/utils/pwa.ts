/** PWA helpers: standalone detection, install prompt, app icon badge. */

const DISMISS_INSTALL_KEY = 'oe_pwa_install_dismissed'

export function isStandaloneDisplay(): boolean {
  if (typeof window === 'undefined') return false
  const mq = window.matchMedia?.('(display-mode: standalone)')?.matches
  const ios = 'standalone' in navigator && Boolean((navigator as Navigator & { standalone?: boolean }).standalone)
  return Boolean(mq || ios)
}

export function isIosDevice(): boolean {
  if (typeof navigator === 'undefined') return false
  return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

export function canUseBeforeInstallPrompt(): boolean {
  return typeof window !== 'undefined' && 'onbeforeinstallprompt' in window
}

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

let deferredPrompt: BeforeInstallPromptEvent | null = null
let promptListeners: Array<(ready: boolean) => void> = []

function notifyPromptListeners() {
  const ready = deferredPrompt != null
  for (const fn of promptListeners) fn(ready)
}

export function initPwaInstallCapture() {
  if (typeof window === 'undefined') return
  window.addEventListener('beforeinstallprompt', (ev) => {
    ev.preventDefault()
    deferredPrompt = ev as BeforeInstallPromptEvent
    notifyPromptListeners()
  })
  window.addEventListener('appinstalled', () => {
    deferredPrompt = null
    localStorage.setItem(DISMISS_INSTALL_KEY, '1')
    notifyPromptListeners()
  })
}

export function onInstallPromptAvailable(fn: (ready: boolean) => void) {
  promptListeners.push(fn)
  fn(deferredPrompt != null)
  return () => {
    promptListeners = promptListeners.filter((x) => x !== fn)
  }
}

export function isInstallPromptReady(): boolean {
  return deferredPrompt != null
}

export function wasInstallDismissed(): boolean {
  return localStorage.getItem(DISMISS_INSTALL_KEY) === '1'
}

export function dismissInstallHint() {
  localStorage.setItem(DISMISS_INSTALL_KEY, '1')
}

export async function promptPwaInstall(): Promise<'accepted' | 'dismissed' | 'unavailable'> {
  if (!deferredPrompt) return 'unavailable'
  const ev = deferredPrompt
  deferredPrompt = null
  notifyPromptListeners()
  await ev.prompt()
  const { outcome } = await ev.userChoice
  if (outcome === 'accepted') localStorage.setItem(DISMISS_INSTALL_KEY, '1')
  return outcome
}

export async function setAppBadgeCount(count: number) {
  if (typeof navigator === 'undefined') return
  const n = Math.max(0, Math.floor(count))
  try {
    if (n > 0 && 'setAppBadge' in navigator) {
      await (navigator as Navigator & { setAppBadge: (v?: number) => Promise<void> }).setAppBadge(n)
    } else if ('clearAppBadge' in navigator) {
      await (navigator as Navigator & { clearAppBadge: () => Promise<void> }).clearAppBadge()
    }
  } catch {
    // ignore
  }

  // Also ask SW (some Chromium builds prefer registration badge).
  try {
    if (!('serviceWorker' in navigator)) return
    const reg = await navigator.serviceWorker.getRegistration('/sw-notify.js')
      ?? (await navigator.serviceWorker.getRegistration())
    reg?.active?.postMessage({ type: 'oe:set-app-badge', count: n })
  } catch {
    // ignore
  }
}
