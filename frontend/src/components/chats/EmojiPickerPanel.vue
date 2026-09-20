<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import data from '@emoji-mart/data'
import i18n from '@emoji-mart/data/i18n/ru.json'
import { Picker } from 'emoji-mart'

export type EmojiSelectPayload = {
  id: string
  name: string
  native: string
  unified: string
  keywords?: string[]
  shortcodes?: string
  skin?: number
}

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  select: [emoji: EmojiSelectPayload]
  close: []
}>()

const hostEl = ref<HTMLElement | null>(null)
let picker: HTMLElement | null = null
let ignoreOutsideUntil = 0

function destroyPicker() {
  if (!picker) return
  picker.remove()
  picker = null
}

async function mountPicker() {
  destroyPicker()
  await nextTick()
  const host = hostEl.value
  if (!host) return

  ignoreOutsideUntil = Date.now() + 250

  const instance = new Picker({
    data,
    i18n,
    locale: 'ru',
    theme: 'light',
    set: 'native',
    emojiVersion: 15,
    previewPosition: 'none',
    skinTonePosition: 'search',
    maxFrequentRows: 2,
    perLine: 8,
    emojiButtonSize: 36,
    emojiSize: 22,
    onEmojiSelect: (emoji: EmojiSelectPayload) => {
      if (emoji?.native) emit('select', emoji)
    },
    onClickOutside: () => {
      if (Date.now() < ignoreOutsideUntil) return
      emit('close')
    },
  })

  picker = instance as unknown as HTMLElement
  host.replaceChildren(picker)
}

watch(
  () => props.open,
  (open) => {
    if (open) void mountPicker()
    else destroyPicker()
  },
)

onBeforeUnmount(() => {
  destroyPicker()
})
</script>

<template>
  <div
    v-show="open"
    class="emoji-picker-panel absolute bottom-[calc(100%+0.5rem)] left-0 z-30 overflow-hidden rounded-2xl border border-line bg-panel shadow-xl shadow-black/10"
  >
    <div ref="hostEl" class="emoji-picker-host" />
  </div>
</template>

<style scoped>
.emoji-picker-panel {
  max-width: min(100vw - 1.5rem, 352px);
}

.emoji-picker-host :deep(em-emoji-picker) {
  --rgb-background: 255, 255, 255;
  --rgb-input: 244, 246, 249;
  --rgb-color: 21, 32, 51;
  border: none;
  width: 100%;
}
</style>
