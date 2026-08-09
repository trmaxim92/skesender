<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Phone,
  Plus,
  Search,
  Upload,
  UserPlus,
  MessageSquare,
  Hand,
} from 'lucide-vue-next'
import {
  addContactCommentRequest,
  claimContactRequest,
  createContactRequest,
  getContactRequest,
  importContactsRequest,
  listContactsRequest,
  telHref,
  updateContactFieldsRequest,
  updateContactRequest,
  type Contact,
  type ContactFilter,
} from '@/api/contacts'
import { ApiError } from '@/api/client'
import Modal from '@/components/ui/Modal.vue'
import ContactSendModal from '@/views/contacts/ContactSendModal.vue'
import { useAuthStore } from '@/stores/auth'
import { useChannelsStore } from '@/stores/channels'
import { contactStatusLabel, type ContactStatus, type FieldDefinition } from '@/types'

const auth = useAuthStore()
const channels = useChannelsStore()
const router = useRouter()

const canWrite = computed(() => auth.can('section.contacts') && auth.can('action.write'))

const items = ref<Contact[]>([])
const total = ref(0)
const loading = ref(false)
const loadError = ref('')
const q = ref('')
const filter = ref<ContactFilter>('all')
const selectedId = ref<number | null>(null)
const detail = ref<Contact | null>(null)
const detailLoading = ref(false)
const commentText = ref('')
const commentBusy = ref(false)
const claimBusy = ref(false)
const actionError = ref('')
const fieldsDraft = ref<Record<string, string>>({})
const fieldsSaving = ref(false)

const createOpen = ref(false)
const createName = ref('')
const createPhone = ref('')
const createBusy = ref(false)
const createError = ref('')

const sendOpen = ref(false)
const importInput = ref<HTMLInputElement | null>(null)
const importBusy = ref(false)
const importMsg = ref('')

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
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить контакты'
  } finally {
    loading.value = false
  }
}

async function loadDetail(id: number) {
  detailLoading.value = true
  actionError.value = ''
  try {
    detail.value = await getContactRequest(id)
    selectedId.value = id
    fieldsDraft.value = { ...detail.value.clientValues }
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.detail : 'Не удалось открыть контакт'
    detail.value = null
    fieldsDraft.value = {}
  } finally {
    detailLoading.value = false
  }
}

function selectContact(id: number) {
  void loadDetail(id)
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

function statusBadge(status: ContactStatus | string) {
  if (status === 'in_work') return 'bg-amber-100 text-amber-800'
  if (status === 'done') return 'bg-emerald-100 text-emerald-800'
  return 'bg-slate-100 text-slate-700'
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function fieldInputType(f: FieldDefinition) {
  if (f.fieldType === 'number') return 'number'
  if (f.fieldType === 'phone') return 'tel'
  if (f.fieldType === 'date') return 'date'
  if (f.fieldType === 'link') return 'url'
  return 'text'
}

function linkHref(value: string | undefined) {
  const raw = (value || '').trim()
  if (!raw) return ''
  if (/^https?:\/\//i.test(raw)) return raw
  return `https://${raw}`
}

async function saveFields() {
  if (!detail.value || !canWrite.value || fieldsSaving.value) return
  fieldsSaving.value = true
  actionError.value = ''
  try {
    const values = Object.entries(fieldsDraft.value)
      .filter(([key]) => !['full_name', 'phone', 'external_id'].includes(key))
      .map(([key, value]) => ({ key, value }))
    detail.value = await updateContactFieldsRequest(detail.value.id, {
      full_name: fieldsDraft.value.full_name ?? '',
      phone: fieldsDraft.value.phone ?? '',
      external_id: fieldsDraft.value.external_id ?? '',
      values,
    })
    fieldsDraft.value = { ...detail.value.clientValues }
    const idx = items.value.findIndex((c) => c.id === detail.value!.id)
    if (idx >= 0) {
      items.value[idx] = {
        ...items.value[idx]!,
        name: detail.value.name,
        phone: detail.value.phone,
        status: detail.value.status,
      }
    }
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить поля'
  } finally {
    fieldsSaving.value = false
  }
}

async function onClaim() {
  if (!detail.value || claimBusy.value || !canWrite.value) return
  claimBusy.value = true
  actionError.value = ''
  try {
    const claimed = await claimContactRequest(detail.value.id)
    detail.value = claimed
    fieldsDraft.value = { ...claimed.clientValues }
    // Уходит из «Все» в «Мои»
    filter.value = 'mine'
    await loadList()
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.detail : 'Не удалось взять в работу'
  } finally {
    claimBusy.value = false
  }
}

async function onAddComment() {
  if (!detail.value || !canWrite.value || commentBusy.value) return
  const text = commentText.value.trim()
  if (!text) return
  commentBusy.value = true
  actionError.value = ''
  try {
    const c = await addContactCommentRequest(detail.value.id, text)
    detail.value = {
      ...detail.value,
      comments: [...detail.value.comments, c],
    }
    commentText.value = ''
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить комментарий'
  } finally {
    commentBusy.value = false
  }
}

async function markDone() {
  if (!detail.value || !canWrite.value) return
  try {
    detail.value = await updateContactRequest(detail.value.id, { status: 'done' })
    await loadList()
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.detail : 'Не удалось обновить статус'
  }
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
    await loadList()
    await loadDetail(c.id)
  } catch (e) {
    createError.value = e instanceof ApiError ? e.detail : 'Не удалось создать'
  } finally {
    createBusy.value = false
  }
}

function openSend() {
  if (!detail.value) return
  sendOpen.value = true
  if (!channels.channels.length) void channels.fetchChannels()
}

function onSent(dialogId: number) {
  sendOpen.value = false
  void router.push({ name: 'chats', query: { dialog: String(dialogId) } })
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
    await loadList()
  } catch (e) {
    importMsg.value = e instanceof ApiError ? e.detail : 'Ошибка импорта'
  } finally {
    importBusy.value = false
  }
}

const canClaim = computed(() => {
  if (!detail.value || !canWrite.value) return false
  return detail.value.assigneeId == null || detail.value.assigneeId === auth.user?.id
})

const isMineOrFree = computed(() => {
  if (!detail.value) return false
  return detail.value.assigneeId == null || detail.value.assigneeId === auth.user?.id
})
</script>

<template>
  <div class="flex h-full min-h-0">
    <!-- List -->
    <aside class="flex w-full max-w-md shrink-0 flex-col border-r border-line bg-panel md:w-[360px]">
      <div class="border-b border-line px-4 py-4">
        <div class="mb-3 flex items-center justify-between gap-2">
          <div>
            <h1 class="text-lg font-bold tracking-tight text-ink">Контакты</h1>
            <p class="text-xs text-muted">
              {{ filter === 'mine' ? 'Ваши в работе' : 'Свободные в пуле' }} · {{ total }}
            </p>
          </div>
          <div class="flex items-center gap-1">
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
              class="inline-flex size-9 items-center justify-center rounded-xl bg-brand text-white hover:opacity-90"
              title="Добавить контакт"
              @click="openCreate"
            >
              <Plus class="size-5" />
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
        <p v-if="importMsg" class="mb-2 text-xs text-muted">{{ importMsg }}</p>

        <form class="space-y-2" @submit.prevent="onSearch">
          <div class="relative">
            <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input
              v-model="q"
              type="search"
              placeholder="Имя или телефон…"
              class="w-full rounded-xl border border-line bg-surface py-2 pl-9 pr-3 text-sm outline-none ring-brand focus:ring-2"
            />
          </div>
          <div class="flex gap-1">
            <button
              v-for="opt in [
                { id: 'all', label: 'Все' },
                { id: 'mine', label: 'Мои контакты' },
              ] as const"
              :key="opt.id"
              type="button"
              class="shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium transition"
              :class="
                filter === opt.id
                  ? 'bg-brand text-white'
                  : 'bg-surface text-muted hover:text-ink'
              "
              @click="filter = opt.id"
            >
              {{ opt.label }}
            </button>
          </div>
        </form>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto">
        <p v-if="loading" class="px-4 py-6 text-sm text-muted">Загрузка…</p>
        <p v-else-if="loadError" class="px-4 py-6 text-sm text-red-600">{{ loadError }}</p>
        <p v-else-if="!items.length" class="px-4 py-6 text-sm text-muted">Контактов пока нет</p>
        <ul v-else>
          <li v-for="c in items" :key="c.id">
            <button
              type="button"
              class="flex w-full flex-col gap-0.5 border-b border-line px-4 py-3 text-left transition hover:bg-surface"
              :class="selectedId === c.id ? 'bg-surface' : ''"
              @click="selectContact(c.id)"
            >
              <span class="flex items-center justify-between gap-2">
                <span class="truncate text-sm font-semibold text-ink">{{ c.name || 'Без имени' }}</span>
                <span
                  class="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase"
                  :class="statusBadge(c.status)"
                >
                  {{ contactStatusLabel[c.status as ContactStatus] || c.status }}
                </span>
              </span>
              <span class="truncate text-xs text-muted">{{ c.phone }}</span>
              <span v-if="c.assigneeName" class="truncate text-[11px] text-muted">
                {{ c.assigneeName }}
              </span>
            </button>
          </li>
        </ul>
      </div>
    </aside>

    <!-- Detail -->
    <section class="flex min-w-0 flex-1 flex-col bg-surface">
      <div v-if="!selectedId" class="flex flex-1 items-center justify-center p-8 text-sm text-muted">
        Выберите контакт слева
      </div>
      <div v-else-if="detailLoading && !detail" class="flex flex-1 items-center justify-center text-sm text-muted">
        Загрузка…
      </div>
      <template v-else-if="detail">
        <header class="border-b border-line bg-panel px-4 py-4 md:px-6">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="min-w-0">
              <h2 class="truncate text-xl font-bold text-ink">{{ detail.name || 'Без имени' }}</h2>
              <a
                :href="telHref(detail.phone)"
                class="mt-1 inline-flex items-center gap-2 text-base font-medium text-brand hover:underline"
              >
                <Phone class="size-4" />
                {{ detail.phone }}
              </a>
              <p class="mt-1 text-xs text-muted">
                <span
                  class="mr-2 inline-block rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase"
                  :class="statusBadge(detail.status)"
                >
                  {{ contactStatusLabel[detail.status] || detail.status }}
                </span>
                <span v-if="detail.assigneeName">Ответственный: {{ detail.assigneeName }}</span>
                <span v-else>Свободный</span>
              </p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button
                v-if="canClaim && detail.assigneeId == null"
                type="button"
                class="inline-flex items-center gap-1.5 rounded-xl bg-brand px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
                :disabled="claimBusy"
                @click="onClaim"
              >
                <Hand class="size-4" />
                Взять в работу
              </button>
              <button
                v-if="canWrite && isMineOrFree"
                type="button"
                class="inline-flex items-center gap-1.5 rounded-xl border border-line bg-panel px-3 py-2 text-sm font-medium text-ink hover:bg-surface"
                @click="openSend"
              >
                <MessageSquare class="size-4" />
                В мессенджер
              </button>
              <button
                v-if="canWrite && detail.status !== 'done' && isMineOrFree"
                type="button"
                class="rounded-xl border border-line px-3 py-2 text-sm text-muted hover:bg-surface"
                @click="markDone"
              >
                Завершить
              </button>
            </div>
          </div>
          <p v-if="actionError" class="mt-2 text-sm text-red-600">{{ actionError }}</p>
        </header>

        <div class="flex min-h-0 flex-1 flex-col">
          <div class="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4 md:px-6">
            <section class="space-y-3 rounded-2xl border border-line bg-panel p-4">
              <h3 class="text-xs font-semibold uppercase tracking-wide text-muted">Карточка клиента</h3>
              <p class="text-[11px] text-muted">
                Те же поля, что в настройках «Поля клиента» и в чатах
              </p>
              <div
                v-for="f in detail.clientFields"
                :key="f.key"
                class="space-y-1"
              >
                <label class="text-[11px] font-semibold uppercase tracking-wide text-muted">
                  {{ f.label }}
                  <span v-if="f.isSystem" class="normal-case text-muted/70">(базовое)</span>
                </label>
                <textarea
                  v-if="f.fieldType === 'textarea'"
                  v-model="fieldsDraft[f.key]"
                  rows="3"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  :readonly="!canWrite"
                />
                <select
                  v-else-if="f.fieldType === 'select'"
                  v-model="fieldsDraft[f.key]"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  :disabled="!canWrite"
                >
                  <option value="">—</option>
                  <option v-for="opt in f.options" :key="opt" :value="opt">{{ opt }}</option>
                </select>
                <div v-else-if="f.fieldType === 'link'" class="space-y-1.5">
                  <input
                    v-model="fieldsDraft[f.key]"
                    type="url"
                    placeholder="https://"
                    class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                    :readonly="!canWrite"
                  />
                  <a
                    v-if="fieldsDraft[f.key]?.trim()"
                    :href="linkHref(fieldsDraft[f.key])"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="inline-block text-xs font-semibold text-brand hover:underline"
                  >
                    Открыть ссылку
                  </a>
                </div>
                <label
                  v-else-if="f.fieldType === 'bool'"
                  class="flex items-center gap-2 text-sm"
                >
                  <input
                    type="checkbox"
                    :checked="fieldsDraft[f.key] === 'true' || fieldsDraft[f.key] === '1'"
                    :disabled="!canWrite"
                    @change="
                      fieldsDraft[f.key] = ($event.target as HTMLInputElement).checked
                        ? 'true'
                        : 'false'
                    "
                  />
                  Да
                </label>
                <input
                  v-else
                  v-model="fieldsDraft[f.key]"
                  :type="fieldInputType(f)"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  :readonly="!canWrite"
                />
              </div>
              <button
                v-if="canWrite"
                type="button"
                class="w-full rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
                :disabled="fieldsSaving"
                @click="saveFields"
              >
                {{ fieldsSaving ? 'Сохранение…' : 'Сохранить карточку' }}
              </button>
            </section>

            <h3 class="text-xs font-semibold uppercase tracking-wide text-muted">Комментарии</h3>
            <p v-if="!detail.comments.length" class="text-sm text-muted">Пока нет комментариев</p>
            <ul v-else class="space-y-2">
              <li
                v-for="cm in detail.comments"
                :key="cm.id"
                class="rounded-xl border border-line bg-panel px-3 py-2"
              >
                <div class="mb-1 flex items-center justify-between gap-2 text-[11px] text-muted">
                  <span class="font-medium text-ink">{{ cm.authorName || 'Менеджер' }}</span>
                  <span>{{ formatDate(cm.createdAt) }}</span>
                </div>
                <p class="whitespace-pre-wrap text-sm text-ink">{{ cm.text }}</p>
              </li>
            </ul>
          </div>

          <form
            v-if="canWrite"
            class="border-t border-line bg-panel px-4 py-3 md:px-6"
            @submit.prevent="onAddComment"
          >
            <textarea
              v-model="commentText"
              rows="2"
              class="mb-2 w-full resize-none rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
              placeholder="Комментарий по звонку…"
            />
            <div class="flex justify-end">
              <button
                type="submit"
                class="rounded-xl bg-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
                :disabled="commentBusy || !commentText.trim()"
              >
                Сохранить
              </button>
            </div>
          </form>
        </div>
      </template>
    </section>

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
            class="inline-flex items-center gap-1.5 rounded-xl bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            :disabled="createBusy"
          >
            <UserPlus class="size-4" />
            Создать
          </button>
        </div>
      </form>
    </Modal>

    <ContactSendModal
      :open="sendOpen"
      :contact-id="detail?.id || 0"
      :contact-name="detail?.name || ''"
      :phone="detail?.phone || ''"
      :channels="channels.channels"
      :loading-channels="channels.loading"
      @close="sendOpen = false"
      @sent="onSent"
    />
  </div>
</template>
