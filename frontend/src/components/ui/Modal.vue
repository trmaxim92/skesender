<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps<{ title: string; wide?: boolean }>()
const emit = defineEmits<{ close: [] }>()

const panel = ref<HTMLElement | null>(null)

function onKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Escape') {
    ev.preventDefault()
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  // Move focus into dialog for keyboard users.
  requestAnimationFrame(() => {
    const focusable = panel.value?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    )
    focusable?.focus()
  })
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})

watch(
  () => props.title,
  () => {
    /* keep prop reactive for aria-labelledby consumers */
  },
)
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-[2px]"
    @click.self="emit('close')"
  >
    <div
      ref="panel"
      class="max-h-[90vh] w-full overflow-auto rounded-2xl border border-line bg-panel shadow-xl"
      :class="wide ? 'max-w-2xl' : 'max-w-lg'"
      role="dialog"
      aria-modal="true"
      :aria-label="title"
      @click.stop
    >
      <div class="flex items-center justify-between border-b border-line px-5 py-4">
        <h2 class="text-base font-semibold">{{ title }}</h2>
        <button
          type="button"
          class="rounded-lg px-2 py-1 text-sm text-muted hover:bg-surface hover:text-ink"
          aria-label="Закрыть"
          @click="emit('close')"
        >
          Закрыть
        </button>
      </div>
      <div class="p-5">
        <slot />
      </div>
    </div>
  </div>
</template>
