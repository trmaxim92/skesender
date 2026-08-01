/**
 * Smoke tests for OS-push gate (no browser).
 * Run: node scripts/notify-gate.test.mjs
 */
import { explainOsPushDecision, shouldShowOsPush } from '../src/utils/notifyGate.js'

let failed = 0

function assert(name, cond) {
  if (cond) {
    console.log(`  ok  ${name}`)
  } else {
    failed += 1
    console.error(`  FAIL ${name}`)
  }
}

console.log('notifyGate')

assert(
  'denied → no',
  shouldShowOsPush({
    pushEnabled: true,
    permission: 'denied',
  }) === false,
)

assert(
  'default → no',
  shouldShowOsPush({
    pushEnabled: true,
    permission: 'default',
  }) === false,
)

assert(
  'push off → no',
  shouldShowOsPush({
    pushEnabled: false,
    permission: 'granted',
  }) === false,
)

assert(
  'force + granted → yes even if push off',
  shouldShowOsPush({
    pushEnabled: false,
    permission: 'granted',
    force: true,
  }) === true,
)

assert(
  'enabled + granted → yes (even active dialog)',
  shouldShowOsPush({
    pushEnabled: true,
    permission: 'granted',
    visibilityState: 'visible',
    isActiveDialog: true,
  }) === true,
)

assert(
  'explain push_disabled',
  explainOsPushDecision({
    pushEnabled: false,
    permission: 'granted',
  }).reason === 'push_disabled',
)

assert(
  'explain ok',
  explainOsPushDecision({
    pushEnabled: true,
    permission: 'granted',
  }).reason === 'ok',
)

assert(
  'explain force',
  explainOsPushDecision({
    pushEnabled: false,
    permission: 'granted',
    force: true,
  }).reason === 'force',
)

if (failed) {
  console.error(`\n${failed} failed`)
  process.exit(1)
}
console.log('\nall passed')
