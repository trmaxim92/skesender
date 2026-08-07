import { api } from '@/api/client'
import { prepareNotifyServiceWorker } from '@/utils/notify'

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const out = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i)
  return out
}

export function isWebPushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  )
}

export async function fetchVapidPublicKey(): Promise<string> {
  const res = await api<{ publicKey: string }>('/api/push/vapid-public-key')
  return res.publicKey
}

export async function subscribeWebPush(): Promise<{ ok: boolean; reason: string }> {
  if (!isWebPushSupported()) {
    return { ok: false, reason: 'unsupported' }
  }
  if (Notification.permission !== 'granted') {
    return { ok: false, reason: 'permission' }
  }

  const ready = await prepareNotifyServiceWorker()
  if (!ready) return { ok: false, reason: 'sw' }

  const reg = await navigator.serviceWorker.ready
  let sub = await reg.pushManager.getSubscription()
  if (!sub) {
    const publicKey = await fetchVapidPublicKey()
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey) as BufferSource,
    })
  }

  const json = sub.toJSON()
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
    return { ok: false, reason: 'incomplete' }
  }

  await api('/api/push/subscribe', {
    method: 'POST',
    json: {
      endpoint: json.endpoint,
      keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
    },
  })
  return { ok: true, reason: 'subscribed' }
}

export async function unsubscribeWebPush(): Promise<void> {
  if (!isWebPushSupported()) return
  try {
    const reg = await navigator.serviceWorker.getRegistration('/sw-notify.js')
    const sub = await reg?.pushManager.getSubscription()
    if (!sub) return
    const endpoint = sub.endpoint
    try {
      await api('/api/push/subscribe', {
        method: 'DELETE',
        json: { endpoint },
      })
    } catch {
      // ignore server errors on logout/disable
    }
    await sub.unsubscribe()
  } catch {
    // ignore
  }
}
