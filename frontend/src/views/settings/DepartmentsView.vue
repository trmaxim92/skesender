<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  createDepartmentRequest,
  deleteDepartmentRequest,
  listDepartmentsRequest,
  mapDepartment,
  updateDepartmentRequest,
} from '@/api/settings'
import { ApiError } from '@/api/client'
import type { Department } from '@/types'

const departments = ref<Department[]>([])
const loading = ref(false)
const error = ref('')
const name = ref('')
const saving = ref(false)

const editId = ref<number | null>(null)
const editName = ref('')
const editSaving = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    departments.value = (await listDepartmentsRequest()).map(mapDepartment)
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
  try {
    const created = await createDepartmentRequest({ name: name.value.trim() })
    departments.value.push(mapDepartment(created))
    name.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось создать'
  } finally {
    saving.value = false
  }
}

function openEdit(d: Department) {
  editId.value = d.id
  editName.value = d.name
}

async function saveEdit() {
  if (editId.value == null || !editName.value.trim()) return
  editSaving.value = true
  try {
    const updated = await updateDepartmentRequest(editId.value, {
      name: editName.value.trim(),
    })
    const mapped = mapDepartment(updated)
    const idx = departments.value.findIndex((d) => d.id === mapped.id)
    if (idx >= 0) departments.value[idx] = mapped
    editId.value = null
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить'
  } finally {
    editSaving.value = false
  }
}

async function remove(d: Department) {
  if (d.slug === 'general') return
  if (!confirm(`Удалить отдел «${d.name}»? Каналы перейдут в «Общий».`)) return
  try {
    await deleteDepartmentRequest(d.id)
    departments.value = departments.value.filter((x) => x.id !== d.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить'
  }
}
</script>

<template>
  <div class="h-full overflow-auto p-6">
    <div class="mb-4 max-w-2xl space-y-1 text-sm text-muted">
      <p>Порядок работы:</p>
      <ol class="list-decimal space-y-0.5 pl-5">
        <li>Создайте отдел здесь</li>
        <li>В <span class="font-medium text-ink">Каналах</span> привяжите мессенджеры к отделу</li>
        <li>В <span class="font-medium text-ink">Пользователях</span> назначьте сотруднику отдел</li>
      </ol>
    </div>
    <p v-if="error" class="mb-3 text-sm text-danger">{{ error }}</p>

    <form class="mb-6 flex max-w-xl gap-2" @submit.prevent="create">
      <input
        v-model="name"
        required
        placeholder="Название отдела (например, Продажи)"
        class="flex-1 rounded-xl border border-line bg-panel px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
      />
      <button
        type="submit"
        class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        :disabled="saving"
      >
        Создать
      </button>
    </form>

    <p v-if="loading" class="text-sm text-muted">Загрузка…</p>
    <div v-else class="grid gap-3 md:grid-cols-2">
      <article
        v-for="d in departments"
        :key="d.id"
        class="rounded-2xl border border-line bg-panel p-4"
      >
        <div class="mb-1 flex items-start justify-between gap-2">
          <div>
            <h3 class="text-sm font-semibold">{{ d.name }}</h3>
            <p class="text-[11px] text-muted">
              каналов: {{ d.channelCount }} · {{ d.isActive ? 'активен' : 'выкл.' }}
            </p>
          </div>
          <div class="flex gap-1">
            <button
              type="button"
              class="rounded-lg px-2 py-1 text-xs text-muted hover:bg-surface hover:text-ink"
              @click="openEdit(d)"
            >
              Изменить
            </button>
            <button
              v-if="d.slug !== 'general'"
              type="button"
              class="rounded-lg px-2 py-1 text-xs text-danger hover:bg-surface"
              @click="remove(d)"
            >
              Удалить
            </button>
          </div>
        </div>

        <div
          v-if="editId === d.id"
          class="mt-3 space-y-2 border-t border-line pt-3"
        >
          <input
            v-model="editName"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
          />
          <div class="flex gap-2">
            <button
              type="button"
              class="rounded-xl bg-brand px-3 py-1.5 text-xs font-semibold text-white"
              :disabled="editSaving"
              @click="saveEdit"
            >
              Сохранить
            </button>
            <button
              type="button"
              class="rounded-xl px-3 py-1.5 text-xs text-muted"
              @click="editId = null"
            >
              Отмена
            </button>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>
