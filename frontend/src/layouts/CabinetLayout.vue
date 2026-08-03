<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
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
} from 'lucide-vue-next'
import { AUTH_EXPIRED_EVENT } from '@/api/client'
import { isSettingsPath, SETTINGS_NAV_GROUPS, settingsLeafTitle } from '@/navigation/settingsNav'
import { useAuthStore } from '@/stores/auth'
import { useChatsStore } from '@/stores/chats'
import {
  isPushEnabled,
  notificationPermission,
  setPushEnabled,
  unlockNotifyAudio,
} from '@/utils/notify'

const SIDEBAR_KEY = 'oe_sidebar_collapsed'
const USERS_GROUP_KEY = 'oe_nav_users_open'
const SETTINGS_GROUP_KEY = 'oe_nav_settings_open'
const BASE_TITLE = 'SkySender'

const auth = useAuthStore()
const chats = useChatsStore()
const route = useRoute()
const router = useRouter()

type NavLeaf = { to: string; label: string; icon: typeof MessageSquare }

const navFlat: NavLeaf[] = [
  { to: '/chats', label: 'Чаты', icon: MessageSquare },
  { to: '/appeals', label: 'Обращения', icon: Inbox },
  { to: '/mailing', label: 'Рассылки', icon: Megaphone },
]

const usersChildren: NavLeaf[] = [
  { to: '/users', label: 'Пользователи', icon: Users },
  { to: '/roles', label: 'Роли', icon: Shield },
  { to: '/departments', label: 'Отделы', icon: Building2 },
]

const collapsed = ref(localStorage.getItem(SIDEBAR_KEY) === '1')
const mobileNavOpen = ref(false)
const isMdUp = ref(typeof window !== 'undefined' ? window.matchMedia('(min-width: 768px)').matches : true)
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

const showUsersGroup = computed(() => auth.canSection('/users'))
const showSettingsGroup = computed(() => settingsGroupsVisible.value.length > 0)
const navBefore = computed(() => navFlat.filter((item) => auth.canSection(item.to)))

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
  if (route.path.startsWith('/users')) return 'Пользователи'
  if (route.path.startsWith('/roles')) return 'Роли'
  if (route.path.startsWith('/departments')) return 'Отделы'
  const settingsTitle = settingsLeafTitle(route.path)
  if (settingsTitle) return settingsTitle
  const all = [...navFlat, ...usersChildren]
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
watch(usersGroupExpanded, (v) => localStorage.setItem(USERS_GROUP_KEY, v ? '1' : '0'))
watch(settingsGroupExpanded, (v) => localStorage.setItem(SETTINGS_GROUP_KEY, v ? '1' : '0'))

watch(
  () => route.path,
  () => {
    profileOpen.value = false
    mobileNavOpen.value = false
    if (onUsersSection.value) usersGroupExpanded.value = true
    if (onSettingsSection.value) settingsGroupExpanded.value = true
  },
)

watch(
  chatsUnread,
  (n) => {
    document.title = n > 0 ? `(${n > 99 ? '99+' : n}) ${BASE_TITLE}` : BASE_TITLE
  },
  { immediate: true },
)

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
  const data = ev.data as { type?: string; dialogId?: string } | null
  if (!data || data.type !== 'oe:open-dialog' || !data.dialogId) return
  window.dispatchEvent(new CustomEvent('oe:open-dialog', { detail: { dialogId: data.dialogId } }))
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
  }
}

let mdMq: MediaQueryList | null = null
function onMdMqChange() {
  if (!mdMq) return
  isMdUp.value = mdMq.matches
  if (mdMq.matches) mobileNavOpen.value = false
}

function toggleUsersGroup() {
  usersGroupExpanded.value = !usersGroupExpanded.value
}

function toggleSettingsGroup() {
  settingsGroupExpanded.value = !settingsGroupExpanded.value
}

function logout() {
  profileOpen.value = false
  chats.disconnectRealtime()
  auth.logout()
  router.push({ name: 'login' })
}

function onAuthExpired() {
  chats.disconnectRealtime()
  auth.logout()
  if (route.name !== 'login') {
    router.push({ name: 'login', query: { redirect: route.fullPath } })
  }
}

function onDocClick(e: MouseEvent) {
  unlockNotifyAudio()
  if (!profileOpen.value) return
  const el = profileRoot.value
  if (el && !el.contains(e.target as Node)) profileOpen.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
  window.addEventListener(AUTH_EXPIRED_EVENT, onAuthExpired)
  window.addEventListener('oe:open-dialog', onOpenDialogFromNotify)
  window.addEventListener('oe:in-app-toast', onInAppToast)
  mdMq = window.matchMedia('(min-width: 768px)')
  onMdMqChange()
  mdMq.addEventListener('change', onMdMqChange)
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', onSwMessage)
  }
  if (isPushEnabled() && notificationPermission() !== 'granted') {
    setPushEnabled(false)
  }
  if (auth.canSection('/chats')) {
    chats.connectRealtime()
    void chats.fetchUnreadSummary()
  }
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener(AUTH_EXPIRED_EVENT, onAuthExpired)
  window.removeEventListener('oe:open-dialog', onOpenDialogFromNotify)
  window.removeEventListener('oe:in-app-toast', onInAppToast)
  mdMq?.removeEventListener('change', onMdMqChange)
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.removeEventListener('message', onSwMessage)
  }
  if (inAppToastTimer != null) window.clearTimeout(inAppToastTimer)
  chats.disconnectRealtime()
  document.title = BASE_TITLE
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
      class="flex shrink-0 flex-col overflow-hidden border-r border-line bg-panel transition-[width,transform] duration-300 ease-out max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-50 max-md:w-72 max-md:shadow-xl"
      :class="[
        isMdUp ? (collapsed ? 'w-[4.25rem]' : 'w-60') : 'w-72',
        !isMdUp && !mobileNavOpen ? '-translate-x-full' : 'translate-x-0',
      ]"
    >
      <div
        class="flex h-14 shrink-0 items-center gap-2 border-b border-line"
        :class="expandedNav ? 'px-3' : 'justify-center px-2'"
      >
        <button
          type="button"
          class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand text-white transition hover:brightness-105"
          :title="!isMdUp ? 'Закрыть меню' : collapsed ? 'Развернуть меню' : 'Свернуть меню'"
          @click="toggleSidebar"
        >
          <X v-if="!isMdUp" class="size-4" />
          <Menu v-else class="size-4" />
        </button>
        <div
          class="min-w-0 overflow-hidden transition-opacity duration-200"
          :class="expandedNav ? 'flex-1 opacity-100' : 'pointer-events-none w-0 opacity-0'"
        >
          <p class="truncate text-sm font-semibold tracking-tight text-ink">SkySender</p>
          <p class="truncate text-[11px] text-mute">Кабинет оператора</p>
        </div>
      </div>

      <nav class="flex flex-1 flex-col gap-0.5 overflow-y-auto p-2">
        <RouterLink
          v-for="item in navBefore"
          :key="item.to"
          :to="item.to"
          class="group relative flex items-center gap-3 rounded-lg px-2.5 py-2.5 text-sm font-medium text-mute transition hover:bg-surface hover:text-ink"
          :class="route.path.startsWith(item.to) ? 'bg-brand-soft text-brand hover:bg-brand-soft hover:text-brand' : ''"
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
            class="absolute flex items-center justify-center rounded-full bg-brand font-semibold text-white"
            :class="
              expandedNav
                ? 'right-2 top-1/2 h-5 min-w-5 -translate-y-1/2 px-1.5 text-[10px]'
                : 'right-1 top-1 size-4 text-[9px]'
            "
          >
            {{ chatsUnread > 99 ? '99+' : chatsUnread }}
          </span>
        </RouterLink>

        <div v-if="showUsersGroup" class="mt-0.5">
          <button
            v-if="expandedNav"
            type="button"
            class="flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-sm font-medium transition hover:bg-surface"
            :class="onUsersSection ? 'text-brand' : 'text-mute hover:text-ink'"
            @click="toggleUsersGroup"
          >
            <Users class="size-[18px] shrink-0 opacity-90" />
            <span class="min-w-0 flex-1 truncate text-left">Пользователи</span>
            <ChevronDown
              class="size-4 shrink-0 text-mute transition-transform duration-200"
              :class="usersGroupExpanded ? 'rotate-180' : ''"
            />
          </button>
          <div
            v-if="expandedNav && usersGroupExpanded"
            class="mt-0.5 space-y-0.5 border-l border-line ml-4 pl-2"
          >
            <RouterLink
              v-for="child in usersChildren"
              :key="child.to"
              :to="child.to"
              class="flex items-center gap-2.5 rounded-lg px-2 py-2 text-[13px] font-medium text-mute transition hover:bg-surface hover:text-ink"
              :class="route.path.startsWith(child.to) ? 'bg-brand-soft text-brand hover:bg-brand-soft hover:text-brand' : ''"
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
              class="flex items-center justify-center rounded-lg px-2.5 py-2.5 text-mute transition hover:bg-surface hover:text-ink"
              :class="route.path.startsWith(child.to) ? 'bg-brand-soft text-brand' : ''"
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
            class="flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-sm font-medium transition hover:bg-surface"
            :class="onSettingsSection ? 'text-brand' : 'text-mute hover:text-ink'"
            @click="toggleSettingsGroup"
          >
            <Settings class="size-[18px] shrink-0 opacity-90" />
            <span class="min-w-0 flex-1 truncate text-left">Настройки</span>
            <ChevronDown
              class="size-4 shrink-0 text-mute transition-transform duration-200"
              :class="settingsGroupExpanded ? 'rotate-180' : ''"
            />
          </button>
          <div
            v-if="expandedNav && settingsGroupExpanded"
            class="mt-0.5 space-y-2 border-l border-line ml-4 pl-2"
          >
            <div v-for="group in settingsGroupsVisible" :key="group.id">
              <p class="px-2 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wide text-mute/80">
                {{ group.title }}
              </p>
              <div class="space-y-0.5">
                <RouterLink
                  v-for="child in group.items"
                  :key="child.to"
                  :to="child.to"
                  class="flex items-center gap-2.5 rounded-lg px-2 py-2 text-[13px] font-medium text-mute transition hover:bg-surface hover:text-ink"
                  :class="route.path.startsWith(child.to) ? 'bg-brand-soft text-brand hover:bg-brand-soft hover:text-brand' : ''"
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
              class="flex items-center justify-center rounded-lg px-2.5 py-2.5 text-mute transition hover:bg-surface hover:text-ink"
              :class="route.path.startsWith(child.to) ? 'bg-brand-soft text-brand' : ''"
              :title="child.label"
            >
              <component :is="child.icon" class="size-[18px] shrink-0 opacity-90" />
            </RouterLink>
          </template>
        </div>
      </nav>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-line bg-panel px-3 md:px-6">
        <div class="flex min-w-0 items-center gap-2">
          <button
            type="button"
            class="flex size-9 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-ink transition hover:bg-panel md:hidden"
            title="Меню"
            @click="mobileNavOpen = true"
          >
            <Menu class="size-4" />
          </button>
          <h1 class="truncate text-base font-semibold tracking-tight text-ink md:text-lg">{{ title }}</h1>
        </div>
        <div ref="profileRoot" class="relative shrink-0">
          <button
            type="button"
            class="flex max-w-[min(100%,14rem)] items-center gap-2 rounded-full border border-line bg-surface py-1 pl-1 pr-2.5 transition hover:border-brand/40 hover:bg-brand-soft/40 sm:max-w-xs sm:gap-2.5 sm:pr-3"
            :aria-expanded="profileOpen"
            aria-haspopup="menu"
            @click.stop="profileOpen = !profileOpen"
          >
            <span
              class="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand text-[11px] font-semibold text-white"
            >{{ initials }}</span>
            <span class="hidden min-w-0 text-left sm:block">
              <span class="block truncate text-sm font-medium text-ink">{{ auth.user?.name }}</span>
              <span class="block truncate text-[11px] text-mute">{{ roleDisplay }}</span>
            </span>
            <ChevronDown
              class="hidden size-4 shrink-0 text-mute transition-transform sm:block"
              :class="profileOpen ? 'rotate-180' : ''"
            />
          </button>

          <div
            v-if="profileOpen"
            class="absolute right-0 z-50 mt-2 w-56 overflow-hidden rounded-xl border border-line bg-panel py-1 shadow-lg"
            role="menu"
          >
            <div class="border-b border-line px-3 py-2.5 sm:hidden">
              <p class="truncate text-sm font-medium text-ink">{{ auth.user?.name }}</p>
              <p class="truncate text-xs text-mute">{{ roleDisplay }}</p>
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
            <button
              type="button"
              class="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm text-danger transition hover:bg-danger-soft"
              role="menuitem"
              @click="logout"
            >
              <LogOut class="size-4" />
              Выйти
            </button>
          </div>
        </div>
      </header>
      <main class="min-h-0 flex-1 overflow-hidden">
        <RouterView />
      </main>
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
