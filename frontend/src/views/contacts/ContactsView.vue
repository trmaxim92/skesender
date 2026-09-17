<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ChevronRight, Hand, Phone, Plus, RefreshCw, Search, SkipForward, Upload, X } from 'lucide-vue-next'
import {
  claimContactsBatchRequest,
  claimNextContactRequest,
  contactsSummaryRequest,
  createContactRequest,
  importContactsRequest,
  listContactsRequest,
  syncContactsFromFleetRequest,
  telHref,
  type Contact,
  type ContactFilter,
} from '@/api/contacts'
import { ApiError } from '@/api/client'
import Modal from '@/components/ui/Modal.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const canWrite = computed(() => auth.can('section.contacts') && auth.can('action.write'))

const items = ref<Contact[]>([])
const total = ref(0)
const summary = ref({ all: 0, mine: 0, callback: 0 })
const loading = ref(false)
const loadError = ref('')
const q = ref('')
const filter = ref<ContactFilter>('all')
const nextBusy = ref(false)
const claimBusy = ref(false)

const selected = ref<Set<number>>(new Set())

const createOpen = ref(false)
const createName = ref('')
const createPhone = ref('')
const createBusy = ref(false)
const createError = ref('')

const importInput = ref<HTMLInputElement | null>(null)
const importBusy = ref(false)
const importMsg = ref('')
const fleetBusy = ref(false)
const actionError = ref('')
const actionOk = ref('')

function fieldValue(c: Contact, keys: string[]) {
  const values = c.clientValues || {}
  for (const key of keys) {
    const v = (values[key] || '').trim()
    if (v) return v
  }
  for (const [k, v] of Object.entries(values)) {
    const lk = k.toLowerCase()
    if (keys.some((want) => lk === want || lk.includes(want)) && (v || '').trim()) {
      return v.trim()
    }
  }
  return ''
}

function companyOf(c: Contact) {
  return fieldValue(c, ['company', 'kompaniya', 'организация', 'firma'])
}

function emailOf(c: Contact) {
  return fieldValue(c, ['email', 'e_mail', 'почта', 'mail'])
}

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  if (parts.length === 1) return parts[0].slice(0, 1).toUpperCase()
  return (parts[0].slice(0, 1) + parts[1].slice(0, 1)).toUpperCase()
}

function isClaimable(c: Contact) {
  return c.assigneeId == null
}

const claimableItems = computed(() => items.value.filter(isClaimable))

const selectedCount = computed(() => selected.value.size)

const allClaimableSelected = computed(() => {
  const free = claimableItems.value
  if (!free.length) return false
  return free.every((c) => selected.value.has(c.id))
})

function clearSelection() {
  selected.value = new Set()
}

function toggleSelect(id: number, claimable: boolean) {
  if (!claimable || !canWrite.value) return
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

function toggleSelectAll() {
  if (!canWrite.value) return
  if (allClaimableSelected.value) {
    clearSelection()
    return
  }
  selected.value = new Set(claimableItems.value.map((c) => c.id))
}

async function loadSummary() {
  try {
    summary.value = await contactsSummaryRequest()
  } catch {
    // non-fatal
  }
}

async function loadList() {
  loading.value = true
  loadError.value = ''
  try {
    const page = await listContactsRequest({
      q: q.value.trim() || undefined,
      filter: filter.value,
      limit: 100,
      offset: 0,
    })
    items.value = page.items
    total.value = page.total
    // Drop selections that left the page / are no longer free.
    const visibleFree = new Set(page.items.filter(isClaimable).map((c) => c.id))
    selected.value = new Set([...selected.value].filter((id) => visibleFree.has(id)))
    await loadSummary()
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить контакты'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadList()
})

watch(filter, () => {
  clearSelection()
  actionOk.value = ''
  actionError.value = ''
  void loadList()
})

function onSearch() {
  clearSelection()
  void loadList()
}

function openContact(id: number) {
  void router.push({ name: 'contact-detail', params: { contactId: String(id) } })
}

function openCreate() {
  createName.value = ''
  createPhone.value = ''
  createError.value = ''
  createOpen.value = true
}

async function submitCreate() {
  if (createBusy.value) return
  createBusy.value = true
  createError.value = ''
  try {
    const c = await createContactRequest({
      name: createName.value.trim(),
      phone: createPhone.value.trim(),
    })
    createOpen.value = false
    await router.push({ name: 'contact-detail', params: { contactId: String(c.id) } })
  } catch (e) {
    createError.value = e instanceof ApiError ? e.detail : 'Не удалось создать'
  } finally {
    createBusy.value = false
  }
}

async function onNext() {
  if (!canWrite.value || nextBusy.value) return
  nextBusy.value = true
  actionError.value = ''
  actionOk.value = ''
  try {
    const c = await claimNextContactRequest()
    await router.push({ name: 'contact-detail', params: { contactId: String(c.id) } })
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.detail : 'Нет свободных контактов'
  } finally {
    nextBusy.value = false
  }
}

async function onClaimSelected() {
  if (!canWrite.value || claimBusy.value || !selectedCount.value) return
  claimBusy.value = true
  actionError.value = ''
  actionOk.value = ''
  try {
    const ids = [...selected.value]
    const res = await claimContactsBatchRequest(ids)
    const n = res.claimed.length
    const skip = res.skipped.length
    if (n && !skip) {
      actionOk.value = `Взято в работу: ${n}`
    } else if (n && skip) {
      actionOk.value = `Взято: ${n}, пропущено: ${skip}`
    } else {
      actionError.value = skip
        ? `Не удалось взять: ${res.skipped.map((s) => `#${s.id}`).join(', ')}`
        : 'Не удалось взять контакты'
    }
    clearSelection()
    await loadList()
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.detail : 'Не удалось взять контакты'
  } finally {
    claimBusy.value = false
  }
}

function triggerImport() {
  importInput.value?.click()
}

async function onImportFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || importBusy.value) return
  importBusy.value = true
  importMsg.value = ''
  try {
    const res = await importContactsRequest(file)
    importMsg.value = `Импорт: создано ${res.created}, пропущено ${res.skipped}`
    filter.value = 'all'
    await loadList()
  } catch (e) {
    importMsg.value = e instanceof ApiError ? e.detail : 'Ошибка импорта'
  } finally {
    importBusy.value = false
  }
}

async function onFleetSync() {
  if (!canWrite.value || fleetBusy.value) return
  const ok = window.confirm(
    'Удалить ВСЕ текущие контакты и загрузить водителей из Яндекс Fleet?\n\nДиалоги в чатах не удаляются.',
  )
  if (!ok) return
  fleetBusy.value = true
  actionError.value = ''
  actionOk.value = ''
  try {
    const res = await syncContactsFromFleetRequest({ purge: true })
    actionOk.value =
      `Fleet: удалено ${res.purged}, получено ${res.fetched}, создано ${res.created}` +
      (res.updated ? `, обновлено ${res.updated}` : '') +
      (res.skipped ? `, пропущено ${res.skipped}` : '')
    filter.value = 'all'
    await loadList()
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.detail : 'Ошибка синхронизации Fleet'
  } finally {
    fleetBusy.value = false
  }
}

function clearFilters() {
  q.value = ''
  filter.value = 'all'
  void loadList()
}

const title = computed(() => {
  if (filter.value === 'mine') return 'Мои клиенты'
  if (filter.value === 'callback') return 'Перезвонить'
  return 'Клиенты'
})

const subtitle = computed(() => {
  if (filter.value === 'mine') return 'Клиенты, которые вы уже взяли в работу'
  if (filter.value === 'callback') return 'Нужно перезвонить клиенту'
  return 'Свободные лиды — отметьте и заберите пачкой или по одному'
})
</script>

<template>
  <div class="relative flex h-full min-h-0 flex-col">
    <div class="border-b border-line bg-panel px-3 py-3 md:px-6 md:py-4">
      <div class="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between md:mb-4">
        <div class="hidden min-w-0 md:block">
          <h1 class="text-lg font-bold tracking-tight text-ink">{{ title }}</h1>
          <p class="mt-0.5 text-xs text-muted">{{ subtitle }}</p>
        </div>
        <div class="flex w-full items-center gap-2 md:w-auto md:flex-wrap">
          <div class="relative min-w-0 flex-1 md:hidden">
            <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input
              v-model="q"
              type="search"
              placeholder="Имя или телефон…"
              class="w-full rounded-xl border border-line bg-surface py-2.5 pl-9 pr-3 text-sm outline-none ring-brand focus:ring-2"
              @keydown.enter.prevent="onSearch"
            />
          </div>
          <button
            v-if="canWrite"
            type="button"
            class="hidden items-center gap-1.5 rounded-xl border border-line bg-surface px-3 py-2 text-sm font-medium text-ink transition hover:bg-brand-soft/50 disabled:opacity-50 sm:inline-flex"
            :disabled="nextBusy"
            title="Взять следующий свободный"
            @click="onNext"
          >
            <SkipForward class="size-4" />
            Следующий
          </button>
          <button
            v-if="canWrite"
            type="button"
            class="hidden size-10 items-center justify-center rounded-xl border border-line bg-surface text-ink transition hover:bg-brand-soft/50 disabled:opacity-50 sm:inline-flex"
            title="Импорт CSV"
            :disabled="importBusy"
            @click="triggerImport"
          >
            <Upload class="size-4" />
          </button>
          <button
            v-if="canWrite"
            type="button"
            class="hidden size-10 items-center justify-center rounded-xl border border-line bg-surface text-ink transition hover:bg-brand-soft/50 disabled:opacity-50 sm:inline-flex"
            title="Синхронизировать водителей из Яндекс Fleet"
            :disabled="fleetBusy"
            @click="onFleetSync"
          >
            <RefreshCw class="size-4" :class="fleetBusy ? 'animate-spin' : ''" />
          </button>
          <button
            v-if="canWrite"
            type="button"
            class="inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand text-white shadow-sm transition hover:opacity-90 md:size-auto md:gap-1.5 md:px-3.5 md:py-2 md:text-sm md:font-semibold"
            @click="openCreate"
          >
            <Plus class="size-5 md:size-4" />
            <span class="hidden md:inline">Добавить</span>
          </button>
        </div>
      </div>

      <form class="mb-3 hidden flex-col gap-3 md:flex md:flex-row md:items-end" @submit.prevent="onSearch">
        <label class="min-w-0 w-full md:flex-1">
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
            Поиск
          </span>
          <div class="relative">
            <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input
              v-model="q"
              type="search"
              placeholder="Имя или телефон…"
              class="w-full rounded-xl border border-line bg-surface py-2 pl-9 pr-3 text-sm outline-none ring-brand focus:ring-2"
            />
          </div>
        </label>
        <button
          type="submit"
          class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 md:w-auto"
          :disabled="loading"
        >
          Найти
        </button>
      </form>

      <input
        ref="importInput"
        type="file"
        accept=".csv,text/csv"
        class="hidden"
        @change="onImportFile"
      />
      <p v-if="importMsg" class="mt-2 text-xs text-muted">{{ importMsg }}</p>
      <p v-if="actionOk" class="mt-2 text-xs text-ok">{{ actionOk }}</p>
      <p v-if="actionError" class="mt-2 text-xs text-danger">{{ actionError }}</p>

      <div class="flex gap-2 overflow-x-auto pb-0.5 md:mt-4 md:flex-wrap">
        <button
          v-for="opt in [
            { id: 'all' as const, label: 'Свободные', count: summary.all },
            { id: 'mine' as const, label: 'Мои', count: summary.mine },
            { id: 'callback' as const, label: 'Перезвонить', count: summary.callback },
          ]"
          :key="opt.id"
          type="button"
          class="shrink-0 rounded-full px-3.5 py-1.5 text-sm font-medium transition"
          :class="
            filter === opt.id
              ? 'bg-brand text-white shadow-sm'
              : 'bg-surface text-muted hover:bg-brand-soft/60 hover:text-ink'
          "
          @click="filter = opt.id"
        >
          {{ opt.label }}
          <span
            class="ml-1 tabular-nums"
            :class="filter === opt.id ? 'text-white/80' : 'text-muted'"
          >
            {{ opt.count }}
          </span>
        </button>
      </div>
    </div>

    <div class="relative min-h-0 flex-1 overflow-auto p-0 md:p-6" :class="selectedCount ? 'pb-28 md:pb-24' : ''">
      <p v-if="loading && !items.length" class="px-4 pt-4 text-sm text-muted md:px-0 md:pt-0">Загрузка…</p>
      <p v-else-if="loadError" class="px-4 pt-4 text-sm text-danger md:px-0 md:pt-0">{{ loadError }}</p>

      <template v-else>
        <p v-if="!items.length" class="mx-4 mt-4 rounded-2xl border border-dashed border-line bg-panel px-6 py-12 text-center text-sm text-muted md:mx-0 md:mt-0">
          Клиентов с такими условиями нет.
          <button type="button" class="ml-1 font-semibold text-brand hover:underline" @click="clearFilters">
            Показать свободные
          </button>
        </p>

        <!-- Mobile list -->
        <div v-else class="divide-y divide-line bg-panel md:hidden">
          <button
            v-for="c in items"
            :key="'m-' + c.id"
            type="button"
            class="flex w-full items-center gap-3 px-3 py-3 text-left transition active:bg-surface"
            :class="selected.has(c.id) ? 'bg-brand-soft/40' : ''"
            @click="openContact(c.id)"
          >
            <div v-if="canWrite" class="shrink-0" @click.stop>
              <input
                type="checkbox"
                class="size-4 rounded border-line accent-brand disabled:opacity-30"
                :checked="selected.has(c.id)"
                :disabled="!isClaimable(c)"
                @change="toggleSelect(c.id, isClaimable(c))"
              />
            </div>
            <div
              class="flex size-11 shrink-0 items-center justify-center rounded-full bg-brand-soft text-sm font-bold text-brand"
            >
              {{ initials(c.name || c.phone) }}
            </div>
            <div class="min-w-0 flex-1">
              <div class="truncate text-[15px] font-semibold text-ink">
                {{ c.name || 'Без имени' }}
              </div>
              <div class="mt-0.5 truncate text-xs text-muted">
                {{ c.phone }}{{ companyOf(c) ? ` · ${companyOf(c)}` : '' }}
              </div>
              <div class="mt-1 flex items-center gap-1.5">
                <span
                  v-if="c.currentAppeal?.statusDef"
                  class="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium"
                  :style="{
                    background: c.currentAppeal.statusDef.color + '22',
                    color: c.currentAppeal.statusDef.color,
                  }"
                >
                  {{ c.currentAppeal.statusDef.name }}
                </span>
                <span class="text-[10px] text-muted">
                  {{ c.assigneeName || 'Свободный' }}
                </span>
              </div>
            </div>
            <a
              v-if="c.phone"
              :href="telHref(c.phone)"
              class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand"
              title="Позвонить"
              @click.stop
            >
              <Phone class="size-4" />
            </a>
            <ChevronRight class="size-4 shrink-0 text-mute" />
          </button>
        </div>

        <div v-if="items.length" class="hidden overflow-x-auto rounded-2xl border border-line bg-panel shadow-sm md:block">
          <table class="w-full min-w-[760px] text-left text-sm">
            <thead class="border-b border-line bg-surface/80 text-[11px] font-semibold uppercase tracking-wide text-muted">
              <tr>
                <th v-if="canWrite" class="w-12 px-3 py-3">
                  <input
                    type="checkbox"
                    class="size-4 rounded border-line accent-brand"
                    :checked="allClaimableSelected"
                    :disabled="!claimableItems.length"
                    :title="claimableItems.length ? 'Выбрать все свободные' : 'Нет свободных на странице'"
                    @change="toggleSelectAll"
                  />
                </th>
                <th class="px-4 py-3">Клиент</th>
                <th class="px-4 py-3">Компания</th>
                <th class="px-4 py-3">Телефон</th>
                <th class="px-4 py-3">Этап</th>
                <th class="px-4 py-3">Менеджер</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="c in items"
                :key="c.id"
                class="cursor-pointer border-b border-line last:border-0 transition"
                :class="
                  selected.has(c.id)
                    ? 'bg-brand-soft/50'
                    : 'hover:bg-brand-soft/30'
                "
                @click="openContact(c.id)"
              >
                <td v-if="canWrite" class="px-3 py-3" @click.stop>
                  <input
                    type="checkbox"
                    class="size-4 rounded border-line accent-brand disabled:opacity-30"
                    :checked="selected.has(c.id)"
                    :disabled="!isClaimable(c)"
                    :title="isClaimable(c) ? 'Отметить' : 'Уже назначен'"
                    @change="toggleSelect(c.id, isClaimable(c))"
                  />
                </td>
                <td class="px-4 py-3">
                  <div class="flex items-center gap-3">
                    <div
                      class="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-bold text-brand"
                    >
                      {{ initials(c.name || c.phone) }}
                    </div>
                    <div class="min-w-0">
                      <div class="truncate font-semibold text-ink">
                        {{ c.name || 'Без имени' }}
                      </div>
                      <div class="truncate text-xs text-muted">
                        {{ emailOf(c) || '—' }}
                      </div>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-3 text-muted">{{ companyOf(c) || '—' }}</td>
                <td class="px-4 py-3" @click.stop>
                  <a
                    :href="telHref(c.phone)"
                    class="inline-flex items-center gap-1.5 font-medium text-brand hover:underline"
                    title="Позвонить"
                  >
                    <Phone class="size-3.5 opacity-70" />
                    {{ c.phone }}
                  </a>
                </td>
                <td class="px-4 py-3 text-xs">
                  <span
                    v-if="c.currentAppeal?.statusDef"
                    class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-medium"
                    :style="{
                      background: c.currentAppeal.statusDef.color + '22',
                      color: c.currentAppeal.statusDef.color,
                    }"
                  >
                    {{ c.currentAppeal.statusDef.name }}
                  </span>
                  <span v-else class="text-muted">—</span>
                </td>
                <td class="px-4 py-3 text-xs text-muted">
                  {{ c.assigneeName || 'Свободный' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="total" class="mt-3 px-4 text-xs text-muted md:px-0">
          Показано {{ items.length }} из {{ total }}
        </div>
      </template>
    </div>

    <!-- Bulk claim bar -->
    <div
      v-if="canWrite && selectedCount"
      class="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex justify-center px-4 pb-[calc(4.25rem+env(safe-area-inset-bottom))] md:pb-6"
    >
      <div
        class="pointer-events-auto flex max-w-full flex-wrap items-center gap-3 rounded-2xl border border-line bg-panel px-4 py-3 shadow-lg"
      >
        <span class="text-sm font-semibold text-ink">
          Выбрано: {{ selectedCount }}
        </span>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="claimBusy"
          @click="onClaimSelected"
        >
          <Hand class="size-4" />
          {{ claimBusy ? 'Забираем…' : 'Взять в работу' }}
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

    <Modal v-if="createOpen" title="Новый клиент" @close="createOpen = false">
      <form class="space-y-3" @submit.prevent="submitCreate">
        <label class="block">
          <span class="mb-1 block text-xs font-semibold text-muted">ФИО</span>
          <input
            v-model="createName"
            type="text"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
            placeholder="Иван Иванов"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs font-semibold text-muted">Телефон</span>
          <input
            v-model="createPhone"
            type="tel"
            required
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
            placeholder="+79991234567"
          />
        </label>
        <p v-if="createError" class="text-sm text-danger">{{ createError }}</p>
        <div class="flex justify-end gap-2 pt-1">
          <button type="button" class="rounded-xl px-3 py-2 text-sm text-muted" @click="createOpen = false">
            Отмена
          </button>
          <button
            type="submit"
            class="rounded-xl bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            :disabled="createBusy"
          >
            Создать
          </button>
        </div>
      </form>
    </Modal>
  </div>
</template>
