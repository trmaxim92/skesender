<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import {
  MessageSquare,
  Users,
  LogOut,
  Inbox,
  Megaphone,
  Shield,
  Menu,
  ChevronDown,
  Settings,
  Building2,
  TextQuote,
  UserRound,
  X,
  CircleUserRound,
  Download,
  Share,
  ContactRound,
  Bell,
  Tags,
  List,
} from 'lucide-vue-next'
import { AUTH_EXPIRED_EVENT, ApiError } from '@/api/client'
import { listPresenceStatusesRequest, mapPresenceStatus } from '@/api/presence'
import { isSettingsPath, SETTINGS_NAV_GROUPS, settingsLeafTitle } from '@/navigation/settingsNav'
import { SESSION_REFRESHED_EVENT, useAuthStore } from '@/stores/auth'
import { useChatsStore } from '@/stores/chats'
import { useNotificationsStore } from '@/stores/notifications'
import type { PresenceStatus } from '@/types'
import {
  isPushEnabled,
  notificationPermission,
  prepareNotifyServiceWorker,
  setPushEnabled,
  unlockNotifyAudio,
} from '@/utils/notify'
import { resetFavicon, setFaviconUnread } from '@/utils/faviconBadge'
import {
  dismissInstallHint,
  isIosDevice,
  isStandaloneDisplay,
  onInstallPromptAvailable,
  promptPwaInstall,
  setAppBadgeCount,
  wasInstallDismissed,
} from '@/utils/pwa'

const SIDEBAR_KEY = 'oe_sidebar_collapsed'
const USERS_GROUP_KEY = 'oe_nav_users_open'
const CLIENTS_GROUP_KEY = 'oe_nav_clients_open'
const SETTINGS_GROUP_KEY = 'oe_nav_settings_open'
const BASE_TITLE = 'СкайСкел'

const auth = useAuthStore()
const { user: authUser } = storeToRefs(auth)
const chats = useChatsStore()
const notifications = useNotificationsStore()
const route = useRoute()
const router = useRouter()

type NavLeaf = { to: string; label: string; icon: typeof MessageSquare }

const navWorkStart: NavLeaf[] = [
  { to: '/chats', label: 'Чаты', icon: MessageSquare },
  { to: '/appeals', label: 'Обращения', icon: Inbox },
]

const navWorkEnd: NavLeaf[] = [
  { to: '/employees', label: 'На смене', icon: CircleUserRound },
  { to: '/mailing', label: 'Рассылки', icon: Megaphone },
]

const clientsChildren: NavLeaf[] = [
  { to: '/contacts', label: 'Список', icon: List },
  { to: '/clients/stages', label: 'Этапы обзвона', icon: Tags },
]

const usersChildren: NavLeaf[] = [
  { to: '/users', label: 'Пользователи', icon: Users },
  { to: '/roles', label: 'Роли', icon: Shield },
  { to: '/departments', label: 'Отделы', icon: Building2 },
]

const collapsed = ref(localStorage.getItem(SIDEBAR_KEY) === '1')
const mobileNavOpen = ref(false)
const isMdUp = ref(typeof window !== 'undefined' ? window.matchMedia('(min-width: 768px)').matches : true)
const clientsGroupExpanded = ref(
  localStorage.getItem(CLIENTS_GROUP_KEY) === '1' ||
    route.path.startsWith('/contacts') ||
    route.path.startsWith('/clients/'),
)
const usersGroupExpanded = ref(
  localStorage.getItem(USERS_GROUP_KEY) === '1' ||
    route.path.startsWith('/users') ||
    route.path.startsWith('/roles') ||
    route.path.startsWith('/departments'),
)
const settingsGroupExpanded = ref(
  localStorage.getItem(SETTINGS_GROUP_KEY) !== '0' || isSettingsPath(route.path),
)
const profileOpen = ref(false)
const profileRoot = ref<HTMLElement | null>(null)
const profileMenu = ref<HTMLElement | null>(null)
const presenceStatuses = ref<PresenceStatus[]>([])
const presenceBusy = ref(false)
const presenceLoadError = ref('')
const profileMenuStyle = ref<Record<string, string>>({})
const bellOpen = ref(false)
const bellRoot = ref<HTMLElement | null>(null)
const bellPanel = ref<HTMLElement | null>(null)
const bellPanelStyle = ref<Record<string, string>>({})
let notificationsPollTimer: number | undefined

const currentPresence = computed(() => authUser.value?.presenceStatus ?? null)
const currentPresenceId = computed(() => authUser.value?.presenceStatusId ?? null)

function placeProfileMenu() {
  if (!profileOpen.value) return
  const el = profileRoot.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const width = 256
  const left = Math.min(Math.max(8, rect.right - width), window.innerWidth - width - 8)
  profileMenuStyle.value = {
    top: `${Math.round(rect.bottom + 8)}px`,
    left: `${Math.round(left)}px`,
  }
}

function placeBellPanel() {
  if (!bellOpen.value) return
  const el = bellRoot.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const width = Math.min(380, window.innerWidth - 16)
  const left = Math.min(Math.max(8, rect.right - width), window.innerWidth - width - 8)
  bellPanelStyle.value = {
    top: `${Math.round(rect.bottom + 8)}px`,
    left: `${Math.round(left)}px`,
    width: `${width}px`,
  }
}

function notificationKindLabel(kind: string) {
  if (kind === 'system_news') return 'Новости системы'
  return 'Оповещение'
}

function formatNotifyAt(iso: string) {
  try {
    return new Date(iso).toLocaleString('ru-RU', {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

/** Expanded labels: always on mobile drawer; rail collapse only from md up. */
const expandedNav = computed(() => !isMdUp.value || !collapsed.value)

const settingsGroupsVisible = computed(() =>
  SETTINGS_NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => auth.can(item.permission)),
  })).filter((group) => group.items.length > 0),
)

const settingsFlatLeaves = computed(() =>
  settingsGroupsVisible.value.flatMap((group) => group.items),
)

const showClientsGroup = computed(
  () => auth.can('section.contacts') || auth.can('section.settings'),
)
const clientsChildrenVisible = computed(() =>
  clientsChildren.filter((child) => {
    if (child.to === '/contacts') return auth.can('section.contacts')
    if (child.to === '/clients/stages') {
      return auth.can('section.contacts') || auth.can('section.settings')
    }
    return true
  }),
)
const showUsersGroup = computed(() => auth.canSection('/users'))
const showSettingsGroup = computed(() => settingsGroupsVisible.value.length > 0)
const navStartVisible = computed(() => navWorkStart.filter((item) => auth.canSection(item.to)))
const navEndVisible = computed(() => navWorkEnd.filter((item) => auth.canSection(item.to)))

type MobileTab = {
  id: string
  to?: string
  label: string
  icon: typeof MessageSquare
  badge?: 'chats'
}

const mobileTabs = computed((): MobileTab[] => {
  const tabs: MobileTab[] = []
  if (auth.canSection('/chats')) {
    tabs.push({ id: 'chats', to: '/chats', label: 'Чаты', icon: MessageSquare, badge: 'chats' })
  }
  if (auth.canSection('/appeals')) {
    tabs.push({ id: 'appeals', to: '/appeals', label: 'Обращения', icon: Inbox })
  }
  if (auth.can('section.contacts')) {
    tabs.push({ id: 'contacts', to: '/contacts', label: 'Клиенты', icon: ContactRound })
  }
  tabs.push({ id: 'more', label: 'Ещё', icon: Menu })
  return tabs
})

const showMobileTabBar = computed(() => !isMdUp.value && !hideChromeForMobileChat.value)

function isMobileTabActive(tab: MobileTab) {
  if (tab.id === 'more') {
    return (
      route.path.startsWith('/employees') ||
      route.path.startsWith('/mailing') ||
      route.path.startsWith('/users') ||
      route.path.startsWith('/roles') ||
      route.path.startsWith('/departments') ||
      route.path.startsWith('/news') ||
      route.path.startsWith('/profile') ||
      route.path.startsWith('/clients/') ||
      isSettingsPath(route.path)
    )
  }
  if (!tab.to) return false
  return route.path === tab.to || route.path.startsWith(`${tab.to}/`)
}

function onMobileTab(tab: MobileTab) {
  if (tab.id === 'more') {
    mobileNavOpen.value = true
    return
  }
  if (tab.to) {
    mobileNavOpen.value = false
    void router.push(tab.to)
  }
}

const onClientsSection = computed(
  () => route.path.startsWith('/contacts') || route.path.startsWith('/clients/'),
)
const onUsersSection = computed(
  () =>
    route.path.startsWith('/users') ||
    route.path.startsWith('/roles') ||
    route.path.startsWith('/departments'),
)
const onSettingsSection = computed(() => isSettingsPath(route.path))

const title = computed(() => {
  if (route.path === '/profile' || route.path.startsWith('/profile?')) return 'Профиль'
  if (route.name === 'profile') return 'Профиль'
  if (route.path.startsWith('/profile/templates')) return 'Мои шаблоны'
  if (route.name === 'appeal-detail') return 'Обращение'
  if (route.path.startsWith('/employees')) return 'На смене'
  if (route.path.startsWith('/news')) return 'Новости'
  if (route.path.startsWith('/users')) return 'Пользователи'
  if (route.path.startsWith('/roles')) return 'Роли'
  if (route.path.startsWith('/departments')) return 'Отделы'
  if (route.path.startsWith('/clients/stages')) return 'Этапы обзвона'
  if (route.path.startsWith('/contacts')) return 'Клиенты'
  const settingsTitle = settingsLeafTitle(route.path)
  if (settingsTitle) return settingsTitle
  const all = [...navWorkStart, ...navWorkEnd, ...clientsChildren, ...usersChildren]
  return all.find((n) => route.path.startsWith(n.to))?.label ?? 'Кабинет'
})

const roleDisplay = computed(() => auth.user?.roleName || auth.user?.role || '')

const initials = computed(() => {
  const name = auth.user?.name?.trim() || '?'
  const parts = name.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    return `${parts[0]![0] ?? ''}${parts[1]![0] ?? ''}`.toUpperCase()
  }
  return name.slice(0, 2).toUpperCase()
})

const chatsUnread = computed(() => chats.totalUnread)
const newAppealsBadge = computed(() => chats.unreadByTab?.new ?? 0)
const appVersion = '2.8.1'
const inAppToast = ref<{
  text: string
  kind: 'ok' | 'warn' | 'err' | 'message'
  title?: string
  dialogId?: string
  initials?: string
} | null>(null)
let inAppToastTimer: number | null = null
if (isPushEnabled() && notificationPermission() !== 'granted') {
  setPushEnabled(false)
}

watch(collapsed, (v) => localStorage.setItem(SIDEBAR_KEY, v ? '1' : '0'))
watch(clientsGroupExpanded, (v) => localStorage.setItem(CLIENTS_GROUP_KEY, v ? '1' : '0'))
watch(usersGroupExpanded, (v) => localStorage.setItem(USERS_GROUP_KEY, v ? '1' : '0'))
watch(settingsGroupExpanded, (v) => localStorage.setItem(SETTINGS_GROUP_KEY, v ? '1' : '0'))

watch(
  () => route.fullPath,
  () => {
    profileOpen.value = false
    bellOpen.value = false
    mobileNavOpen.value = false
    if (onClientsSection.value) clientsGroupExpanded.value = true
    if (onUsersSection.value) usersGroupExpanded.value = true
    if (onSettingsSection.value) settingsGroupExpanded.value = true
  },
)

watch(
  chatsUnread,
  (n) => {
    document.title = n > 0 ? `(${n > 99 ? '99+' : n}) ${BASE_TITLE}` : BASE_TITLE
    setFaviconUnread(n)
    void setAppBadgeCount(n)
  },
  { immediate: true },
)

const hideChromeForMobileChat = computed(
  () =>
    !isMdUp.value &&
    route.name === 'chats' &&
    typeof route.query.dialog === 'string' &&
    Boolean(route.query.dialog),
)

watch(
  hideChromeForMobileChat,
  (immersive) => {
    if (typeof document === 'undefined') return
    document.documentElement.classList.toggle('oe-chat-immersive', immersive)
  },
  { immediate: true },
)

const showInstallBanner = ref(false)
const installPromptReady = ref(false)
const installHelp = ref('')
const iosInstallHint = computed(() => isIosDevice() && !isStandaloneDisplay())

function refreshInstallBanner() {
  if (isStandaloneDisplay() || wasInstallDismissed()) {
    showInstallBanner.value = false
    return
  }
  showInstallBanner.value = true
}

async function onInstallApp() {
  installHelp.value = ''
  const outcome = await promptPwaInstall()
  if (outcome === 'accepted') {
    refreshInstallBanner()
    return
  }
  if (outcome === 'dismissed') {
    installHelp.value = 'Установка отменена — можно попробовать ещё раз'
    return
  }
  if (iosInstallHint.value) {
    installHelp.value = 'На iPhone: Поделиться → «На экран „Домой“»'
    return
  }
  installHelp.value =
    'В меню браузера (⋮) выберите «Установить приложение» или «Добавить на главный экран»'
}

function onDismissInstall() {
  dismissInstallHint()
  showInstallBanner.value = false
  installHelp.value = ''
}

let stopInstallWatch: (() => void) | null = null
stopInstallWatch = onInstallPromptAvailable((ready) => {
  installPromptReady.value = ready
  refreshInstallBanner()
})
refreshInstallBanner()

function onInAppToast(ev: Event) {
  const detail = (ev as CustomEvent<{
    text?: string
    kind?: 'ok' | 'warn' | 'err' | 'message'
    title?: string
    dialogId?: string
    initials?: string
  }>).detail
  if (!detail?.text) return
  inAppToast.value = {
    text: detail.text,
    kind: detail.kind ?? 'ok',
    title: detail.title,
    dialogId: detail.dialogId,
    initials: detail.initials,
  }
  if (inAppToastTimer != null) window.clearTimeout(inAppToastTimer)
  inAppToastTimer = window.setTimeout(() => {
    inAppToast.value = null
    inAppToastTimer = null
  }, 7000)
}

function dismissInAppToast() {
  inAppToast.value = null
  if (inAppToastTimer != null) {
    window.clearTimeout(inAppToastTimer)
    inAppToastTimer = null
  }
}

function openToastDialog() {
  const id = inAppToast.value?.dialogId
  dismissInAppToast()
  if (!id || id === 'test') return
  window.dispatchEvent(new CustomEvent('oe:open-dialog', { detail: { dialogId: id } }))
}

function onSwMessage(ev: MessageEvent) {
  const data = ev.data as { type?: string; dialogId?: string; newsId?: string } | null
  if (!data || typeof data !== 'object') return
  if (data.type === 'oe:open-dialog' && data.dialogId) {
    window.dispatchEvent(new CustomEvent('oe:open-dialog', { detail: { dialogId: data.dialogId } }))
    return
  }
  if (data.type === 'oe:open-notifications') {
    profileOpen.value = false
    if (data.newsId) {
      void router.push({ name: 'news', query: { id: String(data.newsId) } })
      return
    }
    bellOpen.value = true
    placeBellPanel()
    void notifications.fetchList()
  }
}

function onOpenDialogFromNotify(ev: Event) {
  const dialogId = (ev as CustomEvent<{ dialogId?: string }>).detail?.dialogId
  if (!dialogId) return
  profileOpen.value = false
  void router.push({ name: 'chats', query: { dialog: dialogId } })
}

function toggleSidebar() {
  if (!isMdUp.value) {
    mobileNavOpen.value = !mobileNavOpen.value
    return
  }
  collapsed.value = !collapsed.value
}

function closeMobileNav() {
  mobileNavOpen.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    mobileNavOpen.value = false
    profileOpen.value = false
    bellOpen.value = false
  }
}

let mdMq: MediaQueryList | null = null
function onMdMqChange() {
  if (!mdMq) return
  isMdUp.value = mdMq.matches
  if (mdMq.matches) mobileNavOpen.value = false
}

function toggleClientsGroup() {
  clientsGroupExpanded.value = !clientsGroupExpanded.value
}

function toggleUsersGroup() {
  usersGroupExpanded.value = !usersGroupExpanded.value
}

function toggleSettingsGroup() {
  settingsGroupExpanded.value = !settingsGroupExpanded.value
}

function logout() {
  profileOpen.value = false
  bellOpen.value = false
  chats.disconnectRealtime()
  void (async () => {
    await auth.logoutWithOffline()
    router.push({ name: 'login' })
  })()
}

async function loadPresenceStatuses() {
  try {
    const rows = await listPresenceStatusesRequest()
    presenceStatuses.value = rows.map(mapPresenceStatus)
    presenceLoadError.value = ''
  } catch (e) {
    // Keep previous list so a transient error does not hide statuses.
    presenceLoadError.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить статусы'
    if (!presenceStatuses.value.length) {
      window.dispatchEvent(
        new CustomEvent('oe:in-app-toast', {
          detail: { kind: 'err', title: 'Статусы', text: presenceLoadError.value },
        }),
      )
    }
  }
}

function toggleProfileMenu() {
  bellOpen.value = false
  profileOpen.value = !profileOpen.value
  if (profileOpen.value) {
    placeProfileMenu()
    void loadPresenceStatuses()
  }
}

async function toggleBell() {
  profileOpen.value = false
  bellOpen.value = !bellOpen.value
  if (bellOpen.value) {
    placeBellPanel()
    await notifications.fetchList()
  }
}

async function openNotificationItem(id: string) {
  const item = notifications.items.find((n) => n.id === id)
  bellOpen.value = false
  if (item && !item.read) {
    try {
      await notifications.markRead([id])
    } catch {
      // keep navigation usable
    }
  }
  if (item?.link) {
    void router.push(item.link)
    return
  }
  if (item?.kind === 'system_news') {
    const newsId = id.replace(/^news:/, '')
    void router.push({ name: 'news', query: { id: newsId } })
    return
  }
  void router.push({ name: 'news' })
}

async function markAllNotificationsRead() {
  try {
    await notifications.markAllRead()
  } catch (e) {
    window.dispatchEvent(
      new CustomEvent('oe:in-app-toast', {
        detail: {
          kind: 'err',
          title: 'Оповещения',
          text: e instanceof ApiError ? e.detail : 'Не удалось отметить прочитанным',
        },
      }),
    )
  }
}

function openAllNews() {
  bellOpen.value = false
  void router.push({ name: 'news' })
}

async function choosePresence(statusId: number) {
  if (presenceBusy.value || currentPresenceId.value === statusId) {
    profileOpen.value = false
    return
  }
  const selected = presenceStatuses.value.find((s) => s.id === statusId) ?? null
  presenceBusy.value = true
  try {
    await auth.setPresence(statusId, selected)
    profileOpen.value = false
  } catch (e) {
    window.dispatchEvent(
      new CustomEvent('oe:in-app-toast', {
        detail: {
          kind: 'err',
          title: 'Статус',
          text: e instanceof ApiError ? e.detail : 'Не удалось сменить статус',
        },
      }),
    )
  } finally {
    presenceBusy.value = false
  }
}

function onAuthExpired() {
  if (auth.isSessionRefreshing) return
  chats.disconnectRealtime()
  auth.logout()
  if (route.name !== 'login') {
    router.push({ name: 'login', query: { redirect: route.fullPath } })
  }
}

function onSessionRefreshed() {
  if (!auth.isAuthenticated) return
  chats.disconnectRealtime()
  if (auth.canSection('/chats')) {
    chats.connectRealtime()
  }
}

function onDocClick(e: MouseEvent) {
  unlockNotifyAudio()
  const t = e.target as Node
  if (profileOpen.value) {
    if (!(profileRoot.value?.contains(t) || profileMenu.value?.contains(t))) {
      profileOpen.value = false
    }
  }
  if (bellOpen.value) {
    if (!(bellRoot.value?.contains(t) || bellPanel.value?.contains(t))) {
      bellOpen.value = false
    }
  }
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
  window.addEventListener(AUTH_EXPIRED_EVENT, onAuthExpired)
  window.addEventListener(SESSION_REFRESHED_EVENT, onSessionRefreshed)
  window.addEventListener('oe:open-dialog', onOpenDialogFromNotify)
  window.addEventListener('oe:in-app-toast', onInAppToast)
  window.addEventListener('resize', placeProfileMenu)
  window.addEventListener('scroll', placeProfileMenu, true)
  window.addEventListener('resize', placeBellPanel)
  window.addEventListener('scroll', placeBellPanel, true)
  mdMq = window.matchMedia('(min-width: 768px)')
  onMdMqChange()
  mdMq.addEventListener('change', onMdMqChange)
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', onSwMessage)
  }
  if (isPushEnabled() && notificationPermission() !== 'granted') {
    setPushEnabled(false)
  } else if (isPushEnabled()) {
    void prepareNotifyServiceWorker()
    void import('@/utils/webPush').then(({ subscribeWebPush }) => {
      void subscribeWebPush()
    })
  }
  if (auth.canSection('/chats')) {
    chats.connectRealtime()
    void chats.fetchUnreadSummary()
  }
  void loadPresenceStatuses()
  void notifications.fetchUnreadCount()
  notificationsPollTimer = window.setInterval(() => {
    void notifications.fetchUnreadCount()
  }, 60_000)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener(AUTH_EXPIRED_EVENT, onAuthExpired)
  window.removeEventListener(SESSION_REFRESHED_EVENT, onSessionRefreshed)
  window.removeEventListener('oe:open-dialog', onOpenDialogFromNotify)
  window.removeEventListener('oe:in-app-toast', onInAppToast)
  window.removeEventListener('resize', placeProfileMenu)
  window.removeEventListener('scroll', placeProfileMenu, true)
  window.removeEventListener('resize', placeBellPanel)
  window.removeEventListener('scroll', placeBellPanel, true)
  mdMq?.removeEventListener('change', onMdMqChange)
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.removeEventListener('message', onSwMessage)
  }
  if (inAppToastTimer != null) window.clearTimeout(inAppToastTimer)
  if (notificationsPollTimer) window.clearInterval(notificationsPollTimer)
  document.documentElement.classList.remove('oe-chat-immersive')
  stopInstallWatch?.()
  chats.disconnectRealtime()
  document.title = BASE_TITLE
  resetFavicon()
  void setAppBadgeCount(0)
})
</script>

<template>
  <div class="flex h-full min-h-0 bg-surface text-ink">
    <!-- Mobile drawer backdrop -->
    <div
      v-show="mobileNavOpen"
      class="fixed inset-0 z-40 bg-ink/40 md:hidden"
      aria-hidden="true"
      @click="closeMobileNav"
    />

    <aside
      class="flex shrink-0 flex-col overflow-hidden bg-sidebar text-white transition-[width,transform] duration-300 ease-out max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-50 max-md:w-72 max-md:pt-[env(safe-area-inset-top)] max-md:pb-[env(safe-area-inset-bottom)] max-md:shadow-xl"
      :class="[
        isMdUp ? (collapsed ? 'w-[4.25rem]' : 'w-64') : 'w-72',
        !isMdUp && !mobileNavOpen ? '-translate-x-full pointer-events-none' : 'translate-x-0',
      ]"
    >
      <div
        class="flex shrink-0 items-center gap-2.5"
        :class="expandedNav ? 'h-[4.5rem] px-4' : 'h-14 justify-center px-2'"
      >
        <button
          type="button"
          class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand text-white transition hover:brightness-110 md:hidden"
          title="Закрыть меню"
          @click="toggleSidebar"
        >
          <X class="size-4" />
        </button>
        <button
          v-if="isMdUp"
          type="button"
          class="flex size-9 shrink-0 items-center justify-center rounded-lg text-white/70 transition hover:bg-sidebar-hover hover:text-white"
          :title="collapsed ? 'Развернуть меню' : 'Свернуть меню'"
          @click="toggleSidebar"
        >
          <Menu class="size-4" />
        </button>
        <div
          class="min-w-0 overflow-hidden transition-opacity duration-200"
          :class="expandedNav ? 'flex-1 opacity-100' : 'pointer-events-none w-0 opacity-0'"
        >
          <div class="flex items-center gap-2.5">
            <span
              class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand shadow-sm shadow-black/20"
              aria-hidden="true"
            >
              <svg width="22" height="18" viewBox="0 0 22 18" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path
                  d="M5.5 13.5h9.2c2.1 0 3.8-1.6 3.8-3.5S16.8 6.5 14.7 6.5c-.3-2.1-2.1-3.7-4.3-3.7-1.8 0-3.4 1.1-4 2.7-.3-.1-.6-.2-1-.2C3.7 5.3 2 6.9 2 8.9c0 2 1.7 3.6 3.5 3.6Z"
                  stroke="#fff"
                  stroke-width="1.6"
                  stroke-linejoin="round"
                />
                <path d="M11.2 8.2 17 5.4l-1.1 6.2-1.9-2.3-2.8 1.1.9-2.2Z" fill="#fff" />
              </svg>
            </span>
            <div class="min-w-0 leading-tight">
              <p class="truncate text-[15px] font-bold tracking-tight text-white">СкайСкейл</p>
              <p class="truncate text-[11px] text-white/45">ООО СкайСкейл</p>
            </div>
          </div>
        </div>
      </div>

      <nav class="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2.5 pb-3">
        <RouterLink
          v-for="item in navStartVisible"
          :key="item.to"
          :to="item.to"
          class="oe-nav-link relative"
          :class="route.path.startsWith(item.to) ? 'is-active' : ''"
          :title="item.label"
          @click="closeMobileNav"
        >
          <component :is="item.icon" class="size-[18px] shrink-0 opacity-90" />
          <span
            class="min-w-0 flex-1 truncate transition-opacity duration-200"
            :class="expandedNav ? 'opacity-100' : 'w-0 overflow-hidden opacity-0'"
          >{{ item.label }}</span>
          <span
            v-if="item.to === '/chats' && chatsUnread > 0"
            class="flex items-center justify-center rounded-full font-semibold"
            :class="[
              expandedNav
                ? 'h-5 min-w-5 px-1.5 text-[10px]'
                : 'absolute right-1 top-1 h-4 min-w-4 text-[9px]',
              route.path.startsWith('/chats') ? 'bg-white/20 text-white' : 'bg-brand text-white',
            ]"
          >
            {{ chatsUnread > 99 ? '99+' : chatsUnread }}
          </span>
          <span
            v-else-if="item.to === '/appeals' && newAppealsBadge > 0"
            class="flex items-center justify-center rounded-full bg-brand font-semibold text-white"
            :class="
              expandedNav
                ? 'h-5 min-w-5 px-1.5 text-[10px]'
                : 'absolute right-1 top-1 h-4 min-w-4 text-[9px]'
            "
          >
            {{ newAppealsBadge > 99 ? '99+' : newAppealsBadge }}
          </span>
        </RouterLink>

        <div v-if="showClientsGroup && clientsChildrenVisible.length" class="mt-0.5">
          <button
            v-if="expandedNav"
            type="button"
            class="oe-nav-link w-full"
            :class="onClientsSection ? 'text-white' : ''"
            @click="toggleClientsGroup"
          >
            <ContactRound class="size-[18px] shrink-0 opacity-90" />
            <span class="min-w-0 flex-1 truncate text-left">Клиенты</span>
            <ChevronDown
              class="size-4 shrink-0 opacity-60 transition-transform duration-200"
              :class="clientsGroupExpanded ? 'rotate-180' : ''"
            />
          </button>
          <div
            v-if="expandedNav && clientsGroupExpanded"
            class="mt-0.5 space-y-0.5 border-l border-white/10 ml-4 pl-2"
          >
            <RouterLink
              v-for="child in clientsChildrenVisible"
              :key="child.to"
              :to="child.to"
              class="oe-nav-link py-2 text-[13px]"
              :class="route.path.startsWith(child.to) ? 'is-active' : ''"
              :title="child.label"
              @click="closeMobileNav"
            >
              <component :is="child.icon" class="size-4 shrink-0 opacity-90" />
              <span class="truncate">{{ child.label }}</span>
            </RouterLink>
          </div>
          <template v-if="!expandedNav">
            <RouterLink
              v-for="child in clientsChildrenVisible"
              :key="'rail-clients-' + child.to"
              :to="child.to"
              class="oe-nav-link justify-center px-2.5"
              :class="route.path.startsWith(child.to) ? 'is-active' : ''"
              :title="child.label"
            >
              <component :is="child.icon" class="size-[18px] shrink-0 opacity-90" />
            </RouterLink>
          </template>
        </div>

        <RouterLink
          v-for="item in navEndVisible"
          :key="item.to"
          :to="item.to"
          class="oe-nav-link"
          :class="route.path.startsWith(item.to) ? 'is-active' : ''"
          :title="item.label"
          @click="closeMobileNav"
        >
          <component :is="item.icon" class="size-[18px] shrink-0 opacity-90" />
          <span
            class="min-w-0 flex-1 truncate transition-opacity duration-200"
            :class="expandedNav ? 'opacity-100' : 'w-0 overflow-hidden opacity-0'"
          >{{ item.label }}</span>
        </RouterLink>

        <div v-if="showUsersGroup" class="mt-0.5">
          <button
            v-if="expandedNav"
            type="button"
            class="oe-nav-link w-full"
            :class="onUsersSection ? 'text-white' : ''"
            @click="toggleUsersGroup"
          >
            <Users class="size-[18px] shrink-0 opacity-90" />
            <span class="min-w-0 flex-1 truncate text-left">Пользователи</span>
            <ChevronDown
              class="size-4 shrink-0 opacity-60 transition-transform duration-200"
              :class="usersGroupExpanded ? 'rotate-180' : ''"
            />
          </button>
          <div
            v-if="expandedNav && usersGroupExpanded"
            class="mt-0.5 space-y-0.5 border-l border-white/10 ml-4 pl-2"
          >
            <RouterLink
              v-for="child in usersChildren"
              :key="child.to"
              :to="child.to"
              class="oe-nav-link py-2 text-[13px]"
              :class="route.path.startsWith(child.to) ? 'is-active' : ''"
              :title="child.label"
              @click="closeMobileNav"
            >
              <component :is="child.icon" class="size-4 shrink-0 opacity-90" />
              <span class="truncate">{{ child.label }}</span>
            </RouterLink>
          </div>
          <template v-if="!expandedNav">
            <RouterLink
              v-for="child in usersChildren"
              :key="'rail-' + child.to"
              :to="child.to"
              class="oe-nav-link justify-center px-2.5"
              :class="route.path.startsWith(child.to) ? 'is-active' : ''"
              :title="child.label"
            >
              <component :is="child.icon" class="size-[18px] shrink-0 opacity-90" />
            </RouterLink>
          </template>
        </div>

        <div v-if="showSettingsGroup" class="mt-0.5">
          <button
            v-if="expandedNav"
            type="button"
            class="oe-nav-link w-full"
            :class="onSettingsSection ? 'text-white' : ''"
            @click="toggleSettingsGroup"
          >
            <Settings class="size-[18px] shrink-0 opacity-90" />
            <span class="min-w-0 flex-1 truncate text-left">Настройки</span>
            <ChevronDown
              class="size-4 shrink-0 opacity-60 transition-transform duration-200"
              :class="settingsGroupExpanded ? 'rotate-180' : ''"
            />
          </button>
          <div
            v-if="expandedNav && settingsGroupExpanded"
            class="mt-0.5 space-y-2 border-l border-white/10 ml-4 pl-2"
          >
            <div v-for="group in settingsGroupsVisible" :key="group.id">
              <p class="px-2 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wide text-white/35">
                {{ group.title }}
              </p>
              <div class="space-y-0.5">
                <RouterLink
                  v-for="child in group.items"
                  :key="child.to"
                  :to="child.to"
                  class="oe-nav-link py-2 text-[13px]"
                  :class="route.path.startsWith(child.to) ? 'is-active' : ''"
                  :title="child.label"
                  @click="closeMobileNav"
                >
                  <component :is="child.icon" class="size-4 shrink-0 opacity-90" />
                  <span class="truncate">{{ child.label }}</span>
                </RouterLink>
              </div>
            </div>
          </div>
          <template v-if="!expandedNav">
            <RouterLink
              v-for="child in settingsFlatLeaves"
              :key="'rail-settings-' + child.to"
              :to="child.to"
              class="oe-nav-link justify-center px-2.5"
              :class="route.path.startsWith(child.to) ? 'is-active' : ''"
              :title="child.label"
            >
              <component :is="child.icon" class="size-[18px] shrink-0 opacity-90" />
            </RouterLink>
          </template>
        </div>
      </nav>

      <div
        v-if="expandedNav"
        class="shrink-0 border-t border-white/10 px-4 py-3"
      >
        <div class="flex items-center gap-2 text-[12px] text-sidebar-muted">
          <span class="size-1.5 shrink-0 rounded-full bg-ok" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate">Система работает</span>
          <span class="shrink-0 text-[11px] text-white/30">v{{ appVersion }}</span>
        </div>
      </div>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <div
        v-if="showInstallBanner && !hideChromeForMobileChat"
        class="relative shrink-0 overflow-hidden bg-gradient-to-br from-[#7a0a18] via-brand to-[#c41e34] px-3 py-3 text-white shadow-sm md:px-5"
        role="region"
        aria-label="Установка приложения"
      >
        <div
          class="pointer-events-none absolute -left-10 -top-12 size-36 rounded-full bg-white/15 blur-2xl"
          aria-hidden="true"
        />
        <div
          class="pointer-events-none absolute -bottom-16 right-0 size-44 rounded-full bg-cyan-200/25 blur-3xl"
          aria-hidden="true"
        />
        <div class="relative flex items-center gap-3 sm:gap-4">
          <img
            src="/pwa-192.png"
            alt=""
            width="56"
            height="56"
            class="size-12 shrink-0 rounded-[14px] shadow-lg shadow-black/20 ring-2 ring-white/35 sm:size-14 sm:rounded-2xl"
          />
          <div class="min-w-0 flex-1">
            <p class="text-[15px] font-bold leading-snug tracking-tight sm:text-base">
              Установите приложение на телефон
            </p>
            <p
              v-if="iosInstallHint && !installPromptReady"
              class="mt-0.5 text-xs leading-snug text-white/85"
            >
              Нажмите
              <Share class="mx-0.5 inline size-3.5 align-text-bottom opacity-95" />
              «Поделиться» → «На экран „Домой“»
            </p>
            <p v-else class="mt-0.5 text-xs leading-snug text-white/85">
              Ярлык на экране, полный экран и быстрые оповещения — как в обычном приложении.
            </p>
            <div class="mt-2.5 flex flex-wrap items-center gap-2">
              <button
                type="button"
                class="inline-flex items-center gap-1.5 rounded-xl bg-white px-3.5 py-2 text-xs font-bold text-[#0b4fd9] shadow-sm transition hover:bg-white/95 active:scale-[0.98]"
                @click="onInstallApp"
              >
                <Download class="size-3.5" />
                Установить приложение
              </button>
              <button
                type="button"
                class="rounded-xl px-2.5 py-2 text-xs font-semibold text-white/80 transition hover:bg-white/10 hover:text-white"
                @click="onDismissInstall"
              >
                Позже
              </button>
            </div>
            <p v-if="installHelp" class="mt-2 text-xs leading-snug text-white/90">
              {{ installHelp }}
            </p>
          </div>
          <button
            type="button"
            class="shrink-0 self-start rounded-lg p-1.5 text-white/70 transition hover:bg-white/15 hover:text-white"
            title="Закрыть"
            @click="onDismissInstall"
          >
            <X class="size-4" />
          </button>
        </div>
      </div>

      <header
        v-if="!hideChromeForMobileChat"
        class="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-line bg-panel px-3 md:px-6"
      >
        <div class="flex min-w-0 items-center gap-2">
          <h1 class="truncate text-lg font-bold tracking-tight text-ink md:text-xl">{{ title }}</h1>
        </div>
        <div class="flex shrink-0 items-center gap-2 sm:gap-3">
          <div ref="bellRoot" class="relative">
            <button
              type="button"
              class="relative flex size-9 items-center justify-center rounded-full text-ink/70 transition hover:bg-surface hover:text-ink"
              :class="bellOpen ? 'bg-surface text-ink' : ''"
              title="Оповещения"
              :aria-expanded="bellOpen"
              aria-haspopup="dialog"
              @click.stop="toggleBell"
            >
              <Bell class="size-[18px]" />
              <span
                v-if="notifications.unreadCount > 0"
                class="absolute right-1.5 top-1.5 size-2 rounded-full bg-brand ring-2 ring-panel"
              />
            </button>

            <Teleport to="body">
              <div
                v-if="bellOpen"
                ref="bellPanel"
                class="fixed z-[200] overflow-hidden rounded-xl border border-line bg-panel shadow-xl shadow-black/10"
                role="dialog"
                aria-label="Оповещения"
                :style="bellPanelStyle"
                @click.stop
              >
                <div class="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
                  <div class="min-w-0">
                    <p class="text-sm font-semibold text-ink">Оповещения</p>
                    <p class="text-[11px] text-mute">Новости и служебные уведомления</p>
                  </div>
                  <button
                    v-if="notifications.hasUnread"
                    type="button"
                    class="shrink-0 text-xs font-medium text-brand hover:underline"
                    @click="markAllNotificationsRead"
                  >
                    Прочитать все
                  </button>
                </div>

                <div class="max-h-[min(70vh,26rem)] overflow-y-auto">
                  <p
                    v-if="notifications.loading && !notifications.items.length"
                    class="px-4 py-8 text-center text-sm text-mute"
                  >
                    Загрузка…
                  </p>
                  <p
                    v-else-if="notifications.error"
                    class="px-4 py-4 text-center text-sm text-red-600"
                  >
                    {{ notifications.error }}
                  </p>
                  <p
                    v-else-if="!notifications.items.length"
                    class="px-4 py-8 text-center text-sm text-mute"
                  >
                    Пока нет оповещений
                  </p>
                  <button
                    v-for="n in notifications.items"
                    :key="n.id"
                    type="button"
                    class="flex w-full gap-3 border-b border-line px-4 py-3 text-left transition last:border-b-0 hover:bg-surface"
                    :class="!n.read ? 'bg-brand-soft/20' : ''"
                    @click="openNotificationItem(n.id)"
                  >
                    <span
                      class="mt-1.5 size-2 shrink-0 rounded-full"
                      :class="n.read ? 'bg-transparent' : 'bg-brand'"
                      aria-hidden="true"
                    />
                    <div class="min-w-0 flex-1">
                      <div class="flex items-baseline justify-between gap-2">
                        <p class="truncate text-sm font-semibold text-ink">{{ n.title }}</p>
                        <time class="shrink-0 text-[10px] text-mute">{{ formatNotifyAt(n.createdAt) }}</time>
                      </div>
                      <p class="mt-1 line-clamp-2 text-xs leading-relaxed text-mute">{{ n.body }}</p>
                      <p class="mt-1.5 text-[10px] font-medium uppercase tracking-wide text-mute">
                        {{ notificationKindLabel(n.kind) }}
                      </p>
                    </div>
                  </button>
                </div>

                <div class="border-t border-line px-4 py-2.5">
                  <button
                    type="button"
                    class="w-full text-center text-xs font-medium text-brand hover:underline"
                    @click="openAllNews"
                  >
                    Все новости системы
                  </button>
                </div>
              </div>
            </Teleport>
          </div>

          <div ref="profileRoot" class="relative shrink-0">
          <button
            type="button"
            class="flex max-w-[min(100%,18rem)] items-center gap-2.5 rounded-full py-1 pl-1 pr-2 transition hover:bg-surface sm:max-w-xs sm:pr-2.5"
            :aria-expanded="profileOpen"
            aria-haspopup="menu"
            @click.stop="toggleProfileMenu"
          >
            <span class="relative flex size-9 shrink-0 items-center justify-center rounded-full bg-brand text-[12px] font-bold text-white">
              {{ initials }}
            </span>
            <span class="hidden min-w-0 text-left sm:block">
              <span class="block truncate text-sm font-semibold text-ink">{{ auth.user?.name }}</span>
              <span class="flex items-center gap-1.5 truncate text-[11px] text-mute">
                <span
                  v-if="currentPresence"
                  class="size-1.5 shrink-0 rounded-full"
                  :style="{ background: currentPresence.color }"
                />
                {{ currentPresence?.name || roleDisplay }}
              </span>
            </span>
            <ChevronDown
              class="hidden size-4 shrink-0 text-mute transition-transform sm:block"
              :class="profileOpen ? 'rotate-180' : ''"
            />
          </button>

          <Teleport to="body">
            <div
              v-if="profileOpen"
              ref="profileMenu"
              class="fixed z-[200] w-64 overflow-hidden rounded-xl border border-line bg-panel py-1 shadow-lg"
              role="menu"
              :style="profileMenuStyle"
              @click.stop
            >
              <div class="border-b border-line px-3 py-2.5 sm:hidden">
                <p class="truncate text-sm font-medium text-ink">{{ auth.user?.name }}</p>
                <p class="truncate text-xs text-mute">{{ roleDisplay }}</p>
              </div>
              <div class="border-b border-line py-1">
                <p class="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-mute">
                  Статус
                </p>
                <p v-if="!presenceStatuses.length" class="px-3 py-2 text-xs text-mute">
                  {{ presenceLoadError || 'Загрузка…' }}
                </p>
                <div class="max-h-56 overflow-y-auto">
                  <button
                    v-for="s in presenceStatuses"
                    :key="s.id"
                    type="button"
                    class="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition hover:bg-surface"
                    :class="currentPresenceId === s.id ? 'bg-brand-soft/50 text-ink' : 'text-ink'"
                    role="menuitem"
                    :disabled="presenceBusy"
                    @click="choosePresence(s.id)"
                  >
                    <span class="size-2.5 shrink-0 rounded-full" :style="{ background: s.color }" />
                    <span class="flex-1 truncate">{{ s.name }}</span>
                    <span
                      v-if="currentPresenceId === s.id"
                      class="text-[11px] text-brand"
                    >✓</span>
                  </button>
                </div>
                <button
                  type="button"
                  class="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-danger transition hover:bg-danger-soft"
                  role="menuitem"
                  @click="logout"
                >
                  <span class="size-2.5 shrink-0 rounded-full bg-[#9ca3af]" />
                  <span class="flex-1">Выход</span>
                  <LogOut class="size-3.5 opacity-70" />
                </button>
              </div>
              <RouterLink
                :to="{ name: 'profile' }"
                class="flex items-center gap-2.5 px-3 py-2.5 text-sm text-ink transition hover:bg-surface"
                role="menuitem"
                @click="profileOpen = false"
              >
                <UserRound class="size-4 text-mute" />
                Профиль
              </RouterLink>
              <RouterLink
                :to="{ name: 'profile-templates' }"
                class="flex items-center gap-2.5 px-3 py-2.5 text-sm text-ink transition hover:bg-surface"
                role="menuitem"
                @click="profileOpen = false"
              >
                <TextQuote class="size-4 text-mute" />
                Мои шаблоны
              </RouterLink>
            </div>
          </Teleport>
        </div>
        </div>
      </header>

      <main
        class="min-h-0 flex-1 overflow-hidden"
        :class="showMobileTabBar ? 'pb-[calc(3.5rem+env(safe-area-inset-bottom))] md:pb-0' : ''"
      >
        <RouterView v-slot="{ Component }">
          <Transition name="oe-page" mode="out-in">
            <component :is="Component" :key="route.path" />
          </Transition>
        </RouterView>
      </main>

      <nav
        v-if="showMobileTabBar"
        class="oe-tabbar fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-panel/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
        aria-label="Основная навигация"
      >
        <button
          v-for="tab in mobileTabs"
          :key="tab.id"
          type="button"
          class="relative flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 px-1 pt-1.5 text-[10px] font-semibold transition"
          :class="
            isMobileTabActive(tab) ? 'text-brand' : 'text-mute hover:text-ink'
          "
          @click="onMobileTab(tab)"
        >
          <component :is="tab.icon" class="size-5 shrink-0" />
          <span class="truncate">{{ tab.label }}</span>
          <span
            v-if="tab.badge === 'chats' && chatsUnread > 0"
            class="absolute right-[18%] top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand px-1 text-[9px] font-bold text-white"
          >
            {{ chatsUnread > 99 ? '99+' : chatsUnread }}
          </span>
        </button>
      </nav>
    </div>

    <div
      v-if="inAppToast"
      class="pointer-events-none fixed inset-x-0 top-3 z-[100] flex justify-center px-3"
    >
      <div
        class="pointer-events-auto flex max-w-md items-start gap-3 rounded-xl border px-3.5 py-3 shadow-lg"
        :class="{
          'border-line bg-panel text-ink': inAppToast.kind === 'ok' || inAppToast.kind === 'message',
          'border-amber-200 bg-amber-50 text-amber-950': inAppToast.kind === 'warn',
          'border-danger/30 bg-danger-soft text-danger': inAppToast.kind === 'err',
        }"
      >
        <span
          v-if="inAppToast.kind === 'message'"
          class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-brand text-[11px] font-semibold text-white"
        >{{ inAppToast.initials || '?' }}</span>
        <div class="min-w-0 flex-1">
          <p v-if="inAppToast.title" class="text-sm font-semibold leading-snug">{{ inAppToast.title }}</p>
          <p class="text-sm leading-snug" :class="inAppToast.title ? 'mt-0.5 text-mute' : ''">{{ inAppToast.text }}</p>
          <button
            v-if="inAppToast.dialogId && inAppToast.dialogId !== 'test'"
            type="button"
            class="mt-2 text-xs font-semibold text-brand hover:underline"
            @click="openToastDialog"
          >
            Открыть диалог
          </button>
        </div>
        <button
          type="button"
          class="shrink-0 rounded-md px-1.5 py-0.5 text-lg leading-none text-mute hover:bg-black/5"
          aria-label="Закрыть"
          @click="dismissInAppToast"
        >
          ×
        </button>
      </div>
    </div>
  </div>
</template>
