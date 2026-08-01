<script setup lang="ts">
import { computed } from 'vue'
import type { ChannelStatus } from '@/types'
import { statusLabel } from '@/types'

const props = defineProps<{ status: ChannelStatus }>()

const color = computed(() => {
  switch (props.status) {
    case 'online':
      return 'bg-ok'
    case 'qr_pending':
    case 'connecting':
      return 'bg-warn'
    case 'error':
      return 'bg-danger'
    default:
      return 'bg-muted'
  }
})
</script>

<template>
  <span class="inline-flex items-center gap-1.5 text-xs font-medium text-muted">
    <span class="size-1.5 rounded-full" :class="color" />
    {{ statusLabel[status] }}
  </span>
</template>
