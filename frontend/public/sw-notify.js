/* SkySender notify service worker */
const ICON = '/oe-notify-icon.png'
const BADGE = '/oe-badge.png'

self.addEventListener('install', (event) => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const dialogId = event.notification?.data?.dialogId
  const action = event.action
  if (action === 'dismiss') return

  const targetPath = dialogId
    ? `/chats?dialog=${encodeURIComponent(dialogId)}`
    : '/chats'

  event.waitUntil(
    (async () => {
      const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const client of all) {
        if ('focus' in client) {
          await client.focus()
          client.postMessage({ type: 'oe:open-dialog', dialogId })
          return
        }
      }
      if (self.clients.openWindow) {
        await self.clients.openWindow(targetPath)
      }
    })(),
  )
})

// Allow page to ask SW to show a styled notification (keeps options in one place).
self.addEventListener('message', (event) => {
  const data = event.data
  if (!data || data.type !== 'oe:show-notification') return
  const title = data.title || 'SkySender'
  const options = data.options || {}
  event.waitUntil(
    self.registration.showNotification(title, {
      icon: ICON,
      badge: BADGE,
      ...options,
    }),
  )
})
