<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import FieldOptionsEditor from '@/components/settings/FieldOptionsEditor.vue'
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
import { useAuthStore } from '@/stores/auth'
import type { Department, FieldDefinition, FieldType } from '@/types'

const auth = useAuthStore()
const canWrite = computed(() => auth.can('action.write'))

const departments = ref<Department[]>([])
const departmentId = ref<number | null>(null)
const fields = ref<FieldDefinition[]>([])
const loading = ref(false)
const error = ref('')

const label = ref('')
const fieldType = ref<FieldType>('text')
const required = ref(false)
const optionRows = ref<string[]>([''])
const saving = ref(false)

const fieldTypes: { value: FieldType; label: string }[] = [
  { value: 'text', label: 'Текст' },
  { value: 'textarea', label: 'Многострочный' },
  { value: 'number', label: 'Число' },
  { value: 'phone', label: 'Телефон' },
  { value: 'link', label: 'Ссылка' },
  { value: 'select', label: 'Список' },
  { value: 'date', label: 'Дата' },
  { value: 'bool', label: 'Да/Нет' },
]

function typeLabel(type: FieldType | string) {
  return fieldTypes.find((t) => t.value === type)?.label || type
}

const selectedDept = computed(() => departments.value.find((d) => d.id === departmentId.value))
const visibleFields = computed(() =>
  [...fields.value].sort((a, b) => a.sortOrder - b.sortOrder || a.id - b.id),
)

watch(fieldType, (type) => {
  if (type === 'select' && !optionRows.value.length) {
    optionRows.value = ['']
  }
})

async function loadDepartments() {
  departments.value = (await listDepartmentsRequest()).map(mapDepartment)
  if (!departmentId.value && departments.value.length) {
    departmentId.value = departments.value[0]!.id
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
  if (!canWrite.value || !label.value.trim() || departmentId.value == null) return
  saving.value = true
  try {
    const options =
      fieldType.value === 'select'
        ? optionRows.value.map((s) => s.trim()).filter(Boolean)
        : []
    if (fieldType.value === 'select' && !options.length) {
      error.value = 'Добавьте хотя бы один вариант списка'
      saving.value = false
      return
    }
    const created = await createFieldRequest({
      scope: 'appeal',
      department_id: departmentId.value,
      label: label.value.trim(),
      field_type: fieldType.value,
      options,
      required: required.value,
      sort_order: (fields.value.at(-1)?.sortOrder ?? -10) + 10,
    })
    fields.value.push(mapFieldDefinition(created))
    label.value = ''
    optionRows.value = ['']
    fieldType.value = 'text'
    required.value = false
    error.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось добавить'
  } finally {
    saving.value = false
  }
}

async function patchField(f: FieldDefinition, payload: Parameters<typeof updateFieldRequest>[1]) {
  if (!canWrite.value) return
  try {
    const updated = await updateFieldRequest(f.id, payload)
    const mapped = mapFieldDefinition(updated)
    const idx = fields.value.findIndex((x) => x.id === mapped.id)
    if (idx >= 0) fields.value[idx] = mapped
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось обновить'
  }
}

async function removeField(f: FieldDefinition) {
  if (!canWrite.value) return
  if (!confirm(`Отключить поле «${f.label}»? Значения в обращениях сохранятся.`)) return
  try {
    await deleteFieldRequest(f.id)
    const idx = fields.value.findIndex((x) => x.id === f.id)
    if (idx >= 0) fields.value[idx] = { ...fields.value[idx]!, isActive: false }
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось отключить'
  }
}

async function moveField(f: FieldDefinition, dir: -1 | 1) {
  if (!canWrite.value) return
  const ordered = visibleFields.value
  const idx = ordered.findIndex((x) => x.id === f.id)
  const swap = ordered[idx + dir]
  if (!swap) return
  const aOrder = f.sortOrder
  const bOrder = swap.sortOrder
  await patchField(f, { sort_order: bOrder })
  await patchField(swap, { sort_order: aOrder })
}
</script>

<template>
  <div class="h-full overflow-auto p-4 md:p-6">
    <div class="mb-4 max-w-2xl space-y-1 text-sm text-muted">
      <p>
        Набор полей обращения — <span class="font-medium text-ink">отдельный для каждого отдела</span>
        (поддержка, продажи и т.д.). В карточке показывается набор отдела обращения/канала.
      </p>
      <p>
        Сейчас редактируете:
        <span class="font-medium text-ink">{{ selectedDept?.name || '…' }}</span>
      </p>
    </div>
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

    <form v-if="canWrite" class="mb-6 grid max-w-3xl gap-2 sm:grid-cols-4" @submit.prevent="addField">
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
      <label class="flex items-center gap-2 text-sm text-ink sm:col-span-2">
        <input v-model="required" type="checkbox" />
        Обязательное
      </label>
      <div v-if="fieldType === 'select'" class="sm:col-span-4">
        <FieldOptionsEditor v-model="optionRows" />
      </div>
    </form>

    <p v-if="loading" class="text-sm text-muted">Загрузка…</p>
    <div v-else class="overflow-x-auto rounded-2xl border border-line bg-panel">
      <table class="w-full min-w-[720px] text-left text-sm">
        <thead class="border-b border-line bg-surface text-xs uppercase text-muted">
          <tr>
            <th class="px-4 py-3">Поле</th>
            <th class="px-4 py-3">Тип</th>
            <th class="px-4 py-3">Обяз.</th>
            <th class="px-4 py-3">Активно</th>
            <th class="px-4 py-3">Порядок</th>
            <th class="px-4 py-3"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="f in visibleFields"
            :key="f.id"
            class="border-b border-line last:border-0"
            :class="f.isActive ? '' : 'opacity-50'"
          >
            <td class="px-4 py-3">
              <input
                class="w-full rounded-lg border border-transparent bg-transparent px-1 py-0.5 hover:border-line focus:border-line"
                :value="f.label"
                :readonly="!canWrite"
                @change="patchField(f, { label: ($event.target as HTMLInputElement).value })"
              />
              <div class="mt-0.5 font-mono text-[10px] text-muted">{{ f.key }}</div>
            </td>
            <td class="px-4 py-3 text-muted">{{ typeLabel(f.fieldType) }}</td>
            <td class="px-4 py-3">
              <input
                type="checkbox"
                :checked="f.required"
                :disabled="!canWrite"
                @change="
                  patchField(f, {
                    required: ($event.target as HTMLInputElement).checked,
                  })
                "
              />
            </td>
            <td class="px-4 py-3">
              <input
                type="checkbox"
                :checked="f.isActive"
                :disabled="!canWrite"
                @change="
                  patchField(f, {
                    is_active: ($event.target as HTMLInputElement).checked,
                  })
                "
              />
            </td>
            <td class="px-4 py-3">
              <div v-if="canWrite" class="flex gap-1">
                <button
                  type="button"
                  class="rounded border border-line px-2 py-0.5 text-xs hover:bg-surface"
                  @click="moveField(f, -1)"
                >
                  ↑
                </button>
                <button
                  type="button"
                  class="rounded border border-line px-2 py-0.5 text-xs hover:bg-surface"
                  @click="moveField(f, 1)"
                >
                  ↓
                </button>
              </div>
            </td>
            <td class="px-4 py-3 text-right">
              <button
                v-if="canWrite && f.isActive"
                type="button"
                class="text-xs text-danger hover:underline"
                @click="removeField(f)"
              >
                Отключить
              </button>
              <span v-else-if="!f.isActive" class="text-[11px] text-muted">выкл.</span>
            </td>
          </tr>
          <tr v-if="!visibleFields.length">
            <td colspan="6" class="px-4 py-6 text-center text-sm text-muted">
              Пока нет полей — добавьте первое для этого отдела
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
