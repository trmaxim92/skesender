<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  MoreVertical,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-vue-next'
import CreateAppealModal from '@/components/appeals/CreateAppealModal.vue'
import { useAppealsStore } from '@/stores/appeals'
import { useAuthStore } from '@/stores/auth'
import { useChannelsStore } from '@/stores/channels'
import { appealStatusLabel, transportBadge, transportBadgeClass, transportLabel } from '@/types'

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

const pageFrom = computed(() => (appeals.total ? appeals.offset + 1 : 0))
const pageTo = computed(() => Math.min(appeals.offset + appeals.items.length, appeals.total))
const currentPage = computed(() => Math.floor(appeals.offset / appeals.limit) + 1)
const totalPages = computed(() => Math.max(1, Math.ceil(appeals.total / appeals.limit) || 1))

/** Compact page list with ellipsis, e.g. 1 2 3 … 12 */
const pageItems = computed(() => {
  const total = totalPages.value
  const cur = currentPage.value
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const pages = new Set<number>([1, total, cur, cur - 1, cur + 1, 2, total - 1])
  const sorted = [...pages].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b)
  const out: Array<number | '…'> = []
  let prev = 0
  for (const p of sorted) {
    if (prev && p - prev > 1) out.push('…')
    out.push(p)
    prev = p
  }
  return out
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

function initials(name: string | null | undefined) {
  const parts = (name || '?').trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

function contactSub(a: { contactUsername: string | null; contactExternalId: string | null }) {
  if (a.contactUsername) return `@${a.contactUsername}`
  if (a.contactExternalId) return a.contactExternalId
  return '—'
}

function goPage(page: number) {
  const p = Math.min(Math.max(1, page), totalPages.value)
  appeals.offset = (p - 1) * appeals.limit
  void appeals.fetchAppeals()
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
</script>

<template>
  <div class="relative flex h-full min-h-0 flex-col bg-surface">
    <div class="shrink-0 px-3 pb-3 pt-3 md:px-6 md:pb-4 md:pt-5">
      <div class="mb-4 flex items-start justify-between gap-3">
        <div class="min-w-0">
          <h1 class="text-xl font-bold tracking-tight text-ink md:text-2xl">Обращения</h1>
          <p class="mt-0.5 text-sm text-muted">
            Отметьте нужные и закройте или удалите пачкой
          </p>
        </div>
        <button
          v-if="canCreate"
          type="button"
          class="inline-flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand text-white shadow-sm transition hover:brightness-110"
          title="Создать обращение"
          @click="openCreate"
        >
          <Plus class="size-5" />
        </button>
      </div>

      <form
        class="flex flex-col gap-3 rounded-2xl border border-line bg-panel p-3 shadow-sm md:flex-row md:flex-wrap md:items-end md:gap-3 md:p-4"
        @submit.prevent="onSubmit"
      >
        <div class="min-w-0 w-full md:min-w-[240px] md:flex-1">
          <div class="relative">
            <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input
              v-model="appeals.q"
              type="search"
              placeholder="Номер, имя, логин, текст сообщения…"
              class="w-full rounded-xl border border-line bg-surface py-2.5 pl-9 pr-3 text-sm outline-none ring-brand/25 focus:ring-2"
            />
          </div>
        </div>

        <label class="block shrink-0">
          <span class="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-muted">
            Статус
          </span>
          <select
            v-model="appeals.status"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm md:min-w-[8.5rem]"
          >
            <option value="open">Открытые</option>
            <option value="closed">Закрытые</option>
            <option value="all">Все</option>
          </select>
        </label>

        <label class="block shrink-0">
          <span class="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-muted">
            Оператор
          </span>
          <select
            v-model="appeals.assignee"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm md:min-w-[8.5rem]"
          >
            <option value="all">Все</option>
            <option value="mine">Мои</option>
            <option value="unassigned">Свободные</option>
          </select>
        </label>

        <label class="block shrink-0">
          <span class="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-muted">С</span>
          <input
            v-model="appeals.dateFrom"
            type="date"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm md:w-[10.5rem]"
          />
        </label>

        <label class="block shrink-0">
          <span class="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-muted">По</span>
          <input
            v-model="appeals.dateTo"
            type="date"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm md:w-[10.5rem]"
          />
        </label>

        <button
          type="submit"
          class="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-110 disabled:opacity-50 md:w-auto"
          :disabled="appeals.loading"
        >
          <Search class="size-4" />
          Найти
        </button>
      </form>
      <p v-if="bulkMsg" class="mt-2 text-xs text-ok">{{ bulkMsg }}</p>
    </div>

    <div
      class="min-h-0 flex-1 overflow-auto px-3 pb-4 md:px-6"
      :class="selectedCount ? 'pb-28 md:pb-24' : ''"
    >
      <p v-if="appeals.error" class="mb-3 text-sm text-danger">{{ appeals.error }}</p>
      <p v-if="appeals.loading && !appeals.items.length" class="text-sm text-muted">Загрузка…</p>
      <p v-else-if="!appeals.loading && !appeals.items.length" class="text-sm text-muted">
        Обращений не найдено
      </p>

      <!-- Mobile list -->
      <div v-else-if="appeals.items.length" class="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-panel md:hidden">
        <button
          v-for="a in appeals.items"
          :key="'m-' + a.id"
          type="button"
          class="flex w-full items-center gap-3 px-3 py-3 text-left transition active:bg-surface"
          :class="selected.has(a.id) ? 'bg-brand-soft/40' : ''"
          @click="openAppeal(a.id)"
        >
          <div v-if="canBulk" class="shrink-0" @click.stop>
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

      <!-- Desktop table -->
      <div
        v-if="appeals.items.length"
        class="hidden overflow-hidden rounded-2xl border border-line bg-panel shadow-sm md:block"
      >
        <div class="overflow-x-auto">
          <table class="w-full min-w-[920px] text-left text-sm">
            <thead class="border-b border-line bg-surface/80 text-[11px] font-semibold uppercase tracking-wide text-muted">
              <tr>
                <th v-if="canBulk" class="w-12 px-4 py-3.5">
                  <input
                    type="checkbox"
                    class="size-4 rounded border-line accent-brand"
                    :checked="allPageSelected"
                    :disabled="!appeals.items.length"
                    title="Выбрать все на странице"
                    @change="toggleSelectAll"
                  />
                </th>
                <th class="px-3 py-3.5">#</th>
                <th class="px-3 py-3.5">Клиент</th>
                <th class="px-3 py-3.5">Статус</th>
                <th class="px-3 py-3.5">Канал</th>
                <th class="px-3 py-3.5">Оператор</th>
                <th class="px-3 py-3.5">Открыто</th>
                <th class="px-3 py-3.5">Последнее</th>
                <th class="w-12 px-2 py-3.5 text-center">
                  <MoreVertical class="mx-auto size-4 text-muted/50" aria-hidden="true" />
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="a in appeals.items"
                :key="a.id"
                class="cursor-pointer border-b border-line/80 last:border-0 transition"
                :class="selected.has(a.id) ? 'bg-brand-soft/40' : 'hover:bg-surface/80'"
                @click="openAppeal(a.id)"
              >
                <td v-if="canBulk" class="px-4 py-3.5" @click.stop>
                  <input
                    type="checkbox"
                    class="size-4 rounded border-line accent-brand"
                    :checked="selected.has(a.id)"
                    @change="toggleSelect(a.id)"
                  />
                </td>
                <td class="px-3 py-3.5 font-semibold text-ink">#{{ a.number }}</td>
                <td class="px-3 py-3.5">
                  <div class="flex items-center gap-3">
                    <div
                      class="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface text-xs font-bold text-muted ring-1 ring-line"
                    >
                      <img
                        v-if="a.contactAvatarUrl"
                        :src="a.contactAvatarUrl"
                        :alt="a.contactName"
                        class="size-full object-cover"
                        loading="lazy"
                        referrerpolicy="no-referrer"
                      />
                      <span v-else>{{ initials(a.contactName) }}</span>
                    </div>
                    <div class="min-w-0">
                      <div class="truncate font-semibold text-ink">{{ a.contactName }}</div>
                      <div class="truncate text-xs text-muted">{{ contactSub(a) }}</div>
                    </div>
                  </div>
                </td>
                <td class="px-3 py-3.5">
                  <span
                    class="inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold"
                    :class="a.status === 'open' ? 'bg-ok/15 text-ok' : 'bg-muted/15 text-muted'"
                  >
                    {{ appealStatusLabel[a.status] }}
                  </span>
                </td>
                <td class="px-3 py-3.5">
                  <div class="flex min-w-0 items-center gap-2">
                    <span
                      v-if="a.transport"
                      class="flex size-7 shrink-0 items-center justify-center rounded-md text-[9px] font-bold"
                      :class="transportBadgeClass[a.transport]"
                      :title="transportLabel[a.transport]"
                    >
                      {{ transportBadge[a.transport].slice(0, 1) }}
                    </span>
                    <span class="truncate text-xs text-ink">
                      {{ a.channelName || '—' }}
                      <span v-if="a.transport" class="text-muted">
                        · {{ transportLabel[a.transport] }}
                      </span>
                    </span>
                  </div>
                </td>
                <td class="px-3 py-3.5">
                  <div v-if="a.assigneeName" class="flex items-center gap-2">
                    <span
                      class="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[10px] font-bold text-brand"
                    >
                      {{ initials(a.assigneeName) }}
                    </span>
                    <span class="truncate text-xs font-medium text-ink">{{ a.assigneeName }}</span>
                  </div>
                  <span v-else class="text-xs text-muted">Не назначен</span>
                </td>
                <td class="whitespace-nowrap px-3 py-3.5 text-xs text-muted">
                  {{ formatDate(a.openedAt) }}
                </td>
                <td class="max-w-[220px] truncate px-3 py-3.5 text-xs text-muted">
                  {{ a.lastMessage || '—' }}
                </td>
                <td class="px-2 py-3.5 text-center" @click.stop>
                  <button
                    v-if="canDelete"
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
          class="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-xs text-muted"
        >
          <span>
            Показано {{ pageFrom }}–{{ pageTo }} из {{ appeals.total }}
          </span>
          <div class="flex items-center gap-1">
            <button
              type="button"
              class="flex size-8 items-center justify-center rounded-lg border border-line transition hover:bg-surface disabled:opacity-40"
              :disabled="currentPage <= 1 || appeals.loading"
              title="Назад"
              @click="goPage(currentPage - 1)"
            >
              <ChevronLeft class="size-4" />
            </button>
            <template v-for="(item, idx) in pageItems" :key="idx + '-' + item">
              <span v-if="item === '…'" class="px-1 text-muted">…</span>
              <button
                v-else
                type="button"
                class="flex size-8 items-center justify-center rounded-lg text-xs font-semibold transition"
                :class="
                  item === currentPage
                    ? 'bg-brand text-white'
                    : 'border border-line text-ink hover:bg-surface'
                "
                :disabled="appeals.loading"
                @click="goPage(item)"
              >
                {{ item }}
              </button>
            </template>
            <button
              type="button"
              class="flex size-8 items-center justify-center rounded-lg border border-line transition hover:bg-surface disabled:opacity-40"
              :disabled="currentPage >= totalPages || appeals.loading"
              title="Далее"
              @click="goPage(currentPage + 1)"
            >
              <ChevronRight class="size-4" />
            </button>
          </div>
        </div>
      </div>

      <!-- Mobile pagination -->
      <div
        v-if="appeals.total && appeals.items.length"
        class="mt-4 flex items-center justify-between text-xs text-muted md:hidden"
      >
        <span>{{ pageFrom }}–{{ pageTo }} из {{ appeals.total }}</span>
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
