<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
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

type TabId = 'profile' | 'security' | 'notifications'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const tabs: { id: TabId; label: string }[] = [
  { id: 'profile', label: 'Профиль' },
  { id: 'security', label: 'Безопасность' },
  { id: 'notifications', label: 'Оповещения' },
]

const tab = computed<TabId>(() => {
  const raw = String(route.query.tab || 'profile')
  if (raw === 'security' || raw === 'notifications') return raw
  return 'profile'
})

function setTab(id: TabId) {
  void router.replace({ name: 'profile', query: id === 'profile' ? {} : { tab: id } })
}

// —— Profile ——
const name = ref('')
const profileSaving = ref(false)
const profileMsg = ref('')
const profileErr = ref('')

watch(
  () => auth.user?.name,
  (v) => {
    if (v && !profileSaving.value) name.value = v
  },
  { immediate: true },
)

async function saveProfile() {
  profileMsg.value = ''
  profileErr.value = ''
  if (!name.value.trim()) {
    profileErr.value = 'Укажите имя'
    return
  }
  profileSaving.value = true
  try {
    await auth.updateProfile(name.value)
    profileMsg.value = 'Сохранено'
  } catch (e) {
    profileErr.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить'
  } finally {
    profileSaving.value = false
  }
}

// —— Security ——
const currentPassword = ref('')
const newPassword = ref('')
const newPassword2 = ref('')
const passSaving = ref(false)
const passMsg = ref('')
const passErr = ref('')

async function savePassword() {
  passMsg.value = ''
  passErr.value = ''
  if (newPassword.value.length < 6) {
    passErr.value = 'Новый пароль — минимум 6 символов'
    return
  }
  if (newPassword.value !== newPassword2.value) {
    passErr.value = 'Пароли не совпадают'
    return
  }
  passSaving.value = true
  try {
    await auth.changePassword(currentPassword.value, newPassword.value)
    currentPassword.value = ''
    newPassword.value = ''
    newPassword2.value = ''
    passMsg.value = 'Пароль изменён'
  } catch (e) {
    passErr.value = e instanceof ApiError ? e.detail : 'Не удалось сменить пароль'
  } finally {
    passSaving.value = false
  }
}

// —— Notifications ——
const soundOn = ref(isSoundEnabled())
const pushPermission = ref(notificationPermission())
const pushOn = ref(isPushEnabled() && pushPermission.value === 'granted')
const pushTestHint = ref('')

onMounted(() => {
  pushPermission.value = notificationPermission()
  if (pushPermission.value !== 'granted') {
    pushOn.value = false
    setPushEnabled(false)
  } else {
    pushOn.value = isPushEnabled()
  }
})

function toggleSound() {
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
          ? 'Разрешение заблокировано в настройках браузера'
          : 'Нужно разрешить уведомления'
      return
    }
    setPushEnabled(true)
    pushOn.value = true
    const test = await testOsPush()
    pushTestHint.value = test.ok
      ? `Включено (${test.reason})`
      : `Включено, тест: ${test.reason}`
    return
  }
  pushOn.value = false
  setPushEnabled(false)
}

async function runPushTest() {
  pushTestHint.value = 'Запрос…'
  try {
    await ensureNotificationPermission()
    pushPermission.value = notificationPermission()
    const test = await testOsPush()
    if (test.ok) {
      pushOn.value = true
      setPushEnabled(true)
      pushTestHint.value = `OK (${test.reason}). Смотри тост и центр уведомлений.`
    } else {
      pushTestHint.value = `Не ок: ${test.reason}`
    }
  } catch (e) {
    pushTestHint.value = `Ошибка: ${e instanceof Error ? e.message : String(e)}`
  }
}
</script>

<template>
  <div class="h-full overflow-auto p-6">
    <div class="mx-auto max-w-2xl">
      <h1 class="text-lg font-bold tracking-tight">Профиль</h1>
      <p class="mt-1 text-sm text-muted">Личные данные, пароль и оповещения.</p>

      <div class="mt-5 flex gap-1 border-b border-line">
        <button
          v-for="t in tabs"
          :key="t.id"
          type="button"
          class="relative -mb-px px-3.5 py-2.5 text-sm font-semibold transition"
          :class="
            tab === t.id
              ? 'text-brand'
              : 'text-muted hover:text-ink'
          "
          @click="setTab(t.id)"
        >
          {{ t.label }}
          <span
            v-if="tab === t.id"
            class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-brand"
          />
        </button>
      </div>

      <!-- Profile -->
      <div v-if="tab === 'profile'" class="mt-5 space-y-4">
        <label class="block">
          <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
            Email
          </span>
          <input
            type="email"
            :value="auth.user?.email"
            disabled
            class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm text-muted"
          />
        </label>
        <label class="block">
          <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
            Имя
          </span>
          <input
            v-model="name"
            type="text"
            class="w-full rounded-xl border border-line bg-panel px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
          />
        </label>
        <p class="text-xs text-muted">
          Роль: <span class="font-medium text-ink">{{ auth.user?.roleName || auth.user?.role }}</span>
        </p>
        <p v-if="profileErr" class="text-sm text-danger">{{ profileErr }}</p>
        <p v-if="profileMsg" class="text-sm text-ok">{{ profileMsg }}</p>
        <div class="flex justify-end">
          <button
            type="button"
            class="rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
            :disabled="profileSaving || !name.trim()"
            @click="saveProfile"
          >
            {{ profileSaving ? '…' : 'Сохранить' }}
          </button>
        </div>
      </div>

      <!-- Security -->
      <div v-else-if="tab === 'security'" class="mt-5 space-y-4">
        <label class="block">
          <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
            Текущий пароль
          </span>
          <input
            v-model="currentPassword"
            type="password"
            autocomplete="current-password"
            class="w-full rounded-xl border border-line bg-panel px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
          />
        </label>
        <label class="block">
          <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
            Новый пароль
          </span>
          <input
            v-model="newPassword"
            type="password"
            autocomplete="new-password"
            class="w-full rounded-xl border border-line bg-panel px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
          />
        </label>
        <label class="block">
          <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
            Повтор нового пароля
          </span>
          <input
            v-model="newPassword2"
            type="password"
            autocomplete="new-password"
            class="w-full rounded-xl border border-line bg-panel px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
          />
        </label>
        <p v-if="passErr" class="text-sm text-danger">{{ passErr }}</p>
        <p v-if="passMsg" class="text-sm text-ok">{{ passMsg }}</p>
        <div class="flex justify-end">
          <button
            type="button"
            class="rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
            :disabled="passSaving || !currentPassword || !newPassword"
            @click="savePassword"
          >
            {{ passSaving ? '…' : 'Сменить пароль' }}
          </button>
        </div>
      </div>

      <!-- Notifications -->
      <div v-else class="mt-5 space-y-3">
        <button
          type="button"
          class="flex w-full items-center justify-between rounded-2xl border border-line bg-panel px-4 py-3.5 text-left transition hover:border-brand/30"
          @click="toggleSound"
        >
          <div>
            <div class="text-sm font-semibold">Звук входящих</div>
            <div class="text-xs text-muted">Короткий сигнал при новом сообщении</div>
          </div>
          <span class="text-xs font-bold" :class="soundOn ? 'text-ok' : 'text-muted'">
            {{ soundOn ? 'Вкл' : 'Выкл' }}
          </span>
        </button>

        <button
          type="button"
          class="flex w-full items-center justify-between rounded-2xl border border-line bg-panel px-4 py-3.5 text-left transition hover:border-brand/30"
          :title="
            pushPermission === 'denied'
              ? 'Разрешение заблокировано в настройках браузера'
              : undefined
          "
          @click="togglePush"
        >
          <div>
            <div class="text-sm font-semibold">Пуш-уведомления</div>
            <div class="text-xs text-muted">Системные уведомления ОС / браузера</div>
          </div>
          <span
            class="text-xs font-bold"
            :class="pushOn && pushPermission === 'granted' ? 'text-ok' : 'text-muted'"
          >
            {{
              pushPermission === 'denied'
                ? 'Блок'
                : pushOn && pushPermission === 'granted'
                  ? 'Вкл'
                  : 'Выкл'
            }}
          </span>
        </button>

        <button
          type="button"
          class="w-full rounded-2xl border border-dashed border-line bg-surface px-4 py-3 text-sm font-semibold text-ink transition hover:border-brand/40 hover:bg-panel"
          @click="runPushTest"
        >
          Проверить пуш
        </button>
        <p
          v-if="pushTestHint"
          class="text-xs leading-snug"
          :class="pushTestHint.startsWith('OK') || pushTestHint.startsWith('Включено') ? 'text-ok' : 'text-muted'"
        >
          {{ pushTestHint }}
        </p>
      </div>
    </div>
  </div>
</template>
