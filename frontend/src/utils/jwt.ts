/** Decode JWT payload without verifying signature (scheduling only). */

export type JwtClaims = {
  exp?: number
  sub?: string
  ver?: number
  role?: string
}

export function decodeJwtPayload(token: string): JwtClaims | null {
  const parts = token.split('.')
  if (parts.length < 2) return null
  try {
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const pad = b64.length % 4 === 0 ? '' : '='.repeat(4 - (b64.length % 4))
    const json = atob(b64 + pad)
    return JSON.parse(json) as JwtClaims
  } catch {
    return null
  }
}

/** Seconds until JWT `exp`, or null if missing/invalid. */
export function tokenSecondsRemaining(token: string, nowMs = Date.now()): number | null {
  const claims = decodeJwtPayload(token)
  if (!claims?.exp || typeof claims.exp !== 'number') return null
  return claims.exp - Math.floor(nowMs / 1000)
}

/**
 * When to refresh: remaining lifetime below this fraction of total TTL,
 * or below an absolute floor (whichever triggers sooner).
 * Default: refresh when < 2h left, or earlier for short tokens.
 */
export const TOKEN_REFRESH_REMAINING_SEC = 2 * 60 * 60

export function shouldRefreshToken(
  token: string,
  nowMs = Date.now(),
  remainingThresholdSec = TOKEN_REFRESH_REMAINING_SEC,
): boolean {
  const remaining = tokenSecondsRemaining(token, nowMs)
  if (remaining == null) return false
  return remaining <= remainingThresholdSec
}

/** Delay (ms) until we should attempt a quiet refresh; null if already past. */
export function msUntilTokenRefresh(
  token: string,
  nowMs = Date.now(),
  remainingThresholdSec = TOKEN_REFRESH_REMAINING_SEC,
): number | null {
  const remaining = tokenSecondsRemaining(token, nowMs)
  if (remaining == null) return null
  const waitSec = remaining - remainingThresholdSec
  if (waitSec <= 0) return 0
  return waitSec * 1000
}
