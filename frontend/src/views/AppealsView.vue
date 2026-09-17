<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { CheckSquare, ChevronRight, Plus, Search, Trash2, X } from 'lucide-vue-next'
import CreateAppealModal from '@/components/appeals/CreateAppealModal.vue'
import { useAppealsStore } from '@/stores/appeals'
import { useAuthStore } from '@/stores/auth'
import { useChannelsStore } from '@/stores/channels'
import { appealStatusLabel, transportLabel } from '@/types'

const appeals = useAppealsStore()
const channels = useChannelsStore()
const auth = useAuthStore()
const router = useRouter()

const createOpen = ref(false)
const deletingId = ref<number | null>(null)
const bulkBusy = ref(false)
const bulkMsg = ref('')
const selected = ref<Set<number>>(new Set())

const canCreate = computed(() => auth.can('section.chats') && auth.can('action.write'))
const canWrite = computed(() => auth.can('section.appeals') && auth.can('action.write'))
const canDelete = computed(() => auth.can('action.delete_appeals'))
const canBulk = computed(() => canWrite.value || canDelete.value)

const selectedCount = computed(() => selected.value.size)
const selectedOpenCount = computed(
  () => appeals.items.filter((a) => selected.value.has(a.id) && a.status === 'open').length,
)
const allPageSelected = computed(() => {
  if (!appeals.items.length) return false
  return appeals.items.every((a) => selected.value.has(a.id))
})

onMounted(() => {
  void appeals.fetchAppeals()
})

watch(
  () => [appeals.status, appeals.assignee, appeals.dateFrom, appeals.dateTo, appeals.offset],
  () => {
    selected.value = new Set()
    bulkMsg.value = ''
  },
)

function formatDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function openAppeal(appealId: number) {
  void router.push({ name: 'appeal-detail', params: { appealId: String(appealId) } })
}

function onSubmit() {
  selected.value = new Set()
  void appeals.search()
}

async function openCreate() {
  createOpen.value = true
  if (!channels.channels.length) {
    void channels.fetchChannels()
  }
}

function onCreated(dialogId: number) {
  createOpen.value = false
  void router.push({ name: 'chats', query: { dialog: String(dialogId) } })
}

function clearSelection() {
  selected.value = new Set()
}

function toggleSelect(id: number) {
  if (!canBulk.value) return
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

function toggleSelectAll() {
  if (!canBulk.value) return
  if (allPageSelected.value) {
    clearSelection()
    return
  }
  selected.value = new Set(appeals.items.map((a) => a.id))
}

async function onDelete(a: { id: number; number: number; contactName: string }, event: Event) {
  event.stopPropagation()
  if (!canDelete.value || deletingId.value != null) return
  const ok = window.confirm(
    `Удалить обращение #${a.number} (${a.contactName})?\nСообщения этого обращения будут удалены безвозвратно.`,
  )
  if (!ok) return
  deletingId.value = a.id
  try {
    await appeals.removeAppeal(a.id)
    const next = new Set(selected.value)
    next.delete(a.id)
    selected.value = next
  } finally {
    deletingId.value = null
  }
}

async function onBulkClose() {
  if (!canWrite.value || bulkBusy.value || !selectedOpenCount.value) return
  const ids = appeals.items
    .filter((a) => selected.value.has(a.id) && a.status === 'open')
    .map((a) => a.id)
  const ok = window.confirm(`Закрыть выбранные обращения (${ids.length})?`)
  if (!ok) return
  bulkBusy.value = true
  bulkMsg.value = ''
  try {
    const res = await appeals.closeBatch(ids)
    if (!res) return
    clearSelection()
    bulkMsg.value =
      res.skipped.length > 0
        ? `Закрыто: ${res.processed}, пропущено: ${res.skipped.length}`
        : `Закрыто: ${res.processed}`
  } finally {
    bulkBusy.value = false
  }
}

async function onBulkDelete() {
  if (!canDelete.value || bulkBusy.value || !selectedCount.value) return
  const ids = [...selected.value]
  const ok = window.confirm(
    `Удалить выбранные обращения (${ids.length})?\nСообщения этих обращений будут удалены безвозвратно.`,
  )
  if (!ok) return
  bulkBusy.value = true
  bulkMsg.value = ''
  try {
    const res = await appeals.deleteBatch(ids)
    if (!res) return
    clearSelection()
    bulkMsg.value =
      res.skipped.length > 0
        ? `Удалено: ${res.processed}, пропущено: ${res.skipped.length}`
        : `Удалено: ${res.processed}`
  } finally {
    bulkBusy.value = false
  }
}

const pageFrom = () => (appeals.total ? appeals.offset + 1 : 0)
const pageTo = () => Math.min(appeals.offset + appeals.items.length, appeals.total)
</script>

<template>
  <div class="relative flex h-full min-h-0 flex-col">
    <div class="border-b border-line bg-panel px-3 py-3 md:px-6 md:py-4">
      <div class="mb-3 flex items-center justify-between gap-3 md:mb-4">
        <div class="hidden md:block">
          <h1 class="text-lg font-bold tracking-tight text-ink">Обращения</h1>
          <p class="text-xs text-muted">
            Отметьте нужные и закройте или удалите пачкой
          </p>
        </div>
        <div class="min-w-0 flex-1 md:hidden">
          <div class="relative">
            <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input
              v-model="appeals.q"
              type="search"
              placeholder="Поиск обращений…"
              class="w-full rounded-xl border border-line bg-surface py-2.5 pl-9 pr-3 text-sm outline-none ring-brand focus:ring-2"
              @keydown.enter.prevent="onSubmit"
            />
          </div>
        </div>
        <button
          v-if="canCreate"
          type="button"
          class="inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand text-white shadow-sm transition hover:opacity-90"
          title="Создать обращение"
          @click="openCreate"
        >
          <Plus class="size-5" />
        </button>
      </div>

      <form class="hidden flex-col gap-3 md:flex md:flex-row md:flex-wrap md:items-end" @submit.prevent="onSubmit">
        <label class="min-w-0 w-full md:min-w-[220px] md:flex-1">
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
            Поиск
          </span>
          <div class="relative">
            <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input
              v-model="appeals.q"
              type="search"
              placeholder="Номер, имя, логин, текст сообщения…"
              class="w-full rounded-xl border border-line bg-surface py-2 pl-9 pr-3 text-sm outline-none ring-brand focus:ring-2"
            />
          </div>
        </label>

        <label>
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
            Статус
          </span>
          <select
            v-model="appeals.status"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm md:w-auto"
            @change="appeals.search()"
          >
            <option value="open">Открытые</option>
            <option value="closed">Закрытые</option>
            <option value="all">Все</option>
          </select>
        </label>

        <label>
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
            Оператор
          </span>
          <select
            v-model="appeals.assignee"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm md:w-auto"
            @change="appeals.search()"
          >
            <option value="all">Все</option>
            <option value="mine">Мои</option>
            <option value="unassigned">Свободные</option>
          </select>
        </label>

        <label>
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
            С
          </span>
          <input
            v-model="appeals.dateFrom"
            type="date"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm md:w-auto"
            @change="appeals.search()"
          />
        </label>

        <label>
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
            По
          </span>
          <input
            v-model="appeals.dateTo"
            type="date"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm md:w-auto"
            @change="appeals.search()"
          />
        </label>

        <button
          type="submit"
          class="w-full rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 md:w-auto"
          :disabled="appeals.loading"
        >
          Найти
        </button>
      </form>
      <p v-if="bulkMsg" class="mt-2 text-xs text-ok">{{ bulkMsg }}</p>
      <div class="mt-3 flex gap-2 overflow-x-auto md:hidden">
        <button
          v-for="opt in [
            { id: 'open' as const, label: 'Открытые' },
            { id: 'closed' as const, label: 'Закрытые' },
            { id: 'all' as const, label: 'Все' },
          ]"
          :key="opt.id"
          type="button"
          class="shrink-0 rounded-full px-3.5 py-1.5 text-xs font-semibold transition"
          :class="
            appeals.status === opt.id
              ? 'bg-brand text-white'
              : 'bg-surface text-muted'
          "
          @click="appeals.status = opt.id; appeals.search()"
        >
          {{ opt.label }}
        </button>
      </div>
    </div>

    <div
      class="min-h-0 flex-1 overflow-auto p-0 md:p-6"
      :class="selectedCount ? 'pb-28 md:pb-24' : ''"
    >
      <p v-if="appeals.error" class="mb-4 px-4 pt-4 text-sm text-danger md:px-0 md:pt-0">{{ appeals.error }}</p>
      <p v-if="appeals.loading && !appeals.items.length" class="px-4 pt-4 text-sm text-muted md:px-0 md:pt-0">Загрузка…</p>
      <p
        v-else-if="!appeals.loading && !appeals.items.length"
        class="px-4 pt-4 text-sm text-muted md:px-0 md:pt-0"
      >
        Обращений не найдено
      </p>

      <!-- Mobile native list -->
      <div v-else-if="appeals.items.length" class="divide-y divide-line bg-panel md:hidden">
        <button
          v-for="a in appeals.items"
          :key="'m-' + a.id"
          type="button"
          class="flex w-full items-center gap-3 px-3 py-3 text-left transition active:bg-surface"
          :class="selected.has(a.id) ? 'bg-brand-soft/40' : ''"
          @click="openAppeal(a.id)"
        >
          <div
            v-if="canBulk"
            class="shrink-0"
            @click.stop
          >
            <input
              type="checkbox"
              class="size-4 rounded border-line accent-brand"
              :checked="selected.has(a.id)"
              @change="toggleSelect(a.id)"
            />
          </div>
          <div
            class="flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface text-sm font-bold text-muted"
          >
            <img
              v-if="a.contactAvatarUrl"
              :src="a.contactAvatarUrl"
              :alt="a.contactName"
              class="size-full object-cover"
              loading="lazy"
              referrerpolicy="no-referrer"
            />
            <span v-else>{{ a.contactName.slice(0, 1) }}</span>
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-2">
              <span class="truncate text-[15px] font-semibold text-ink">{{ a.contactName }}</span>
              <span class="shrink-0 text-[10px] text-muted">{{ formatDate(a.lastAt || a.openedAt) }}</span>
            </div>
            <div class="mt-0.5 flex items-center gap-1.5">
              <span class="text-xs font-semibold text-muted">#{{ a.number }}</span>
              <span
                class="rounded-full px-1.5 py-0.5 text-[10px] font-bold"
                :class="a.status === 'open' ? 'bg-ok/15 text-ok' : 'bg-muted/15 text-muted'"
              >
                {{ appealStatusLabel[a.status] }}
              </span>
            </div>
            <p class="mt-0.5 truncate text-xs text-muted">{{ a.lastMessage || a.assigneeName || '—' }}</p>
          </div>
          <ChevronRight class="size-4 shrink-0 text-mute" />
        </button>
      </div>

      <div v-if="appeals.items.length" class="mt-0 hidden overflow-x-auto rounded-2xl border border-line bg-panel md:mt-0 md:block">
        <table class="w-full min-w-[680px] text-left text-sm">
          <thead class="border-b border-line bg-surface text-[11px] uppercase tracking-wide text-muted">
            <tr>
              <th v-if="canBulk" class="w-12 px-3 py-3">
                <input
                  type="checkbox"
                  class="size-4 rounded border-line accent-brand"
                  :checked="allPageSelected"
                  :disabled="!appeals.items.length"
                  title="Выбрать все на странице"
                  @change="toggleSelectAll"
                />
              </th>
              <th class="px-4 py-3 font-semibold">#</th>
              <th class="px-4 py-3 font-semibold">Клиент</th>
              <th class="px-4 py-3 font-semibold">Статус</th>
              <th class="px-4 py-3 font-semibold">Канал</th>
              <th class="px-4 py-3 font-semibold">Оператор</th>
              <th class="px-4 py-3 font-semibold">Открыто</th>
              <th class="px-4 py-3 font-semibold">Последнее</th>
              <th v-if="canDelete" class="w-12 px-2 py-3" />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="a in appeals.items"
              :key="a.id"
              class="cursor-pointer border-b border-line last:border-0 transition"
              :class="selected.has(a.id) ? 'bg-brand-soft/50' : 'hover:bg-brand-soft/40'"
              @click="openAppeal(a.id)"
            >
              <td v-if="canBulk" class="px-3 py-3" @click.stop>
                <input
                  type="checkbox"
                  class="size-4 rounded border-line accent-brand"
                  :checked="selected.has(a.id)"
                  @change="toggleSelect(a.id)"
                />
              </td>
              <td class="px-4 py-3 font-semibold">#{{ a.number }}</td>
              <td class="px-4 py-3">
                <div class="flex items-center gap-3">
                  <div
                    class="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface text-xs font-bold text-muted"
                  >
                    <img
                      v-if="a.contactAvatarUrl"
                      :src="a.contactAvatarUrl"
                      :alt="a.contactName"
                      class="size-full object-cover"
                      loading="lazy"
                      referrerpolicy="no-referrer"
                    />
                    <span v-else>{{ a.contactName.slice(0, 1) }}</span>
                  </div>
                  <div class="min-w-0">
                    <div class="truncate font-semibold">{{ a.contactName }}</div>
                    <div class="truncate text-xs text-muted">
                      {{ a.contactUsername ? `@${a.contactUsername}` : a.contactExternalId || '—' }}
                    </div>
                  </div>
                </div>
              </td>
              <td class="px-4 py-3">
                <span
                  class="rounded-full px-2 py-0.5 text-[10px] font-bold"
                  :class="a.status === 'open' ? 'bg-ok/15 text-ok' : 'bg-muted/15 text-muted'"
                >
                  {{ appealStatusLabel[a.status] }}
                </span>
              </td>
              <td class="px-4 py-3 text-xs text-muted">
                {{ a.channelName || '—' }}
                <span v-if="a.transport"> · {{ transportLabel[a.transport] }}</span>
              </td>
              <td class="px-4 py-3 text-xs">{{ a.assigneeName || 'Не назначен' }}</td>
              <td class="px-4 py-3 text-xs text-muted">{{ formatDate(a.openedAt) }}</td>
              <td class="max-w-[220px] truncate px-4 py-3 text-xs text-muted">
                {{ a.lastMessage || '—' }}
              </td>
              <td v-if="canDelete" class="px-2 py-3" @click.stop>
                <button
                  type="button"
                  class="rounded-lg p-1.5 text-muted transition hover:bg-danger/10 hover:text-danger disabled:opacity-40"
                  :disabled="deletingId === a.id"
                  title="Удалить обращение"
                  @click="onDelete(a, $event)"
                >
                  <Trash2 class="size-3.5" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div
        v-if="appeals.total"
        class="mt-4 flex items-center justify-between px-4 text-xs text-muted md:px-0"
      >
        <span>
          {{ pageFrom() }}–{{ pageTo() }} из {{ appeals.total }}
        </span>
        <div class="flex gap-2">
          <button
            type="button"
            class="rounded-lg border border-line px-3 py-1.5 font-semibold disabled:opacity-40"
            :disabled="appeals.offset <= 0 || appeals.loading"
            @click="appeals.prevPage()"
          >
            Назад
          </button>
          <button
            type="button"
            class="rounded-lg border border-line px-3 py-1.5 font-semibold disabled:opacity-40"
            :disabled="appeals.offset + appeals.limit >= appeals.total || appeals.loading"
            @click="appeals.nextPage()"
          >
            Далее
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="canBulk && selectedCount"
      class="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex justify-center px-4 pb-[calc(4.25rem+env(safe-area-inset-bottom))] md:pb-6"
    >
      <div
        class="pointer-events-auto flex max-w-full flex-wrap items-center gap-3 rounded-2xl border border-line bg-panel px-4 py-3 shadow-lg"
      >
        <span class="inline-flex items-center gap-1.5 text-sm font-semibold text-ink">
          <CheckSquare class="size-4 text-brand" />
          Выбрано: {{ selectedCount }}
        </span>
        <button
          v-if="canWrite"
          type="button"
          class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="bulkBusy || !selectedOpenCount"
          :title="selectedOpenCount ? 'Закрыть открытые из выбранных' : 'Нет открытых среди выбранных'"
          @click="onBulkClose"
        >
          {{ bulkBusy ? '…' : `Закрыть (${selectedOpenCount})` }}
        </button>
        <button
          v-if="canDelete"
          type="button"
          class="rounded-xl border border-danger/30 bg-danger/10 px-4 py-2 text-sm font-semibold text-danger disabled:opacity-50"
          :disabled="bulkBusy"
          @click="onBulkDelete"
        >
          Удалить
        </button>
        <button
          type="button"
          class="inline-flex items-center gap-1 rounded-xl px-2 py-2 text-sm text-muted hover:text-ink"
          title="Снять выделение"
          @click="clearSelection"
        >
          <X class="size-4" />
        </button>
      </div>
    </div>

    <CreateAppealModal
      :open="createOpen"
      :channels="channels.channels"
      :loading-channels="channels.loading"
      @close="createOpen = false"
      @created="onCreated"
    />
  </div>
</template>
