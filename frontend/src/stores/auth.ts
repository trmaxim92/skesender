import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { loginRequest, mapUser, meRequest, updateMeRequest, changePasswordRequest } from '@/api/auth'
import { setMyPresenceRequest } from '@/api/presence'
import { ApiError, setToken } from '@/api/client'
import {
  FIRST_SECTION_PATHS,
  SECTION_BY_PATH,
  type PermissionCode,
  type User,
} from '@/types'

const USER_KEY = 'oe_auth_user'

function readStoredUser(): User | null {
  const stored = localStorage.getItem(USER_KEY)
  if (!stored) return null
  try {
    return JSON.parse(stored) as User
  } catch {
    localStorage.removeItem(USER_KEY)
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(readStoredUser())
  const token = ref<string | null>(localStorage.getItem('oe_access_token'))
  const error = ref('')
  const loading = ref(false)

  const isAuthenticated = computed(() => !!user.value && !!token.value)

  function persistUser(next: User) {
    user.value = next
    localStorage.setItem(USER_KEY, JSON.stringify(next))
  }

  function can(code: PermissionCode): boolean {
    if (!user.value) return false
    // Admin always has full access (covers stale cached permissions)
    if (user.value.role === 'admin') return true
    const perms = user.value.permissions
    if (!perms?.length) {
      if (user.value.role === 'viewer') {
        return code === 'section.chats' || code === 'section.appeals'
      }
      return (
        code === 'section.chats' ||
        code === 'section.appeals' ||
        code === 'section.mailing' ||
        code === 'action.write'
      )
    }
    return perms.includes(code)
  }

  function canSection(path: string): boolean {
    if (path === '/employees' || path.startsWith('/employees/')) {
      return can('section.chats') || can('section.employees')
    }
    const code = SECTION_BY_PATH[path]
    return code ? can(code) : true
  }

  function firstAllowedPath(): string {
    for (const p of FIRST_SECTION_PATHS) {
      if (canSection(p)) return p
    }
    return '/chats'
  }

  async function login(email: string, password: string) {
    error.value = ''
    loading.value = true
    try {
      const result = await loginRequest(email.trim(), password)
      setToken(result.access_token)
      token.value = result.access_token
      const me = await meRequest()
      persistUser(mapUser(me))
      return true
    } catch (e) {
      setToken(null)
      token.value = null
      user.value = null
      localStorage.removeItem(USER_KEY)
      error.value =
        e instanceof ApiError ? e.detail : 'Не удалось войти. Проверьте backend на :8000'
      return false
    } finally {
      loading.value = false
    }
  }

  async function hydrate() {
    const stored = localStorage.getItem('oe_access_token')
    token.value = stored
    if (!stored) {
      user.value = null
      return
    }
    try {
      const me = await meRequest()
      persistUser(mapUser(me))
    } catch {
      logout()
    }
  }

  async function updateProfile(name: string) {
    const me = await updateMeRequest(name.trim())
    persistUser(mapUser(me))
  }

  async function changePassword(currentPassword: string, newPassword: string) {
    await changePasswordRequest(currentPassword, newPassword)
  }

  async function setPresence(statusId: number) {
    const me = await setMyPresenceRequest(statusId)
    persistUser(mapUser(me))
  }

  async function goOffline() {
    try {
      const { listPresenceStatusesRequest } = await import('@/api/presence')
      const statuses = await listPresenceStatusesRequest(true)
      const offline = statuses.find((s) => s.slug === 'offline')
      if (offline) await setMyPresenceRequest(offline.id)
    } catch {
      // Best-effort: logout even if presence update fails.
    }
  }

  function logout() {
    user.value = null
    token.value = null
    setToken(null)
    localStorage.removeItem(USER_KEY)
  }

  async function logoutWithOffline() {
    await goOffline()
    logout()
  }

  return {
    user,
    token,
    error,
    loading,
    isAuthenticated,
    can,
    canSection,
    firstAllowedPath,
    login,
    logout,
    logoutWithOffline,
    hydrate,
    updateProfile,
    changePassword,
    setPresence,
  }
})