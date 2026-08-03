<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Download, X } from 'lucide-vue-next'
import AuthMedia from '@/components/chats/AuthMedia.vue'
import { attachmentPath, downloadAuthFile, resolveAuthMediaUrl } from '@/utils/authMedia'

export type GalleryImage = {
  id: number | string
  path: string
  fileName?: string
}

const props = defineProps<{
  images: GalleryImage[]
  index: number
}>()

const emit = defineEmits<{
  close: []
  'update:index': [value: number]
}>()

const src = ref('')
const failed = ref(false)
const loading = ref(false)
let requestKey = ''

const current = computed(() => props.images[props.index] ?? null)
const hasMany = computed(() => props.images.length > 1)
const counter = computed(() =>
  hasMany.value ? `${props.index + 1} / ${props.images.length}` : '',
)
const showStrip = computed(() => hasMany.value && props.images.length <= 24)

async function load() {
  const item = current.value
  if (!item) {
    src.value = ''
    return
  }
  const path = attachmentPath(item.path)
  requestKey = path
  failed.value = false
  loading.value = true
  src.value = ''
  try {
    const url = await resolveAuthMediaUrl(path)
    if (requestKey === path) src.value = url
  } catch {
    if (requestKey === path) failed.value = true
  } finally {
    if (requestKey === path) loading.value = false
  }
}

function close() {
  emit('close')
}

function go(delta: number) {
  if (!hasMany.value) return
  const next = (props.index + delta + props.images.length) % props.images.length
  emit('update:index', next)
}

async function downloadCurrent() {
  const item = current.value
  if (!item) return
  await downloadAuthFile(item.path, item.fileName)
}

function onKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Escape') {
    ev.preventDefault()
    close()
  } else if (ev.key === 'ArrowLeft') {
    ev.preventDefault()
    go(-1)
  } else if (ev.key === 'ArrowRight') {
    ev.preventDefault()
    go(1)
  }
}

watch(
  () => [props.index, current.value?.path] as const,
  () => {
    void load()
  },
  { immediate: true },
)

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  document.body.style.overflow = 'hidden'
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
  requestKey = ''
})
</script>

<template>
  <div
    class="fixed inset-0 z-[80] flex flex-col bg-ink/90 backdrop-blur-sm"
    role="dialog"
    aria-modal="true"
    aria-label="Просмотр фото"
    @click.self="close"
  >
    <header class="flex shrink-0 items-center justify-between gap-3 px-4 py-3 text-white">
      <div class="min-w-0">
        <p class="truncate text-sm font-medium">{{ current?.fileName || 'Фото' }}</p>
        <p v-if="counter" class="text-xs text-white/60">{{ counter }}</p>
      </div>
      <div class="flex shrink-0 items-center gap-1">
        <button
          type="button"
          class="flex size-10 items-center justify-center rounded-xl text-white/80 transition hover:bg-white/10 hover:text-white"
          title="Скачать"
          @click="downloadCurrent"
        >
          <Download class="size-4" />
        </button>
        <button
          type="button"
          class="flex size-10 items-center justify-center rounded-xl text-white/80 transition hover:bg-white/10 hover:text-white"
          title="Закрыть"
          @click="close"
        >
          <X class="size-5" />
        </button>
      </div>
    </header>

    <div class="relative flex min-h-0 flex-1 items-center justify-center px-2 pb-4 sm:px-14">
      <button
        v-if="hasMany"
        type="button"
        class="absolute left-2 z-10 flex size-11 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/20 sm:left-4"
        title="Предыдущее"
        @click="go(-1)"
      >
        <ChevronLeft class="size-6" />
      </button>

      <div class="flex max-h-full max-w-full items-center justify-center" @click.stop>
        <div v-if="loading && !src" class="size-40 animate-pulse rounded-2xl bg-white/10" />
        <p v-else-if="failed" class="text-sm text-white/70">Не удалось загрузить фото</p>
        <img
          v-else-if="src"
          :src="src"
          :alt="current?.fileName || ''"
          class="max-h-[calc(100vh-7rem)] max-w-full select-none object-contain"
          draggable="false"
        />
      </div>

      <button
        v-if="hasMany"
        type="button"
        class="absolute right-2 z-10 flex size-11 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/20 sm:right-4"
        title="Следующее"
        @click="go(1)"
      >
        <ChevronRight class="size-6" />
      </button>
    </div>

    <div
      v-if="showStrip"
      class="flex shrink-0 gap-2 overflow-x-auto px-4 pb-4"
      @click.stop
    >
      <button
        v-for="(img, i) in images"
        :key="img.id"
        type="button"
        class="size-14 shrink-0 overflow-hidden rounded-lg border-2 transition"
        :class="i === index ? 'border-brand' : 'border-transparent opacity-60 hover:opacity-100'"
        @click="emit('update:index', i)"
      >
        <AuthMedia
          :path="img.path"
          :alt="img.fileName"
          kind="image"
          img-class="size-full object-cover"
        />
      </button>
    </div>
  </div>
</template>
