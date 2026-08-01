<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Pause, Play } from 'lucide-vue-next'
import { attachmentPath, resolveAuthMediaUrl } from '@/utils/authMedia'

const props = defineProps<{
  src: string
  outgoing?: boolean
  fileName?: string
  durationHint?: number | null
}>()

const audio = ref<HTMLAudioElement | null>(null)
const resolvedSrc = ref('')
const playing = ref(false)
const current = ref(0)
const duration = ref(0)
const error = ref(false)
let requestPath = ''

async function loadSrc() {
  const path = attachmentPath(props.src)
  requestPath = path
  error.value = false
  resolvedSrc.value = ''
  // Optimistic / blob: already local
  if (path.startsWith('blob:') || path.startsWith('data:')) {
    resolvedSrc.value = path
    return
  }
  try {
    const url = await resolveAuthMediaUrl(path)
    if (requestPath === path) resolvedSrc.value = url
  } catch {
    if (requestPath === path) error.value = true
  }
}

watch(
  () => props.src,
  () => {
    playing.value = false
    current.value = 0
    duration.value = 0
    void loadSrc()
  },
  { immediate: true },
)

const total = computed(() => {
  if (duration.value > 0) return duration.value
  if (props.durationHint && props.durationHint > 0) return props.durationHint
  return 0
})

const progress = computed(() => {
  if (!total.value) return 0
  return Math.min(100, (current.value / total.value) * 100)
})

const bars = computed(() => {
  // Decorative waveform; seeded from filename for stable look per message.
  const seed = (props.fileName || props.src || 'voice')
    .split('')
    .reduce((acc, ch) => acc + ch.charCodeAt(0), 0)
  return Array.from({ length: 28 }, (_, i) => {
    const n = Math.sin(seed * 0.17 + i * 0.55) * 0.5 + 0.5
    return 22 + Math.round(n * 78)
  })
})

function formatDuration(sec: number) {
  if (!sec || !Number.isFinite(sec)) return '0:00'
  const s = Math.max(0, Math.floor(sec))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${String(r).padStart(2, '0')}`
}

function toggle() {
  const el = audio.value
  if (!el || error.value || !resolvedSrc.value) return
  if (playing.value) {
    el.pause()
  } else {
    void el.play().catch(() => {
      error.value = true
      playing.value = false
    })
  }
}

function onSeek(event: MouseEvent) {
  const el = audio.value
  if (!el || !total.value) return
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
  el.currentTime = ratio * total.value
  current.value = el.currentTime
}

onBeforeUnmount(() => {
  requestPath = ''
  audio.value?.pause()
})
</script>

<template>
  <div
    class="flex w-[240px] max-w-full items-center gap-3 rounded-2xl px-1 py-0.5"
    :class="outgoing ? 'text-white' : 'text-ink'"
  >
    <audio
      v-if="resolvedSrc"
      ref="audio"
      :src="resolvedSrc"
      preload="metadata"
      class="hidden"
      @play="playing = true"
      @pause="playing = false"
      @ended="playing = false; current = 0"
      @timeupdate="current = audio?.currentTime || 0"
      @loadedmetadata="duration = audio?.duration || 0"
      @error="error = true"
    />

    <button
      type="button"
      class="flex size-10 shrink-0 items-center justify-center rounded-full transition"
      :class="
        outgoing
          ? 'bg-white/20 hover:bg-white/30'
          : 'bg-brand text-white hover:brightness-105'
      "
      :disabled="error"
      @click="toggle"
    >
      <Pause v-if="playing" class="size-4" />
      <Play v-else class="ml-0.5 size-4" />
    </button>

    <div class="min-w-0 flex-1">
      <button
        type="button"
        class="flex h-8 w-full items-end gap-[2px]"
        :title="error ? 'Не удалось загрузить аудио' : 'Перемотка'"
        @click="onSeek"
      >
        <span
          v-for="(h, i) in bars"
          :key="i"
          class="w-[3px] rounded-full transition-colors"
          :style="{ height: `${h}%` }"
          :class="
            error
              ? outgoing
                ? 'bg-white/25'
                : 'bg-line'
              : i / bars.length <= progress / 100
                ? outgoing
                  ? 'bg-white'
                  : 'bg-brand'
                : outgoing
                  ? 'bg-white/35'
                  : 'bg-line'
          "
        />
      </button>
      <div
        class="mt-1 flex items-center justify-between text-[10px] font-medium"
        :class="outgoing ? 'text-white/75' : 'text-muted'"
      >
        <span>{{ error ? 'ошибка файла' : formatDuration(current || total) }}</span>
        <span v-if="!error && total">{{ formatDuration(total) }}</span>
      </div>
    </div>
  </div>
</template>
