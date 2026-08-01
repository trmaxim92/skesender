<script setup lang="ts">
import { ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    name: string
    url?: string | null
    size?: 'sm' | 'md' | 'lg'
  }>(),
  { url: null, size: 'md' },
)

const failed = ref(false)

watch(
  () => props.url,
  () => {
    failed.value = false
  },
)

const sizeClass = {
  sm: 'size-8 text-[11px]',
  md: 'size-10 text-xs',
  lg: 'size-12 text-sm',
}

function initials(name: string) {
  const parts = (name || '?').trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}
</script>

<template>
  <div
    class="flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface font-bold text-muted ring-1 ring-line"
    :class="sizeClass[size]"
    :title="name"
  >
    <img
      v-if="url && !failed"
      :src="url"
      :alt="name"
      class="size-full object-cover"
      loading="lazy"
      referrerpolicy="no-referrer"
      @error="failed = true"
    />
    <span v-else>{{ initials(name) }}</span>
  </div>
</template>
