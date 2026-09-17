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

const syncEnabled = ref(true)
const intervalSec = ref(3600)
const workStatuses = ref('working,not_working')

async function load() {
  loading.value = true
  error.value = ''
  try {
    status.value = await fleetStatusRequest()
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
    status.value = await fleetUpdateSettingsRequest({
      sync_enabled: syncEnabled.value,
      interval_sec: Number(intervalSec.value) || 3600,
      work_statuses: workStatuses.value.trim(),
    })
    okMsg.value = 'Настройки сохранены'
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

    <section v-if="status" class="space-y-4 rounded-2xl border border-line bg-panel p-4">
      <div class="flex flex-wrap items-center gap-2">
        <span
          class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
          :class="status.configured ? 'bg-ok/15 text-ok' : 'bg-danger/15 text-danger'"
        >
          {{ status.configured ? 'Подключено' : 'Нет credentials' }}
        </span>
        <span class="text-[11px] text-muted">источник: {{ status.credentialsSource }}</span>
      </div>

      <dl class="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt class="text-[11px] font-semibold uppercase tracking-wide text-muted">Client-ID</dt>
          <dd class="mt-0.5 break-all font-mono text-xs text-ink">{{ status.clientId || '—' }}</dd>
        </div>
        <div>
          <dt class="text-[11px] font-semibold uppercase tracking-wide text-muted">Park ID</dt>
          <dd class="mt-0.5 break-all font-mono text-xs text-ink">{{ status.parkId || '—' }}</dd>
        </div>
        <div>
          <dt class="text-[11px] font-semibold uppercase tracking-wide text-muted">API-Key</dt>
          <dd class="mt-0.5 font-mono text-xs text-ink">{{ status.apiKeyMasked || '—' }}</dd>
        </div>
      </dl>
      <p class="text-xs text-muted">
        Ключи задаются в <code class="rounded bg-surface px-1">backend/.env</code>
        (<code class="rounded bg-surface px-1">FLEET_*</code>).
      </p>
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
      <h3 class="text-sm font-semibold">Параметры</h3>
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
        <span class="mt-1 block text-[11px] text-muted">
          working / not_working / fired — без fired обычно лучше
        </span>
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
