<script setup lang="ts">
import { computed } from 'vue'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import type { Appeal } from '@/types'
import { appealStatusLabel } from '@/types'

const props = defineProps<{
  appeals: Appeal[]
  viewingAppealId: number | null
  currentAppealId?: number | null
}>()

const emit = defineEmits<{
  select: [appealId: number]
}>()

const sorted = computed(() =>
  [...props.appeals].sort((a, b) => a.number - b.number),
)

const hasPrevious = computed(() => sorted.value.length > 1)

const viewing = computed(
  () => sorted.value.find((a) => a.id === props.viewingAppealId) ?? null,
)

const viewingIndex = computed(() =>
  sorted.value.findIndex((a) => a.id === props.viewingAppealId),
)

const label = computed(() => {
  if (!hasPrevious.value) return 'Нет предыдущих заявок'
  const a = viewing.value
  if (!a) return 'Обращения'
  const when = new Date(a.openedAt).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
  const status = appealStatusLabel[a.status] || a.status
  const isCurrent = a.id === props.currentAppealId
  return `#${a.number} · ${status}${isCurrent ? '' : ' · архив'} · от ${when}`
})

function go(delta: number) {
  const idx = viewingIndex.value
  if (idx < 0) return
  const next = sorted.value[idx + delta]
  if (next) emit('select', next.id)
}

function pageVisible(index: number) {
  // Compact window around current page when many appeals.
  const total = sorted.value.length
  if (total <= 7) return true
  const cur = viewingIndex.value
  if (index === 0 || index === total - 1) return true
  return Math.abs(index - cur) <= 2
}
</script>

<template>
  <div
    v-if="hasPrevious"
    class="flex items-center gap-2 border-b border-line bg-panel/80 px-3 py-1.5 md:gap-3 md:px-5 md:py-2"
  >
    <div class="min-w-0 flex-1 text-center text-xs font-medium text-muted">
      <span
        class="inline-flex max-w-full items-center truncate rounded-full bg-surface px-2.5 py-1 md:px-3"
        :class="
          hasPrevious && viewing && viewing.id !== currentAppealId
            ? 'text-ink'
            : 'text-muted'
        "
      >
        {{ label }}
      </span>
    </div>

    <div class="flex shrink-0 items-center gap-0.5">
      <button
        type="button"
        class="flex size-9 items-center justify-center rounded-lg text-muted transition hover:bg-surface hover:text-ink disabled:opacity-30 md:size-7 md:rounded-md"
        :disabled="viewingIndex <= 0"
        title="Предыдущее обращение"
        @click="go(-1)"
      >
        <ChevronLeft class="size-4" />
      </button>
      <template v-for="(appeal, index) in sorted" :key="appeal.id">
        <span
          v-if="!pageVisible(index) && pageVisible(index - 1)"
          class="px-1 text-[11px] text-muted"
        >…</span>
        <button
          v-if="pageVisible(index)"
          type="button"
          class="flex size-9 items-center justify-center rounded-lg text-[12px] font-semibold transition md:size-7 md:rounded-md"
          :class="
            appeal.id === viewingAppealId
              ? 'bg-brand text-white'
              : 'text-muted hover:bg-surface hover:text-ink'
          "
          :title="`Обращение #${appeal.number}`"
          @click="emit('select', appeal.id)"
        >
          {{ appeal.number }}
        </button>
      </template>
      <button
        type="button"
        class="flex size-9 items-center justify-center rounded-lg text-muted transition hover:bg-surface hover:text-ink disabled:opacity-30 md:size-7 md:rounded-md"
        :disabled="viewingIndex < 0 || viewingIndex >= sorted.length - 1"
        title="Следующее обращение"
        @click="go(1)"
      >
        <ChevronRight class="size-4" />
      </button>
    </div>
  </div>
</template>
