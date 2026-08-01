<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRightLeft, UserRound } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import type { User } from '@/types'

const props = defineProps<{
  open: boolean
  operators: User[]
  currentAssigneeId: number | null
  currentUserId: number | null
  departmentId?: number | null
  busy?: boolean
}>()

const emit = defineEmits<{
  close: []
  transfer: [assigneeId: number | null]
}>()

const selectedId = ref<number | null>(null)

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) selectedId.value = props.currentAssigneeId
  },
)

const managers = computed(() => {
  const deptId = props.departmentId
  if (deptId == null) return props.operators
  return props.operators.filter(
    (u) => u.allChannels || (u.departmentIds ?? []).includes(deptId),
  )
})

function pick(id: number | null) {
  selectedId.value = id
}

function confirm() {
  if (selectedId.value === props.currentAssigneeId) {
    emit('close')
    return
  }
  emit('transfer', selectedId.value)
}
</script>

<template>
  <Modal v-if="open" title="Передать чат" @close="emit('close')">
    <p class="mb-4 text-sm text-muted">
      Выберите менеджера. После передачи чат появится у него во вкладке «Мои».
    </p>

    <div class="mb-3 max-h-72 space-y-1.5 overflow-auto">
      <button
        type="button"
        class="flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition"
        :class="
          selectedId === null
            ? 'border-brand bg-brand-soft/60'
            : 'border-line hover:border-brand/40 hover:bg-surface'
        "
        @click="pick(null)"
      >
        <div class="flex size-9 items-center justify-center rounded-full bg-surface text-muted">
          <UserRound class="size-4" />
        </div>
        <div class="min-w-0 flex-1">
          <div class="text-sm font-semibold">Без оператора</div>
          <div class="text-[11px] text-muted">Вернуть в «Новые»</div>
        </div>
      </button>

      <button
        v-for="u in managers"
        :key="u.id"
        type="button"
        class="flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition"
        :class="
          selectedId === u.id
            ? 'border-brand bg-brand-soft/60'
            : 'border-line hover:border-brand/40 hover:bg-surface'
        "
        @click="pick(u.id)"
      >
        <div
          class="flex size-9 items-center justify-center rounded-full bg-brand-soft text-xs font-bold text-brand"
        >
          {{ u.name.slice(0, 1).toUpperCase() }}
        </div>
        <div class="min-w-0 flex-1">
          <div class="truncate text-sm font-semibold">
            {{ u.name }}
            <span v-if="u.id === currentUserId" class="font-normal text-muted">(вы)</span>
          </div>
          <div class="truncate font-mono text-[11px] text-muted">{{ u.email }}</div>
        </div>
        <span
          v-if="u.id === currentAssigneeId"
          class="shrink-0 rounded-md bg-surface px-1.5 py-0.5 text-[10px] font-semibold text-muted"
        >
          сейчас
        </span>
      </button>
    </div>

    <p v-if="!managers.length" class="mb-3 text-sm text-muted">Нет доступных менеджеров</p>

    <div class="flex justify-end gap-2">
      <button
        type="button"
        class="rounded-xl border border-line px-3 py-2 text-sm"
        @click="emit('close')"
      >
        Отмена
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
        :disabled="busy"
        @click="confirm"
      >
        <ArrowRightLeft class="size-3.5" />
        {{ busy ? '…' : 'Передать' }}
      </button>
    </div>
  </Modal>
</template>
