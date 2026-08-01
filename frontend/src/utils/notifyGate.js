/**
 * Pure gate for OS push (shared with Node smoke tests).
 * @param {{
 *   pushEnabled: boolean,
 *   permission: 'granted' | 'denied' | 'default' | 'unsupported',
 *   visibilityState?: 'visible' | 'hidden' | 'prerender',
 *   isActiveDialog?: boolean,
 *   force?: boolean,
 * }} opts
 */
export function shouldShowOsPush(opts) {
  const { pushEnabled, permission, force = false } = opts
  if (permission !== 'granted') return false
  if (!pushEnabled && !force) return false
  return true
}

/**
 * @param {{
 *   pushEnabled: boolean,
 *   permission: string,
 *   visibilityState?: string,
 *   isActiveDialog?: boolean,
 *   force?: boolean,
 * }} opts
 */
export function explainOsPushDecision(opts) {
  if (opts.permission !== 'granted') {
    return { show: false, reason: `permission=${opts.permission}` }
  }
  if (!opts.pushEnabled && !opts.force) {
    return { show: false, reason: 'push_disabled' }
  }
  if (opts.force) {
    return { show: true, reason: 'force' }
  }
  return { show: true, reason: 'ok' }
}
