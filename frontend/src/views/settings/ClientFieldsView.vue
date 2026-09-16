<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Lock } from 'lucide-vue-next'
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
import type { Department, FieldDefinition, FieldType } from '@/types'

/** null = shared (all departments); number = department extras */
const contextDeptId = ref<number | null>(null)
const departments = ref<Department[]>([])
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

const contextLabel = computed(() => {
  if (contextDeptId.value == null) return 'Общие (все отделы)'
  return departments.value.find((d) => d.id === contextDeptId.value)?.name || 'Отдел'
})

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
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (contextDeptId.value == null) {
      fields.value = (
        await listFieldsRequest({ scope: 'client', include_inactive: true })
      ).map(mapFieldDefinition)
    } else {
      fields.value = (
        await listFieldsRequest({
          scope: 'client',
          department_id: contextDeptId.value,
          include_inactive: true,
          manage: true,
        })
      ).map(mapFieldDefinition)
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    await loadDepartments()
    await load()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Ошибка загрузки'
  }
})

watch(contextDeptId, () => {
  void load()
})

async function addField() {
  if (!label.value.trim()) return
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
      scope: 'client',
      department_id: contextDeptId.value,
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
  if (f.isSystem) return
  if (!confirm(`Отключить поле «${f.label}»?`)) return
  try {
    await deleteFieldRequest(f.id)
    const idx = fields.value.findIndex((x) => x.id === f.id)
    if (idx >= 0) fields.value[idx] = { ...fields.value[idx]!, isActive: false }
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось отключить'
  }
}

async function moveField(f: FieldDefinition, dir: -1 | 1) {
  if (f.isSystem) return
  const ordered = visibleFields.value.filter((x) => !x.isSystem)
  const idx = ordered.findIndex((x) => x.id === f.id)
  const swap = ordered[idx + dir]
  if (!swap) return
  await patchField(f, { sort_order: swap.sortOrder })
  await patchField(swap, { sort_order: f.sortOrder })
}
</script>

<template>
  <div class="h-full overflow-auto p-4 md:p-6">
    <div class="mb-4 max-w-2xl space-y-1 text-sm text-muted">
      <p>
        <span class="font-medium text-ink">Общие</span> поля видят все отделы (ФИО, телефон…).
        Дополнительно у каждого отдела — свой набор полей карточки клиента.
      </p>
      <p>
        В чате/обращении оператор видит общие + поля
        <span class="font-medium text-ink">отдела обращения</span>.
      </p>
    </div>
    <p v-if="error" class="mb-3 text-sm text-danger">{{ error }}</p>

    <div class="mb-4 max-w-sm">
      <label class="mb-1 block text-xs font-semibold text-muted">Контекст</label>
      <select
        class="w-full rounded-xl border border-line bg-panel px-3 py-2 text-sm"
        :value="contextDeptId == null ? '' : String(contextDeptId)"
        @change="
          contextDeptId = ($event.target as HTMLSelectElement).value
            ? Number(($event.target as HTMLSelectElement).value)
            : null
        "
      >
        <option value="">Общие (все отделы)</option>
        <option v-for="d in departments" :key="d.id" :value="String(d.id)">
          Доп. поля: {{ d.name }}
        </option>
      </select>
      <p class="mt-1 text-xs text-muted">Сейчас: {{ contextLabel }}</p>
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
              <div class="flex items-center gap-1.5">
                <Lock v-if="f.isSystem" class="size-3.5 shrink-0 text-muted" />
                <input
                  class="w-full rounded-lg border border-transparent bg-transparent px-1 py-0.5 hover:border-line focus:border-line"
                  :value="f.label"
                  @change="patchField(f, { label: ($event.target as HTMLInputElement).value })"
                />
              </div>
              <div class="mt-0.5 font-mono text-[10px] text-muted">{{ f.key }}</div>
            </td>
            <td class="px-4 py-3 text-muted">{{ typeLabel(f.fieldType) }}</td>
            <td class="px-4 py-3">
              <input
                type="checkbox"
                :checked="f.required"
                :disabled="f.isSystem"
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
                :disabled="f.isSystem"
                @change="
                  patchField(f, {
                    is_active: ($event.target as HTMLInputElement).checked,
                  })
                "
              />
            </td>
            <td class="px-4 py-3">
              <div v-if="!f.isSystem" class="flex gap-1">
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
              <span v-if="f.isSystem" class="text-[11px] text-muted">базовое</span>
              <button
                v-else-if="f.isActive"
                type="button"
                class="text-xs text-danger hover:underline"
                @click="removeField(f)"
              >
                Отключить
              </button>
              <span v-else class="text-[11px] text-muted">выкл.</span>
            </td>
          </tr>
          <tr v-if="!visibleFields.length">
            <td colspan="6" class="px-4 py-6 text-center text-sm text-muted">
              Нет полей в этом контексте
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
