<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, MessageSquare, NotebookPen } from 'lucide-vue-next'
import {
  createNoteRequest,
  listMessagesRequest,
  type ApiMessage,
} from '@/api/chats'
import { getAppealRequest, type ApiAppealDetail } from '@/api/appeals'
import { ApiError } from '@/api/client'
import AuthMedia from '@/components/chats/AuthMedia.vue'
import ChatComposer from '@/components/chats/ChatComposer.vue'
import ContactAvatar from '@/components/chats/ContactAvatar.vue'
import MessageBody from '@/components/chats/MessageBody.vue'
import MessageTicks from '@/components/chats/MessageTicks.vue'
import VoiceMessage from '@/components/chats/VoiceMessage.vue'
import { useAuthStore } from '@/stores/auth'
import { attachmentPath, downloadAuthFile } from '@/utils/authMedia'
import {
  appealStatusLabel,
  transportBadge,
  transportBadgeClass,
  type Message,
  type MessageAttachment,
} from '@/types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const appeal = ref<ApiAppealDetail | null>(null)
const messages = ref<Message[]>([])
const loading = ref(false)
const loadingMessages = ref(false)
const loadingOlder = ref(false)
const hasMore = ref(false)
const error = ref('')
const draft = ref('')
const sending = ref(false)
const threadEl = ref<HTMLElement | null>(null)

const canWrite = computed(() => auth.can('action.write') && auth.can('section.chats'))
const appealId = computed(() => Number(route.params.appealId))

const contactSubtitle = computed(() => {
  if (!appeal.value) return ''
  if (appeal.value.contact_username) return `@${appeal.value.contact_username}`
  if (appeal.value.contact_external_id) return appeal.value.contact_external_id
  return '—'
})

function mapMessage(m: ApiMessage): Message {
  return {
    id: String(m.id),
    dialogId: String(m.dialog_id),
    direction: m.direction,
    text: m.text,
    at: m.created_at,
    status: m.status,
    operatorName: m.operator_name ?? undefined,
    editedAt: m.edited_at ?? null,
    deletedAt: m.deleted_at ?? null,
    isInternal: Boolean(m.is_internal),
    appealId: m.appeal_id ?? null,
    attachments: (m.attachments || []).map((a) => ({
      id: a.id,
      kind: a.kind,
      fileName: a.file_name,
      mimeType: a.mime_type,
      sizeBytes: a.size_bytes,
      url: a.url,
    })),
    replyTo: m.reply_to
      ? {
          id: String(m.reply_to.id),
          text: m.reply_to.text,
          direction: m.reply_to.direction,
          operatorName: m.reply_to.operator_name,
        }
      : null,
  }
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

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

function mediaSrc(att: MessageAttachment) {
  return attachmentPath(att.url)
}

function openAttachment(att: MessageAttachment) {
  void downloadAuthFile(att.url, att.fileName)
}

function dayKey(iso: string) {
  const d = new Date(iso)
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`
}

function dayLabel(iso: string) {
  const d = new Date(iso)
  const today = new Date()
  const yesterday = new Date()
  yesterday.setDate(today.getDate() - 1)
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  if (sameDay(d, today)) return 'Сегодня'
  if (sameDay(d, yesterday)) return 'Вчера'
  return d.toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: d.getFullYear() === today.getFullYear() ? undefined : 'numeric',
  })
}

type ThreadRow =
  | { type: 'day'; key: string; label: string }
  | { type: 'message'; key: string; message: Message }

const threadRows = computed((): ThreadRow[] => {
  const rows: ThreadRow[] = []
  let lastDay = ''
  const sorted = [...messages.value].sort((a, b) => {
    const ta = +new Date(a.at)
    const tb = +new Date(b.at)
    if (ta !== tb) return ta - tb
    return Number(a.id) - Number(b.id)
  })
  for (const message of sorted) {
    const key = dayKey(message.at)
    if (key !== lastDay) {
      rows.push({ type: 'day', key: `day-${key}`, label: dayLabel(message.at) })
      lastDay = key
    }
    rows.push({ type: 'message', key: message.id, message })
  }
  return rows
})

async function scrollToBottom() {
  await nextTick()
  if (threadEl.value) threadEl.value.scrollTop = threadEl.value.scrollHeight
}

async function loadAppeal() {
  if (!Number.isFinite(appealId.value) || appealId.value <= 0) {
    error.value = 'Некорректный номер обращения'
    return
  }
  loading.value = true
  error.value = ''
  try {
    appeal.value = await getAppealRequest(appealId.value)
    await loadMessages()
  } catch (e) {
    appeal.value = null
    messages.value = []
    error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить обращение'
  } finally {
    loading.value = false
  }
}

async function loadMessages() {
  if (!appeal.value) return
  loadingMessages.value = true
  try {
    const page = await listMessagesRequest(appeal.value.dialog_id, {
      limit: 50,
      appealId: appeal.value.id,
    })
    messages.value = page.items.map(mapMessage)
    hasMore.value = page.has_more
    await scrollToBottom()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить сообщения'
  } finally {
    loadingMessages.value = false
  }
}

async function loadOlder() {
  if (!appeal.value || !hasMore.value || loadingOlder.value) return
  const oldest = messages.value[0]
  if (!oldest) return
  loadingOlder.value = true
  try {
    const page = await listMessagesRequest(appeal.value.dialog_id, {
      limit: 50,
      beforeId: Number(oldest.id),
      appealId: appeal.value.id,
    })
    const existing = new Set(messages.value.map((m) => m.id))
    const older = page.items.map(mapMessage).filter((m) => !existing.has(m.id))
    messages.value = [...older, ...messages.value]
    hasMore.value = page.has_more
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить историю'
  } finally {
    loadingOlder.value = false
  }
}

async function sendNote() {
  if (!appeal.value || !canWrite.value || sending.value) return
  const text = draft.value.trim()
  if (!text) return
  sending.value = true
  error.value = ''
  try {
    const msg = await createNoteRequest(appeal.value.dialog_id, text, appeal.value.id)
    const mapped = mapMessage(msg)
    if (!messages.value.some((m) => m.id === mapped.id)) {
      messages.value.push(mapped)
    }
    draft.value = ''
    await scrollToBottom()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить заметку'
  } finally {
    sending.value = false
  }
}

function openInChats() {
  if (!appeal.value?.can_open_in_chats) return
  void router.push({ name: 'chats', query: { dialog: String(appeal.value.dialog_id) } })
}

function goBack() {
  void router.push({ name: 'appeals' })
}

watch(appealId, () => {
  void loadAppeal()
})

onMounted(() => {
  void loadAppeal()
})

onUnmounted(() => {
  appeal.value = null
  messages.value = []
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <header class="flex items-center gap-3 border-b border-line bg-panel px-5 py-3">
      <button
        type="button"
        class="flex size-9 shrink-0 items-center justify-center rounded-lg border border-line text-muted transition hover:border-brand/40 hover:bg-brand-soft hover:text-brand"
        title="К списку обращений"
        @click="goBack"
      >
        <ArrowLeft class="size-4" />
      </button>

      <template v-if="appeal">
        <ContactAvatar :name="appeal.contact_name" :url="appeal.contact_avatar_url" size="md" />
        <div class="min-w-0 flex-1">
          <div class="flex min-w-0 flex-wrap items-center gap-2">
            <div class="truncate text-sm font-semibold">{{ appeal.contact_name }}</div>
            <span
              v-if="appeal.transport"
              class="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide"
              :class="transportBadgeClass[appeal.transport]"
            >
              {{ transportBadge[appeal.transport] }}
            </span>
            <span
              class="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold"
              :class="
                appeal.status === 'open' ? 'bg-ok/15 text-ok' : 'bg-muted/15 text-muted'
              "
            >
              #{{ appeal.number }} · {{ appealStatusLabel[appeal.status] }}
            </span>
          </div>
          <div class="truncate text-xs text-muted">
            {{ contactSubtitle }}
            <span v-if="appeal.channel_name"> · {{ appeal.channel_name }}</span>
          </div>
        </div>

        <button
          v-if="appeal.can_open_in_chats"
          type="button"
          class="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-xl bg-brand px-3 text-xs font-semibold text-white transition hover:opacity-90"
          @click="openInChats"
        >
          <MessageSquare class="size-3.5" />
          Открыть в Чатах
        </button>
      </template>
      <div v-else class="min-w-0 flex-1 text-sm font-semibold">Обращение</div>
    </header>

    <p v-if="error" class="border-b border-line bg-panel px-5 py-2 text-xs text-danger">
      {{ error }}
    </p>

    <div
      v-if="appeal"
      class="flex flex-wrap gap-x-4 gap-y-1 border-b border-line bg-surface px-5 py-2 text-[11px] text-muted"
    >
      <span>Открыто: {{ formatDate(appeal.opened_at) }}</span>
      <span v-if="appeal.closed_at">Закрыто: {{ formatDate(appeal.closed_at) }}</span>
      <span v-if="appeal.closed_by_name">Закрыл: {{ appeal.closed_by_name }}</span>
      <span>Оператор: {{ appeal.assignee_name || 'Не назначен' }}</span>
    </div>

    <div class="relative min-h-0 flex-1 bg-surface">
      <div ref="threadEl" class="h-full space-y-3 overflow-auto px-5 py-4">
        <p v-if="loading" class="text-center text-sm text-muted">Загрузка…</p>
        <template v-else>
          <div v-if="hasMore" class="flex justify-center py-1">
            <button
              type="button"
              class="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-muted transition hover:border-brand/40 hover:bg-brand-soft hover:text-brand disabled:opacity-50"
              :disabled="loadingOlder"
              @click="loadOlder"
            >
              {{ loadingOlder ? 'Загрузка…' : 'Загрузить раньше' }}
            </button>
          </div>
          <p v-if="loadingMessages" class="text-center text-sm text-muted">Загрузка сообщений…</p>
          <p
            v-else-if="!messages.length"
            class="text-center text-sm text-muted"
          >
            В этом обращении пока нет сообщений
          </p>
          <template v-for="row in threadRows" :key="row.key">
            <div v-if="row.type === 'day'" class="flex items-center justify-center py-2">
              <span class="rounded-full bg-panel px-3 py-1 text-[11px] font-semibold text-muted">
                {{ row.label }}
              </span>
            </div>
            <div
              v-else
              class="flex items-end gap-2"
              :class="
                row.message.direction === 'out' || row.message.isInternal
                  ? 'justify-end'
                  : 'justify-start'
              "
            >
              <ContactAvatar
                v-if="row.message.direction === 'in' && !row.message.isInternal"
                :name="appeal?.contact_name"
                :url="appeal?.contact_avatar_url"
                size="sm"
              />
              <div
                class="max-w-[min(70%,420px)] min-w-0 rounded-2xl px-3.5 py-2.5 text-sm shadow-sm"
                :class="
                  row.message.isInternal
                    ? 'rounded-br-md border border-dashed border-bubble-note-border bg-bubble-note text-bubble-note-ink'
                    : row.message.direction === 'out'
                      ? 'rounded-br-md bg-bubble-out text-white'
                      : 'rounded-bl-md border border-line bg-panel text-ink'
                "
              >
                <template v-if="row.message.deletedAt">
                  <p class="italic opacity-70">Сообщение удалено</p>
                </template>
                <template v-else>
                  <div
                    v-if="row.message.isInternal"
                    class="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-bubble-note-ink/70"
                  >
                    <NotebookPen class="size-3" />
                    Заметка
                    <span
                      v-if="row.message.operatorName"
                      class="font-medium normal-case tracking-normal"
                    >
                      · {{ row.message.operatorName }}
                    </span>
                  </div>
                  <div v-if="row.message.attachments?.length" class="mb-2 space-y-2">
                    <template v-for="att in row.message.attachments" :key="att.id">
                      <button
                        v-if="att.kind === 'image'"
                        type="button"
                        class="block w-full overflow-hidden rounded-xl text-left"
                        @click="openAttachment(att)"
                      >
                        <AuthMedia :path="mediaSrc(att)" :alt="att.fileName" kind="image" />
                      </button>
                      <AuthMedia
                        v-else-if="att.kind === 'video'"
                        :path="mediaSrc(att)"
                        kind="video"
                      />
                      <VoiceMessage
                        v-else-if="att.kind === 'audio'"
                        :src="mediaSrc(att)"
                        :outgoing="row.message.direction === 'out' && !row.message.isInternal"
                        :file-name="att.fileName"
                      />
                      <button
                        v-else
                        type="button"
                        class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs font-medium underline-offset-2 hover:underline"
                        :class="
                          row.message.direction === 'out' && !row.message.isInternal
                            ? 'bg-white/15'
                            : 'bg-surface'
                        "
                        @click="openAttachment(att)"
                      >
                        📎 {{ att.fileName }}
                      </button>
                    </template>
                  </div>
                  <MessageBody
                    v-if="row.message.text"
                    :text="row.message.text"
                    :outgoing="row.message.direction === 'out' && !row.message.isInternal"
                  />
                  <div
                    class="mt-1.5 flex items-center justify-end gap-1.5 text-[10px]"
                    :class="
                      row.message.isInternal
                        ? 'text-bubble-note-ink/60'
                        : row.message.direction === 'out'
                          ? 'text-white/70'
                          : 'text-muted'
                    "
                  >
                    <span v-if="row.message.editedAt" class="opacity-80">изм.</span>
                    <span>{{ formatTime(row.message.at) }}</span>
                    <MessageTicks
                      v-if="row.message.direction === 'out' && !row.message.isInternal"
                      :status="row.message.status"
                      tone="onBrand"
                    />
                  </div>
                </template>
              </div>
            </div>
          </template>
        </template>
      </div>
    </div>

    <div
      v-if="appeal && !appeal.can_open_in_chats"
      class="border-t border-line bg-panel px-5 py-2 text-center text-[11px] text-muted"
    >
      Текущее обращение диалога закрыто — ответить в мессенджер нельзя, пока клиент не напишет снова.
      Здесь можно оставлять внутренние заметки.
    </div>

    <ChatComposer
      v-if="appeal && canWrite"
      v-model="draft"
      notes-only
      :note-mode="true"
      :files="[]"
      :sending="sending"
      :templates="[]"
      @update:note-mode="() => {}"
      @add-files="() => {}"
      @remove-file="() => {}"
      @apply-template="() => {}"
      @clear-reply="() => {}"
      @send="sendNote"
    />
    <div
      v-else-if="appeal"
      class="border-t border-line bg-panel px-5 py-3 text-center text-xs text-muted"
    >
      Режим просмотра — заметки недоступны
    </div>
  </div>
</template>
