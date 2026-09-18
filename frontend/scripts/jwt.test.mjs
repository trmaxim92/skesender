/**
 * JWT scheduling helpers (no browser APIs beyond atob).
 * Run: node --experimental-strip-types scripts/jwt.test.mjs
 */
import {
  decodeJwtPayload,
  msUntilTokenRefresh,
  shouldRefreshToken,
  tokenSecondsRemaining,
  TOKEN_REFRESH_REMAINING_SEC,
} from '../src/utils/jwt.ts'

let failed = 0

function assert(name, cond) {
  if (cond) {
    console.log(`  ok  ${name}`)
  } else {
    failed += 1
    console.error(`  FAIL ${name}`)
  }
}

function fakeJwt(payload) {
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url')
  return `hdr.${body}.sig`
}

console.log('jwt')

assert('garbage → null', decodeJwtPayload('not-a-jwt') === null)

const nowSec = Math.floor(Date.now() / 1000)
const longLived = fakeJwt({ exp: nowSec + 20 * 3600, sub: 'a@b.c' })
const nearExpiry = fakeJwt({ exp: nowSec + 30 * 60, sub: 'a@b.c' })

assert('decode exp', decodeJwtPayload(longLived)?.exp === nowSec + 20 * 3600)
assert(
  'remaining ~20h',
  Math.abs((tokenSecondsRemaining(longLived) ?? 0) - 20 * 3600) < 2,
)
assert('long-lived → no refresh yet', shouldRefreshToken(longLived) === false)
assert('near expiry → refresh', shouldRefreshToken(nearExpiry) === true)
assert(
  'msUntil for long-lived > 0',
  (msUntilTokenRefresh(longLived) ?? -1) > (20 * 3600 - TOKEN_REFRESH_REMAINING_SEC - 5) * 1000,
)
assert('msUntil near expiry → 0', msUntilTokenRefresh(nearExpiry) === 0)

console.log(failed ? `\n${failed} failed` : '\nall passed')
process.exit(failed ? 1 : 0)
