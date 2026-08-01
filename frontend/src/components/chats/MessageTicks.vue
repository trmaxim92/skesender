<script setup lang="ts">
import { Check, CheckCheck } from 'lucide-vue-next'
import { computed } from 'vue'
import { messageStatusLabel, type MessageStatus } from '@/types'

const props = withDefaults(
  defineProps<{
    status: MessageStatus
    /** onBrand — на синем пузыре; muted — в списке диалогов */
    tone?: 'onBrand' | 'muted'
  }>(),
  { tone: 'muted' },
)

const title = computed(() => messageStatusLabel[props.status] || props.status)

const colorClass = computed(() => {
  if (props.status === 'failed') {
    return props.tone === 'onBrand' ? 'text-red-200' : 'text-danger'
  }
  if (props.status === 'read') {
    // Яркий циан на бирюзовом пузыре — не сливается с «доставлено».
    return props.tone === 'onBrand' ? 'text-read-tick' : 'text-sky-500'
  }
  return props.tone === 'onBrand' ? 'text-white/70' : 'text-muted'
})
</script>

<template>
  <span
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
