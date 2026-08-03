<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Pencil, Trash2 } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import { useAuthStore } from '@/stores/auth'
import { useEmployeesStore } from '@/stores/employees'
import { listDepartmentsRequest, mapDepartment } from '@/api/settings'
import type { Department, User } from '@/types'

const auth = useAuthStore()
const employees = useEmployeesStore()
const departments = ref<Department[]>([])

const name = ref('')
const email = ref('')
const password = ref('demo')
const accessRoleId = ref<number | null>(null)
const departmentIds = ref<number[]>([])
const saving = ref(false)

const editOpen = ref(false)
const editSaving = ref(false)
const editing = ref<User | null>(null)
const editName = ref('')
const editEmail = ref('')
const editPassword = ref('')
const editRoleId = ref<number | null>(null)
const editDepartmentIds = ref<number[]>([])
const editActive = ref(true)
const deletingId = ref<number | null>(null)

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

function toggleEditDepartment(id: number) {
  if (editDepartmentIds.value.includes(id)) {
    editDepartmentIds.value = editDepartmentIds.value.filter((x) => x !== id)
  } else {
    editDepartmentIds.value = [...editDepartmentIds.value, id]
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

function openEdit(user: User) {
  editing.value = user
  editName.value = user.name
  editEmail.value = user.email
  editPassword.value = ''
  editRoleId.value = user.accessRoleId ?? null
  editDepartmentIds.value = [...(user.departmentIds ?? [])]
  editActive.value = user.isActive !== false
  editOpen.value = true
  employees.error = ''
}

function closeEdit() {
  editOpen.value = false
  editing.value = null
  editPassword.value = ''
}

async function saveEdit() {
  if (!editing.value || !editName.value.trim() || !editEmail.value.trim() || !editRoleId.value) return
  editSaving.value = true
  const payload: {
    name: string
    email: string
    accessRoleId: number
    departmentIds: number[]
    isActive: boolean
    password?: string
  } = {
    name: editName.value.trim(),
    email: editEmail.value.trim(),
    accessRoleId: editRoleId.value,
    departmentIds: editDepartmentIds.value,
    isActive: editActive.value,
  }
  if (editPassword.value.trim()) {
    payload.password = editPassword.value.trim()
  }
  const ok = await employees.updateEmployee(editing.value.id, payload)
  editSaving.value = false
  if (!ok) return
  closeEdit()
}

async function remove(user: User) {
  if (user.id === auth.user?.id) return
  if (!window.confirm(`Удалить пользователя «${user.name}» (${user.email})?\nЭто действие нельзя отменить.`)) {
    return
  }
  deletingId.value = user.id
  employees.error = ''
  await employees.removeEmployee(user.id)
  deletingId.value = null
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

function departmentLabel(user: User) {
  const ids = user.departmentIds ?? []
  if (!ids.length) return '—'
  return ids
    .map((id) => departments.value.find((d) => d.id === id)?.name)
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
            <th class="px-4 py-3 font-semibold">Статус</th>
            <th class="w-24 px-2 py-3" />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="e in employees.employees"
            :key="e.id"
            class="border-b border-line align-top last:border-0"
            :class="e.isActive === false ? 'opacity-60' : ''"
          >
            <td class="px-4 py-3 font-medium">{{ e.name }}</td>
            <td class="px-4 py-3 font-mono text-xs text-muted">{{ e.email }}</td>
            <td class="px-4 py-3">
              {{ employees.roles.find((r) => r.id === e.accessRoleId)?.name || e.roleName || e.role }}
            </td>
            <td class="px-4 py-3 text-xs text-muted">{{ departmentLabel(e) }}</td>
            <td class="px-4 py-3 text-xs text-muted">{{ roleChannelLabel(e) }}</td>
            <td class="px-4 py-3">
              <span
                class="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                :class="
                  e.isActive === false
                    ? 'bg-muted/15 text-muted'
                    : 'bg-ok/15 text-ok'
                "
              >
                {{ e.isActive === false ? 'Выкл.' : 'Активен' }}
              </span>
            </td>
            <td class="px-2 py-3">
              <div class="flex items-center gap-1">
                <button
                  type="button"
                  class="inline-flex size-8 items-center justify-center rounded-lg border border-line text-muted transition hover:border-brand/40 hover:bg-brand-soft hover:text-brand"
                  title="Редактировать"
                  @click="openEdit(e)"
                >
                  <Pencil class="size-3.5" />
                </button>
                <button
                  v-if="e.id !== auth.user?.id"
                  type="button"
                  class="inline-flex size-8 items-center justify-center rounded-lg border border-line text-muted transition hover:border-danger/40 hover:bg-danger/10 hover:text-danger disabled:opacity-50"
                  title="Удалить"
                  :disabled="deletingId === e.id"
                  @click="remove(e)"
                >
                  <Trash2 class="size-3.5" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Modal v-if="editOpen && editing" title="Редактировать пользователя" @close="closeEdit">
      <form class="space-y-4" @submit.prevent="saveEdit">
        <label class="block">
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">Имя</span>
          <input
            v-model="editName"
            required
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">Email</span>
          <input
            v-model="editEmail"
            required
            type="email"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
            Новый пароль
          </span>
          <input
            v-model="editPassword"
            type="password"
            placeholder="Оставьте пустым, чтобы не менять"
            minlength="4"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">Роль</span>
          <select
            v-model.number="editRoleId"
            required
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none"
          >
            <option v-for="r in employees.roles" :key="r.id" :value="r.id">{{ r.name }}</option>
          </select>
        </label>
        <div>
          <div class="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">Отделы</div>
          <div class="flex flex-wrap gap-2">
            <label
              v-for="d in departments"
              :key="d.id"
              class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs"
            >
              <input
                type="checkbox"
                :checked="editDepartmentIds.includes(d.id)"
                @change="toggleEditDepartment(d.id)"
              />
              {{ d.name }}
            </label>
            <span v-if="!departments.length" class="text-xs text-muted">Нет отделов</span>
          </div>
        </div>
        <label class="inline-flex cursor-pointer items-center gap-2 text-sm">
          <input v-model="editActive" type="checkbox" class="size-4 rounded border-line" />
          Активен
        </label>
        <div class="flex justify-end gap-2 pt-2">
          <button
            type="button"
            class="rounded-xl border border-line px-4 py-2 text-sm font-semibold text-muted transition hover:bg-surface"
            @click="closeEdit"
          >
            Отмена
          </button>
          <button
            type="submit"
            class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            :disabled="editSaving"
          >
            {{ editSaving ? '…' : 'Сохранить' }}
          </button>
        </div>
      </form>
    </Modal>
  </div>
</template>
