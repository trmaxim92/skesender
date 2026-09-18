<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Calendar, ChevronLeft, ChevronRight } from 'lucide-vue-next'

const props = defineProps<{
  modelValue: string
  ariaLabel?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const open = ref(false)
const rootEl = ref<HTMLElement | null>(null)
const viewYear = ref(new Date().getFullYear())
const viewMonth = ref(new Date().getMonth())

const MONTHS = [
  'Январь',
  'Февраль',
  'Март',
  'Апрель',
  'Май',
  'Июнь',
  'Июль',
  'Август',
  'Сентябрь',
  'Октябрь',
  'Ноябрь',
  'Декабрь',
]
const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

function parseYmd(value: string): Date | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const [y, m, d] = value.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) return null
  return dt
}

function toYmd(d: Date) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function formatDisplay(value: string) {
  const d = parseYmd(value)
  if (!d) return ''
  const day = String(d.getDate()).padStart(2, '0')
  const m = String(d.getMonth() + 1).padStart(2, '0')
  return `${day}.${m}.${d.getFullYear()}`
}

const display = computed(() => formatDisplay(props.modelValue))
const todayYmd = toYmd(new Date())

const cells = computed(() => {
  const first = new Date(viewYear.value, viewMonth.value, 1)
  // Monday-first: JS getDay() Sun=0 → shift
  const startPad = (first.getDay() + 6) % 7
  const daysInMonth = new Date(viewYear.value, viewMonth.value + 1, 0).getDate()
  const prevDays = new Date(viewYear.value, viewMonth.value, 0).getDate()
  const out: Array<{ ymd: string; day: number; inMonth: boolean }> = []

  for (let i = startPad - 1; i >= 0; i--) {
    const day = prevDays - i
    const d = new Date(viewYear.value, viewMonth.value - 1, day)
    out.push({ ymd: toYmd(d), day, inMonth: false })
  }
  for (let day = 1; day <= daysInMonth; day++) {
    const d = new Date(viewYear.value, viewMonth.value, day)
    out.push({ ymd: toYmd(d), day, inMonth: true })
  }
  const trailing = (7 - (out.length % 7)) % 7
  for (let day = 1; day <= trailing; day++) {
    const d = new Date(viewYear.value, viewMonth.value + 1, day)
    out.push({ ymd: toYmd(d), day, inMonth: false })
  }
  return out
})

const title = computed(() => `${MONTHS[viewMonth.value]} ${viewYear.value}`)

function syncViewFromValue() {
  const d = parseYmd(props.modelValue) ?? new Date()
  viewYear.value = d.getFullYear()
  viewMonth.value = d.getMonth()
}

function toggle() {
  if (!open.value) syncViewFromValue()
  open.value = !open.value
}

function close() {
  open.value = false
}

function prevMonth() {
  if (viewMonth.value === 0) {
    viewMonth.value = 11
    viewYear.value -= 1
  } else {
    viewMonth.value -= 1
  }
}

function nextMonth() {
  if (viewMonth.value === 11) {
    viewMonth.value = 0
    viewYear.value += 1
  } else {
    viewMonth.value += 1
  }
}

function pick(ymd: string) {
  emit('update:modelValue', ymd)
  close()
}

function clear() {
  emit('update:modelValue', '')
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

watch(
  () => props.modelValue,
  () => {
    if (open.value) syncViewFromValue()
  },
)

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
      class="oe-filter-field oe-filter-date flex w-full items-center text-left"
      :aria-expanded="open"
      :aria-label="ariaLabel"
      @click="toggle"
    >
      <span v-if="display" class="min-w-0 flex-1 truncate">{{ display }}</span>
      <span v-else class="min-w-0 flex-1 truncate text-muted">ДД.ММ.ГГГГ</span>
      <Calendar
        class="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-muted"
        aria-hidden="true"
      />
    </button>

    <div v-if="open" class="oe-filter-menu oe-filter-calendar absolute left-0 z-50 mt-1.5 w-[17.5rem] p-3">
      <div class="mb-2 flex items-center justify-between gap-1">
        <button
          type="button"
          class="inline-flex size-8 items-center justify-center rounded-lg text-muted transition hover:bg-surface hover:text-ink"
          aria-label="Предыдущий месяц"
          @click="prevMonth"
        >
          <ChevronLeft class="size-4" />
        </button>
        <div class="text-sm font-semibold text-ink">{{ title }}</div>
        <button
          type="button"
          class="inline-flex size-8 items-center justify-center rounded-lg text-muted transition hover:bg-surface hover:text-ink"
          aria-label="Следующий месяц"
          @click="nextMonth"
        >
          <ChevronRight class="size-4" />
        </button>
      </div>

      <div class="mb-1 grid grid-cols-7 gap-0.5">
        <span
          v-for="wd in WEEKDAYS"
          :key="wd"
          class="py-1 text-center text-[10px] font-semibold uppercase tracking-wide text-muted"
        >
          {{ wd }}
        </span>
      </div>

      <div class="grid grid-cols-7 gap-0.5">
        <button
          v-for="cell in cells"
          :key="cell.ymd"
          type="button"
          class="flex h-8 items-center justify-center rounded-lg text-sm transition"
          :class="[
            cell.inMonth ? 'text-ink' : 'text-muted/45',
            cell.ymd === modelValue
              ? 'bg-brand font-semibold text-white hover:bg-brand'
              : cell.ymd === todayYmd
                ? 'bg-brand-soft font-semibold text-brand hover:bg-brand-soft'
                : 'hover:bg-surface',
          ]"
          @click="pick(cell.ymd)"
        >
          {{ cell.day }}
        </button>
      </div>

      <div class="mt-2 flex items-center justify-between border-t border-line/70 pt-2">
        <button
          type="button"
          class="rounded-lg px-2 py-1 text-xs font-medium text-muted transition hover:bg-surface hover:text-ink"
          @click="clear"
        >
          Сбросить
        </button>
        <button
          type="button"
          class="rounded-lg px-2 py-1 text-xs font-semibold text-brand transition hover:bg-brand-soft"
          @click="pick(todayYmd)"
        >
          Сегодня
        </button>
      </div>
    </div>
  </div>
</template>
