import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listChannelsRequest, mapChannel } from '@/api/auth'
import {
  createRoleRequest,
  createUserRequest,
  deleteRoleRequest,
  listPermissionCatalogRequest,
  listRolesRequest,
  listUsersRequest,
  mapApiRole,
  mapApiUser,
  mapPermissionCatalog,
  updateRoleRequest,
  updateUserRequest,
} from '@/api/cabinet'
import { ApiError } from '@/api/client'
import type { AccessRole, Channel, PermissionCatalogItem, PermissionCode, User } from '@/types'

export const useEmployeesStore = defineStore('employees', () => {
  const employees = ref<User[]>([])
  const roles = ref<AccessRole[]>([])
  const catalog = ref<PermissionCatalogItem[]>([])
  const allChannels = ref<Channel[]>([])
  const loading = ref(false)
  const error = ref('')

  async function fetchEmployees() {
    loading.value = true
    error.value = ''
    try {
      const list = await listUsersRequest(true)
      employees.value = list.map(mapApiUser)
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить сотрудников'
    } finally {
      loading.value = false
    }
  }

  async function fetchRoles() {
    try {
      const [roleList, permList, channels] = await Promise.all([
        listRolesRequest(),
        listPermissionCatalogRequest(),
        listChannelsRequest(),
      ])
      roles.value = roleList.map(mapApiRole)
      catalog.value = mapPermissionCatalog(permList)
      allChannels.value = channels.map(mapChannel)
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить роли'
    }
  }

  async function addEmployee(payload: {
    name: string
    email: string
    password: string
    accessRoleId: number
    channelIds: number[]
    departmentIds?: number[]
  }) {
    try {
      const created = await createUserRequest({
        name: payload.name,
        email: payload.email,
        password: payload.password,
        access_role_id: payload.accessRoleId,
        channel_ids: payload.channelIds,
        department_ids: payload.departmentIds ?? [],
      })
      employees.value.push(mapApiUser(created))
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось добавить'
      return false
    }
  }

  async function updateEmployee(
    id: number,
    payload: {
      accessRoleId?: number
      channelIds?: number[]
      departmentIds?: number[]
      isActive?: boolean
      name?: string
      email?: string
      password?: string
    },
  ) {
    try {
      const updated = await updateUserRequest(id, {
        name: payload.name,
        email: payload.email,
        password: payload.password,
        access_role_id: payload.accessRoleId,
        channel_ids: payload.channelIds,
        department_ids: payload.departmentIds,
        is_active: payload.isActive,
      })
      const mapped = mapApiUser(updated)
      const idx = employees.value.findIndex((x) => x.id === id)
      if (idx >= 0) employees.value[idx] = mapped
      else employees.value.push(mapped)
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось обновить'
      await fetchEmployees()
      return false
    }
  }

  async function saveRole(payload: {
    id?: number
    name: string
    permissions: PermissionCode[]
    allChannels: boolean
    channelIds?: number[]
  }) {
    try {
      if (payload.id) {
        const updated = await updateRoleRequest(payload.id, {
          name: payload.name,
          permissions: payload.permissions,
          all_channels: payload.allChannels,
          channel_ids: payload.allChannels ? [] : (payload.channelIds ?? []),
        })
        const mapped = mapApiRole(updated)
        const idx = roles.value.findIndex((r) => r.id === mapped.id)
        if (idx >= 0) roles.value[idx] = mapped
        else roles.value.push(mapped)
      } else {
        const created = await createRoleRequest({
          name: payload.name,
          permissions: payload.permissions,
          all_channels: payload.allChannels,
          channel_ids: payload.allChannels ? [] : (payload.channelIds ?? []),
        })
        roles.value.push(mapApiRole(created))
      }
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить роль'
      return false
    }
  }

  async function removeRole(id: number) {
    try {
      await deleteRoleRequest(id)
      roles.value = roles.value.filter((r) => r.id !== id)
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить роль'
      return false
    }
  }

  return {
    employees,
    roles,
    catalog,
    allChannels,
    loading,
    error,
    fetchEmployees,
    fetchRoles,
    addEmployee,
    updateEmployee,
    saveRole,
    removeRole,
  }
})
