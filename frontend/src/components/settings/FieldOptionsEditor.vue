<script setup lang="ts">
import { Plus, Trash2 } from 'lucide-vue-next'

const options = defineModel<string[]>({ required: true })

function addRow() {
  options.value = [...options.value, '']
}

function removeRow(index: number) {
  if (options.value.length <= 1) {
    options.value = ['']
    return
  }
  options.value = options.value.filter((_, i) => i !== index)
}

function updateRow(index: number, value: string) {
  const next = [...options.value]
  next[index] = value
  options.value = next
}
</script>

<template>
  <div class="space-y-2 rounded-xl border border-line bg-panel p-3">
    <div class="flex items-center justify-between gap-2">
      <div class="text-xs font-semibold text-muted">Варианты списка</div>
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1 text-xs font-semibold text-muted transition hover:border-brand/40 hover:bg-brand-soft hover:text-brand"
        @click="addRow"
      >
        <Plus class="size-3.5" />
        Добавить
      </button>
    </div>
    <div class="space-y-2">
      <div v-for="(opt, idx) in options" :key="idx" class="flex items-center gap-2">
        <input
          :value="opt"
          :placeholder="`Вариант ${idx + 1}`"
          class="min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
          @input="updateRow(idx, ($event.target as HTMLInputElement).value)"
        />
        <button
          type="button"
          class="inline-flex size-9 shrink-0 items-center justify-center rounded-xl border border-line text-muted transition hover:border-danger/40 hover:bg-danger/10 hover:text-danger"
          title="Удалить вариант"
          @click="removeRow(idx)"
        >
          <Trash2 class="size-3.5" />
        </button>
      </div>
    </div>
  </div>
</template>
