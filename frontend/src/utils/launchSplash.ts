/** Cold-start splash for installed PWA (standalone). */

const SPLASH_ID = 'oe-splash'

function sleep(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

export async function finishLaunchSplash(options?: {
  minMs?: number
  fadeMs?: number
}): Promise<void> {
  const el = document.getElementById(SPLASH_ID)
  if (!el) return

  const minMs = options?.minMs ?? 1200
  const fadeMs = options?.fadeMs ?? 520
  const startedAttr = el.getAttribute('data-started')
  const started = startedAttr ? Number(startedAttr) : performance.now()
  const elapsed = performance.now() - started
  const wait = Math.max(0, minMs - elapsed)

  await sleep(wait)

  el.classList.add('oe-splash--leave')
  document.documentElement.classList.add('oe-launched')

  await sleep(fadeMs)
  el.remove()
}
