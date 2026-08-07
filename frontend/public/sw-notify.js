/* SkySender notify + PWA service worker */
const ICON = '/oe-notify-icon.png'
const BADGE = '/oe-badge.png'

self.addEventListener('install', (event) => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

function sameOrigin(url) {
  try {
    return new URL(url).origin === self.location.origin
  } catch {
    return false
  }
}

async function openOrFocusChat(dialogId) {
  const targetPath = dialogId
    ? `/chats?dialog=${encodeURIComponent(String(dialogId))}`
    : '/chats'
  const absolute = new URL(targetPath, self.location.origin).href

  const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
  for (const client of all) {
    if (!sameOrigin(client.url)) continue
    if ('focus' in client) {
      await client.focus()
      try {
        if ('navigate' in client && typeof client.navigate === 'function') {
          await client.navigate(absolute)
        }
      } catch {
        // navigate unsupported — postMessage is enough for the SPA router
      }
      client.postMessage({ type: 'oe:open-dialog', dialogId: dialogId ? String(dialogId) : null })
      return
    }
  }
  if (self.clients.openWindow) {
    await self.clients.openWindow(absolute)
  }
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const dialogId = event.notification?.data?.dialogId
  const action = event.action
  if (action === 'dismiss') return

  event.waitUntil(openOrFocusChat(dialogId))
})

self.addEventListener('notificationclose', () => {
  // no-op — reserved for analytics later
})

// Allow page to ask SW to show a styled notification (keeps options in one place).
self.addEventListener('message', (event) => {
  const data = event.data
  if (!data || typeof data !== 'object') return

  if (data.type === 'oe:show-notification') {
    const title = data.title || 'SkySender'
    const options = data.options || {}
    event.waitUntil(
      self.registration.showNotification(title, {
        icon: ICON,
        badge: BADGE,
        ...options,
      }),
    )
    return
  }

  if (data.type === 'oe:set-app-badge') {
    const n = Number(data.count) || 0
    event.waitUntil(
      (async () => {
        try {
          if (n > 0 && self.registration.setAppBadge) {
            await self.registration.setAppBadge(n)
          } else if (self.registration.clearAppBadge) {
            await self.registration.clearAppBadge()
          }
        } catch {
          // Badging API optional
        }
      })(),
    )
  }
})
