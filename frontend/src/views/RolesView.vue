<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useEmployeesStore } from '@/stores/employees'
import type { AccessRole, PermissionCode } from '@/types'

const employees = useEmployeesStore()

const roleEditorOpen = ref(false)
const editingRoleId = ref<number | null>(null)
const roleName = ref('')
const rolePerms = ref<PermissionCode[]>([])
const roleAllChannels = ref(false)
const roleChannelIds = ref<number[]>([])
const roleSaving = ref(false)

const emptyChannelAclWarn = computed(
  () => roleEditorOpen.value && !roleAllChannels.value && roleChannelIds.value.length === 0,
)

onMounted(() => {
  void employees.fetchRoles()
})

watch(roleAllChannels, (all) => {
  if (all) roleChannelIds.value = []
})

function openCreateRole() {
  editingRoleId.value = null
  roleName.value = ''
  rolePerms.value = ['section.chats', 'section.appeals', 'action.write']
  roleAllChannels.value = true
  roleChannelIds.value = []
  roleEditorOpen.value = true
}

function openEditRole(role: AccessRole) {
  editingRoleId.value = role.id
  roleName.value = role.name
  rolePerms.value = [...role.permissions]
  roleAllChannels.value = role.allChannels
  roleChannelIds.value = [...(role.channelIds ?? [])]
  roleEditorOpen.value = true
}

function togglePerm(code: PermissionCode) {
  if (rolePerms.value.includes(code)) {
    rolePerms.value = rolePerms.value.filter((c) => c !== code)
  } else {
    rolePerms.value = [...rolePerms.value, code]
  }
}

function toggleChannel(id: number) {
  if (roleChannelIds.value.includes(id)) {
    roleChannelIds.value = roleChannelIds.value.filter((x) => x !== id)
  } else {
    roleChannelIds.value = [...roleChannelIds.value, id]
  }
}

function channelNames(ids: number[]) {
  return ids
    .map((id) => employees.allChannels.find((c) => c.id === id)?.name)
    .filter(Boolean)
    .join(', ')
}

async function saveRole() {
  if (!roleName.value.trim()) return
  roleSaving.value = true
  const ok = await employees.saveRole({
    id: editingRoleId.value ?? undefined,
    name: roleName.value.trim(),
    permissions: rolePerms.value,
    allChannels: roleAllChannels.value,
    channelIds: roleChannelIds.value,
  })
  roleSaving.value = false
  if (ok) roleEditorOpen.value = false
}
</script>

<template>
  <div class="h-full overflow-auto p-6">
    <p v-if="employees.error" class="mb-3 text-sm text-danger">{{ employees.error }}</p>

    <div class="mb-4 flex justify-end">
      <button
        type="button"
        class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white"
        @click="openCreateRole"
      >
        Создать роль
      </button>
    </div>

    <div class="grid gap-3 md:grid-cols-2">
      <article
        v-for="r in employees.roles"
        :key="r.id"
        class="rounded-2xl border border-line bg-panel p-4"
      >
        <div class="mb-2 flex items-start justify-between gap-2">
          <div>
            <h3 class="text-sm font-semibold">{{ r.name }}</h3>
            <p class="text-[11px] text-muted">
              {{ r.isSystem ? 'Системная' : 'Пользовательская' }}
              · диалоги:
              {{
                r.allChannels
                  ? 'все каналы'
                  : channelNames(r.channelIds).length
                    ? channelNames(r.channelIds)
                    : 'каналы не выбраны'
              }}
            </p>
          </div>
          <div class="flex gap-2">
            <button
              type="button"
              class="rounded-lg border border-line px-2 py-1 text-xs"
              @click="openEditRole(r)"
            >
              Изменить
            </button>
            <button
              v-if="!r.isSystem"
              type="button"
              class="rounded-lg border border-line px-2 py-1 text-xs text-danger"
              @click="employees.removeRole(r.id)"
            >
              Удалить
            </button>
          </div>
        </div>
        <div class="flex flex-wrap gap-1.5">
          <span
            v-for="p in r.permissions"
            :key="p"
            class="rounded bg-surface px-1.5 py-0.5 text-[10px] text-muted"
          >
            {{ employees.catalog.find((c) => c.code === p)?.label ?? p }}
          </span>
        </div>
      </article>
    </div>

    <div
      v-if="roleEditorOpen"
      class="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4"
      @click.self="roleEditorOpen = false"
    >
      <div class="max-h-[90vh] w-full max-w-lg overflow-auto rounded-2xl border border-line bg-panel p-5 shadow-xl">
        <h3 class="mb-3 text-sm font-semibold">
          {{ editingRoleId ? 'Редактировать роль' : 'Новая роль' }}
        </h3>
        <input
          v-model="roleName"
          placeholder="Название"
          class="mb-3 w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none"
        />
        <div class="mb-3 rounded-xl border border-line bg-surface p-3">
          <div class="mb-1 text-xs font-semibold text-muted">Доступ к диалогам в каналах</div>
          <p class="mb-2 text-[11px] text-muted">
            Это не раздел настроек «Каналы». Здесь — какие чаты видит сотрудник.
          </p>
          <label class="mb-2 flex items-center gap-2 text-sm">
            <input v-model="roleAllChannels" type="checkbox" />
            Доступ ко всем каналам
          </label>
          <div v-if="!roleAllChannels" class="flex flex-wrap gap-2">
            <label
              v-for="ch in employees.allChannels"
              :key="ch.id"
              class="inline-flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs"
            >
              <input
                type="checkbox"
                :checked="roleChannelIds.includes(ch.id)"
                @change="toggleChannel(ch.id)"
              />
              {{ ch.name }}
            </label>
            <span v-if="!employees.allChannels.length" class="text-xs text-muted">Нет каналов</span>
          </div>
          <p v-if="emptyChannelAclWarn" class="mt-2 text-xs text-danger">
            Операторы с этой ролью не увидят ни одного чата — включите «все каналы» или выберите каналы.
          </p>
        </div>
        <div class="mb-4 max-h-48 space-y-1.5 overflow-auto">
          <div class="mb-1 text-xs font-semibold text-muted">Права разделов</div>
          <p class="mb-2 text-[11px] text-muted">
            «Раздел „Каналы“ (настройки)» — только экран подключения/удаления каналов, не доступ к чатам.
          </p>
          <label
            v-for="item in employees.catalog"
            :key="item.code"
            class="flex items-center gap-2 text-sm"
          >
            <input
              type="checkbox"
              :checked="rolePerms.includes(item.code)"
              @change="togglePerm(item.code)"
            />
            {{ item.label }}
          </label>
        </div>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            class="rounded-xl border border-line px-3 py-2 text-sm"
            @click="roleEditorOpen = false"
          >
            Отмена
          </button>
          <button
            type="button"
            class="rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
            :disabled="roleSaving"
            @click="saveRole"
          >
            Сохранить
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
