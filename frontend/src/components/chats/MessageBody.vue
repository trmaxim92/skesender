<script setup lang="ts">
import { computed } from 'vue'
import { ExternalLink } from 'lucide-vue-next'
import {
  parseTicketCard,
  shortUrlLabel,
  splitMessageParts,
} from '@/utils/messageText'

const props = defineProps<{
  text: string
  outgoing?: boolean
}>()

const ticket = computed(() => parseTicketCard(props.text))
const parts = computed(() => (ticket.value ? [] : splitMessageParts(props.text)))
</script>

<template>
  <div
    v-if="ticket"
    class="min-w-0 overflow-hidden rounded-xl border"
    :class="outgoing ? 'border-white/20 bg-white/10' : 'border-line bg-surface'"
  >
    <div class="px-3 py-2.5">
      <div
        class="text-[11px] font-semibold uppercase tracking-wide"
        :class="outgoing ? 'text-white/70' : 'text-brand'"
      >
        {{ ticket.title }}
      </div>
      <a
        :href="ticket.url"
        target="_blank"
        rel="noopener noreferrer"
        class="mt-1.5 inline-flex max-w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-[13px] font-semibold underline-offset-2 transition hover:underline"
        :class="outgoing ? 'bg-white/15 text-white' : 'bg-brand-soft text-brand'"
      >
        <ExternalLink class="size-3.5 shrink-0 opacity-80" />
        <span class="truncate">{{ ticket.ticketLabel }}</span>
      </a>
      <div
        class="mt-1 truncate text-[10px]"
        :class="outgoing ? 'text-white/55' : 'text-muted'"
        :title="ticket.url"
      >
        {{ shortUrlLabel(ticket.url) }}
      </div>
    </div>
  </div>
  <p
    v-else
    class="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]"
  >
    <template v-for="(part, idx) in parts" :key="idx">
      <a
        v-if="part.type === 'link'"
        :href="part.href"
        target="_blank"
        rel="noopener noreferrer"
        class="font-medium underline underline-offset-2 break-all"
        :class="outgoing ? 'text-white' : 'text-brand'"
        >{{ part.value }}</a
      >
      <template v-else>{{ part.value }}</template>
    </template>
  </p>
</template>
