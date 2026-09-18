<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  createAppealStatusRequest,
  deleteAppealStatusRequest,
  listAppealStatusesManageRequest,
  mapAppealStatusDef,
  updateAppealStatusRequest,
} from '@/api/appealStatuses'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { AppealStatusDef } from '@/types'

const auth = useAuthStore()
const canWrite = computed(() => auth.can('action.write'))

const items = ref<AppealStatusDef[]>([])
const loading = ref(false)
const error = ref('')
const saving = ref(false)

const name = ref('')
const color = ref('#1a6dff')
const isTerminal = ref(false)
const needsCallback = ref(false)
const countsAsOpen = ref(true)

const editId = ref<number | null>(null)
const editName = ref('')
const editColor = ref('#9ca3af')
const editTerminal = ref(false)
const editCallback = ref(false)
const editOpen = ref(true)
const editActive = ref(true)
const editSaving = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    items.value = (await listAppealStatusesManageRequest()).map(mapAppealStatusDef)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})

async function create() {
  if (!canWrite.value || !name.value.trim()) return
  saving.value = true
  error.value = ''
  try {
    const created = await createAppealStatusRequest({
      name: name.value.trim(),
      color: color.value,
      is_terminal: isTerminal.value,
      needs_callback: needsCallback.value,
      counts_as_open: isTerminal.value ? false : countsAsOpen.value,
      sort_order: (items.value.at(-1)?.sortOrder ?? 0) + 10,
    })
    items.value.push(mapAppealStatusDef(created))
    name.value = ''
    color.value = '#1a6dff'
    isTerminal.value = false
    needsCallback.value = false
    countsAsOpen.value = true
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось создать'
  } finally {
    saving.value = false
  }
}

function openEdit(s: AppealStatusDef) {
  if (!canWrite.value) return
  editId.value = s.id
  editName.value = s.name
  editColor.value = s.color
  editTerminal.value = s.isTerminal
  editCallback.value = s.needsCallback
  editOpen.value = s.countsAsOpen
  editActive.value = s.isActive
}

async function saveEdit() {
  if (!canWrite.value || editId.value == null || !editName.value.trim()) return
  editSaving.value = true
  error.value = ''
  try {
    const updated = await updateAppealStatusRequest(editId.value, {
      name: editName.value.trim(),
      color: editColor.value,
      is_terminal: editTerminal.value,
      needs_callback: editCallback.value,
      counts_as_open: editTerminal.value ? false : editOpen.value,
      is_active: editActive.value,
    })
    const mapped = mapAppealStatusDef(updated)
    const idx = items.value.findIndex((x) => x.id === mapped.id)
    if (idx >= 0) items.value[idx] = mapped
    editId.value = null
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить'
  } finally {
    editSaving.value = false
  }
}

async function remove(s: AppealStatusDef) {
  if (!canWrite.value || s.slug === 'new') return
  if (!confirm(`Удалить статус «${s.name}»? Обращения перейдут в «Новое».`)) return
  try {
    await deleteAppealStatusRequest(s.id)
    items.value = items.value.filter((x) => x.id !== s.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить'
  }
}
</script>

<template>
  <div class="h-full overflow-auto p-6">
    <div class="mb-4 max-w-2xl space-y-1 text-sm text-muted">
      <p>
        Статусы — этапы обзвона в разделе «Клиенты». Можно переименовывать, отключать и
        удалять (кроме базового «Новое»). Флаги: завершает кейс / очередь «Перезвонить».
      </p>
    </div>
    <p v-if="error" class="mb-3 text-sm text-danger">{{ error }}</p>

    <form
      v-if="canWrite"
      class="mb-6 max-w-2xl space-y-3 rounded-xl border border-line bg-panel p-4"
      @submit.prevent="create"
    >      <div class="flex flex-wrap gap-2">
        <input
          v-model="name"
          required
          placeholder="Название статуса"
          class="min-w-[12rem] flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
        />
        <label class="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-sm">
          <span class="text-muted">Цвет</span>
          <input v-model="color" type="color" class="size-7 cursor-pointer rounded border-0 bg-transparent" />
        </label>
        <button
          type="submit"
          class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="saving"
        >
          Добавить
        </button>
      </div>
      <div class="flex flex-wrap gap-4 text-sm text-ink">
        <label class="flex items-center gap-2">
          <input v-model="isTerminal" type="checkbox" class="rounded border-line" />
          Завершает обращение
        </label>
        <label class="flex items-center gap-2">
          <input v-model="needsCallback" type="checkbox" class="rounded border-line" />
          Перезвонить
        </label>
        <label class="flex items-center gap-2">
          <input v-model="countsAsOpen" type="checkbox" class="rounded border-line" :disabled="isTerminal" />
          Считается открытым
        </label>
      </div>
    </form>

    <p v-if="loading" class="text-sm text-muted">Загрузка…</p>
    <div v-else class="grid gap-3 md:grid-cols-2">
      <article
        v-for="s in items"
        :key="s.id"
        class="rounded-xl border border-line bg-panel p-4"
      >
        <div v-if="editId === s.id" class="space-y-3">
          <div class="flex gap-2">
            <input
              v-model="editName"
              class="flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
            />
            <input v-model="editColor" type="color" class="size-9 rounded border border-line" />
          </div>
          <div class="flex flex-wrap gap-3 text-sm">
            <label class="flex items-center gap-2">
              <input v-model="editTerminal" type="checkbox" />
              Завершает
            </label>
            <label class="flex items-center gap-2">
              <input v-model="editCallback" type="checkbox" />
              Перезвонить
            </label>
            <label class="flex items-center gap-2">
              <input v-model="editOpen" type="checkbox" :disabled="editTerminal" />
              Открытое
            </label>
            <label class="flex items-center gap-2">
              <input v-model="editActive" type="checkbox" :disabled="s.slug === 'new'" />
              Активен
            </label>
          </div>
          <div class="flex gap-2">
            <button
              type="button"
              class="rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
              :disabled="editSaving"
              @click="saveEdit"
            >
              Сохранить
            </button>
            <button
              type="button"
              class="rounded-lg border border-line px-3 py-1.5 text-sm"
              @click="editId = null"
            >
              Отмена
            </button>
          </div>
        </div>
        <template v-else>
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <span class="size-2.5 shrink-0 rounded-full" :style="{ background: s.color }" />
                <h3 class="truncate font-semibold text-ink">{{ s.name }}</h3>
                <span
                  v-if="s.slug === 'new'"
                  class="rounded bg-surface px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted"
                >базовый</span>
              </div>
              <p class="mt-2 flex flex-wrap gap-2 text-xs text-muted">
                <span>{{ s.isTerminal ? 'завершает' : 'в работе' }}</span>
                <span>·</span>
                <span>{{ s.needsCallback ? 'перезвонить' : 'без перезвона' }}</span>
                <span>·</span>
                <span>{{ s.countsAsOpen ? 'открытое' : 'закрытое' }}</span>
                <span v-if="!s.isActive">· выключен</span>
              </p>
            </div>
            <div v-if="canWrite" class="flex shrink-0 gap-1">
              <button
                type="button"
                class="rounded-lg px-2 py-1 text-xs text-brand hover:bg-brand-soft"
                @click="openEdit(s)"
              >
                Изменить
              </button>
              <button
                v-if="s.slug !== 'new'"
                type="button"
                class="rounded-lg px-2 py-1 text-xs text-danger hover:bg-danger/10"
                @click="remove(s)"
              >
                Удалить
              </button>
            </div>
          </div>
        </template>
      </article>
    </div>
  </div>
</template>
