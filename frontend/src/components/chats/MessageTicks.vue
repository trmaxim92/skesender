<script setup lang="ts">
import { Check, CheckCheck } from 'lucide-vue-next'
import { computed } from 'vue'
import { messageStatusLabel, type MessageStatus } from '@/types'

const props = withDefaults(
  defineProps<{
    status: MessageStatus
    /** onBrand — на синем пузыре; muted — в списке диалогов */
    tone?: 'onBrand' | 'muted'
    clickable?: boolean
  }>(),
  { tone: 'muted', clickable: false },
)

const emit = defineEmits<{
  click: []
}>()

const title = computed(() => {
  if (props.status === 'failed' && props.clickable) {
    return 'Ошибка отправки — нажмите для подробностей'
  }
  return messageStatusLabel[props.status] || props.status
})

const colorClass = computed(() => {
  if (props.status === 'failed') {
    return props.tone === 'onBrand' ? 'text-red-200' : 'text-danger'
  }
  if (props.status === 'read') {
    return props.tone === 'onBrand' ? 'text-read-tick' : 'text-sky-500'
  }
  return props.tone === 'onBrand' ? 'text-white/70' : 'text-muted'
})

const isFailedClickable = computed(() => props.status === 'failed' && props.clickable)
</script>

<template>
  <button
    v-if="isFailedClickable"
    type="button"
    class="inline-flex shrink-0 items-center rounded px-0.5 leading-none transition hover:bg-white/15 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/50"
    :class="colorClass"
    :title="title"
    :aria-label="title"
    @click.stop="emit('click')"
  >
    <span class="text-[11px] font-bold">!</span>
  </button>
  <span
    v-else
    class="inline-flex shrink-0 items-center leading-none"
    :class="colorClass"
    :title="title"
    aria-hidden="false"
    :aria-label="title"
  >
    <span v-if="status === 'failed'" class="text-[11px] font-bold">!</span>
    <span
      v-else-if="status === 'sending'"
      class="inline-block size-3 animate-pulse rounded-full"
      :class="tone === 'onBrand' ? 'bg-white/70' : 'bg-muted'"
    />
    <Check v-else-if="status === 'sent'" class="size-3.5" :stroke-width="2.5" />
    <CheckCheck v-else class="size-3.5" :stroke-width="2.5" />
  </span>
</template>
