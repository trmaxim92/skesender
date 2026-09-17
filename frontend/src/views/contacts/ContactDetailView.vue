<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Phone, MessageSquare, Hand } from 'lucide-vue-next'
import {
  addContactCommentRequest,
  claimContactRequest,
  claimNextContactRequest,
  getContactRequest,
  setContactAppealStatusRequest,
  telHref,
  updateContactFieldsRequest,
  type Contact,
} from '@/api/contacts'
import { ApiError } from '@/api/client'
import ContactSendModal from '@/views/contacts/ContactSendModal.vue'
import { useAuthStore } from '@/stores/auth'
import { useChannelsStore } from '@/stores/channels'
import type { FieldDefinition } from '@/types'

const auth = useAuthStore()
const channels = useChannelsStore()
const route = useRoute()
const router = useRouter()

const canWrite = computed(() => auth.can('section.contacts') && auth.can('action.write'))

const detail = ref<Contact | null>(null)
const loading = ref(false)
const error = ref('')
const fieldsDraft = ref<Record<string, string>>({})
const appealDraft = ref<Record<string, string>>({})
const fieldsSaving = ref(false)
const commentText = ref('')
const commentBusy = ref(false)
const claimBusy = ref(false)
const statusBusy = ref(false)
const nextBusy = ref(false)
const sendOpen = ref(false)

const contactId = computed(() => Number(route.params.contactId))

const canClaim = computed(() => {
  if (!detail.value || !canWrite.value) return false
  return detail.value.assigneeId == null || detail.value.assigneeId === auth.user?.id
})

const isMineOrFree = computed(() => {
  if (!detail.value) return false
  return detail.value.assigneeId == null || detail.value.assigneeId === auth.user?.id
})

const currentStatusId = computed(() => detail.value?.currentAppeal?.statusId ?? null)

type TimelineItem = {
  kind: 'comment'
  id: string
  at: string
  text: string
  author: string | null
}

const timeline = computed((): TimelineItem[] => {
  if (!detail.value) return []
  return detail.value.comments
    .map((cm) => ({
      kind: 'comment' as const,
      id: `c-${cm.id}`,
      at: cm.createdAt,
      text: cm.text,
      author: cm.authorName,
    }))
    .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
})

async function load() {
  if (!Number.isFinite(contactId.value) || contactId.value <= 0) {
    error.value = 'Контакт не найден'
    return
  }
  loading.value = true
  error.value = ''
  try {
    detail.value = await getContactRequest(contactId.value)
    fieldsDraft.value = { ...detail.value.clientValues }
    appealDraft.value = { ...detail.value.appealValues }
  } catch (e) {
    detail.value = null
    error.value = e instanceof ApiError ? e.detail : 'Не удалось открыть контакт'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})

watch(
  () => route.params.contactId,
  () => {
    void load()
  },
)

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
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

const isTerminalStage = computed(() => {
  const st = detail.value?.currentAppeal?.statusDef
  return Boolean(st?.isTerminal || (st && !st.countsAsOpen))
})

function goBack() {
  void router.push({ name: 'contacts' })
}

async function saveFields() {
  if (!detail.value || !canWrite.value || fieldsSaving.value) return
  fieldsSaving.value = true
  error.value = ''
  try {
    const values = Object.entries(fieldsDraft.value)
      .filter(([key]) => !['full_name', 'phone', 'external_id'].includes(key))
      .map(([key, value]) => ({ key, value }))
    const appeal_values = Object.entries(appealDraft.value).map(([key, value]) => ({
      key,
      value,
    }))
    detail.value = await updateContactFieldsRequest(detail.value.id, {
      full_name: fieldsDraft.value.full_name ?? '',
      phone: fieldsDraft.value.phone ?? '',
      external_id: fieldsDraft.value.external_id ?? '',
      values,
      appeal_values,
    })
    fieldsDraft.value = { ...detail.value.clientValues }
    appealDraft.value = { ...detail.value.appealValues }
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить поля'
  } finally {
    fieldsSaving.value = false
  }
}

async function onClaim() {
  if (!detail.value || claimBusy.value || !canWrite.value) return
  claimBusy.value = true
  error.value = ''
  try {
    detail.value = await claimContactRequest(detail.value.id)
    fieldsDraft.value = { ...detail.value.clientValues }
    appealDraft.value = { ...detail.value.appealValues }
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось взять в работу'
  } finally {
    claimBusy.value = false
  }
}

async function onAppealStatus(statusId: number) {
  if (!detail.value || !canWrite.value || statusBusy.value) return
  if (currentStatusId.value === statusId) return
  statusBusy.value = true
  error.value = ''
  try {
    detail.value = await setContactAppealStatusRequest(detail.value.id, statusId)
    fieldsDraft.value = { ...detail.value.clientValues }
    appealDraft.value = { ...detail.value.appealValues }
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось сменить статус'
  } finally {
    statusBusy.value = false
  }
}

async function onAddComment() {
  if (!detail.value || !canWrite.value || commentBusy.value) return
  const text = commentText.value.trim()
  if (!text) return
  commentBusy.value = true
  error.value = ''
  try {
    const c = await addContactCommentRequest(detail.value.id, text)
    detail.value = {
      ...detail.value,
      comments: [...detail.value.comments, c],
    }
    commentText.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить комментарий'
  } finally {
    commentBusy.value = false
  }
}

async function markDone() {
  if (!detail.value || !canWrite.value || statusBusy.value) return
  const terminal = detail.value.appealStatuses.find((s) => s.isTerminal || !s.countsAsOpen)
  if (!terminal) {
    error.value = 'Нет завершающего этапа — добавьте в «Клиенты → Этапы обзвона»'
    return
  }
  await onAppealStatus(terminal.id)
}

async function onNext() {
  if (!canWrite.value || nextBusy.value) return
  nextBusy.value = true
  error.value = ''
  try {
    const c = await claimNextContactRequest()
    await router.push({ name: 'contact-detail', params: { contactId: String(c.id) } })
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Нет свободных контактов'
  } finally {
    nextBusy.value = false
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
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-surface md:flex-row">
    <!-- Left: client + appeal card (same light palette as the rest) -->
    <aside
      class="flex w-full shrink-0 flex-col border-b border-line bg-panel md:h-full md:w-[360px] md:border-b-0 md:border-r"
    >
      <div class="flex items-center gap-2 border-b border-line px-4 py-3">
        <button
          type="button"
          class="rounded-lg p-1.5 text-muted hover:bg-surface hover:text-ink"
          title="К списку"
          @click="goBack"
        >
          <ArrowLeft class="size-4" />
        </button>
        <div class="min-w-0 flex-1">
          <div class="truncate text-sm font-semibold text-ink">
            {{ detail?.name || (loading ? '…' : 'Контакт') }}
          </div>
          <div class="text-[11px] text-muted">#{{ contactId }}</div>
        </div>
      </div>

      <div class="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
        <p v-if="loading" class="text-sm text-muted">Загрузка…</p>
        <p v-else-if="error && !detail" class="text-sm text-red-600">{{ error }}</p>
        <template v-else-if="detail">
          <div class="flex flex-wrap items-center gap-2">
            <span
              v-if="(fieldsDraft.fleet_role || '').trim()"
              class="inline-flex items-center rounded-full bg-brand-soft px-2 py-0.5 text-[11px] font-semibold text-brand"
            >
              {{ fieldsDraft.fleet_role }}
            </span>
            <span
              v-if="detail.currentAppeal?.statusDef"
              class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold"
              :style="{
                background: detail.currentAppeal.statusDef.color + '22',
                color: detail.currentAppeal.statusDef.color,
              }"
            >
              <span
                class="size-1.5 rounded-full"
                :style="{ background: detail.currentAppeal.statusDef.color }"
              />
              {{ detail.currentAppeal.statusDef.name }}
            </span>
            <span v-if="detail.assigneeName" class="text-[11px] text-muted">
              {{ detail.assigneeName }}
            </span>
            <span v-else class="text-[11px] text-muted">Свободный</span>
          </div>

          <section class="space-y-3">
            <h3 class="text-xs font-semibold uppercase tracking-wide text-muted">
              Карточка клиента
            </h3>
            <div v-for="f in detail.clientFields" :key="'c-' + f.key" class="space-y-1">
              <label class="text-[11px] font-semibold uppercase tracking-wide text-muted">
                {{ f.label }}
                <span v-if="f.required" class="text-danger">*</span>
              </label>
              <textarea
                v-if="f.fieldType === 'textarea'"
                v-model="fieldsDraft[f.key]"
                rows="3"
                class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none ring-brand focus:ring-2"
                :readonly="!canWrite"
              />
              <select
                v-else-if="f.fieldType === 'select'"
                v-model="fieldsDraft[f.key]"
                class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none ring-brand focus:ring-2"
                :disabled="!canWrite"
              >
                <option value="">—</option>
                <option v-for="opt in f.options" :key="opt" :value="opt">{{ opt }}</option>
              </select>
              <div v-else-if="f.fieldType === 'link'" class="space-y-1">
                <input
                  v-model="fieldsDraft[f.key]"
                  type="url"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none ring-brand focus:ring-2"
                  :readonly="!canWrite"
                />
                <a
                  v-if="fieldsDraft[f.key]?.trim()"
                  :href="linkHref(fieldsDraft[f.key])"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-xs text-brand hover:underline"
                >
                  Открыть
                </a>
              </div>
              <label
                v-else-if="f.fieldType === 'bool'"
                class="flex items-center gap-2 text-sm text-ink"
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
                class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none ring-brand focus:ring-2"
                :readonly="!canWrite || f.key === 'external_id' || f.key.startsWith('fleet_')"
              />
            </div>
          </section>

          <section class="space-y-3 border-t border-line pt-4">
            <h3 class="text-xs font-semibold uppercase tracking-wide text-muted">
              Поля обращения
            </h3>
            <p v-if="!detail.appealFields.length" class="text-xs text-muted">
              Нет полей обращения для отдела. Добавьте их в настройках.
            </p>
            <div v-for="f in detail.appealFields" :key="'a-' + f.key" class="space-y-1">
              <label class="text-[11px] font-semibold uppercase tracking-wide text-muted">
                {{ f.label }}
                <span v-if="f.required" class="text-danger">*</span>
              </label>
              <textarea
                v-if="f.fieldType === 'textarea'"
                v-model="appealDraft[f.key]"
                rows="3"
                class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none ring-brand focus:ring-2"
                :readonly="!canWrite"
              />
              <select
                v-else-if="f.fieldType === 'select'"
                v-model="appealDraft[f.key]"
                class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none ring-brand focus:ring-2"
                :disabled="!canWrite"
              >
                <option value="">—</option>
                <option v-for="opt in f.options" :key="opt" :value="opt">{{ opt }}</option>
              </select>
              <div v-else-if="f.fieldType === 'link'" class="space-y-1">
                <input
                  v-model="appealDraft[f.key]"
                  type="url"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none ring-brand focus:ring-2"
                  :readonly="!canWrite"
                />
              </div>
              <label
                v-else-if="f.fieldType === 'bool'"
                class="flex items-center gap-2 text-sm text-ink"
              >
                <input
                  type="checkbox"
                  :checked="appealDraft[f.key] === 'true' || appealDraft[f.key] === '1'"
                  :disabled="!canWrite"
                  @change="
                    appealDraft[f.key] = ($event.target as HTMLInputElement).checked
                      ? 'true'
                      : 'false'
                  "
                />
                Да
              </label>
              <input
                v-else
                v-model="appealDraft[f.key]"
                :type="fieldInputType(f)"
                class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none ring-brand focus:ring-2"
                :readonly="!canWrite"
              />
            </div>
          </section>

          <button
            v-if="canWrite"
            type="button"
            class="w-full rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
            :disabled="fieldsSaving"
            @click="saveFields"
          >
            {{ fieldsSaving ? 'Сохранение…' : 'Сохранить карточку' }}
          </button>
          <p v-if="error && detail" class="text-sm text-red-600 md:hidden">{{ error }}</p>
        </template>
      </div>
    </aside>

    <!-- Right: activity -->
    <section class="flex min-w-0 flex-1 flex-col bg-surface">
      <header class="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-panel px-4 py-3 md:px-6">
        <div class="text-sm font-semibold text-ink">История</div>
        <div class="flex flex-wrap gap-2">
          <a
            v-if="detail"
            :href="telHref(detail.phone)"
            class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:opacity-90"
            title="Откроет SIP / телефонное приложение"
          >
            <Phone class="size-4" />
            Связаться
          </a>
          <button
            v-if="canClaim && detail?.assigneeId == null"
            type="button"
            class="inline-flex items-center gap-1.5 rounded-xl bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            :disabled="claimBusy"
            @click="onClaim"
          >
            <Hand class="size-4" />
            Взять
          </button>
          <button
            v-if="canWrite && isMineOrFree"
            type="button"
            class="inline-flex items-center gap-1.5 rounded-xl border border-line px-3 py-2 text-sm text-ink hover:bg-surface"
            @click="openSend"
          >
            <MessageSquare class="size-4" />
            Мессенджер
          </button>
          <button
            v-if="canWrite"
            type="button"
            class="rounded-xl border border-line px-3 py-2 text-sm text-muted hover:bg-surface disabled:opacity-50"
            :disabled="nextBusy"
            @click="onNext"
          >
            Следующий
          </button>
          <button
            v-if="canWrite && detail && !isTerminalStage && isMineOrFree"
            type="button"
            class="rounded-xl border border-line px-3 py-2 text-sm text-muted hover:bg-surface disabled:opacity-50"
            :disabled="statusBusy"
            @click="markDone"
          >
            Завершить
          </button>
        </div>
      </header>

      <p v-if="error && detail" class="border-b border-line px-4 py-2 text-sm text-red-600 md:px-6">
        {{ error }}
      </p>

      <!-- Appeal status panel -->
      <div
        v-if="detail && canWrite && isMineOrFree"
        class="border-b border-line bg-panel px-4 py-4 md:px-6"
      >
        <div class="rounded-2xl border border-line bg-surface/80 p-4">
          <div class="mb-3 flex flex-wrap items-center gap-2 text-sm">
            <span class="font-semibold text-ink">
              Обращение
              <template v-if="detail.currentAppeal">#{{ detail.currentAppeal.number }}</template>
            </span>
            <span
              v-if="detail.currentAppeal?.statusDef"
              class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium"
              :style="{
                background: detail.currentAppeal.statusDef.color + '22',
                color: detail.currentAppeal.statusDef.color,
              }"
            >
              <span
                class="size-1.5 rounded-full"
                :style="{ background: detail.currentAppeal.statusDef.color }"
              />
              {{ detail.currentAppeal.statusDef.name }}
            </span>
            <a :href="telHref(detail.phone)" class="ml-auto font-medium text-brand hover:underline">
              {{ detail.phone }}
            </a>
          </div>
          <p class="mb-2 text-xs text-muted">Этап обзвона</p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="st in detail.appealStatuses"
              :key="st.id"
              type="button"
              class="rounded-full border px-3.5 py-1.5 text-xs font-medium transition disabled:opacity-50"
              :class="
                currentStatusId === st.id
                  ? 'border-transparent text-white'
                  : 'border-line bg-panel text-ink hover:border-brand/40 hover:bg-brand-soft/50'
              "
              :style="currentStatusId === st.id ? { background: st.color } : undefined"
              :disabled="statusBusy"
              @click="onAppealStatus(st.id)"
            >
              {{ st.name }}
            </button>
          </div>
          <p v-if="!detail.appealStatuses.length" class="text-xs text-muted">
            Этапы ещё не настроены. Добавьте в «Клиенты → Этапы обзвона».
          </p>
        </div>
      </div>

      <!-- Timeline -->
      <div class="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4 md:px-6">
        <p v-if="loading" class="text-sm text-muted">Загрузка…</p>
        <p v-else-if="!timeline.length" class="text-sm text-muted">Пока нет примечаний</p>
        <ul v-else class="space-y-3">
          <li
            v-for="item in timeline"
            :key="item.id"
            class="rounded-xl border border-line bg-panel px-3 py-2.5"
          >
            <div class="mb-1 flex items-center justify-between gap-2 text-[11px] text-muted">
              <span class="font-medium text-ink">Примечание</span>
              <span>{{ formatDate(item.at) }}</span>
            </div>
            <p class="whitespace-pre-wrap text-sm text-ink">
              {{ item.text }}
            </p>
            <p class="mt-1 text-[11px] text-muted">{{ item.author || 'Менеджер' }}</p>
          </li>
        </ul>
      </div>

      <!-- Note composer -->
      <form
        v-if="canWrite && detail"
        class="border-t border-line bg-panel px-4 py-3 md:px-6"
        @submit.prevent="onAddComment"
      >
        <label class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
          Примечание
        </label>
        <textarea
          v-model="commentText"
          rows="2"
          class="mb-2 w-full resize-none rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
          placeholder="Введите текст"
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
    </section>

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
