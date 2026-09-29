<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, ChevronDown } from 'lucide-vue-next'

export type SoftSelectOption = { value: string; label: string }

const props = withDefaults(
  defineProps<{
    modelValue: string
    options: SoftSelectOption[]
    ariaLabel?: string
    placeholder?: string
    disabled?: boolean
  }>(),
  {
    placeholder: 'Выберите…',
    disabled: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const open = ref(false)
const rootEl = ref<HTMLElement | null>(null)
const listEl = ref<HTMLElement | null>(null)

const selected = computed(
  () => props.options.find((o) => o.value === props.modelValue) ?? null,
)

const displayLabel = computed(() => selected.value?.label || props.placeholder)

const isPlaceholder = computed(() => !props.modelValue)

function close() {
  open.value = false
}

function toggle() {
  if (props.disabled) return
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
      class="relative flex h-[2.625rem] w-full items-center rounded-xl border border-line bg-surface px-3.5 pr-10 text-left text-sm outline-none transition ring-brand/20"
      :class="[
        disabled ? 'cursor-not-allowed opacity-60' : 'hover:border-brand/30 focus:ring-2',
        open ? 'border-brand/40 ring-2' : '',
        isPlaceholder ? 'text-muted' : 'text-ink',
      ]"
      :aria-expanded="open"
      :aria-label="ariaLabel"
      :disabled="disabled"
      @click="toggle"
    >
      <span class="min-w-0 flex-1 truncate">{{ displayLabel }}</span>
      <ChevronDown
        class="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted transition-transform duration-150"
        :class="open ? 'rotate-180' : ''"
        aria-hidden="true"
      />
    </button>

    <div
      v-if="open"
      ref="listEl"
      class="absolute left-0 right-0 z-50 mt-1.5 max-h-60 overflow-auto rounded-xl border border-line bg-panel py-1 shadow-lg"
      role="listbox"
    >
      <button
        v-for="opt in options"
        :key="opt.value === '' ? '__empty' : opt.value"
        type="button"
        role="option"
        class="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-sm transition hover:bg-surface focus-visible:bg-surface focus-visible:outline-none"
        :class="opt.value === modelValue ? 'bg-brand-soft/50 text-brand' : 'text-ink'"
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
