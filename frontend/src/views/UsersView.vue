<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useEmployeesStore } from '@/stores/employees'
import { listDepartmentsRequest, mapDepartment } from '@/api/settings'
import type { Department } from '@/types'

const employees = useEmployeesStore()
const departments = ref<Department[]>([])

const name = ref('')
const email = ref('')
const password = ref('demo')
const accessRoleId = ref<number | null>(null)
const departmentIds = ref<number[]>([])
const saving = ref(false)

onMounted(async () => {
  await Promise.all([employees.fetchEmployees(), employees.fetchRoles()])
  try {
    departments.value = (await listDepartmentsRequest()).map(mapDepartment)
  } catch {
    departments.value = []
  }
  if (!accessRoleId.value && employees.roles.length) {
    const op = employees.roles.find((r) => r.slug === 'operator') ?? employees.roles[0]
    accessRoleId.value = op.id
  }
})

function toggleDepartment(id: number) {
  if (departmentIds.value.includes(id)) {
    departmentIds.value = departmentIds.value.filter((x) => x !== id)
  } else {
    departmentIds.value = [...departmentIds.value, id]
  }
}

async function add() {
  if (!name.value.trim() || !email.value.trim() || !password.value || !accessRoleId.value) return
  saving.value = true
  const ok = await employees.addEmployee({
    name: name.value.trim(),
    email: email.value.trim(),
    password: password.value,
    accessRoleId: accessRoleId.value,
    channelIds: [],
    departmentIds: departmentIds.value,
  })
  saving.value = false
  if (!ok) return
  name.value = ''
  email.value = ''
  password.value = 'demo'
  departmentIds.value = []
}

async function onEmployeeRoleChange(userId: number, roleId: number) {
  await employees.updateEmployee(userId, { accessRoleId: roleId })
}

async function onEmployeeDepartmentsChange(userId: number, ids: number[]) {
  await employees.updateEmployee(userId, { departmentIds: ids })
}

function roleChannelLabel(user: { accessRoleId?: number | null }) {
  const role = employees.roles.find((r) => r.id === user.accessRoleId)
  if (!role) return '—'
  if (role.allChannels) return 'Все каналы (из роли)'
  if (!role.channelIds?.length) return 'Каналы роли не заданы'
  return role.channelIds
    .map((id) => employees.allChannels.find((c) => c.id === id)?.name)
    .filter(Boolean)
    .join(', ')
}
</script>

<template>
  <div class="h-full overflow-auto p-4 md:p-6">
    <p v-if="employees.error" class="mb-3 text-sm text-danger">{{ employees.error }}</p>

    <div class="mb-6 max-w-5xl rounded-2xl border border-line bg-panel p-4">
      <h2 class="mb-3 text-sm font-semibold">Добавить пользователя</h2>
      <form class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" @submit.prevent="add">
        <input
          v-model="name"
          required
          placeholder="Имя"
          class="rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
        />
        <input
          v-model="email"
          required
          type="email"
          placeholder="Email"
          class="rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
        />
        <input
          v-model="password"
          required
          type="password"
          placeholder="Пароль"
          class="rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
        />
        <select
          v-model.number="accessRoleId"
          class="rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none"
        >
          <option v-for="r in employees.roles" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
        <button
          type="submit"
          class="rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="saving"
        >
          {{ saving ? '…' : 'Добавить' }}
        </button>
      </form>
      <div class="mt-3">
        <div class="mb-1.5 text-xs font-semibold text-muted">Отделы</div>
        <p class="mb-2 text-[11px] text-muted">
          Сотрудник видит чаты только своих отделов. Доступ к каналам задаётся в роли.
        </p>
        <div class="flex flex-wrap gap-2">
          <label
            v-for="d in departments"
            :key="d.id"
            class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs"
          >
            <input
              type="checkbox"
              :checked="departmentIds.includes(d.id)"
              @change="toggleDepartment(d.id)"
            />
            {{ d.name }}
          </label>
          <span v-if="!departments.length" class="text-xs text-muted">Сначала создайте отдел</span>
        </div>
      </div>
    </div>

    <div class="overflow-x-auto rounded-2xl border border-line bg-panel">
      <p v-if="employees.loading" class="p-4 text-sm text-muted">Загрузка…</p>
      <table v-else class="w-full min-w-[640px] text-left text-sm">
        <thead class="border-b border-line bg-surface text-xs uppercase tracking-wide text-muted">
          <tr>
            <th class="px-4 py-3 font-semibold">Имя</th>
            <th class="px-4 py-3 font-semibold">Email</th>
            <th class="px-4 py-3 font-semibold">Роль</th>
            <th class="px-4 py-3 font-semibold">Отделы</th>
            <th class="px-4 py-3 font-semibold">Каналы (из роли)</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="e in employees.employees"
            :key="e.id"
            class="border-b border-line align-top last:border-0"
          >
            <td class="px-4 py-3 font-medium">{{ e.name }}</td>
            <td class="px-4 py-3 font-mono text-xs text-muted">{{ e.email }}</td>
            <td class="px-4 py-3">
              <select
                class="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm"
                :value="e.accessRoleId ?? ''"
                @change="
                  onEmployeeRoleChange(e.id, Number(($event.target as HTMLSelectElement).value))
                "
              >
                <option v-for="r in employees.roles" :key="r.id" :value="r.id">{{ r.name }}</option>
              </select>
            </td>
            <td class="px-4 py-3">
              <div class="flex max-w-xs flex-wrap gap-1.5">
                <label
                  v-for="d in departments"
                  :key="d.id"
                  class="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-[11px]"
                >
                  <input
                    type="checkbox"
                    :checked="(e.departmentIds ?? []).includes(d.id)"
                    @change="
                      onEmployeeDepartmentsChange(
                        e.id,
                        (e.departmentIds ?? []).includes(d.id)
                          ? (e.departmentIds ?? []).filter((id) => id !== d.id)
                          : [...(e.departmentIds ?? []), d.id],
                      )
                    "
                  />
                  {{ d.name }}
                </label>
              </div>
            </td>
            <td class="px-4 py-3 text-xs text-muted">{{ roleChannelLabel(e) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
