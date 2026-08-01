<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { attachmentPath, resolveAuthMediaUrl } from '@/utils/authMedia'

const props = defineProps<{
  path: string
  alt?: string
  kind?: 'image' | 'video'
}>()

const src = ref('')
const failed = ref(false)
let requestPath = ''

async function load() {
  const path = attachmentPath(props.path)
  requestPath = path
  failed.value = false
  src.value = ''
  try {
    const url = await resolveAuthMediaUrl(path)
    if (requestPath === path) src.value = url
  } catch {
    if (requestPath === path) failed.value = true
  }
}

watch(
  () => props.path,
  () => {
    void load()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  requestPath = ''
})
</script>

<template>
  <p v-if="failed" class="text-xs opacity-70">Не удалось загрузить вложение</p>
  <img
    v-else-if="kind !== 'video' && src"
    :src="src"
    :alt="alt || ''"
    class="max-h-64 w-full object-cover"
  />
  <video
    v-else-if="kind === 'video' && src"
    :src="src"
    controls
    class="max-h-64 w-full rounded-xl"
  />
  <div v-else class="h-24 animate-pulse rounded-xl bg-black/5" />
</template>
