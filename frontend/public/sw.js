/* Kill legacy service workers from previous apps on this origin.
 * New SkySender only uses /sw-notify.js (push UI), which does not cache pages.
 */
self.addEventListener('install', (event) => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      try {
        const keys = await caches.keys()
        await Promise.all(keys.map((k) => caches.delete(k)))
      } catch {
        // ignore
      }
      try {
        await self.registration.unregister()
      } catch {
        // ignore
      }
      const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const client of clients) {
        if ('navigate' in client) {
          try {
            await client.navigate(client.url)
          } catch {
            // ignore
          }
        }
      }
    })(),
  )
})
