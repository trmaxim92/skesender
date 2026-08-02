<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, ArrowRightLeft, CircleCheckBig, Hand, NotebookPen, PanelRight, Pencil, Plus, Reply, Search, Trash2 } from 'lucide-vue-next'
import AppealHistoryBar from '@/components/chats/AppealHistoryBar.vue'
import AuthMedia from '@/components/chats/AuthMedia.vue'
import ChatComposer from '@/components/chats/ChatComposer.vue'
import ChatSidePanel from '@/components/chats/ChatSidePanel.vue'
import CloseAppealModal from '@/components/chats/CloseAppealModal.vue'
import ContactAvatar from '@/components/chats/ContactAvatar.vue'
import MessageTicks from '@/components/chats/MessageTicks.vue'
import MessageBody from '@/components/chats/MessageBody.vue'
import TransferChatModal from '@/components/chats/TransferChatModal.vue'
import VoiceMessage from '@/components/chats/VoiceMessage.vue'
import CreateAppealModal from '@/components/appeals/CreateAppealModal.vue'
import { useAuthStore } from '@/stores/auth'
import { useChannelsStore } from '@/stores/channels'
import { useChatsStore } from '@/stores/chats'
import { useMyTemplatesStore } from '@/stores/myTemplates'
import { useTemplatesStore } from '@/stores/templates'
import { attachmentPath, downloadAuthFile } from '@/utils/authMedia'
import {
  appealStatusLabel,
  transportBadge,
  transportBadgeClass,
  typingLabel,
  type Message,
  type MessageAttachment,
  type TemplateGroup,
} from '@/types'

const chats = useChatsStore()
const channels = useChannelsStore()
const templates = useTemplatesStore()
const myTemplates = useMyTemplatesStore()
const auth = useAuthStore()

const composerTemplateGroups = computed((): TemplateGroup[] => {
  return [...myTemplates.forTransportGrouped(chats.activeDialog?.transport)]
})

const composerTemplates = computed(() => [
  ...myTemplates.forTransport(chats.activeDialog?.transport),
])

const canWrite = computed(() => auth.can('action.write'))
const canCreateOutbound = computed(() => canWrite.value && auth.can('section.appeals'))

const createOpen = ref(false)

const route = useRoute()
const router = useRouter()
const threadEl = ref<HTMLElement | null>(null)
const editingId = ref<string | null>(null)
const editDraft = ref('')
const actionBusy = ref(false)
const transferOpen = ref(false)
const transferBusy = ref(false)
const transferNotice = ref('')
const closeOpen = ref(false)
const stickToBottom = ref(true)
const pendingBelow = ref(0)
let pollTimer: number | undefined
let noticeTimer: number | undefined
let syncingUrl = false

const assigneeLabel = computed(() => {
  const id = chats.activeDialog?.assigneeId
  if (!id) return 'Не назначен'
  if (id === auth.user?.id) return 'Вы'
  return chats.operators.find((u) => u.id === id)?.name || `ID ${id}`
})

const canClaim = computed(
  () =>
    canWrite.value &&
    !!chats.activeDialog &&
    chats.canCompose &&
    !chats.activeDialog.assigneeId,
)

const headerAppealNumber = computed(
  () => chats.viewingAppeal?.number ?? chats.activeDialog?.appealNumber ?? null,
)
const headerAppealStatus = computed(
  () => chats.viewingAppeal?.status ?? chats.activeDialog?.appealStatus ?? null,
)

const claimBusy = ref(false)
const searchInput = ref('')
let searchTimer: number | undefined

const emptyHint = computed(() => {
  if (chats.searchQuery.trim()) return 'Ничего не найдено по запросу.'
  if (chats.channelFilterId != null) return 'В этом канале нет диалогов по текущему фильтру.'
  if (chats.filter === 'new') return 'Новых обращений нет — хороший знак.'
  if (chats.filter === 'mine') return 'Пока нет ваших чатов. Заберите из «Новые».'
  return 'Чужих чатов в этой вкладке нет.'
})

const emptyHintAction = computed(() => {
  if (chats.searchQuery.trim()) return null
  if (!canCreateOutbound.value) return null
  return { action: 'create' as const, label: 'Создать исходящее' }
})

async function openCreateOutbound() {
  createOpen.value = true
  if (!channels.channels.length) {
    void channels.fetchChannels()
  }
}

async function onOutboundCreated(dialogId: number) {
  createOpen.value = false
  await chats.openDialogById(String(dialogId))
  await router.replace({ name: 'chats', query: { ...route.query, dialog: String(dialogId) } })
}

function onChannelFilterChange(ev: Event) {
  const raw = (ev.target as HTMLSelectElement).value
  const id = raw === '' ? null : Number(raw)
  void chats.setChannelFilter(Number.isFinite(id as number) ? id : null)
}

const closePreview = computed(() => {
  const dialog = chats.activeDialog
  if (!dialog) return ''
  const tpl = templates.closeTemplateFor(dialog.transport)
  if (!tpl) return ''
  return tpl.body
    .replaceAll('{{operator}}', auth.user?.name || 'Оператор')
    .replaceAll('{{contact}}', dialog.contactName || 'Клиент')
    .replaceAll('{{appeal}}', dialog.appealNumber != null ? String(dialog.appealNumber) : '')
    .trim()
})

type ThreadRow =
  | { type: 'day'; key: string; label: string }
  | { type: 'message'; key: string; message: Message }

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

const threadRows = computed((): ThreadRow[] => {
  const rows: ThreadRow[] = []
  let lastDay = ''
  for (const message of chats.activeMessages) {
    const key = dayKey(message.at)
    if (key !== lastDay) {
      rows.push({ type: 'day', key: `day-${key}`, label: dayLabel(message.at) })
      lastDay = key
    }
    rows.push({ type: 'message', key: message.id, message })
  }
  return rows
})

function onSearchInput() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    void chats.setSearchQuery(searchInput.value)
  }, 250)
}

function onDialogsScroll(event: Event) {
  const el = event.target as HTMLElement
  if (el.scrollHeight - el.scrollTop - el.clientHeight > 120) return
  void chats.loadMoreDialogs()
}

async function claimDialog() {
  if (!chats.activeDialog || !auth.user || claimBusy.value) return
  claimBusy.value = true
  const dialogId = chats.activeDialog.id
  const ok = await chats.assignOperator(dialogId, auth.user.id)
  claimBusy.value = false
  if (!ok) return
  await chats.setFilter('mine', { keepActive: true })
  chats.activeDialogId = dialogId
  transferNotice.value = 'Чат забран — вы ответственный'
  if (noticeTimer) window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => {
    transferNotice.value = ''
  }, 3500)
}

async function confirmTransfer(assigneeId: number | null) {
  if (!chats.activeDialog) return
  transferBusy.value = true
  const dialogId = chats.activeDialog.id
  const name =
    assigneeId == null
      ? 'Новые'
      : assigneeId === auth.user?.id
        ? 'себе'
        : chats.operators.find((u) => u.id === assigneeId)?.name || 'менеджеру'
  const ok = await chats.assignOperator(dialogId, assigneeId)
  transferBusy.value = false
  if (!ok) return
  transferOpen.value = false
  const nextFilter =
    assigneeId == null ? 'new' : assigneeId === auth.user?.id ? 'mine' : 'others'
  await chats.setFilter(nextFilter, { keepActive: true })
  chats.activeDialogId = dialogId
  transferNotice.value =
    assigneeId == null ? 'Чат возвращён в «Новые»' : `Чат передан: ${name}`
  if (noticeTimer) window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => {
    transferNotice.value = ''
  }, 3500)
}

async function confirmCloseAppeal(withReply: boolean) {
  const ok = await chats.closeAppeal(withReply)
  if (ok) closeOpen.value = false
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

function mediaSrc(att: MessageAttachment) {
  return attachmentPath(att.url)
}

function openAttachment(att: MessageAttachment) {
  void downloadAuthFile(att.url, att.fileName)
}

function isEmojiOnlyPreview(text: string) {
  return /^[📷🎬🎵📎]/.test(text)
}

function replyQuoteAuthor(preview: NonNullable<Message['replyTo']>) {
  if (preview.direction === 'out') return preview.operatorName || 'Вы'
  return chats.activeDialog?.contactName || 'Клиент'
}

function initials(name: string | undefined | null) {
  const parts = (name || '?').trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

function avatarLabel(m: Message) {
  if (m.direction === 'out') return m.operatorName || 'Оператор'
  return chats.activeDialog?.contactName || 'Клиент'
}

function startEdit(m: Message) {
  editingId.value = m.id
  editDraft.value = m.text
}

function cancelEdit() {
  editingId.value = null
  editDraft.value = ''
}

async function saveEdit() {
  if (!editingId.value || !editDraft.value.trim() || actionBusy.value) return
  actionBusy.value = true
  const ok = await chats.editMessage(editingId.value, editDraft.value)
  actionBusy.value = false
  if (ok) cancelEdit()
}

async function confirmDelete(m: Message) {
  if (actionBusy.value) return
  const ok = m.isInternal
    ? window.confirm('Удалить внутреннюю заметку?')
    : window.confirm('Удалить сообщение у клиента и в кабинете?')
  if (!ok) return
  actionBusy.value = true
  await chats.removeMessage(m.id)
  actionBusy.value = false
  if (editingId.value === m.id) cancelEdit()
}

function onThreadScroll() {
  const el = threadEl.value
  if (!el) return
  const dist = el.scrollHeight - el.scrollTop - el.clientHeight
  stickToBottom.value = dist < 80
  if (stickToBottom.value) pendingBelow.value = 0
}

async function scrollThreadToBottom() {
  await nextTick()
  if (threadEl.value) {
    threadEl.value.scrollTop = threadEl.value.scrollHeight
    pendingBelow.value = 0
    stickToBottom.value = true
  }
}

async function selectDialog(id: string) {
  await chats.selectDialog(id)
  syncingUrl = true
  await router.replace({ name: 'chats', query: { ...route.query, dialog: id } })
  syncingUrl = false
  stickToBottom.value = true
  pendingBelow.value = 0
  await scrollThreadToBottom()
}

watch(
  () => chats.activeMessages.map((m) => m.id).join(','),
  async (ids, prev) => {
    if (!ids || ids === prev) return
    if (stickToBottom.value) {
      await scrollThreadToBottom()
    } else if (prev) {
      const prevCount = prev.split(',').filter(Boolean).length
      const nextCount = ids.split(',').filter(Boolean).length
      if (nextCount > prevCount) pendingBelow.value += nextCount - prevCount
    }
  },
)

watch(
  () => chats.activeDialogId,
  () => cancelEdit(),
)

onMounted(async () => {
  await Promise.all([
    chats.fetchOperators(),
    templates.fetchCloseTemplate(),
    myTemplates.fetchAll(),
    chats.fetchUnreadSummary(),
    channels.fetchChannels(),
  ])
  const dialogId = typeof route.query.dialog === 'string' ? route.query.dialog : null
  if (dialogId) {
    await chats.openDialogById(dialogId)
  } else {
    await chats.fetchDialogs()
    if (chats.activeDialogId) {
      syncingUrl = true
      await router.replace({
        name: 'chats',
        query: { ...route.query, dialog: chats.activeDialogId },
      })
      syncingUrl = false
    }
  }
  stickToBottom.value = true
  await scrollThreadToBottom()
  pollTimer = window.setInterval(() => {
    if (chats.wsStatus !== 'open') {
      void chats.fetchDialogs({ reloadMessages: true })
    } else {
      void chats.fetchDialogs({ reloadMessages: false })
    }
    void chats.fetchUnreadSummary()
  }, 30000)
})

watch(
  () => route.query.dialog,
  async (dialogId) => {
    if (syncingUrl) return
    if (typeof dialogId === 'string' && dialogId && dialogId !== chats.activeDialogId) {
      await chats.openDialogById(dialogId)
      stickToBottom.value = true
      pendingBelow.value = 0
      await scrollThreadToBottom()
    }
  },
)

watch(
  () => chats.activeDialogId,
  async (id) => {
    if (!id || syncingUrl) return
    if (route.query.dialog === id) return
    syncingUrl = true
    await router.replace({ name: 'chats', query: { ...route.query, dialog: id } })
    syncingUrl = false
  },
)

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  if (noticeTimer) window.clearTimeout(noticeTimer)
  if (searchTimer) window.clearTimeout(searchTimer)
})
</script>

<template>
  <div class="flex h-full min-h-0">
    <aside class="flex w-80 shrink-0 flex-col border-r border-line bg-panel">
      <div class="flex items-center gap-1 border-b border-line p-3">
        <button
          v-for="f in [
            { id: 'new', label: 'Новые' },
            { id: 'mine', label: 'Мои' },
            { id: 'others', label: 'Чужие' },
          ] as const"
          :key="f.id"
          type="button"
          class="relative flex flex-1 items-center justify-center gap-1 rounded-lg px-2.5 py-2 text-xs font-semibold transition"
          :class="
            chats.filter === f.id ? 'bg-brand-soft text-brand' : 'text-muted hover:bg-surface'
          "
          @click="chats.setFilter(f.id)"
        >
          {{ f.label }}
          <span
            v-if="chats.unreadByTab[f.id] > 0"
            class="unread-badge inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-ok px-1 text-[9px] font-bold leading-none text-white"
          >
            {{ chats.unreadByTab[f.id] > 99 ? '99+' : chats.unreadByTab[f.id] }}
          </span>
        </button>
        <button
          v-if="canCreateOutbound"
          type="button"
          class="shrink-0 rounded-lg p-2 text-brand transition hover:bg-brand-soft"
          title="Новое исходящее"
          @click="openCreateOutbound"
        >
          <Plus class="size-4" />
        </button>
      </div>
      <div class="space-y-2 border-b border-line p-3 pt-0">
        <div class="relative">
          <Search class="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
          <input
            v-model="searchInput"
            type="search"
            placeholder="Имя, телефон, #обращения…"
            class="w-full rounded-lg border border-line bg-surface py-2 pl-8 pr-2 text-xs outline-none ring-brand focus:ring-2"
            @input="onSearchInput"
          />
        </div>
        <select
          class="w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-xs outline-none ring-brand focus:ring-2"
          :value="chats.channelFilterId ?? ''"
          @change="onChannelFilterChange"
        >
          <option value="">Все каналы</option>
          <option v-for="ch in channels.channels" :key="ch.id" :value="ch.id">
            {{ ch.name }}
          </option>
        </select>
      </div>
      <div class="min-h-0 flex-1 overflow-auto" @scroll="onDialogsScroll">
        <p v-if="chats.loadingDialogs && !chats.dialogs.length" class="p-4 text-center text-sm text-muted">
          Загрузка…
        </p>
        <button
          v-for="d in chats.filteredDialogs"
          :key="d.id"
          type="button"
          class="flex w-full gap-3 border-b border-line px-3 py-3 text-left transition hover:bg-[#eceff3]"
          :class="chats.activeDialogId === d.id ? 'bg-[#e5e8ed]' : ''"
          @click="selectDialog(d.id)"
        >
          <ContactAvatar :name="d.contactName" :url="d.contactAvatarUrl" size="md" />
          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-2">
              <span class="truncate text-sm font-semibold">{{ d.contactName }}</span>
              <span class="shrink-0 text-[10px] text-muted">
                <MessageTicks
                  v-if="d.lastDirection === 'out' && d.lastStatus"
                  :status="d.lastStatus"
                  tone="muted"
                  class="mr-0.5 inline-block align-middle"
                />
                {{ formatTime(d.lastAt) }}
              </span>
            </div>
            <div class="mt-0.5 flex items-start justify-between gap-2">
              <div class="min-w-0 flex-1">
                <div
                  class="truncate text-xs"
                  :class="chats.typingDialogId === d.id ? 'italic text-brand' : 'text-muted'"
                >
                  {{ chats.typingDialogId === d.id ? typingLabel : d.lastMessage || '—' }}
                </div>
                <div class="mt-1 flex items-center gap-1.5">
                  <span
                    v-if="d.transport"
                    class="rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide"
                    :class="transportBadgeClass[d.transport]"
                  >
                    {{ transportBadge[d.transport] }}
                  </span>
                  <span
                    v-if="d.appealNumber"
                    class="rounded-full px-1.5 text-[10px] font-bold"
                    :class="
                      d.appealStatus === 'closed'
                        ? 'bg-muted/15 text-muted'
                        : 'bg-ok/15 text-ok'
                    "
                  >
                    #{{ d.appealNumber }}
                    {{ d.appealStatus === 'closed' ? 'закр.' : '' }}
                  </span>
                </div>
              </div>
              <span
                v-if="d.unread"
                class="unread-badge mt-0.5 flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-ok px-1.5 text-[10px] font-bold text-white shadow-sm"
              >
                {{ d.unread > 99 ? '99+' : d.unread }}
              </span>
            </div>
          </div>
        </button>
        <p v-if="!chats.loadingDialogs && !chats.filteredDialogs.length" class="p-4 text-center text-sm text-muted">
          {{ emptyHint }}
          <button
            v-if="emptyHintAction"
            type="button"
            class="mt-2 block w-full text-xs font-semibold text-brand hover:underline"
            @click="openCreateOutbound"
          >
            {{ emptyHintAction.label }}
          </button>
        </p>
        <p
          v-else-if="chats.loadingMoreDialogs"
          class="p-3 text-center text-[11px] text-muted"
        >
          Загрузка…
        </p>
      </div>
    </aside>

    <section v-if="chats.activeDialog" class="flex min-w-0 flex-1 flex-col bg-surface">
      <header class="flex items-center gap-3 border-b border-line bg-panel px-5 py-3">
        <ContactAvatar
          :name="chats.activeDialog.contactName"
          :url="chats.activeDialog.contactAvatarUrl"
          size="md"
        />
        <div class="min-w-0 flex-1">
          <div class="flex min-w-0 items-center gap-2">
            <div class="truncate text-sm font-semibold">{{ chats.activeDialog.contactName }}</div>
            <span
              v-if="chats.activeDialog.transport"
              class="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide"
              :class="transportBadgeClass[chats.activeDialog.transport]"
            >
              {{ transportBadge[chats.activeDialog.transport] }}
            </span>
            <span
              v-if="headerAppealNumber"
              class="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold"
              :class="
                headerAppealStatus === 'closed'
                  ? 'bg-muted/15 text-muted'
                  : 'bg-ok/15 text-ok'
              "
            >
              #{{ headerAppealNumber }} ·
              {{ headerAppealStatus ? appealStatusLabel[headerAppealStatus] : '' }}
            </span>
          </div>
          <div
            class="text-xs"
            :class="
              chats.typingDialogId === chats.activeDialog.id
                ? 'italic text-brand'
                : 'text-muted'
            "
          >
            {{
              chats.typingDialogId === chats.activeDialog.id
                ? typingLabel
                : chats.activeDialog.contactPhone || '—'
            }}
          </div>
        </div>
        <div
          v-if="auth.can('action.write')"
          class="flex shrink-0 items-center gap-1"
        >
          <span
            class="mr-1 hidden max-w-[7rem] truncate text-[10px] text-muted sm:inline"
            :title="assigneeLabel"
          >
            {{ assigneeLabel }}
          </span>
          <button
            v-if="canClaim"
            type="button"
            class="inline-flex h-8 items-center gap-1 rounded-lg bg-ok px-2 text-[11px] font-semibold text-white transition hover:brightness-105 disabled:opacity-50"
            title="Забрать обращение"
            :disabled="claimBusy"
            @click="claimDialog"
          >
            <Hand class="size-3.5" />
            {{ claimBusy ? '…' : 'Забрать' }}
          </button>
          <button
            type="button"
            class="inline-flex h-8 items-center gap-1 rounded-lg border border-line px-2 text-[11px] font-semibold text-muted transition hover:border-brand/40 hover:bg-brand-soft hover:text-brand"
            title="Передать другому менеджеру"
            @click="transferOpen = true"
          >
            <ArrowRightLeft class="size-3.5" />
            Передать
          </button>
          <button
            v-if="chats.canCompose"
            type="button"
            class="inline-flex h-8 items-center gap-1 rounded-lg border border-line px-2 text-[11px] font-semibold text-muted transition hover:border-ok/40 hover:bg-ok/10 hover:text-ok disabled:opacity-50"
            :disabled="chats.closing"
            title="Закрыть обращение"
            @click="closeOpen = true"
          >
            <CircleCheckBig class="size-3.5" />
            {{ chats.closing ? '…' : 'Закрыть' }}
          </button>
        </div>
        <button
          type="button"
          class="flex size-8 shrink-0 items-center justify-center rounded-lg border border-line text-muted transition hover:border-brand/40 hover:bg-brand-soft hover:text-brand"
          title="Карточка клиента / обращения"
          @click="chats.openSidePanel()"
        >
          <PanelRight class="size-3.5" />
        </button>
      </header>

      <p
        v-if="transferNotice"
        class="border-b border-line bg-ok/10 px-5 py-2 text-xs font-medium text-ok"
      >
        {{ transferNotice }}
      </p>
      <p v-if="chats.error" class="border-b border-line bg-panel px-5 py-2 text-xs text-danger">
        {{ chats.error }}
      </p>

      <AppealHistoryBar
        :appeals="chats.dialogAppeals"
        :viewing-appeal-id="chats.viewingAppealId"
        :current-appeal-id="chats.activeDialog.appealId"
        @select="chats.selectAppeal($event)"
      />

      <div class="relative min-h-0 flex-1">
      <div ref="threadEl" class="h-full space-y-3 overflow-auto px-5 py-4" @scroll="onThreadScroll">
        <div v-if="chats.hasMoreMessages" class="flex justify-center py-1">
          <button
            type="button"
            class="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-muted transition hover:border-brand/40 hover:bg-brand-soft hover:text-brand disabled:opacity-50"
            :disabled="chats.loadingOlder"
            @click="chats.loadOlderMessages()"
          >
            {{ chats.loadingOlder ? 'Загрузка…' : 'Загрузить раньше' }}
          </button>
        </div>
        <p v-if="chats.loadingMessages" class="text-center text-sm text-muted">Загрузка сообщений…</p>
        <template v-for="row in threadRows" :key="row.key">
          <div
            v-if="row.type === 'day'"
            class="flex items-center justify-center py-2"
          >
            <span class="rounded-full bg-panel px-3 py-1 text-[11px] font-semibold text-muted">
              {{ row.label }}
            </span>
          </div>
          <div
            v-else
            class="group flex items-end gap-2"
            :class="row.message.direction === 'out' || row.message.isInternal ? 'justify-end' : 'justify-start'"
          >
            <ContactAvatar
              v-if="row.message.direction === 'in' && !row.message.isInternal"
              :name="avatarLabel(row.message)"
              :url="chats.activeDialog?.contactAvatarUrl"
              size="sm"
            />

            <div
              class="max-w-[min(70%,420px)] min-w-0 rounded-2xl px-3.5 py-2.5 text-sm shadow-sm"
              :class="[
                row.message.isInternal
                  ? 'rounded-br-md border border-dashed border-bubble-note-border bg-bubble-note text-bubble-note-ink'
                  : row.message.direction === 'out'
                    ? 'rounded-br-md bg-bubble-out text-white'
                    : 'rounded-bl-md border border-line bg-panel text-ink',
                row.message.status === 'failed' ? 'opacity-80 ring-1 ring-danger/60' : '',
                row.message.status === 'sending' ? 'opacity-90' : '',
              ]"
            >
              <template v-if="row.message.deletedAt">
                <p class="italic opacity-70">Сообщение удалено</p>
                <div
                  class="mt-1.5 flex items-center justify-end gap-2 text-[10px]"
                  :class="
                    row.message.isInternal
                      ? 'text-bubble-note-ink/60'
                      : row.message.direction === 'out'
                        ? 'text-white/70'
                        : 'text-muted'
                  "
                >
                  <span>{{ formatTime(row.message.at) }}</span>
                </div>
              </template>
              <template v-else>
                <div
                  v-if="row.message.isInternal"
                  class="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-bubble-note-ink/70"
                >
                  <NotebookPen class="size-3" />
                  Заметка
                  <span v-if="row.message.operatorName" class="font-medium normal-case tracking-normal">
                    · {{ row.message.operatorName }}
                  </span>
                </div>
                <div
                  v-if="row.message.replyTo"
                  class="mb-2 rounded-lg px-2.5 py-1.5 text-xs"
                  :class="row.message.direction === 'out' ? 'bg-white/15' : 'bg-surface'"
                >
                  <div
                    class="font-semibold"
                    :class="row.message.direction === 'out' ? 'text-white/90' : 'text-brand'"
                  >
                    {{ replyQuoteAuthor(row.message.replyTo) }}
                  </div>
                  <div
                    class="mt-0.5 line-clamp-2"
                    :class="row.message.direction === 'out' ? 'text-white/75' : 'text-muted'"
                  >
                    {{ row.message.replyTo.text || 'Вложение' }}
                  </div>
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
                      :class="row.message.direction === 'out' && !row.message.isInternal ? 'bg-white/15' : 'bg-surface'"
                      @click="openAttachment(att)"
                    >
                      📎 {{ att.fileName }}
                    </button>
                  </template>
                </div>

                <div v-if="editingId === row.message.id" class="space-y-2">
                  <textarea
                    v-model="editDraft"
                    rows="3"
                    class="w-full resize-none rounded-xl px-2.5 py-2 text-sm outline-none"
                    :class="
                      row.message.isInternal
                        ? 'border border-bubble-note-border bg-white/60 text-bubble-note-ink'
                        : 'border border-white/30 bg-white/15 text-white placeholder:text-white/50'
                    "
                    @keydown.enter.exact.prevent="saveEdit"
                    @keydown.esc.exact="cancelEdit"
                  />
                  <div class="flex justify-end gap-2">
                    <button
                      type="button"
                      class="rounded-lg px-2 py-1 text-[11px] font-semibold"
                      :class="
                        row.message.isInternal
                          ? 'text-bubble-note-ink/80 hover:bg-black/5'
                          : 'text-white/80 hover:bg-white/10'
                      "
                      @click="cancelEdit"
                    >
                      Отмена
                    </button>
                    <button
                      type="button"
                      class="rounded-lg px-2 py-1 text-[11px] font-semibold disabled:opacity-40"
                      :class="
                        row.message.isInternal
                          ? 'bg-bubble-note-ink/15 hover:bg-bubble-note-ink/25'
                          : 'bg-white/20 hover:bg-white/30'
                      "
                      :disabled="actionBusy || !editDraft.trim()"
                      @click="saveEdit"
                    >
                      Сохранить
                    </button>
                  </div>
                </div>
                <MessageBody
                  v-else-if="row.message.text && !(row.message.attachments?.length && isEmojiOnlyPreview(row.message.text))"
                  :text="row.message.text"
                  :outgoing="row.message.direction === 'out' && !row.message.isInternal"
                />

                <div
                  class="mt-1.5 flex items-center gap-1.5 text-[10px]"
                  :class="
                    row.message.isInternal
                      ? 'text-bubble-note-ink/60'
                      : row.message.direction === 'out'
                        ? 'text-white/70'
                        : 'text-muted'
                  "
                >
                  <template v-if="canWrite && chats.canCompose && !row.message.pending">
                    <button
                      v-if="!row.message.isInternal"
                      type="button"
                      class="rounded p-0.5 opacity-50 transition hover:opacity-100"
                      :class="row.message.direction === 'out' ? 'hover:bg-white/15' : 'hover:bg-surface hover:text-brand'"
                      title="Ответить"
                      @click="chats.setReplyTo(row.message)"
                    >
                      <Reply class="size-3.5" />
                    </button>
                    <template v-if="row.message.direction === 'out'">
                      <button
                        type="button"
                        class="rounded p-0.5 opacity-50 transition hover:opacity-100"
                        :class="row.message.isInternal ? 'hover:bg-black/5' : 'hover:bg-white/15'"
                        title="Изменить"
                        @click="startEdit(row.message)"
                      >
                        <Pencil class="size-3.5" />
                      </button>
                      <button
                        type="button"
                        class="rounded p-0.5 opacity-50 transition hover:opacity-100"
                        :class="row.message.isInternal ? 'hover:bg-black/5' : 'hover:bg-white/15'"
                        title="Удалить"
                        @click="confirmDelete(row.message)"
                      >
                        <Trash2 class="size-3.5" />
                      </button>
                    </template>
                  </template>
                  <span class="min-w-0 flex-1" />
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

            <div
              v-if="row.message.direction === 'out'"
              class="mb-0.5 flex size-8 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
              :class="
                row.message.isInternal
                  ? 'border border-dashed border-bubble-note-border bg-bubble-note text-bubble-note-ink'
                  : 'bg-bubble-out text-white'
              "
              :title="avatarLabel(row.message)"
            >
              {{ initials(avatarLabel(row.message)) }}
            </div>
          </div>
        </template>
      </div>
      <button
        v-if="pendingBelow > 0"
        type="button"
        class="absolute bottom-3 left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-1 rounded-full bg-brand px-3 py-1.5 text-xs font-semibold text-white shadow-sm"
        @click="scrollThreadToBottom"
      >
        <ArrowDown class="size-3.5" />
        {{ pendingBelow > 99 ? '99+' : pendingBelow }} новых
      </button>
      </div>

      <div
        v-if="chats.isViewingPastAppeal"
        class="border-t border-line bg-panel px-5 py-3 text-center text-xs text-muted"
      >
        Просмотр предыдущего обращения. Чтобы ответить, откройте текущее
        <button
          v-if="chats.activeDialog.appealId"
          type="button"
          class="font-semibold text-brand hover:underline"
          @click="chats.selectAppeal(chats.activeDialog.appealId!)"
        >
          #{{ chats.activeDialog.appealNumber }}
        </button>
      </div>
      <div
        v-else-if="chats.activeDialog.appealStatus === 'closed'"
        class="border-t border-line bg-panel px-5 py-3 text-center text-xs text-muted"
      >
        Обращение закрыто. Новое откроется, когда клиент напишет снова.
      </div>
      <ChatComposer
        v-else-if="canWrite && chats.canCompose"
        v-model="chats.draft"
        :note-mode="chats.noteMode"
        :files="chats.pendingFiles"
        :sending="chats.sending"
        :templates="composerTemplates"
        :template-groups="composerTemplateGroups"
        :replying-to="chats.replyingTo"
        @update:note-mode="chats.setNoteMode($event)"
        @add-files="chats.addFiles($event)"
        @remove-file="chats.removePendingFile($event)"
        @apply-template="chats.applyTemplate($event)"
        @clear-reply="chats.clearReply()"
        @send="chats.sendMessage()"
      />
      <div
        v-else
        class="border-t border-line bg-panel px-5 py-3 text-center text-xs text-muted"
      >
        Режим просмотра — отправка недоступна
      </div>
    </section>

    <div v-else class="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center text-sm text-muted">
      <p>Выберите диалог слева</p>
      <button
        v-if="canCreateOutbound"
        type="button"
        class="text-xs font-semibold text-brand hover:underline"
        @click="openCreateOutbound"
      >
        Или создайте исходящее обращение
      </button>
    </div>

    <CreateAppealModal
      :open="createOpen"
      :channels="channels.channels"
      :loading-channels="channels.loading"
      @close="createOpen = false"
      @created="onOutboundCreated"
    />

    <ChatSidePanel
      :open="chats.sidePanelOpen"
      :loading="chats.sidebarLoading"
      :data="chats.sidebar"
      @close="chats.closeSidePanel()"
    />

    <CloseAppealModal
      :open="closeOpen"
      :busy="chats.closing"
      :preview-text="closePreview"
      :contact-name="chats.activeDialog?.contactName || 'Клиент'"
      :appeal-number="chats.activeDialog?.appealNumber ?? null"
      @close="closeOpen = false"
      @confirm="confirmCloseAppeal"
    />

    <TransferChatModal
      :open="transferOpen"
      :operators="chats.operators"
      :current-assignee-id="chats.activeDialog?.assigneeId ?? null"
      :current-user-id="auth.user?.id ?? null"
      :department-id="chats.activeDialog?.departmentId ?? null"
      :busy="transferBusy"
      @close="transferOpen = false"
      @transfer="confirmTransfer"
    />
  </div>
</template>
