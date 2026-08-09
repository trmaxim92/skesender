<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Search, Upload, SkipForward } from 'lucide-vue-next'
import {
  claimNextContactRequest,
  contactsSummaryRequest,
  createContactRequest,
  importContactsRequest,
  listContactsRequest,
  telHref,
  type Contact,
  type ContactFilter,
} from '@/api/contacts'
import { ApiError } from '@/api/client'
import Modal from '@/components/ui/Modal.vue'
import { useAuthStore } from '@/stores/auth'
import {
  contactOutcomeLabel,
  contactStatusLabel,
  type ContactCallOutcome,
  type ContactStatus,
} from '@/types'

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

const createOpen = ref(false)
const createName = ref('')
const createPhone = ref('')
const createBusy = ref(false)
const createError = ref('')

const importInput = ref<HTMLInputElement | null>(null)
const importBusy = ref(false)
const importMsg = ref('')
const actionError = ref('')

function fieldValue(c: Contact, keys: string[]) {
  const values = c.clientValues || {}
  for (const key of keys) {
    const v = (values[key] || '').trim()
    if (v) return v
  }
  // match by lowercase key contains
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
  void loadList()
})

function onSearch() {
  void loadList()
}

function openContact(id: number) {
  void router.push({ name: 'contact-detail', params: { contactId: String(id) } })
}

function statusBadge(status: ContactStatus | string) {
  if (status === 'in_work') return 'bg-amber-100 text-amber-800'
  if (status === 'done') return 'bg-emerald-100 text-emerald-800'
  return 'bg-slate-100 text-slate-700'
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
  try {
    const c = await claimNextContactRequest()
    await router.push({ name: 'contact-detail', params: { contactId: String(c.id) } })
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.detail : 'Нет свободных контактов'
  } finally {
    nextBusy.value = false
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

function clearFilters() {
  q.value = ''
  filter.value = 'all'
  void loadList()
}

const title = computed(() => {
  if (filter.value === 'mine') return 'Мои контакты'
  if (filter.value === 'callback') return 'Перезвонить'
  return 'Все контакты'
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-surface">
    <header class="border-b border-line bg-panel px-4 py-3 md:px-6">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div class="min-w-0">
          <h1 class="truncate text-sm font-bold uppercase tracking-wide text-ink">
            {{ title }}
          </h1>
          <p class="text-xs text-muted">{{ total }} элементов</p>
        </div>

        <form class="flex min-w-0 flex-1 lg:max-w-xl" @submit.prevent="onSearch">
          <div class="relative w-full">
            <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input
              v-model="q"
              type="search"
              placeholder="Поиск и фильтр"
              class="w-full rounded-xl border border-line bg-surface py-2 pl-9 pr-3 text-sm outline-none ring-brand focus:ring-2"
            />
          </div>
        </form>

        <div class="flex flex-wrap items-center gap-2">
          <button
            v-if="canWrite"
            type="button"
            class="inline-flex items-center gap-1.5 rounded-xl border border-line bg-surface px-3 py-2 text-xs font-medium text-ink hover:bg-panel disabled:opacity-50"
            :disabled="nextBusy"
            @click="onNext"
          >
            <SkipForward class="size-3.5" />
            Следующий
          </button>
          <button
            v-if="canWrite"
            type="button"
            class="inline-flex size-9 items-center justify-center rounded-xl border border-line bg-surface text-ink hover:bg-panel"
            title="Импорт CSV"
            :disabled="importBusy"
            @click="triggerImport"
          >
            <Upload class="size-4" />
          </button>
          <button
            v-if="canWrite"
            type="button"
            class="inline-flex items-center gap-1.5 rounded-xl bg-brand px-3 py-2 text-xs font-bold uppercase tracking-wide text-white hover:opacity-90"
            @click="openCreate"
          >
            <Plus class="size-4" />
            Добавить контакт
          </button>
        </div>
      </div>

      <input
        ref="importInput"
        type="file"
        accept=".csv,text/csv"
        class="hidden"
        @change="onImportFile"
      />
      <p v-if="importMsg" class="mt-2 text-xs text-muted">{{ importMsg }}</p>
      <p v-if="actionError" class="mt-2 text-xs text-red-600">{{ actionError }}</p>

      <div class="mt-3 flex flex-wrap gap-1">
        <button
          v-for="opt in [
            { id: 'all' as const, label: `Все (${summary.all})` },
            { id: 'mine' as const, label: `Мои (${summary.mine})` },
            { id: 'callback' as const, label: `Перезвонить (${summary.callback})` },
          ]"
          :key="opt.id"
          type="button"
          class="rounded-lg px-3 py-1.5 text-xs font-medium transition"
          :class="filter === opt.id ? 'bg-brand text-white' : 'bg-surface text-muted hover:text-ink'"
          @click="filter = opt.id"
        >
          {{ opt.label }}
        </button>
      </div>
    </header>

    <div class="min-h-0 flex-1 overflow-auto">
      <p v-if="loading" class="px-6 py-8 text-sm text-muted">Загрузка…</p>
      <p v-else-if="loadError" class="px-6 py-8 text-sm text-red-600">{{ loadError }}</p>

      <div v-else class="min-w-full">
        <table class="w-full min-w-[720px] border-collapse text-left text-sm">
          <thead class="sticky top-0 z-10 border-b border-line bg-panel text-[11px] font-bold uppercase tracking-wide text-muted">
            <tr>
              <th class="px-4 py-3 md:px-6">Наименование</th>
              <th class="px-3 py-3">Компания</th>
              <th class="px-3 py-3">Телефон</th>
              <th class="px-3 py-3">Email</th>
              <th class="px-3 py-3">Статус</th>
              <th class="px-4 py-3 md:px-6">Исход</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!items.length">
              <td colspan="6" class="px-6 py-10 text-center text-sm text-red-600">
                К сожалению, контактов с выбранными вами условиями не найдено.
                <button type="button" class="ml-1 underline" @click="clearFilters">
                  Показать все
                </button>
              </td>
            </tr>
            <tr
              v-for="c in items"
              :key="c.id"
              class="cursor-pointer border-b border-line bg-panel transition hover:bg-surface"
              @click="openContact(c.id)"
            >
              <td class="px-4 py-3 font-medium text-ink md:px-6">
                {{ c.name || 'Без имени' }}
              </td>
              <td class="px-3 py-3 text-muted">{{ companyOf(c) || '—' }}</td>
              <td class="px-3 py-3" @click.stop>
                <a
                  :href="telHref(c.phone)"
                  class="font-medium text-brand hover:underline"
                  title="Откроет SIP / телефон"
                >
                  {{ c.phone }}
                </a>
              </td>
              <td class="px-3 py-3 text-muted">{{ emailOf(c) || '—' }}</td>
              <td class="px-3 py-3">
                <span
                  class="inline-block rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase"
                  :class="statusBadge(c.status)"
                >
                  {{ contactStatusLabel[c.status as ContactStatus] || c.status }}
                </span>
              </td>
              <td class="px-4 py-3 text-xs text-muted md:px-6">
                {{
                  c.lastOutcome
                    ? contactOutcomeLabel[c.lastOutcome as ContactCallOutcome] || c.lastOutcome
                    : '—'
                }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <Modal v-if="createOpen" title="Новый контакт" @close="createOpen = false">
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
          <span class="mb-1 block text-xs font-semibold text-muted">Телефон / номер</span>
          <input
            v-model="createPhone"
            type="tel"
            required
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
            placeholder="+79991234567"
          />
        </label>
        <p v-if="createError" class="text-sm text-red-600">{{ createError }}</p>
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
