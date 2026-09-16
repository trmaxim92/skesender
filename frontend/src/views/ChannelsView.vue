<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Copy, Pencil, Plus, Power, RefreshCw, Trash2 } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useChannelsStore } from '@/stores/channels'
import { transportLabel, type Channel, type Department } from '@/types'
import StatusDot from '@/components/ui/StatusDot.vue'
import Modal from '@/components/ui/Modal.vue'
import AddChannelModal from '@/components/channels/AddChannelModal.vue'
import { listDepartmentsRequest, mapDepartment } from '@/api/settings'
import {
  listChannelEventsRequest,
  mapChannelEvent,
  type ChannelEvent,
} from '@/api/auth'
import { ApiError } from '@/api/client'

const auth = useAuthStore()
const channels = useChannelsStore()
const departments = ref<Department[]>([])

const tab = ref<'channels' | 'diagnostics'>('channels')

const editOpen = ref(false)
const editChannel = ref<Channel | null>(null)
const editName = ref('')
const editDepartmentId = ref<number | null>(null)
const editSaving = ref(false)
const editError = ref('')

const deleteOpen = ref(false)
const deleteChannel = ref<Channel | null>(null)
const deleteBusy = ref(false)
const deleteError = ref('')

const snippetOpen = ref(false)
const snippetChannel = ref<Channel | null>(null)
const snippetCopied = ref(false)
const toggleBusyId = ref<number | null>(null)
const reconnectBusyId = ref<number | null>(null)
const reconnectError = ref('')

const diagEvents = ref<ChannelEvent[]>([])
const diagLoading = ref(false)
const diagError = ref('')
const diagChannelFilter = ref<string>('all')
let diagTimer: number | undefined

const kindLabel: Record<string, string> = {
  online: 'Онлайн',
  offline: 'Оффлайн',
  connecting: 'Подключение',
  qr: 'QR',
  error: 'Ошибка',
  disconnect: 'Обрыв',
  reconnect: 'Переподключение',
  reconnect_attempt: 'Попытка',
  gave_up: 'Сбой',
  manual_reconnect: 'Вручную',
  note: 'Заметка',
  status: 'Статус',
}

async function loadDiagnostics() {
  diagLoading.value = true
  diagError.value = ''
  try {
    const channelId =
      diagChannelFilter.value === 'all' ? null : Number(diagChannelFilter.value)
    const rows = await listChannelEventsRequest({
      channelId: Number.isFinite(channelId as number) ? (channelId as number) : null,
      limit: 150,
    })
    diagEvents.value = rows.map(mapChannelEvent)
  } catch (e) {
    diagError.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить логи'
  } finally {
    diagLoading.value = false
  }
}

function startDiagPoll() {
  stopDiagPoll()
  diagTimer = window.setInterval(() => {
    if (tab.value === 'diagnostics') void loadDiagnostics()
  }, 8000)
}

function stopDiagPoll() {
  if (diagTimer) {
    window.clearInterval(diagTimer)
    diagTimer = undefined
  }
}

onMounted(async () => {
  void channels.fetchChannels()
  try {
    departments.value = (await listDepartmentsRequest()).map(mapDepartment)
  } catch {
    departments.value = []
  }
})

onUnmounted(() => {
  channels.closeConnect()
  stopDiagPoll()
})

watch(tab, (t) => {
  if (t === 'diagnostics') {
    void loadDiagnostics()
    startDiagPoll()
  } else {
    stopDiagPoll()
  }
})

watch(diagChannelFilter, () => {
  if (tab.value === 'diagnostics') void loadDiagnostics()
})

const canManage = computed(() => auth.can('action.manage_channels'))

function formatDiagAt(iso: string) {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function levelClass(level: string) {
  if (level === 'error') return 'text-danger'
  if (level === 'warn') return 'text-amber-700'
  return 'text-muted'
}

const transportTone = computed(() => ({
  maxbot: 'bg-max text-white',
  max: 'bg-max text-white',
  telegram: 'bg-tg text-white',
  tgapi: 'bg-tg text-white',
  vk: 'bg-vk text-white',
  webchat: 'bg-brand text-white',
}))

const sortedChannels = computed(() =>
  [...channels.channels].sort((a, b) => {
    const da = a.departmentName || ''
    const db = b.departmentName || ''
    if (da !== db) return da.localeCompare(db, 'ru')
    return a.name.localeCompare(b.name, 'ru')
  }),
)

function embedSnippet(ch: Channel): string {
  const key = ch.publicKey || ''
  const src = `${window.location.origin}/widget.js`
  return `<script src="${src}" data-key="${key}" async><\/script>`
}

function openSnippet(ch: Channel) {
  snippetChannel.value = ch
  snippetCopied.value = false
  snippetOpen.value = true
}

function closeSnippet() {
  snippetOpen.value = false
  snippetChannel.value = null
}

async function copySnippet() {
  if (!snippetChannel.value) return
  try {
    await navigator.clipboard.writeText(embedSnippet(snippetChannel.value))
    snippetCopied.value = true
  } catch {
    snippetCopied.value = false
  }
}

async function toggleWebchat(ch: Channel) {
  if (toggleBusyId.value != null) return
  const next = ch.status === 'online' ? 'offline' : 'online'
  toggleBusyId.value = ch.id
  await channels.updateChannel(ch.id, { status: next })
  toggleBusyId.value = null
}

function canReconnect(ch: Channel) {
  return (
    canManage.value &&
    ch.hasCredentials &&
    (ch.transport === 'max' || ch.transport === 'tgapi')
  )
}

async function reconnectChannel(ch: Channel) {
  if (reconnectBusyId.value != null || !canReconnect(ch)) return
  reconnectBusyId.value = ch.id
  reconnectError.value = ''
  channels.loadError = ''
  const ok = await channels.reconnectChannel(ch.id)
  reconnectBusyId.value = null
  if (!ok) {
    reconnectError.value = channels.loadError || 'Не удалось переподключить'
  }
}

function openEdit(ch: Channel) {
  editChannel.value = ch
  editName.value = ch.name
  editDepartmentId.value = ch.departmentId ?? departments.value[0]?.id ?? null
  editError.value = ''
  editOpen.value = true
}

function closeEdit() {
  editOpen.value = false
  editChannel.value = null
  editError.value = ''
}

async function saveEdit() {
  if (!editChannel.value || !editName.value.trim()) {
    editError.value = 'Укажите название'
    return
  }
  if (editDepartmentId.value == null) {
    editError.value = 'Выберите отдел'
    return
  }
  editSaving.value = true
  editError.value = ''
  const ok = await channels.updateChannel(editChannel.value.id, {
    name: editName.value.trim(),
    departmentId: editDepartmentId.value,
  })
  editSaving.value = false
  if (ok) closeEdit()
  else editError.value = channels.loadError || 'Не удалось сохранить'
}

function openDelete(ch: Channel) {
  deleteChannel.value = ch
  deleteError.value = ''
  deleteOpen.value = true
}

function closeDelete() {
  if (deleteBusy.value) return
  deleteOpen.value = false
  deleteChannel.value = null
  deleteError.value = ''
}

async function confirmDelete() {
  if (!deleteChannel.value || deleteBusy.value) return
  deleteBusy.value = true
  deleteError.value = ''
  const ok = await channels.removeChannel(deleteChannel.value.id)
  deleteBusy.value = false
  if (ok) {
    closeDelete()
    return
  }
  deleteError.value = channels.loadError || 'Не удалось удалить канал'
}

watch(
  () => editDepartmentId.value,
  (id) => {
    if (!editOpen.value || !id || !editChannel.value) return
    const dept = departments.value.find((d) => d.id === id)
    if (!dept) return
    // if name still looks like "Dept · Transport", refresh dept part
    const parts = editName.value.split(' · ')
    if (parts.length >= 2) {
      parts[0] = dept.name
      editName.value = parts.join(' · ')
    }
  },
)
</script>

<template>
  <div class="h-full overflow-auto p-4 md:p-6">
    <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div>
        <div class="mb-2 flex gap-1 rounded-lg bg-surface p-0.5 w-fit">
          <button
            type="button"
            class="rounded-md px-3 py-1.5 text-xs font-semibold transition"
            :class="tab === 'channels' ? 'bg-panel text-ink shadow-sm' : 'text-muted'"
            @click="tab = 'channels'"
          >
            Каналы
          </button>
          <button
            type="button"
            class="rounded-md px-3 py-1.5 text-xs font-semibold transition"
            :class="tab === 'diagnostics' ? 'bg-panel text-ink shadow-sm' : 'text-muted'"
            @click="tab = 'diagnostics'"
          >
            Диагностика
          </button>
        </div>
        <template v-if="tab === 'channels'">
          <p class="text-sm text-muted">
            Онлайн: <span class="font-semibold text-ink">{{ channels.onlineCount }}</span>
            из {{ channels.channels.length }}
            <span v-if="channels.loading" class="ml-2">загрузка…</span>
          </p>
          <p class="mt-1 text-xs text-muted">
            Называйте каналы по отделу (например «Продажи · Telegram бот»), чтобы было ясно, кому
            назначать.
          </p>
          <p v-if="channels.loadError" class="mt-1 text-sm text-danger">{{ channels.loadError }}</p>
          <p v-else-if="reconnectError" class="mt-1 text-sm text-danger">{{ reconnectError }}</p>
        </template>
        <template v-else>
          <p class="text-sm text-muted">
            Журнал подключений: обрывы, автопереподключения и ошибки сессии.
          </p>
          <p v-if="diagError" class="mt-1 text-sm text-danger">{{ diagError }}</p>
        </template>
      </div>
      <button
        v-if="canManage && tab === 'channels'"
        type="button"
        class="inline-flex items-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:brightness-105"
        @click="channels.openConnect()"
      >
        <Plus class="size-4" />
        Добавить канал
      </button>
      <button
        v-else-if="tab === 'diagnostics'"
        type="button"
        class="inline-flex items-center gap-2 rounded-xl border border-line px-4 py-2.5 text-sm font-semibold text-muted hover:bg-surface hover:text-ink disabled:opacity-50"
        :disabled="diagLoading"
        @click="loadDiagnostics"
      >
        <RefreshCw class="size-4" :class="diagLoading ? 'animate-spin' : ''" />
        Обновить
      </button>
    </div>

    <template v-if="tab === 'diagnostics'">
      <div class="mb-4 flex flex-wrap items-center gap-2">
        <label class="text-xs font-semibold uppercase tracking-wide text-muted">Канал</label>
        <select
          v-model="diagChannelFilter"
          class="rounded-xl border border-line bg-panel px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
        >
          <option value="all">Все каналы</option>
          <option v-for="ch in sortedChannels" :key="ch.id" :value="String(ch.id)">
            {{ ch.name }}
          </option>
        </select>
      </div>
      <p v-if="diagLoading && !diagEvents.length" class="text-sm text-muted">Загрузка…</p>
      <p
        v-else-if="!diagEvents.length"
        class="rounded-2xl border border-dashed border-line bg-panel p-8 text-center text-sm text-muted"
      >
        Пока нет событий. Они появятся при обрыве связи, переподключении или ошибке канала.
      </p>
      <ul v-else class="space-y-2">
        <li
          v-for="ev in diagEvents"
          :key="ev.id"
          class="rounded-2xl border border-line bg-panel px-4 py-3"
        >
          <div class="flex flex-wrap items-center gap-2 text-[11px]">
            <span
              class="rounded-md px-1.5 py-0.5 font-bold uppercase tracking-wide"
              :class="
                ev.level === 'error'
                  ? 'bg-danger/15 text-danger'
                  : ev.level === 'warn'
                    ? 'bg-amber-500/15 text-amber-800'
                    : 'bg-surface text-muted'
              "
            >
              {{ kindLabel[ev.kind] || ev.kind }}
            </span>
            <span v-if="ev.transport" class="rounded-md bg-surface px-1.5 py-0.5 text-muted">
              {{ transportLabel[ev.transport] }}
            </span>
            <span class="font-semibold text-ink">{{ ev.channelName || `#${ev.channelId}` }}</span>
            <span class="ml-auto text-muted">{{ formatDiagAt(ev.createdAt) }}</span>
          </div>
          <p class="mt-1.5 text-sm" :class="levelClass(ev.level)">{{ ev.message }}</p>
          <p v-if="ev.detail" class="mt-1 whitespace-pre-wrap font-mono text-[11px] text-muted">
            {{ ev.detail }}
          </p>
        </li>
      </ul>
    </template>

    <template v-else>

    <div
      v-if="!channels.loading && !channels.channels.length"
      class="rounded-2xl border border-dashed border-line bg-panel p-8 text-center text-sm text-muted"
    >
      Каналов пока нет. Добавьте канал с названием и отделом.
    </div>

    <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <article
        v-for="ch in sortedChannels"
        :key="ch.id"
        class="rounded-2xl border border-line bg-panel p-4 shadow-sm"
      >
        <div class="mb-3 flex items-start justify-between gap-2">
          <div class="min-w-0">
            <div class="mb-1.5 flex flex-wrap items-center gap-2">
              <span
                class="rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide"
                :class="transportTone[ch.transport]"
              >
                {{ transportLabel[ch.transport] }}
              </span>
              <StatusDot :status="ch.status" />
              <span
                v-if="ch.departmentName"
                class="rounded-md bg-surface px-2 py-0.5 text-[10px] font-semibold text-muted"
              >
                {{ ch.departmentName }}
              </span>
            </div>
            <h3 class="truncate text-sm font-semibold">{{ ch.name }}</h3>
            <p class="mt-0.5 truncate font-mono text-xs text-muted">{{ ch.identity }}</p>
            <p v-if="ch.lastError" class="mt-1 text-xs text-danger">{{ ch.lastError }}</p>
          </div>
          <div v-if="canManage" class="flex shrink-0 gap-0.5">
            <button
              type="button"
              class="rounded-lg p-1.5 text-muted hover:bg-surface hover:text-ink"
              title="Редактировать"
              @click="openEdit(ch)"
            >
              <Pencil class="size-4" />
            </button>
            <button
              type="button"
              class="rounded-lg p-1.5 text-muted hover:bg-surface hover:text-danger"
              title="Удалить"
              @click="openDelete(ch)"
            >
              <Trash2 class="size-4" />
            </button>
          </div>
        </div>
        <div class="flex items-center justify-between text-xs text-muted">
          <span>
            {{
              ch.transport === 'webchat'
                ? ch.publicKey || 'виджет'
                : ch.hasCredentials
                  ? 'токен сохранён'
                  : 'без credentials'
            }}
          </span>
          <span v-if="ch.connectedAt">
            с {{ new Date(ch.connectedAt).toLocaleDateString('ru-RU') }}
          </span>
        </div>
        <div v-if="ch.transport === 'webchat' && canManage" class="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-xs font-semibold text-muted transition hover:border-brand/40 hover:bg-brand-soft hover:text-brand"
            @click="openSnippet(ch)"
          >
            <Copy class="size-3.5" />
            Код для сайта
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-xs font-semibold transition"
            :class="
              ch.status === 'online'
                ? 'text-ok hover:border-ok/40 hover:bg-ok/10'
                : 'text-muted hover:border-brand/40 hover:bg-brand-soft hover:text-brand'
            "
            :disabled="toggleBusyId === ch.id"
            @click="toggleWebchat(ch)"
          >
            <Power class="size-3.5" />
            {{
              toggleBusyId === ch.id
                ? '…'
                : ch.status === 'online'
                  ? 'Выключить'
                  : 'Включить'
            }}
          </button>
        </div>
        <div v-else-if="canReconnect(ch)" class="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-xs font-semibold transition"
            :class="
              ch.status === 'error' || ch.lastError
                ? 'border-danger/30 text-danger hover:bg-danger/10'
                : 'text-muted hover:border-brand/40 hover:bg-brand-soft hover:text-brand'
            "
            :disabled="reconnectBusyId === ch.id"
            @click="reconnectChannel(ch)"
          >
            <RefreshCw
              class="size-3.5"
              :class="reconnectBusyId === ch.id ? 'animate-spin' : ''"
            />
            {{
              reconnectBusyId === ch.id ? 'Переподключение…' : 'Переподключить'
            }}
          </button>
        </div>
      </article>
    </div>
    </template>

    <AddChannelModal v-if="channels.connectOpen && canManage" />

    <Modal
      v-if="snippetOpen && snippetChannel"
      title="Код виджета"
      @close="closeSnippet"
    >
      <div class="space-y-3">
        <p class="text-sm text-muted">
          Вставьте этот код перед <span class="font-mono">&lt;/body&gt;</span> на сайте.
        </p>
        <pre
          class="overflow-x-auto rounded-xl border border-line bg-surface p-3 text-xs leading-relaxed text-ink"
        >{{ embedSnippet(snippetChannel) }}</pre>
        <p class="font-mono text-[11px] text-muted">Ключ: {{ snippetChannel.publicKey }}</p>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            class="rounded-xl px-4 py-2 text-sm text-muted hover:bg-surface"
            @click="closeSnippet"
          >
            Закрыть
          </button>
          <button
            type="button"
            class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white"
            @click="copySnippet"
          >
            {{ snippetCopied ? 'Скопировано' : 'Копировать' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal v-if="editOpen && editChannel" title="Редактировать канал" @close="closeEdit">
      <div class="space-y-4">
        <div class="flex flex-wrap items-center gap-2">
          <span
            class="rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide"
            :class="transportTone[editChannel.transport]"
          >
            {{ transportLabel[editChannel.transport] }}
          </span>
          <StatusDot :status="editChannel.status" />
        </div>
        <p class="font-mono text-xs text-muted">{{ editChannel.identity || '—' }}</p>
        <p class="text-xs text-muted">
          Транспорт и учётные данные меняются только через переподключение. Здесь — название и отдел
          (отдел влияет на назначение чатов).
        </p>
        <label class="block">
          <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
            Название
          </span>
          <input
            v-model="editName"
            type="text"
            class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
            :disabled="editSaving"
          />
        </label>
        <label class="block">
          <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
            Отдел
          </span>
          <select
            v-model.number="editDepartmentId"
            class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm"
            :disabled="editSaving || !departments.length"
          >
            <option v-if="!departments.length" :value="null">Нет отделов</option>
            <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
        </label>
        <p v-if="editError" class="text-sm text-danger">{{ editError }}</p>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            class="rounded-xl px-4 py-2 text-sm text-muted hover:bg-surface"
            :disabled="editSaving"
            @click="closeEdit"
          >
            Отмена
          </button>
          <button
            type="button"
            class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            :disabled="editSaving || !editName.trim() || editDepartmentId == null"
            @click="saveEdit"
          >
            {{ editSaving ? '…' : 'Сохранить' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal v-if="deleteOpen && deleteChannel" title="Удалить канал?" @close="closeDelete">
      <div class="space-y-4">
        <p class="text-sm text-muted">
          Канал
          <span class="font-semibold text-ink">{{ deleteChannel.name }}</span>
          (
          {{ transportLabel[deleteChannel.transport] }}
          <span v-if="deleteChannel.identity"> · {{ deleteChannel.identity }}</span>
          ) будет отключён. Сессия мессенджера остановится; диалоги в кабинете останутся.
        </p>
        <p v-if="deleteError" class="text-sm text-danger">{{ deleteError }}</p>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            class="rounded-xl px-4 py-2 text-sm text-muted hover:bg-surface"
            :disabled="deleteBusy"
            @click="closeDelete"
          >
            Отмена
          </button>
          <button
            type="button"
            class="rounded-xl bg-danger px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            :disabled="deleteBusy"
            @click="confirmDelete"
          >
            {{ deleteBusy ? '…' : 'Удалить' }}
          </button>
        </div>
      </div>
    </Modal>
  </div>
</template>
