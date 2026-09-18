<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, ChevronDown } from 'lucide-vue-next'

export type FilterSelectOption = { value: string; label: string }

const props = defineProps<{
  modelValue: string
  options: FilterSelectOption[]
  ariaLabel?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const open = ref(false)
const rootEl = ref<HTMLElement | null>(null)
const listEl = ref<HTMLElement | null>(null)

const selected = computed(
  () => props.options.find((o) => o.value === props.modelValue) ?? props.options[0] ?? null,
)

function close() {
  open.value = false
}

function toggle() {
  open.value = !open.value
}

function pick(value: string) {
  emit('update:modelValue', value)
  close()
}

function onDocPointer(e: PointerEvent) {
  if (!open.value || !rootEl.value) return
  if (e.target instanceof Node && rootEl.value.contains(e.target)) return
  close()
}

function onKey(e: KeyboardEvent) {
  if (!open.value) return
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
  }
}

watch(open, async (isOpen) => {
  if (!isOpen) return
  await nextTick()
  listEl.value?.querySelector<HTMLElement>('[data-active="1"]')?.focus()
})

onMounted(() => {
  document.addEventListener('pointerdown', onDocPointer)
  document.addEventListener('keydown', onKey)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocPointer)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="rootEl" class="relative">
    <button
      type="button"
      class="oe-filter-field oe-filter-select relative flex w-full items-center text-left"
      :aria-expanded="open"
      :aria-label="ariaLabel"
      @click="toggle"
    >
      <span class="min-w-0 flex-1 truncate">{{ selected?.label || '—' }}</span>
      <ChevronDown
        class="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-muted transition-transform duration-150"
        :class="open ? 'rotate-180' : ''"
        aria-hidden="true"
      />
    </button>

    <div
      v-if="open"
      ref="listEl"
      class="oe-filter-menu absolute left-0 right-0 z-50 mt-1.5 overflow-hidden py-1"
      role="listbox"
    >
      <button
        v-for="opt in options"
        :key="opt.value"
        type="button"
        role="option"
        class="oe-filter-menu-item"
        :data-active="opt.value === modelValue ? '1' : '0'"
        :aria-selected="opt.value === modelValue"
        @click="pick(opt.value)"
      >
        <span class="min-w-0 flex-1 truncate">{{ opt.label }}</span>
        <Check
          v-if="opt.value === modelValue"
          class="size-3.5 shrink-0 text-brand"
          aria-hidden="true"
        />
      </button>
    </div>
  </div>
</template>
