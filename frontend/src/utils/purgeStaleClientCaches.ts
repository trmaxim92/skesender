/**
 * Drop stale service workers / Cache Storage left by previous apps on this origin.
 * Keeps only /sw-notify.js (notifications; does not cache the SPA shell).
 */
export async function purgeStaleClientCaches(): Promise<void> {
  if (typeof window === 'undefined') return

  try {
    if ('serviceWorker' in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations()
      await Promise.all(
        regs.map(async (reg) => {
          const script =
            reg.active?.scriptURL ||
            reg.waiting?.scriptURL ||
            reg.installing?.scriptURL ||
            ''
          if (script.endsWith('/sw-notify.js')) return
          try {
            await reg.unregister()
          } catch {
            // ignore
          }
        }),
      )
    }
  } catch {
    // ignore
  }

  try {
    if ('caches' in window) {
      const keys = await caches.keys()
      await Promise.all(keys.map((k) => caches.delete(k)))
    }
  } catch {
    // ignore
  }
}
