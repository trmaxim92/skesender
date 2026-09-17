<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import {
  fleetStatusRequest,
  fleetSyncRequest,
  fleetUpdateSettingsRequest,
  type FleetStatus,
} from '@/api/fleet'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canWrite = computed(() => auth.can('section.settings') && auth.can('action.write'))
const canSync = computed(
  () =>
    auth.can('action.write') && (auth.can('section.settings') || auth.can('section.contacts')),
)

const status = ref<FleetStatus | null>(null)
const loading = ref(false)
const saving = ref(false)
const syncing = ref(false)
const error = ref('')
const okMsg = ref('')

const clientId = ref('')
const parkId = ref('')
const apiKey = ref('')
const syncEnabled = ref(true)
const intervalSec = ref(3600)
const workStatuses = ref('working,not_working')

async function load() {
  loading.value = true
  error.value = ''
  try {
    status.value = await fleetStatusRequest()
    clientId.value = status.value.clientId
    parkId.value = status.value.parkId
    apiKey.value = ''
    syncEnabled.value = status.value.syncEnabled
    intervalSec.value = status.value.intervalSec
    workStatuses.value = status.value.workStatuses
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить статус Fleet'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})

async function saveSettings() {
  if (!canWrite.value || saving.value) return
  saving.value = true
  error.value = ''
  okMsg.value = ''
  try {
    const payload: {
      sync_enabled: boolean
      interval_sec: number
      work_statuses: string
      client_id: string
      park_id: string
      api_key?: string
    } = {
      sync_enabled: syncEnabled.value,
      interval_sec: Number(intervalSec.value) || 3600,
      work_statuses: workStatuses.value.trim(),
      client_id: clientId.value.trim(),
      park_id: parkId.value.trim(),
    }
    const key = apiKey.value.trim()
    if (key) payload.api_key = key
    status.value = await fleetUpdateSettingsRequest(payload)
    apiKey.value = ''
    okMsg.value = 'Настройки сохранены'
    await load()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить'
  } finally {
    saving.value = false
  }
}

async function runSync(purge: boolean) {
  if (!canSync.value || syncing.value) return
  if (purge) {
    const ok = window.confirm(
      'Удалить ВСЕ текущие контакты и загрузить исполнителей из Яндекс Fleet?\n\nДиалоги в чатах не удаляются.',
    )
    if (!ok) return
  }
  syncing.value = true
  error.value = ''
  okMsg.value = ''
  try {
    const res = await fleetSyncRequest({ purge })
    okMsg.value =
      `Синхронизация: получено ${res.fetched}, создано ${res.created}, обновлено ${res.updated}` +
      (res.purged ? `, удалено ${res.purged}` : '') +
      (res.skipped ? `, пропущено ${res.skipped}` : '')
    await load()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Ошибка синхронизации'
  } finally {
    syncing.value = false
  }
}

function formatDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const sourceLabel = computed(() => {
  const s = status.value?.credentialsSource
  if (s === 'db') return 'сохранены в CRM'
  if (s === 'env') return 'из .env (пока не перезаписаны)'
  return 'не заданы'
})
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6 p-6">
    <div>
      <h2 class="text-lg font-semibold tracking-tight">Яндекс Fleet</h2>
      <p class="mt-1 text-sm text-muted">
        Интеграция с парком: исполнители → контакты CRM. Дальше — авто, заказы, баланс.
      </p>
    </div>

    <p v-if="error" class="text-sm text-danger">{{ error }}</p>
    <p v-if="okMsg" class="text-sm text-ok">{{ okMsg }}</p>
    <p v-if="loading && !status" class="text-sm text-muted">Загрузка…</p>

    <section v-if="canWrite" class="space-y-4 rounded-2xl border border-line bg-panel p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h3 class="text-sm font-semibold">Подключение</h3>
        <span
          v-if="status"
          class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
          :class="status.configured ? 'bg-ok/15 text-ok' : 'bg-danger/15 text-danger'"
        >
          {{ status.configured ? 'Подключено' : 'Нет ключей' }}
        </span>
      </div>
      <p class="text-xs text-muted">Ключи: {{ sourceLabel }}</p>
      <label class="block">
        <span class="mb-1 block text-xs font-semibold text-muted">Client-ID</span>
        <input
          v-model="clientId"
          type="text"
          placeholder="taxi/park/…"
          class="w-full rounded-xl border border-line bg-surface px-3 py-2 font-mono text-sm outline-none ring-brand focus:ring-2"
        />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs font-semibold text-muted">Park ID</span>
        <input
          v-model="parkId"
          type="text"
          class="w-full rounded-xl border border-line bg-surface px-3 py-2 font-mono text-sm outline-none ring-brand focus:ring-2"
        />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs font-semibold text-muted">API-Key</span>
        <input
          v-model="apiKey"
          type="password"
          autocomplete="new-password"
          :placeholder="
            status?.hasApiKey
              ? `Сохранён: ${status.apiKeyMasked} — введите новый, чтобы заменить`
              : 'Вставьте API-ключ'
          "
          class="w-full rounded-xl border border-line bg-surface px-3 py-2 font-mono text-sm outline-none ring-brand focus:ring-2"
        />
      </label>
    </section>

    <section v-else-if="status" class="space-y-3 rounded-2xl border border-line bg-panel p-4">
      <div class="flex flex-wrap items-center gap-2">
        <span
          class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
          :class="status.configured ? 'bg-ok/15 text-ok' : 'bg-danger/15 text-danger'"
        >
          {{ status.configured ? 'Подключено' : 'Нет credentials' }}
        </span>
        <span class="text-[11px] text-muted">{{ sourceLabel }}</span>
      </div>
      <dl class="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt class="text-[11px] font-semibold uppercase tracking-wide text-muted">Client-ID</dt>
          <dd class="mt-0.5 break-all font-mono text-xs">{{ status.clientId || '—' }}</dd>
        </div>
        <div>
          <dt class="text-[11px] font-semibold uppercase tracking-wide text-muted">Park ID</dt>
          <dd class="mt-0.5 break-all font-mono text-xs">{{ status.parkId || '—' }}</dd>
        </div>
        <div>
          <dt class="text-[11px] font-semibold uppercase tracking-wide text-muted">API-Key</dt>
          <dd class="mt-0.5 font-mono text-xs">{{ status.apiKeyMasked || '—' }}</dd>
        </div>
      </dl>
    </section>

    <section class="space-y-4 rounded-2xl border border-line bg-panel p-4">
      <h3 class="text-sm font-semibold">Синхронизация контактов</h3>
      <div class="flex flex-wrap gap-2">
        <button
          v-if="canSync"
          type="button"
          class="inline-flex items-center gap-1.5 rounded-xl bg-brand px-3.5 py-2 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="syncing || !status?.configured"
          @click="runSync(false)"
        >
          <RefreshCw class="size-4" :class="syncing ? 'animate-spin' : ''" />
          Синхронизировать
        </button>
        <button
          v-if="canSync"
          type="button"
          class="rounded-xl border border-line bg-surface px-3.5 py-2 text-sm font-medium text-ink disabled:opacity-50"
          :disabled="syncing || !status?.configured"
          @click="runSync(true)"
        >
          Очистить и загрузить
        </button>
      </div>

      <dl v-if="status" class="grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt class="text-[11px] font-semibold uppercase tracking-wide text-muted">Последний запуск</dt>
          <dd class="mt-0.5 text-ink">{{ formatDate(status.lastFinishedAt) }}</dd>
        </div>
        <div>
          <dt class="text-[11px] font-semibold uppercase tracking-wide text-muted">Результат</dt>
          <dd class="mt-0.5 text-ink">
            <span v-if="status.lastOk === true" class="text-ok">OK</span>
            <span v-else-if="status.lastOk === false" class="text-danger">Ошибка</span>
            <span v-else class="text-muted">ещё не было</span>
          </dd>
        </div>
        <div class="sm:col-span-2 text-xs text-muted">
          получено {{ status.lastFetched }}, создано {{ status.lastCreated }}, обновлено
          {{ status.lastUpdated }}, пропущено {{ status.lastSkipped }}
          <template v-if="status.lastPurged">, удалено {{ status.lastPurged }}</template>
        </div>
        <div v-if="status.lastError" class="sm:col-span-2 text-sm text-danger">
          {{ status.lastError }}
        </div>
      </dl>
    </section>

    <section v-if="canWrite" class="space-y-4 rounded-2xl border border-line bg-panel p-4">
      <h3 class="text-sm font-semibold">Параметры синка</h3>
      <label class="flex items-center gap-2 text-sm text-ink">
        <input v-model="syncEnabled" type="checkbox" class="size-4" />
        Автосинхронизация по расписанию
      </label>
      <label class="block">
        <span class="mb-1 block text-xs font-semibold text-muted">Интервал (сек)</span>
        <input
          v-model.number="intervalSec"
          type="number"
          min="60"
          class="w-full max-w-xs rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
        />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs font-semibold text-muted">
          Статусы исполнителей (через запятую)
        </span>
        <input
          v-model="workStatuses"
          type="text"
          placeholder="working,not_working"
          class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
        />
      </label>
      <button
        type="button"
        class="rounded-xl bg-brand px-3.5 py-2 text-sm font-semibold text-white disabled:opacity-50"
        :disabled="saving"
        @click="saveSettings"
      >
        {{ saving ? 'Сохранение…' : 'Сохранить' }}
      </button>
    </section>
  </div>
</template>
