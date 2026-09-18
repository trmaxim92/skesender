import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  loginRequest,
  mapUser,
  meRequest,
  updateMeRequest,
  changePasswordRequest,
  refreshTokenRequest,
} from '@/api/auth'
import { setMyPresenceRequest } from '@/api/presence'
import { ApiError, AUTH_EXPIRED_EVENT, setToken } from '@/api/client'
import {
  FIRST_SECTION_PATHS,
  SECTION_BY_PATH,
  type PermissionCode,
  type PresenceStatus,
  type SendMode,
  type User,
} from '@/types'
import { shouldLogoutOnHydrateError, userCan } from '@/utils/authCan'
import { msUntilTokenRefresh, shouldRefreshToken } from '@/utils/jwt'

const USER_KEY = 'oe_auth_user'
const TOKEN_KEY = 'oe_access_token'
/** Other tabs / WS should re-auth after password rotate without full logout. */
export const SESSION_REFRESHED_EVENT = 'oe:session-refreshed'

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
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const error = ref('')
  const loading = ref(false)
  /** Ignore AUTH_EXPIRED while rotating password / applying a fresh token. */
  const sessionRefreshDepth = ref(0)
  let syncStarted = false
  let refreshTimer: number | null = null
  let refreshInFlight: Promise<boolean> | null = null
  let visibilityHooked = false

  const isAuthenticated = computed(() => !!user.value && !!token.value)
  const isSessionRefreshing = computed(() => sessionRefreshDepth.value > 0)

  function persistUser(next: User) {
    user.value = next
    localStorage.setItem(USER_KEY, JSON.stringify(next))
  }

  function beginSessionRefresh() {
    sessionRefreshDepth.value += 1
  }

  function endSessionRefresh() {
    sessionRefreshDepth.value = Math.max(0, sessionRefreshDepth.value - 1)
  }

  function clearRefreshTimer() {
    if (refreshTimer != null) {
      window.clearTimeout(refreshTimer)
      refreshTimer = null
    }
  }

  function scheduleTokenRefresh() {
    clearRefreshTimer()
    const current = token.value
    if (!current || typeof window === 'undefined') return
    const waitMs = msUntilTokenRefresh(current)
    if (waitMs == null) return
    // Cap sleep so clock skew / long TTL still get a check (~6h).
    const delay = Math.min(Math.max(waitMs, 5_000), 6 * 60 * 60 * 1000)
    refreshTimer = window.setTimeout(() => {
      void refreshSession(true).then((ok) => {
        if (ok) scheduleTokenRefresh()
      })
    }, delay)
  }

  function applyAccessToken(next: string, notify = true) {
    setToken(next)
    token.value = next
    if (notify) {
      window.dispatchEvent(new CustomEvent(SESSION_REFRESHED_EVENT))
    }
    scheduleTokenRefresh()
  }

  /**
   * Quietly slide JWT expiry. Returns false on auth failure (caller may logout).
   * Network/5xx: keep current token and retry on next schedule.
   */
  async function refreshSession(force = false): Promise<boolean> {
    const current = token.value ?? localStorage.getItem(TOKEN_KEY)
    if (!current) return false
    if (!force && !shouldRefreshToken(current)) {
      scheduleTokenRefresh()
      return true
    }
    if (refreshInFlight) return refreshInFlight

    refreshInFlight = (async () => {
      beginSessionRefresh()
      try {
        const result = await refreshTokenRequest()
        applyAccessToken(result.access_token, true)
        return true
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          clearRefreshTimer()
          endSessionRefresh()
          window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT))
          return false
        }
        // Transient: keep session, retry later.
        scheduleTokenRefresh()
        return true
      } finally {
        if (sessionRefreshDepth.value > 0) {
          window.setTimeout(() => endSessionRefresh(), 1500)
        }
        refreshInFlight = null
      }
    })()

    return refreshInFlight
  }

  function onVisibilityForRefresh() {
    if (document.visibilityState !== 'visible') return
    const current = token.value
    if (!current) return
    if (shouldRefreshToken(current)) {
      void refreshSession(true)
    } else {
      scheduleTokenRefresh()
    }
  }

  function startTokenRefresh() {
    if (typeof window === 'undefined') return
    if (!visibilityHooked) {
      visibilityHooked = true
      document.addEventListener('visibilitychange', onVisibilityForRefresh)
    }
    scheduleTokenRefresh()
    const current = token.value
    if (current && shouldRefreshToken(current)) {
      void refreshSession(true)
    }
  }

  function can(code: PermissionCode): boolean {
    return userCan(user.value, code)
  }

  function canSection(path: string): boolean {
    if (path === '/employees' || path.startsWith('/employees/')) {
      return can('section.chats') || can('section.employees')
    }
    if (path === '/clients/stages' || path.startsWith('/clients/stages')) {
      return can('section.contacts') || can('section.settings')
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
      applyAccessToken(result.access_token, false)
      const me = await meRequest()
      persistUser(mapUser(me))
      startTokenRefresh()
      return true
    } catch (e) {
      clearRefreshTimer()
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
    const stored = localStorage.getItem(TOKEN_KEY)
    token.value = stored
    if (!stored) {
      user.value = null
      clearRefreshTimer()
      return
    }
    try {
      const me = await meRequest()
      persistUser(mapUser(me))
      startTokenRefresh()
    } catch (e) {
      // Only clear session on definitive auth failure — keep cache on network/5xx.
      if (e instanceof ApiError && shouldLogoutOnHydrateError(e.status)) {
        logout()
      } else {
        startTokenRefresh()
      }
    }
  }

  async function updateProfile(name: string) {
    const me = await updateMeRequest({ name: name.trim() })
    persistUser(mapUser(me))
  }

  async function updateSendMode(mode: SendMode) {
    const me = await updateMeRequest({ send_mode: mode })
    persistUser(mapUser(me))
  }

  async function changePassword(currentPassword: string, newPassword: string) {
    beginSessionRefresh()
    try {
      const result = await changePasswordRequest(currentPassword, newPassword)
      applyAccessToken(result.access_token, true)
    } finally {
      // Allow in-flight WS close / 401 from old token to settle.
      window.setTimeout(() => endSessionRefresh(), 1500)
    }
  }

  async function setPresence(statusId: number, localStatus?: PresenceStatus | null) {
    const prev = user.value
    if (prev && localStatus) {
      persistUser({
        ...prev,
        presenceStatusId: statusId,
        presenceStatus: { ...localStatus },
        canWriteChats: can('action.write') && localStatus.canWriteChats,
      })
    }
    try {
      const me = await setMyPresenceRequest(statusId)
      const mapped = mapUser(me)
      if (!mapped.presenceStatus && localStatus) {
        mapped.presenceStatus = { ...localStatus }
        mapped.presenceStatusId = statusId
      }
      persistUser(mapped)
    } catch (e) {
      if (prev) persistUser(prev)
      throw e
    }
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
    clearRefreshTimer()
    user.value = null
    token.value = null
    setToken(null)
    localStorage.removeItem(USER_KEY)
  }

  async function logoutWithOffline() {
    await goOffline()
    logout()
  }

  /** Cross-tab session sync (storage events fire only in *other* tabs). */
  function startSessionSync() {
    if (syncStarted || typeof window === 'undefined') return
    syncStarted = true
    window.addEventListener('storage', (e: StorageEvent) => {
      if (e.key !== TOKEN_KEY && e.key !== USER_KEY) return
      const nextToken = localStorage.getItem(TOKEN_KEY)
      if (!nextToken) {
        clearRefreshTimer()
        user.value = null
        token.value = null
        window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT))
        return
      }
      if (nextToken !== token.value) {
        token.value = nextToken
        scheduleTokenRefresh()
        void hydrate().then(() => {
          window.dispatchEvent(new CustomEvent(SESSION_REFRESHED_EVENT))
        })
        return
      }
      if (e.key === USER_KEY && e.newValue) {
        try {
          user.value = JSON.parse(e.newValue) as User
        } catch {
          /* ignore corrupt mirror */
        }
      }
    })
  }

  return {
    user,
    token,
    error,
    loading,
    isAuthenticated,
    isSessionRefreshing,
    can,
    canSection,
    firstAllowedPath,
    login,
    logout,
    logoutWithOffline,
    hydrate,
    updateProfile,
    updateSendMode,
    changePassword,
    setPresence,
    startSessionSync,
    startTokenRefresh,
    refreshSession,
    beginSessionRefresh,
    endSessionRefresh,
  }
})
