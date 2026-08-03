<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  createPresenceStatusRequest,
  deletePresenceStatusRequest,
  listPresenceStatusesManageRequest,
  mapPresenceStatus,
  updatePresenceStatusRequest,
} from '@/api/presence'
import { ApiError } from '@/api/client'
import type { PresenceStatus } from '@/types'

const items = ref<PresenceStatus[]>([])
const loading = ref(false)
const error = ref('')
const saving = ref(false)

const name = ref('')
const color = ref('#6366f1')
const participatesInRouting = ref(false)
const canWriteChats = ref(true)
const onDuty = ref(true)

const editId = ref<number | null>(null)
const editName = ref('')
const editColor = ref('#9ca3af')
const editRouting = ref(false)
const editWrite = ref(true)
const editOnDuty = ref(true)
const editActive = ref(true)
const editSaving = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    items.value = (await listPresenceStatusesManageRequest()).map(mapPresenceStatus)
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
  if (!name.value.trim()) return
  saving.value = true
  error.value = ''
  try {
    const created = await createPresenceStatusRequest({
      name: name.value.trim(),
      color: color.value,
      participates_in_routing: participatesInRouting.value,
      can_write_chats: canWriteChats.value,
      on_duty: onDuty.value,
      sort_order: (items.value.at(-1)?.sortOrder ?? 0) + 10,
    })
    items.value.push(mapPresenceStatus(created))
    name.value = ''
    color.value = '#6366f1'
    participatesInRouting.value = false
    canWriteChats.value = true
    onDuty.value = true
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось создать'
  } finally {
    saving.value = false
  }
}

function openEdit(s: PresenceStatus) {
  editId.value = s.id
  editName.value = s.name
  editColor.value = s.color
  editRouting.value = s.participatesInRouting
  editWrite.value = s.canWriteChats
  editOnDuty.value = s.onDuty
  editActive.value = s.isActive
}

async function saveEdit() {
  if (editId.value == null || !editName.value.trim()) return
  editSaving.value = true
  error.value = ''
  try {
    const updated = await updatePresenceStatusRequest(editId.value, {
      name: editName.value.trim(),
      color: editColor.value,
      participates_in_routing: editRouting.value,
      can_write_chats: editWrite.value,
      on_duty: editOnDuty.value,
      is_active: editActive.value,
    })
    const mapped = mapPresenceStatus(updated)
    const idx = items.value.findIndex((x) => x.id === mapped.id)
    if (idx >= 0) items.value[idx] = mapped
    editId.value = null
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить'
  } finally {
    editSaving.value = false
  }
}

async function remove(s: PresenceStatus) {
  if (s.isSystem) return
  if (!confirm(`Удалить статус «${s.name}»? Сотрудники перейдут в «Оффлайн».`)) return
  try {
    await deletePresenceStatusRequest(s.id)
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
        Статусы присутствия — поверх роли. Роль задаёт потолок прав, статус может только сужать
        (например запретить писать в чаты или автораспределение).
      </p>
    </div>
    <p v-if="error" class="mb-3 text-sm text-danger">{{ error }}</p>

    <form class="mb-6 max-w-2xl space-y-3 rounded-xl border border-line bg-panel p-4" @submit.prevent="create">
      <div class="flex flex-wrap gap-2">
        <input
          v-model="name"
          required
          placeholder="Название статуса"
          class="min-w-[12rem] flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
        />
        <label class="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-sm">
          <span class="text-mute">Цвет</span>
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
          <input v-model="participatesInRouting" type="checkbox" class="rounded border-line" />
          Автораспределение
        </label>
        <label class="flex items-center gap-2">
          <input v-model="canWriteChats" type="checkbox" class="rounded border-line" />
          Писать в чаты
        </label>
        <label class="flex items-center gap-2">
          <input v-model="onDuty" type="checkbox" class="rounded border-line" />
          На смене
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
              <input v-model="editRouting" type="checkbox" />
              Автораспределение
            </label>
            <label class="flex items-center gap-2">
              <input v-model="editWrite" type="checkbox" />
              Писать в чаты
            </label>
            <label class="flex items-center gap-2">
              <input v-model="editOnDuty" type="checkbox" />
              На смене
            </label>
            <label class="flex items-center gap-2">
              <input v-model="editActive" type="checkbox" :disabled="s.slug === 'offline'" />
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
                  v-if="s.isSystem"
                  class="rounded bg-surface px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-mute"
                >системный</span>
              </div>
              <p class="mt-2 flex flex-wrap gap-2 text-xs text-mute">
                <span>{{ s.participatesInRouting ? 'автораспред.' : 'без автораспред.' }}</span>
                <span>·</span>
                <span>{{ s.canWriteChats ? 'писать' : 'только просмотр' }}</span>
                <span>·</span>
                <span>{{ s.onDuty ? 'на смене' : 'не на смене' }}</span>
                <span v-if="!s.isActive">· выключен</span>
              </p>
            </div>
            <div class="flex shrink-0 gap-1">
              <button
                type="button"
                class="rounded-lg px-2 py-1 text-xs text-brand hover:bg-brand-soft"
                @click="openEdit(s)"
              >
                Изменить
              </button>
              <button
                v-if="!s.isSystem"
                type="button"
                class="rounded-lg px-2 py-1 text-xs text-danger hover:bg-danger-soft"
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
