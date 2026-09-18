/**
 * Auth permission / hydrate-error gate (no browser).
 * Run: node --experimental-strip-types scripts/auth-can.test.mjs
 */
import { shouldLogoutOnHydrateError, userCan } from '../src/utils/authCan.ts'

let failed = 0

function assert(name, cond) {
  if (cond) {
    console.log(`  ok  ${name}`)
  } else {
    failed += 1
    console.error(`  FAIL ${name}`)
  }
}

console.log('authCan')

assert('null user → deny', userCan(null, 'action.write') === false)

assert(
  'admin → any code',
  userCan({ role: 'admin', permissions: [] }, 'action.manage_users') === true,
)

assert(
  'empty permissions → deny (no legacy write)',
  userCan({ role: 'operator', permissions: [] }, 'action.write') === false,
)

assert(
  'empty permissions → deny section',
  userCan({ role: 'operator', permissions: [] }, 'section.chats') === false,
)

assert(
  'explicit write → allow',
  userCan({ role: 'operator', permissions: ['section.chats', 'action.write'] }, 'action.write') ===
    true,
)

assert(
  'missing code → deny',
  userCan({ role: 'operator', permissions: ['section.chats'] }, 'action.write') === false,
)

assert(
  'viewer without manage_users',
  userCan({ role: 'viewer', permissions: ['section.chats'] }, 'action.manage_users') === false,
)

assert('hydrate 401 → logout', shouldLogoutOnHydrateError(401) === true)
assert('hydrate 503 → keep', shouldLogoutOnHydrateError(503) === false)
assert('hydrate 500 → keep', shouldLogoutOnHydrateError(500) === false)
assert('hydrate undefined → keep', shouldLogoutOnHydrateError(undefined) === false)

console.log(failed ? `\n${failed} failed` : '\nall passed')
process.exit(failed ? 1 : 0)
