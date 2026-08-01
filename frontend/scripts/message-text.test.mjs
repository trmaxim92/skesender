/**
 * Smoke tests for chat message text helpers.
 * Run: node --experimental-strip-types scripts/message-text.test.mjs
 * or duplicate via dynamic import of compiled paths — plain assert file:
 */
import assert from 'node:assert/strict'
import {
  normalizeMessageText,
  parseTicketCard,
  splitMessageParts,
} from '../src/utils/messageText.ts'

const gappy = 'Новая заявка:\n\n\n\n\nhttps://skyscale.helpdeskeddy.com/ru/ticket/list/filter/id/0/ticket/2163'
assert.equal(
  normalizeMessageText(gappy),
  'Новая заявка:\n\nhttps://skyscale.helpdeskeddy.com/ru/ticket/list/filter/id/0/ticket/2163',
)

const card = parseTicketCard(gappy)
assert.ok(card)
assert.equal(card.ticketLabel, '#2163')
assert.match(card.url, /ticket\/2163/)

const parts = splitMessageParts('Смотри https://example.com/a и текст')
assert.equal(parts.length, 3)
assert.equal(parts[0].type, 'text')
assert.equal(parts[1].type, 'link')
assert.equal(parts[2].type, 'text')

console.log('messageText: all passed')
