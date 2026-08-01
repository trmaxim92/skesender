<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import {
  MessageSquare,
  Radio,
  Users,
  FileText,
  Webhook,
  LogOut,
  Inbox,
  Megaphone,
  Shield,
  Menu,
  ChevronDown,
  Settings,
  Building2,
  FormInput,
  IdCard,
  TextQuote,
  Bell,
  BellOff,
  Volume2,
  VolumeX,
} from 'lucide-vue-next'
import { AUTH_EXPIRED_EVENT } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useChatsStore } from '@/stores/chats'
import {
  ensureNotificationPermission,
  isPushEnabled,
  isSoundEnabled,
  notificationPermission,
  playIncomingSound,
  setPushEnabled,
  setSoundEnabled,
  testOsPush,
  unlockNotifyAudio,
} from '@/utils/notify'

const SIDEBAR_KEY = 'oe_sidebar_collapsed'
const USERS_GROUP_KEY = 'oe_nav_users_open'
const SETTINGS_GROUP_KEY = 'oe_nav_settings_open'
const BASE_TITLE = 'Order Elite'

const auth = useAuthStore()
const chats = useChatsStore()
const route = useRoute()
const router = useRouter()

type NavLeaf = { to: string; label: string; icon: typeof MessageSquare }

const navFlat: NavLeaf[] = [
  { to: '/chats', label: 'Чаты', icon: MessageSquare },
  { to: '/appeals', label: 'Обращения', icon: Inbox },
  { to: '/mailing', label: 'Рассылки', icon: Megaphone },
  { to: '/channels', label: 'Каналы', icon: Radio },
]

const usersChildren: NavLeaf[] = [
  { to: '/users', label: 'Пользователи', icon: Users },
  { to: '/roles', label: 'Роли', icon: Shield },
  { to: '/departments', label: 'Отделы', icon: Building2 },
]

const settingsChildren: NavLeaf[] = [
  { to: '/settings/appeal-fields', label: 'Поля обращения', icon: FormInput },
  { to: '/settings/client-fields', label: 'Карточка клиента', icon: IdCard },
]

const navTail: NavLeaf[] = [
  { to: '/templates', label: 'Шаблоны', icon: FileText },
  { to: '/webhooks', label: 'Webhooks', icon: Webhook },
]

const collapsed = ref(localStorage.getItem(SIDEBAR_KEY) === '1')
const usersGroupExpanded = ref(
  localStorage.getItem(USERS_GROUP_KEY) === '1' ||
    route.path.startsWith('/users') ||
    route.path.startsWith('/roles') ||
    route.path.startsWith('/departments'),
)
const settingsGroupExpanded = ref(
  localStorage.getItem(SETTINGS_GROUP_KEY) !== '0',
)
const profileOpen = ref(false)
const profileRoot = ref<HTMLElement | null>(null)

const showUsersGroup = computed(() => auth.canSection('/users'))
const showSettingsGroup = computed(
  () =>
    auth.can('section.settings') ||
    auth.can('action.manage_users') ||
    auth.canSection('/settings/appeal-fields'),
)
const navBefore = computed(() => navFlat.filter((item) => auth.canSection(item.to)))
const navAfter = computed(() => navTail.filter((item) => auth.canSection(item.to)))

const onUsersSection = computed(
  () =>
    route.path.startsWith('/users') ||
    route.path.startsWith('/roles') ||
    route.path.startsWith('/departments'),
)
const onSettingsSection = computed(
  () =>
    route.path.startsWith('/settings/appeal-fields') ||
    route.path.startsWith('/settings/client-fields'),
)

const title = computed(() => {
  if (route.path.startsWith('/profile/templates')) return 'Мои шаблоны'
  if (route.name === 'appeal-detail') return 'Обращение'
  if (route.path.startsWith('/users')) return 'Пользователи'
  if (route.path.startsWith('/roles')) return 'Роли'
  if (route.path.startsWith('/departments')) return 'Отделы'
  if (route.path.startsWith('/settings/appeal-fields')) return 'Поля обращения'
  if (route.path.startsWith('/settings/client-fields')) return 'Карточка клиента'
  const all = [...navFlat, ...usersChildren, ...settingsChildren, ...navTail]
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
const soundOn = ref(isSoundEnabled())
const pushPermission = ref(notificationPermission())
const pushOn = ref(isPushEnabled() && pushPermission.value === 'granted')
const pushTestHint = ref('')
const inAppToast = ref<{
  text: string
  kind: 'ok' | 'warn' | 'err' | 'message'
  title?: string
  dialogId?: string
  initials?: string
} | null>(null)
let inAppToastTimer: number | null = null
if (isPushEnabled() && pushPermission.value !== 'granted') {
  setPushEnabled(false)
}

watch(collapsed, (v) => localStorage.setItem(SIDEBAR_KEY, v ? '1' : '0'))
watch(usersGroupExpanded, (v) => localStorage.setItem(USERS_GROUP_KEY, v ? '1' : '0'))
watch(settingsGroupExpanded, (v) => localStorage.setItem(SETTINGS_GROUP_KEY, v ? '1' : '0'))

watch(
  () => route.path,
  () => {
    profileOpen.value = false
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

async function toggleSound() {
  unlockNotifyAudio()
  soundOn.value = !soundOn.value
  setSoundEnabled(soundOn.value)
  if (soundOn.value) playIncomingSound()
}

async function togglePush() {
  pushTestHint.value = ''
  if (!pushOn.value) {
    const perm = await ensureNotificationPermission()
    pushPermission.value = perm
    if (perm !== 'granted') {
      pushOn.value = false
      setPushEnabled(false)
      pushTestHint.value =
        perm === 'denied'
          ? 'Браузер заблокировал уведомления для localhost'
          : 'Разрешение не выдано'
      return
    }
    pushOn.value = true
    setPushEnabled(true)
    const test = await testOsPush()
    pushTestHint.value = test.ok
      ? 'Тестовый пуш отправлен — проверь системный тост'
      : `Тест не прошёл: ${test.reason}`
    return
  }
  pushOn.value = false
  setPushEnabled(false)
}

async function runPushTest() {
  pushTestHint.value = 'Запрос…'
  try {
    const test = await testOsPush()
    pushPermission.value = notificationPermission()
    if (test.ok) {
      pushOn.value = true
      pushTestHint.value = `OK (${test.reason}), permission=${test.permission}. Смотри зелёный тост справа и центр уведомлений Windows.`
    } else {
      pushTestHint.value = `Не ок: ${test.reason}`
    }
  } catch (e) {
    pushTestHint.value = `Ошибка: ${e instanceof Error ? e.message : String(e)}`
  }
}

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
  collapsed.value = !collapsed.value
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

function syncPushStateFromBrowser() {
  pushPermission.value = notificationPermission()
  if (pushPermission.value !== 'granted') {
    pushOn.value = false
    if (isPushEnabled()) setPushEnabled(false)
  } else {
    pushOn.value = isPushEnabled()
  }
}

watch(profileOpen, (open) => {
  if (open) syncPushStateFromBrowser()
})

onMounted(() => {
  document.addEventListener('click', onDocClick)
  window.addEventListener(AUTH_EXPIRED_EVENT, onAuthExpired)
  window.addEventListener('oe:open-dialog', onOpenDialogFromNotify)
  window.addEventListener('oe:in-app-toast', onInAppToast)
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', onSwMessage)
  }
  syncPushStateFromBrowser()
  if (auth.canSection('/chats')) {
    chats.connectRealtime()
    void chats.fetchUnreadSummary()
  }
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener(AUTH_EXPIRED_EVENT, onAuthExpired)
  window.removeEventListener('oe:open-dialog', onOpenDialogFromNotify)
  window.removeEventListener('oe:in-app-toast', onInAppToast)
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
    <aside
      class="flex shrink-0 flex-col overflow-hidden border-r border-line bg-panel transition-[width] duration-300 ease-out"
      :class="collapsed ? 'w-[4.25rem]' : 'w-60'"
    >
      <div
        class="flex h-14 shrink-0 items-center gap-2 border-b border-line"
        :class="collapsed ? 'justify-center px-2' : 'px-3'"
      >
        <button
          type="button"
          class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand text-white transition hover:brightness-105"
          :title="collapsed ? 'Развернуть меню' : 'Свернуть меню'"
          @click="toggleSidebar"
        >
          <Menu class="size-4" />
        </button>
        <div
          class="min-w-0 overflow-hidden transition-opacity duration-200"
          :class="collapsed ? 'pointer-events-none w-0 opacity-0' : 'flex-1 opacity-100'"
        >
          <div class="truncate text-sm font-bold tracking-tight">Order Elite</div>
          <div class="truncate text-[11px] text-muted">омниканальный кабинет</div>
        </div>
      </div>

      <nav class="flex flex-1 flex-col gap-0.5 overflow-x-hidden overflow-y-auto p-2">
        <RouterLink
          v-for="item in navBefore"
          :key="item.to"
          :to="item.to"
          class="relative flex items-center gap-2.5 rounded-lg py-2.5 text-sm font-medium text-muted transition hover:bg-surface hover:text-ink"
          :class="collapsed ? 'justify-center px-2' : 'px-3'"
          :title="collapsed ? item.label : undefined"
          active-class="!bg-brand-soft !text-brand"
        >
          <component :is="item.icon" class="size-4 shrink-0" />
          <span v-if="!collapsed" class="truncate whitespace-nowrap">{{ item.label }}</span>
          <span
            v-if="item.to === '/chats' && chatsUnread > 0"
            class="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-ok px-1 text-[9px] font-bold leading-none text-white"
            :class="collapsed ? 'absolute right-1 top-1' : 'ml-auto'"
          >
            {{ chatsUnread > 99 ? '99+' : chatsUnread }}
          </span>
        </RouterLink>

        <div v-if="showUsersGroup" class="mt-0.5">
          <template v-if="!collapsed">
            <button
              type="button"
              class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium text-muted transition hover:bg-surface hover:text-ink"
              :class="onUsersSection ? 'text-ink' : ''"
              @click="toggleUsersGroup"
            >
              <Users class="size-4 shrink-0" />
              <span class="min-w-0 flex-1 truncate text-left whitespace-nowrap">Персонал</span>
              <ChevronDown
                class="size-4 shrink-0 transition-transform duration-200"
                :class="usersGroupExpanded ? 'rotate-0' : '-rotate-90'"
              />
            </button>
            <div
              class="grid transition-[grid-template-rows] duration-200 ease-out"
              :class="usersGroupExpanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'"
            >
              <div class="overflow-hidden">
                <RouterLink
                  v-for="item in usersChildren"
                  :key="item.to"
                  :to="item.to"
                  class="ml-2 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-muted transition hover:bg-surface hover:text-ink"
                  active-class="!bg-brand-soft !text-brand"
                >
                  <component :is="item.icon" class="size-4 shrink-0" />
                  <span class="truncate whitespace-nowrap">{{ item.label }}</span>
                </RouterLink>
              </div>
            </div>
          </template>
          <template v-else>
            <RouterLink
              v-for="item in usersChildren"
              :key="item.to"
              :to="item.to"
              class="flex items-center justify-center rounded-lg px-2 py-2.5 text-muted transition hover:bg-surface hover:text-ink"
              :title="item.label"
              active-class="!bg-brand-soft !text-brand"
            >
              <component :is="item.icon" class="size-4 shrink-0" />
            </RouterLink>
          </template>
        </div>

        <div v-if="showSettingsGroup" class="mt-0.5">
          <template v-if="!collapsed">
            <button
              type="button"
              class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium text-muted transition hover:bg-surface hover:text-ink"
              :class="onSettingsSection ? 'text-ink' : ''"
              @click="toggleSettingsGroup"
            >
              <Settings class="size-4 shrink-0" />
              <span class="min-w-0 flex-1 truncate text-left whitespace-nowrap">Настройки</span>
              <ChevronDown
                class="size-4 shrink-0 transition-transform duration-200"
                :class="settingsGroupExpanded ? 'rotate-0' : '-rotate-90'"
              />
            </button>
            <div
              class="grid transition-[grid-template-rows] duration-200 ease-out"
              :class="settingsGroupExpanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'"
            >
              <div class="overflow-hidden">
                <RouterLink
                  v-for="item in settingsChildren"
                  :key="item.to"
                  :to="item.to"
                  class="ml-2 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-muted transition hover:bg-surface hover:text-ink"
                  active-class="!bg-brand-soft !text-brand"
                >
                  <component :is="item.icon" class="size-4 shrink-0" />
                  <span class="truncate whitespace-nowrap">{{ item.label }}</span>
                </RouterLink>
              </div>
            </div>
          </template>
          <template v-else>
            <RouterLink
              v-for="item in settingsChildren"
              :key="item.to"
              :to="item.to"
              class="flex items-center justify-center rounded-lg px-2 py-2.5 text-muted transition hover:bg-surface hover:text-ink"
              :title="item.label"
              active-class="!bg-brand-soft !text-brand"
            >
              <component :is="item.icon" class="size-4 shrink-0" />
            </RouterLink>
          </template>
        </div>

        <RouterLink
          v-for="item in navAfter"
          :key="item.to"
          :to="item.to"
          class="flex items-center gap-2.5 rounded-lg py-2.5 text-sm font-medium text-muted transition hover:bg-surface hover:text-ink"
          :class="collapsed ? 'justify-center px-2' : 'px-3'"
          :title="collapsed ? item.label : undefined"
          active-class="!bg-brand-soft !text-brand"
        >
          <component :is="item.icon" class="size-4 shrink-0" />
          <span v-if="!collapsed" class="truncate whitespace-nowrap">{{ item.label }}</span>
        </RouterLink>
      </nav>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="flex h-14 shrink-0 items-center gap-4 border-b border-line bg-panel px-6">
        <h1 class="min-w-0 truncate text-base font-semibold tracking-tight">{{ title }}</h1>

        <div ref="profileRoot" class="relative ml-auto">
          <button
            type="button"
            class="flex items-center gap-2 rounded-full border border-line bg-surface py-1 pl-1 pr-2.5 transition hover:border-brand/40 hover:bg-brand-soft/40"
            :aria-expanded="profileOpen"
            @click.stop="profileOpen = !profileOpen"
          >
            <span
              class="flex size-8 items-center justify-center rounded-full bg-brand text-[11px] font-bold tracking-wide text-white"
              :title="auth.user?.name"
            >
              {{ initials }}
            </span>
            <span class="hidden max-w-[140px] truncate text-left text-sm font-medium sm:block">
              {{ auth.user?.name }}
            </span>
            <ChevronDown
              class="size-3.5 shrink-0 text-muted transition-transform"
              :class="profileOpen ? 'rotate-180' : ''"
            />
          </button>

          <div
            v-if="profileOpen"
            class="absolute right-0 z-50 mt-2 w-64 overflow-hidden rounded-2xl border border-line bg-panel shadow-lg"
          >
            <div class="border-b border-line px-4 py-3">
              <div class="truncate text-sm font-semibold">{{ auth.user?.name }}</div>
              <div class="truncate text-[11px] text-muted">{{ roleDisplay }}</div>
              <div class="mt-0.5 truncate text-[11px] text-muted">{{ auth.user?.email }}</div>
            </div>
            <div class="p-1.5">
              <RouterLink
                to="/profile/templates"
                class="flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-medium text-ink transition hover:bg-surface"
                @click="profileOpen = false"
              >
                <TextQuote class="size-4 text-muted" />
                Мои шаблоны
              </RouterLink>
              <button
                type="button"
                class="flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-medium text-ink transition hover:bg-surface"
                @click="toggleSound"
              >
                <Volume2 v-if="soundOn" class="size-4 text-muted" />
                <VolumeX v-else class="size-4 text-muted" />
                <span class="min-w-0 flex-1 text-left">Звук входящих</span>
                <span class="text-[11px] font-semibold" :class="soundOn ? 'text-ok' : 'text-muted'">
                  {{ soundOn ? 'вкл' : 'выкл' }}
                </span>
              </button>
              <button
                type="button"
                class="flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-medium text-ink transition hover:bg-surface"
                :title="
                  pushPermission === 'denied'
                    ? 'Разрешение заблокировано в настройках браузера'
                    : undefined
                "
                @click="togglePush"
              >
                <Bell v-if="pushOn && pushPermission !== 'denied'" class="size-4 text-muted" />
                <BellOff v-else class="size-4 text-muted" />
                <span class="min-w-0 flex-1 text-left">Пуш-уведомления</span>
                <span
                  class="text-[11px] font-semibold"
                  :class="pushOn && pushPermission === 'granted' ? 'text-ok' : 'text-muted'"
                >
                  {{
                    pushPermission === 'denied'
                      ? 'блок'
                      : pushOn && pushPermission === 'granted'
                        ? 'вкл'
                        : 'выкл'
                  }}
                </span>
              </button>
              <button
                type="button"
                class="flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-medium text-ink transition hover:bg-surface"
                @click="runPushTest"
              >
                <Bell class="size-4 text-muted" />
                <span class="min-w-0 flex-1 text-left">Проверить пуш</span>
              </button>
              <p
                v-if="pushTestHint"
                class="px-3 pb-2 text-[11px] leading-snug"
                :class="pushTestHint.startsWith('OK') ? 'text-ok' : 'text-danger'"
              >
                {{ pushTestHint }}
              </p>
              <button
                type="button"
                class="flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-medium text-danger transition hover:bg-danger/5"
                @click="logout"
              >
                <LogOut class="size-4" />
                Выйти
              </button>
            </div>
          </div>
        </div>
      </header>
      <main class="min-h-0 flex-1 overflow-hidden">
        <RouterView />
      </main>
    </div>

    <Transition
      enter-active-class="transition duration-300 ease-out"
      enter-from-class="translate-y-3 opacity-0"
      enter-to-class="translate-y-0 opacity-100"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="translate-y-0 opacity-100"
      leave-to-class="translate-y-2 opacity-0"
    >
      <div
        v-if="inAppToast"
        class="fixed bottom-5 right-5 z-[200] w-[min(22rem,calc(100vw-1.5rem))] overflow-hidden rounded-2xl border border-line bg-panel shadow-[0_18px_50px_-24px_rgba(21,32,51,0.55)]"
        role="status"
      >
        <div class="h-1 w-full bg-brand" />
        <button
          type="button"
          class="flex w-full items-start gap-3 px-3.5 py-3 text-left transition hover:bg-brand-soft/40"
          @click="openToastDialog"
        >
          <div
            class="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl text-[12px] font-bold tracking-wide text-white"
            :class="
              inAppToast.kind === 'err'
                ? 'bg-danger'
                : inAppToast.kind === 'warn'
                  ? 'bg-warn'
                  : 'bg-brand'
            "
          >
            {{ inAppToast.initials || (inAppToast.kind === 'err' ? '!' : 'OE') }}
          </div>
          <div class="min-w-0 flex-1 pt-0.5">
            <div class="flex items-start justify-between gap-2">
              <div class="truncate text-[13px] font-semibold text-ink">
                {{ inAppToast.title || (inAppToast.kind === 'err' ? 'Ошибка' : 'Order Elite') }}
              </div>
              <span class="shrink-0 text-[10px] font-medium uppercase tracking-wide text-muted"
                >сейчас</span
              >
            </div>
            <div class="mt-0.5 line-clamp-2 text-[12.5px] leading-snug text-muted">
              {{ inAppToast.text }}
            </div>
          </div>
        </button>
        <button
          type="button"
          class="absolute right-1.5 top-2.5 rounded-lg px-2 py-1 text-[11px] text-muted transition hover:bg-surface hover:text-ink"
          aria-label="Закрыть"
          @click.stop="dismissInAppToast"
        >
          ✕
        </button>
      </div>
    </Transition>
  </div>
</template>
