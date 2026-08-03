<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  createFieldRequest,
  deleteFieldRequest,
  listDepartmentsRequest,
  listFieldsRequest,
  mapDepartment,
  mapFieldDefinition,
  updateFieldRequest,
} from '@/api/settings'
import { ApiError } from '@/api/client'
import type { Department, FieldDefinition, FieldType } from '@/types'

const departments = ref<Department[]>([])
const departmentId = ref<number | null>(null)
const fields = ref<FieldDefinition[]>([])
const loading = ref(false)
const error = ref('')

const label = ref('')
const fieldType = ref<FieldType>('text')
const optionsText = ref('')
const saving = ref(false)

const fieldTypes: { value: FieldType; label: string }[] = [
  { value: 'text', label: 'Текст' },
  { value: 'textarea', label: 'Многострочный' },
  { value: 'number', label: 'Число' },
  { value: 'phone', label: 'Телефон' },
  { value: 'select', label: 'Список' },
  { value: 'date', label: 'Дата' },
  { value: 'bool', label: 'Да/Нет' },
]

const selectedDept = computed(() => departments.value.find((d) => d.id === departmentId.value))

async function loadDepartments() {
  departments.value = (await listDepartmentsRequest()).map(mapDepartment)
  if (!departmentId.value && departments.value.length) {
    departmentId.value = departments.value[0].id
  }
}

async function loadFields() {
  if (departmentId.value == null) {
    fields.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    fields.value = (
      await listFieldsRequest({
        scope: 'appeal',
        department_id: departmentId.value,
        include_inactive: true,
      })
    ).map(mapFieldDefinition)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить поля'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    await loadDepartments()
    await loadFields()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Ошибка загрузки'
  }
})

watch(departmentId, () => {
  void loadFields()
})

async function addField() {
  if (!label.value.trim() || departmentId.value == null) return
  saving.value = true
  try {
    const options =
      fieldType.value === 'select'
        ? optionsText.value
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
        : []
    const created = await createFieldRequest({
      scope: 'appeal',
      department_id: departmentId.value,
      label: label.value.trim(),
      field_type: fieldType.value,
      options,
      sort_order: fields.value.length,
    })
    fields.value.push(mapFieldDefinition(created))
    label.value = ''
    optionsText.value = ''
    fieldType.value = 'text'
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось добавить'
  } finally {
    saving.value = false
  }
}

async function removeField(f: FieldDefinition) {
  if (f.isSystem) return
  if (!confirm(`Удалить поле «${f.label}»?`)) return
  try {
    await deleteFieldRequest(f.id)
    fields.value = fields.value.filter((x) => x.id !== f.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить'
  }
}

async function renameField(f: FieldDefinition, newLabel: string) {
  const trimmed = newLabel.trim()
  if (!trimmed || trimmed === f.label) return
  try {
    const updated = await updateFieldRequest(f.id, { label: trimmed })
    const mapped = mapFieldDefinition(updated)
    const idx = fields.value.findIndex((x) => x.id === f.id)
    if (idx >= 0) fields.value[idx] = mapped
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось обновить'
  }
}
</script>

<template>
  <div class="h-full overflow-auto p-4 md:p-6">
    <p class="mb-4 text-sm text-muted">
      Набор полей обращения зависит от отдела. У
      <span class="font-medium text-ink">{{ selectedDept?.name || '…' }}</span>
      свой список.
    </p>
    <p v-if="error" class="mb-3 text-sm text-danger">{{ error }}</p>

    <div class="mb-4 max-w-sm">
      <label class="mb-1 block text-xs font-semibold text-muted">Отдел</label>
      <select
        v-model.number="departmentId"
        class="w-full rounded-xl border border-line bg-panel px-3 py-2 text-sm"
      >
        <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
      </select>
    </div>

    <form class="mb-6 grid max-w-3xl gap-2 sm:grid-cols-4" @submit.prevent="addField">
      <input
        v-model="label"
        required
        placeholder="Название поля"
        class="rounded-xl border border-line bg-panel px-3 py-2 text-sm sm:col-span-2"
      />
      <select v-model="fieldType" class="rounded-xl border border-line bg-panel px-3 py-2 text-sm">
        <option v-for="t in fieldTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
      </select>
      <button
        type="submit"
        class="rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
        :disabled="saving"
      >
        Добавить
      </button>
      <input
        v-if="fieldType === 'select'"
        v-model="optionsText"
        placeholder="Варианты через запятую"
        class="rounded-xl border border-line bg-panel px-3 py-2 text-sm sm:col-span-4"
      />
    </form>

    <p v-if="loading" class="text-sm text-muted">Загрузка…</p>
    <div v-else class="overflow-x-auto rounded-2xl border border-line bg-panel">
      <table class="w-full min-w-[560px] text-left text-sm">
        <thead class="border-b border-line bg-surface text-xs uppercase text-muted">
          <tr>
            <th class="px-4 py-3">Поле</th>
            <th class="px-4 py-3">Тип</th>
            <th class="px-4 py-3">Ключ</th>
            <th class="px-4 py-3"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in fields" :key="f.id" class="border-b border-line last:border-0">
            <td class="px-4 py-3">
              <input
                class="w-full rounded-lg border border-transparent bg-transparent px-1 py-0.5 hover:border-line focus:border-line"
                :value="f.label"
                @change="renameField(f, ($event.target as HTMLInputElement).value)"
              />
            </td>
            <td class="px-4 py-3 text-muted">{{ f.fieldType }}</td>
            <td class="px-4 py-3 font-mono text-xs text-muted">{{ f.key }}</td>
            <td class="px-4 py-3 text-right">
              <button
                type="button"
                class="text-xs text-danger hover:underline"
                @click="removeField(f)"
              >
                Удалить
              </button>
            </td>
          </tr>
          <tr v-if="!fields.length">
            <td colspan="4" class="px-4 py-6 text-center text-sm text-muted">
              Пока нет полей — добавьте первое
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
