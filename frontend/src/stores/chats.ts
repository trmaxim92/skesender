import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  assignDialogRequest,
  closeDialogRequest,
  deleteMessageRequest,
  editMessageRequest,
  fetchSidebarRequest,
  listDialogAppealsRequest,
  listDialogsRequest,
  listMessagesRequest,
  listUsersRequest,
  mapApiUser,
  markDialogReadRequest,
  sendMessageRequest,
  createNoteRequest,
  unreadSummaryRequest,
  updateAppealFieldsRequest,
  updateClientFieldsRequest,
  type ApiAppeal,
  type ApiDialog,
  type ApiDialogSidebar,
  type ApiMessage,
} from '@/api/chats'
import { ApiError } from '@/api/client'
import { ChatsSocket, type ChatSocketEvent } from '@/api/ws'
import type { Appeal, Dialog, DialogSidebar, Message, Template, User } from '@/types'
import { useAuthStore } from '@/stores/auth'
import { notifyIncomingMessage, showInAppToast } from '@/utils/notify'

type DialogDraft = { text: string; files: File[] }

function mapDialog(d: ApiDialog): Dialog {
  return {
    id: String(d.id),
    channelId: String(d.channel_id),
    contactName: d.contact_name,
    contactAvatarUrl: d.contact_avatar_url ?? null,
    contactPhone: d.contact_phone || (d.contact_username ? `@${d.contact_username}` : ''),
    lastMessage: d.last_message,
    lastAt: d.last_at,
    lastDirection: d.last_direction ?? null,
    lastStatus: d.last_status ?? null,
    unread: d.last_direction === 'out' ? 0 : d.unread,
    assigneeId: d.assignee_id,
    transport: d.transport,
    appealId: d.appeal_id ?? null,
    appealNumber: d.appeal_number ?? null,
    appealStatus: d.appeal_status ?? null,
    departmentId: d.department_id ?? null,
  }
}

function mapAppeal(a: ApiDialogSidebar['appeals'][number] | ApiAppeal): Appeal {
  return {
    id: a.id,
    dialogId: a.dialog_id,
    number: a.number,
    status: a.status,
    openedAt: a.opened_at,
    closedAt: a.closed_at ?? null,
    closedById: a.closed_by_id ?? null,
    closedByName: a.closed_by_name ?? null,
  }
}

function mapField(f: NonNullable<ApiDialogSidebar['client_fields']>[number]) {
  return {
    id: f.id,
    scope: f.scope,
    departmentId: f.department_id,
    key: f.key,
    label: f.label,
    fieldType: f.field_type as import('@/types').FieldType,
    options: f.options ?? [],
    required: f.required,
    sortOrder: f.sort_order,
    isSystem: f.is_system,
    isActive: f.is_active,
  }
}

function mapSidebar(s: ApiDialogSidebar): DialogSidebar {
  return {
    client: {
      contactName: s.client.contact_name,
      contactUsername: s.client.contact_username,
      contactAvatarUrl: s.client.contact_avatar_url ?? null,
      contactExternalId: s.client.contact_external_id,
      contactPhone: s.client.contact_phone,
      channelId: s.client.channel_id,
      transport: s.client.transport,
      channelName: s.client.channel_name,
      dialogCreatedAt: s.client.dialog_created_at,
      appealsCount: s.client.appeals_count,
      assigneeId: s.client.assignee_id ?? null,
      assigneeName: s.client.assignee_name ?? null,
      departmentId: s.client.department_id ?? null,
    },
    currentAppeal: s.current_appeal ? mapAppeal(s.current_appeal) : null,
    appeals: s.appeals.map(mapAppeal),
    clientFields: (s.client_fields ?? []).map(mapField),
    appealFields: (s.appeal_fields ?? []).map(mapField),
    clientValues: s.client_values ?? {},
    appealValues: s.appeal_values ?? {},
  }
}

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

export const useChatsStore = defineStore('chats', () => {
  const dialogs = ref<Dialog[]>([])
  const messages = ref<Message[]>([])
  const operators = ref<User[]>([])
  const activeDialogId = ref<string | null>(null)
  const draft = ref('')
  const pendingFiles = ref<File[]>([])
  const noteMode = ref(false)
  const draftsByDialog = ref<Record<string, DialogDraft>>({})
  const replyingTo = ref<Message | null>(null)
  const dialogAppeals = ref<Appeal[]>([])
  const viewingAppealId = ref<number | null>(null)
  const filter = ref<'new' | 'mine' | 'others'>('new')
  const channelFilterId = ref<number | null>(null)
  const searchQuery = ref('')
  const unreadByTab = ref({ new: 0, mine: 0, others: 0 })
  const loadingDialogs = ref(false)
  const loadingMoreDialogs = ref(false)
  const hasMoreDialogs = ref(false)
  const dialogsOffset = ref(0)
  const DIALOGS_PAGE_SIZE = 50
  const loadingMessages = ref(false)
  const loadingOlder = ref(false)
  const hasMoreMessages = ref(false)
  const sending = ref(false)
  const error = ref('')
  const wsStatus = ref<'connecting' | 'open' | 'closed'>('closed')
  const typingDialogId = ref<string | null>(null)
  const sidePanelOpen = ref(false)
  const sidebar = ref<DialogSidebar | null>(null)
  const sidebarLoading = ref(false)
  const closing = ref(false)
  let typingTimer: number | undefined
  let socket: ChatsSocket | null = null
  let dialogsRequestId = 0
  let messagesRequestId = 0

  const activeDialog = computed(() => dialogs.value.find((d) => d.id === activeDialogId.value) ?? null)

  const viewingAppeal = computed(
    () => dialogAppeals.value.find((a) => a.id === viewingAppealId.value) ?? null,
  )

  const isViewingPastAppeal = computed(() => {
    const dialog = activeDialog.value
    const viewing = viewingAppeal.value
    if (!dialog || !viewing) return false
    return viewing.id !== dialog.appealId
  })

  const canCompose = computed(() => {
    const dialog = activeDialog.value
    if (!dialog) return false
    if (isViewingPastAppeal.value) return false
    return dialog.appealStatus === 'open'
  })

  const filteredDialogs = computed(() =>
    [...dialogs.value]
      .filter((d) => d.appealStatus !== 'closed')
      .sort((a, b) => +new Date(b.lastAt) - +new Date(a.lastAt)),
  )

  const activeMessages = computed(() =>
    messages.value
      .filter((m) => m.dialogId === activeDialogId.value)
      .sort((a, b) => {
        const ta = +new Date(a.at)
        const tb = +new Date(b.at)
        if (ta !== tb) return ta - tb
        return Number(a.id) - Number(b.id)
      }),
  )

  const totalUnread = computed(
    () => unreadByTab.value.new + unreadByTab.value.mine + unreadByTab.value.others,
  )

  function matchesFilter(d: Dialog): boolean {
    if (d.appealStatus === 'closed') return false
    const auth = useAuthStore()
    if (filter.value === 'new') return !d.assigneeId
    if (filter.value === 'mine') return d.assigneeId === auth.user?.id
    if (filter.value === 'others') return !!d.assigneeId && d.assigneeId !== auth.user?.id
    return true
  }

  function saveDraftFor(dialogId: string | null) {
    if (!dialogId) return
    draftsByDialog.value[dialogId] = {
      text: draft.value,
      files: [...pendingFiles.value],
    }
  }

  function restoreDraftFor(dialogId: string) {
    const saved = draftsByDialog.value[dialogId]
    draft.value = saved?.text ?? ''
    pendingFiles.value = saved?.files ? [...saved.files] : []
  }

  function clearDraftFor(dialogId: string) {
    delete draftsByDialog.value[dialogId]
    draft.value = ''
    pendingFiles.value = []
  }

  function upsertDialog(mapped: Dialog) {
    const idx = dialogs.value.findIndex((d) => d.id === mapped.id)
    if (idx >= 0) {
      if (matchesFilter(mapped)) dialogs.value[idx] = mapped
      else dialogs.value.splice(idx, 1)
      return
    }
    if (matchesFilter(mapped)) {
      dialogs.value.unshift(mapped)
    }
  }

  function messageBelongsToView(msg: Message, dialog: Dialog | null = activeDialog.value): boolean {
    if (msg.dialogId !== activeDialogId.value) return false
    const d = dialog ?? activeDialog.value
    const viewId = viewingAppealId.value
    if (viewId == null) return true
    if (msg.appealId == null) return viewId === (d?.appealId ?? null)
    return msg.appealId === viewId
  }

  function applySocketEvent(event: ChatSocketEvent) {
    if (event.type === 'ping') return

    if (event.type === 'message.created') {
      const mappedDialog = mapDialog(event.dialog)
      const mappedMsg = mapMessage(event.message)
      const viewingHere =
        activeDialogId.value === mappedDialog.id && !isViewingPastAppeal.value

      // Own outbound reply means the thread was handled — never keep a stale unread badge.
      if (mappedMsg.direction === 'out' && !mappedMsg.isInternal) {
        mappedDialog.unread = 0
      } else if (viewingHere) {
        // Optimistic UI; server mark-read keeps badges in sync with bump_unread.
        mappedDialog.unread = 0
      }
      upsertDialog(mappedDialog)

      if (messageBelongsToView(mappedMsg, mappedDialog)) {
        if (!messages.value.some((m) => m.id === mappedMsg.id)) {
          messages.value.push(mappedMsg)
        }
      } else if (
        mappedMsg.dialogId === activeDialogId.value &&
        mappedDialog.appealId != null &&
        mappedDialog.appealId !== viewingAppealId.value
      ) {
        // New appeal opened while browsing history — refresh appeals list.
        void fetchDialogAppeals(mappedDialog.id)
      }
      if (mappedMsg.direction === 'in' && !mappedMsg.pending && !mappedMsg.isInternal) {
        notifyIncomingMessage({
          dialogId: mappedDialog.id,
          contactName: mappedDialog.contactName,
          text: mappedMsg.text || (mappedMsg.attachments?.[0]?.fileName ?? 'Вложение'),
          isActiveDialog: viewingHere,
        })
        if (viewingHere) {
          void markActiveDialogRead(mappedDialog.id)
          return
        }
      }
      void fetchUnreadSummary()
      return
    }

    if (event.type === 'message.updated' || event.type === 'message.deleted') {
      const mappedDialog = mapDialog(event.dialog)
      upsertDialog(mappedDialog)
      const mappedMsg = mapMessage(event.message)
      const idx = messages.value.findIndex((m) => m.id === mappedMsg.id)
      if (idx >= 0) {
        if (messageBelongsToView(mappedMsg, mappedDialog)) messages.value[idx] = mappedMsg
        else messages.value.splice(idx, 1)
      } else if (messageBelongsToView(mappedMsg, mappedDialog)) {
        messages.value.push(mappedMsg)
      }
      void fetchUnreadSummary()
      return
    }

    if (event.type === 'dialog.updated' || event.type === 'dialog.assigned') {
      const mappedDialog = mapDialog(event.dialog)
      if (activeDialogId.value === mappedDialog.id) {
        const prevAppealId = dialogs.value.find((d) => d.id === mappedDialog.id)?.appealId
        if (mappedDialog.appealId != null && mappedDialog.appealId !== prevAppealId) {
          void fetchDialogAppeals(mappedDialog.id)
        }
        // Keep server unread when viewing; do not fake-zero (badges drifted before).
        if (!isViewingPastAppeal.value && mappedDialog.unread > 0) {
          void markActiveDialogRead(mappedDialog.id)
          mappedDialog.unread = 0
        }
      }
      const idx = dialogs.value.findIndex((d) => d.id === mappedDialog.id)
      if (idx >= 0) {
        if (matchesFilter(mappedDialog)) dialogs.value[idx] = mappedDialog
        else dialogs.value.splice(idx, 1)
      } else if (matchesFilter(mappedDialog)) {
        dialogs.value.unshift(mappedDialog)
      }
      void fetchUnreadSummary()
      return
    }

    if (event.type === 'dialog.typing') {
      const id = String(event.dialog_id)
      typingDialogId.value = id
      if (typingTimer) window.clearTimeout(typingTimer)
      typingTimer = window.setTimeout(() => {
        if (typingDialogId.value === id) typingDialogId.value = null
      }, 4000)
    }
  }

  let markReadInflight: string | null = null
  let markReadQueued: string | null = null

  async function markActiveDialogRead(dialogId: string) {
    if (activeDialogId.value !== dialogId || isViewingPastAppeal.value) return
    if (markReadInflight === dialogId) {
      markReadQueued = dialogId
      return
    }
    markReadInflight = dialogId
    try {
      const updated = await markDialogReadRequest(Number(dialogId))
      if (activeDialogId.value !== dialogId) return
      const mapped = mapDialog(updated)
      mapped.unread = 0
      upsertDialog(mapped)
      void fetchUnreadSummary()
    } catch {
      // Non-fatal: list refresh / next open will clear.
      void fetchUnreadSummary()
    } finally {
      if (markReadInflight === dialogId) markReadInflight = null
      if (markReadQueued === dialogId) {
        markReadQueued = null
        void markActiveDialogRead(dialogId)
      }
    }
  }

  function connectRealtime() {
    if (socket) return
    socket = new ChatsSocket({
      onEvent: applySocketEvent,
      onStatus: (status) => {
        wsStatus.value = status
      },
      onAuthFailure: () => {
        window.dispatchEvent(new CustomEvent('oe:auth-expired'))
      },
    })
    socket.connect()
  }

  function disconnectRealtime() {
    socket?.disconnect()
    socket = null
    wsStatus.value = 'closed'
    typingDialogId.value = null
    if (typingTimer) window.clearTimeout(typingTimer)
  }

  async function fetchOperators() {
    try {
      const list = await listUsersRequest()
      operators.value = list
        .map((u) =>
          mapApiUser({
            ...u,
            permissions: (u as { permissions?: string[] }).permissions,
            all_channels: (u as { all_channels?: boolean }).all_channels,
            channel_ids: (u as { channel_ids?: number[] }).channel_ids,
            department_ids: u.department_ids,
          }),
        )
        .filter(
          (u) =>
            u.permissions?.includes('action.write') ||
            (u.role !== 'viewer' && !u.permissions?.length),
        )
    } catch {
      operators.value = []
    }
  }

  async function fetchUnreadSummary() {
    try {
      const data = await unreadSummaryRequest()
      unreadByTab.value = {
        new: data.new || 0,
        mine: data.mine || 0,
        others: data.others || 0,
      }
    } catch {
      // ignore — badge is optional
    }
  }

  async function fetchDialogs(opts: { reloadMessages?: boolean; append?: boolean } = {}) {
    const reloadMessages = opts.reloadMessages ?? true
    const append = opts.append ?? false
    if (append) {
      if (!hasMoreDialogs.value || loadingMoreDialogs.value || loadingDialogs.value) return
    }
    const reqId = ++dialogsRequestId
    const offset = append ? dialogsOffset.value : 0
    if (append) loadingMoreDialogs.value = true
    else {
      loadingDialogs.value = true
      dialogsOffset.value = 0
      hasMoreDialogs.value = false
    }
    error.value = ''
    try {
      const page = await listDialogsRequest(filter.value, searchQuery.value, {
        limit: DIALOGS_PAGE_SIZE,
        offset,
        channelId: channelFilterId.value,
      })
      if (reqId !== dialogsRequestId) return
      const mapped = page.items
        .map(mapDialog)
        .filter((d) => d.appealStatus !== 'closed')
      if (append) {
        const existing = new Set(dialogs.value.map((d) => d.id))
        dialogs.value = [...dialogs.value, ...mapped.filter((d) => !existing.has(d.id))]
      } else {
        dialogs.value = mapped
      }
      hasMoreDialogs.value = page.has_more
      dialogsOffset.value = offset + page.items.length
      if (reloadMessages && activeDialogId.value) {
        await fetchMessages(activeDialogId.value)
      }
      void fetchUnreadSummary()
    } catch (e) {
      if (reqId !== dialogsRequestId) return
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить диалоги'
    } finally {
      if (reqId === dialogsRequestId) {
        loadingDialogs.value = false
        loadingMoreDialogs.value = false
      }
    }
  }

  async function loadMoreDialogs() {
    await fetchDialogs({ reloadMessages: false, append: true })
  }

  async function fetchDialogAppeals(dialogId: string) {
    try {
      const list = await listDialogAppealsRequest(Number(dialogId))
      if (activeDialogId.value !== dialogId) return
      dialogAppeals.value = list.map(mapAppeal)
      const dialog = dialogs.value.find((d) => d.id === dialogId)
      if (
        viewingAppealId.value == null ||
        !dialogAppeals.value.some((a) => a.id === viewingAppealId.value)
      ) {
        viewingAppealId.value =
          dialog?.appealId ?? dialogAppeals.value[dialogAppeals.value.length - 1]?.id ?? null
      }
    } catch {
      if (activeDialogId.value !== dialogId) return
      dialogAppeals.value = []
    }
  }

  function resolveAppealIdForDialog(dialogId: string, preferred?: number | null): number | null {
    const dialog = dialogs.value.find((d) => d.id === dialogId)
    const preferredId = preferred !== undefined ? preferred : viewingAppealId.value
    if (preferredId != null) {
      if (dialogAppeals.value.some((a) => a.id === preferredId)) return preferredId
      if (dialog?.appealId === preferredId) return preferredId
      // Stale appeal from another dialog — don't send it.
    }
    if (dialog?.appealId != null) return dialog.appealId
    if (dialogAppeals.value.length) {
      return dialogAppeals.value[dialogAppeals.value.length - 1]?.id ?? null
    }
    return null
  }

  async function fetchMessages(dialogId: string, appealId?: number | null) {
    const reqId = ++messagesRequestId
    const requested = dialogId
    const targetAppealId = resolveAppealIdForDialog(dialogId, appealId)
    if (activeDialogId.value === dialogId && viewingAppealId.value !== targetAppealId) {
      viewingAppealId.value = targetAppealId
    }
    loadingMessages.value = true
    hasMoreMessages.value = false
    try {
      const page = await listMessagesRequest(Number(dialogId), {
        limit: 50,
        appealId: targetAppealId,
      })
      if (reqId !== messagesRequestId || activeDialogId.value !== requested) return
      messages.value = page.items.map(mapMessage)
      hasMoreMessages.value = page.has_more
      const d = dialogs.value.find((x) => x.id === dialogId)
      if (d && (targetAppealId == null || targetAppealId === d.appealId)) d.unread = 0
      void fetchUnreadSummary()
    } catch (e) {
      if (reqId !== messagesRequestId || activeDialogId.value !== requested) return
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить сообщения'
    } finally {
      if (reqId === messagesRequestId) loadingMessages.value = false
    }
  }

  let olderRequestId = 0

  async function loadOlderMessages() {
    const dialogId = activeDialogId.value
    if (!dialogId || !hasMoreMessages.value || loadingOlder.value || loadingMessages.value) return
    const oldest = activeMessages.value[0]
    if (!oldest) return
    const reqId = ++olderRequestId
    const viewAppeal = viewingAppealId.value
    loadingOlder.value = true
    error.value = ''
    try {
      const page = await listMessagesRequest(Number(dialogId), {
        limit: 50,
        beforeId: Number(oldest.id),
        appealId: resolveAppealIdForDialog(dialogId, viewAppeal),
      })
      if (
        reqId !== olderRequestId ||
        activeDialogId.value !== dialogId ||
        viewingAppealId.value !== viewAppeal
      ) {
        return
      }
      const existing = new Set(messages.value.map((m) => m.id))
      const older = page.items.map(mapMessage).filter((m) => !existing.has(m.id))
      messages.value = [...older, ...messages.value]
      hasMoreMessages.value = page.has_more
    } catch (e) {
      if (reqId !== olderRequestId) return
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить историю'
    } finally {
      if (reqId === olderRequestId) loadingOlder.value = false
    }
  }

  async function selectAppeal(appealId: number) {
    if (viewingAppealId.value === appealId || !activeDialogId.value) return
    viewingAppealId.value = appealId
    replyingTo.value = null
    noteMode.value = false
    await fetchMessages(activeDialogId.value, appealId)
  }

  async function setSearchQuery(value: string) {
    searchQuery.value = value
    await fetchDialogs({ reloadMessages: false })
  }

  async function selectDialog(id: string) {
    if (activeDialogId.value === id) return
    saveDraftFor(activeDialogId.value)
    activeDialogId.value = id
    restoreDraftFor(id)
    replyingTo.value = null
    noteMode.value = false
    sidePanelOpen.value = false
    sidebar.value = null
    dialogAppeals.value = []
    const dialog = dialogs.value.find((d) => d.id === id)
    viewingAppealId.value = dialog?.appealId ?? null
    await fetchDialogAppeals(id)
    await fetchMessages(id, viewingAppealId.value)
  }

  function clearActiveDialog() {
    saveDraftFor(activeDialogId.value)
    activeDialogId.value = null
    viewingAppealId.value = null
    dialogAppeals.value = []
    replyingTo.value = null
    noteMode.value = false
    sidePanelOpen.value = false
    sidebar.value = null
  }

  function setReplyTo(message: Message | null) {
    if (message?.isInternal) return
    replyingTo.value = message
    if (message) noteMode.value = false
  }

  function setNoteMode(value: boolean) {
    noteMode.value = value
    if (value) {
      replyingTo.value = null
      pendingFiles.value = []
    }
  }

  function clearReply() {
    replyingTo.value = null
  }

  function addFiles(fileList: FileList | File[] | null) {
    if (!fileList) return
    const incoming = Array.from(fileList)
    if (!incoming.length) return
    pendingFiles.value = [...pendingFiles.value, ...incoming]
  }

  function removePendingFile(index: number) {
    pendingFiles.value = pendingFiles.value.filter((_, i) => i !== index)
  }

  function applyTemplate(template: Template) {
    const auth = useAuthStore()
    const contact = activeDialog.value?.contactName || 'Клиент'
    const text = template.body
      .replaceAll('{{operator}}', auth.user?.name || 'Оператор')
      .replaceAll('{{contact}}', contact)
    draft.value = text
  }

  async function setFilter(value: 'new' | 'mine' | 'others', opts?: { keepActive?: boolean }) {
    const pinned = opts?.keepActive ? activeDialogId.value : null
    filter.value = value
    await fetchDialogs({ reloadMessages: false })
    if (pinned) {
      activeDialogId.value = pinned
      const dialog = dialogs.value.find((d) => d.id === pinned)
      if (!dialogs.value.some((d) => d.id === pinned)) {
        // Keep viewing claimed/transferred dialog outside current filter list.
        viewingAppealId.value = dialog?.appealId ?? viewingAppealId.value
        await fetchDialogAppeals(pinned)
        await fetchMessages(pinned, viewingAppealId.value)
      } else if (!messages.value.some((m) => m.dialogId === pinned)) {
        viewingAppealId.value = dialog?.appealId ?? null
        await fetchDialogAppeals(pinned)
        await fetchMessages(pinned, viewingAppealId.value)
      }
      return
    }
    if (activeDialogId.value && !dialogs.value.some((d) => d.id === activeDialogId.value)) {
      activeDialogId.value = dialogs.value[0]?.id ?? null
      if (activeDialogId.value) {
        const dialog = dialogs.value.find((d) => d.id === activeDialogId.value)
        viewingAppealId.value = dialog?.appealId ?? null
        dialogAppeals.value = []
        await fetchDialogAppeals(activeDialogId.value)
        await fetchMessages(activeDialogId.value, viewingAppealId.value)
      } else {
        viewingAppealId.value = null
        dialogAppeals.value = []
        messages.value = []
      }
    }
  }

  async function setChannelFilter(channelId: number | null) {
    channelFilterId.value = channelId
    await fetchDialogs({ reloadMessages: false })
    if (activeDialogId.value && !dialogs.value.some((d) => d.id === activeDialogId.value)) {
      activeDialogId.value = dialogs.value[0]?.id ?? null
      if (activeDialogId.value) {
        const dialog = dialogs.value.find((d) => d.id === activeDialogId.value)
        viewingAppealId.value = dialog?.appealId ?? null
        dialogAppeals.value = []
        await fetchDialogAppeals(activeDialogId.value)
        await fetchMessages(activeDialogId.value, viewingAppealId.value)
      } else {
        viewingAppealId.value = null
        dialogAppeals.value = []
        messages.value = []
      }
    }
  }

  function filterForAssignee(assigneeId: number | null | undefined): 'new' | 'mine' | 'others' {
    const auth = useAuthStore()
    if (!assigneeId) return 'new'
    if (assigneeId === auth.user?.id) return 'mine'
    return 'others'
  }

  async function openDialogById(dialogId: string) {
    saveDraftFor(activeDialogId.value)
    activeDialogId.value = dialogId
    restoreDraftFor(dialogId)
    replyingTo.value = null
    noteMode.value = false
    dialogAppeals.value = []
    const dialog = dialogs.value.find((d) => d.id === dialogId)
    viewingAppealId.value = dialog?.appealId ?? null
    await fetchDialogAppeals(dialogId)
    await fetchMessages(dialogId, viewingAppealId.value)
    try {
      const data = await fetchSidebarRequest(Number(dialogId))
      const assigneeId = data.client.assignee_id ?? null
      filter.value = filterForAssignee(assigneeId)
    } catch {
      filter.value = 'new'
    }
    await fetchDialogs({ reloadMessages: false })
  }

  async function assignOperator(dialogId: string, operatorId: number | null) {
    try {
      const updated = await assignDialogRequest(Number(dialogId), operatorId)
      const mapped = mapDialog(updated)
      const idx = dialogs.value.findIndex((d) => d.id === dialogId)
      if (matchesFilter(mapped)) {
        if (idx >= 0) dialogs.value[idx] = mapped
        else dialogs.value.unshift(mapped)
      } else if (idx >= 0) {
        dialogs.value.splice(idx, 1)
      }
      if (sidePanelOpen.value && activeDialogId.value === dialogId) {
        await openSidePanel()
      }
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось передать чат'
      return false
    }
  }

  async function sendMessage() {
    if (noteMode.value) {
      await sendNote()
      return
    }
    if (isViewingPastAppeal.value) {
      error.value = 'Это предыдущее обращение. Вернитесь к текущему, чтобы ответить.'
      return
    }
    const text = draft.value.trim()
    const dialog = activeDialog.value
    const files = [...pendingFiles.value]
    const reply = replyingTo.value
    const replyId = reply ? Number(reply.id) : null
    if ((!text && !files.length) || !dialog || sending.value) return
    if (dialog.appealStatus === 'closed') {
      error.value = 'Обращение закрыто. Дождитесь нового сообщения клиента.'
      return
    }
    const auth = useAuthStore()
    const tempId = `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const objectUrls: string[] = []
    const optimisticAttachments = files.map((file, index) => {
      const url = URL.createObjectURL(file)
      objectUrls.push(url)
      const kind =
        file.type.startsWith('image/')
          ? ('image' as const)
          : file.type.startsWith('video/')
            ? ('video' as const)
            : file.type.startsWith('audio/')
              ? ('audio' as const)
              : ('file' as const)
      return {
        id: -(index + 1),
        kind,
        fileName: file.name,
        mimeType: file.type || null,
        sizeBytes: file.size,
        url,
      }
    })
    const optimistic: Message = {
      id: tempId,
      dialogId: dialog.id,
      direction: 'out',
      text: text || (files.length ? files.map((f) => f.name).join(', ') : ''),
      at: new Date().toISOString(),
      status: 'sending',
      pending: true,
      operatorName: auth.user?.name,
      attachments: optimisticAttachments.length ? optimisticAttachments : undefined,
      replyTo: reply
        ? {
            id: reply.id,
            text: reply.text,
            direction: reply.direction,
            operatorName: reply.operatorName ?? null,
          }
        : null,
    }
    messages.value.push(optimistic)
    dialog.lastMessage = optimistic.text
    dialog.lastAt = optimistic.at
    dialog.lastDirection = 'out'
    dialog.lastStatus = 'sent'
    // Composer stays until success so a failed send can be retried without losing text/files.
    const savedDraft = text
    const savedFiles = files
    const savedReply = reply
    draft.value = ''
    pendingFiles.value = []
    replyingTo.value = null

    sending.value = true
    error.value = ''
    try {
      const { message: msg, warning } = await sendMessageRequest(
        Number(dialog.id),
        text,
        files,
        replyId,
      )
      const mapped = mapMessage(msg)
      messages.value = messages.value.filter((m) => m.id !== tempId)
      for (const u of objectUrls) URL.revokeObjectURL(u)
      if (!messages.value.some((m) => m.id === mapped.id)) {
        messages.value.push(mapped)
      }
      clearDraftFor(dialog.id)
      dialog.lastMessage = mapped.text || (files[0] ? files[0].name : text)
      dialog.lastAt = msg.created_at
      dialog.lastDirection = 'out'
      dialog.lastStatus = mapped.status
      dialog.unread = 0
      void fetchUnreadSummary()
      if (warning) {
        error.value = warning
        showInAppToast({
          text: warning,
          kind: 'warn',
          title: 'Часть вложений не отправлена',
        })
      }
      const claimed = !dialog.assigneeId && !!auth.user
      if (claimed && auth.user) {
        dialog.assigneeId = auth.user.id
        if (filter.value === 'new') {
          await setFilter('mine', { keepActive: true })
        }
      } else if (auth.user && dialog.assigneeId === auth.user.id && filter.value === 'new') {
        // Server already claimed us (e.g. WS arrived first) — leave «Новые».
        await setFilter('mine', { keepActive: true })
      }
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось отправить'
      messages.value = messages.value.filter((m) => m.id !== tempId)
      for (const u of objectUrls) URL.revokeObjectURL(u)
      draft.value = savedDraft
      pendingFiles.value = savedFiles
      if (savedReply) replyingTo.value = savedReply
      dialog.lastStatus = 'failed'
      // Failed row is durable in CRM (+ WS); refresh so the ! tick is visible even if WS raced.
      void fetchMessages(dialog.id, viewingAppealId.value)
      showInAppToast({
        text: error.value || 'Сообщение не доставлено',
        kind: 'warn',
        title: 'Ошибка отправки',
      })
    } finally {
      sending.value = false
    }
  }

  async function sendNote() {
    if (isViewingPastAppeal.value) {
      error.value = 'Заметки можно добавлять только в текущем обращении.'
      return
    }
    const text = draft.value.trim()
    const dialog = activeDialog.value
    if (!text || !dialog || sending.value) return
    const auth = useAuthStore()
    const tempId = `tmp-note-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const optimistic: Message = {
      id: tempId,
      dialogId: dialog.id,
      direction: 'out',
      text,
      at: new Date().toISOString(),
      status: 'sending',
      pending: true,
      isInternal: true,
      operatorName: auth.user?.name,
    }
    messages.value.push(optimistic)
    const savedNote = text
    draft.value = ''

    sending.value = true
    error.value = ''
    try {
      const msg = await createNoteRequest(Number(dialog.id), text)
      const mapped = mapMessage(msg)
      messages.value = messages.value.filter((m) => m.id !== tempId)
      if (!messages.value.some((m) => m.id === mapped.id)) {
        messages.value.push(mapped)
      }
      delete draftsByDialog.value[dialog.id]
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить заметку'
      messages.value = messages.value.filter((m) => m.id !== tempId)
      draft.value = savedNote
    } finally {
      sending.value = false
    }
  }

  async function closeAppeal(withReply = true) {
    const dialog = activeDialog.value
    if (!dialog || closing.value) return false
    const closedId = dialog.id
    closing.value = true
    error.value = ''
    try {
      const { warning } = await closeDialogRequest(Number(closedId), withReply)
      // Сразу убираем из вкладок Новые/Мои/Чужие — закрытые там не живут.
      dialogs.value = dialogs.value.filter((d) => d.id !== closedId)
      if (activeDialogId.value === closedId) {
        activeDialogId.value = dialogs.value[0]?.id ?? null
        if (activeDialogId.value) await fetchMessages(activeDialogId.value)
        else messages.value = []
      }
      sidePanelOpen.value = false
      sidebar.value = null
      void fetchUnreadSummary()
      if (warning) {
        error.value = warning
        showInAppToast({
          text: warning,
          kind: 'warn',
          title: 'Обращение закрыто',
        })
      }
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось закрыть'
      return false
    } finally {
      closing.value = false
    }
  }

  async function loadSidebar(dialogId: string) {
    sidebarLoading.value = true
    try {
      sidebar.value = mapSidebar(await fetchSidebarRequest(Number(dialogId)))
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить карточку'
      sidebar.value = null
    } finally {
      sidebarLoading.value = false
    }
  }

  async function saveClientFields(payload: {
    full_name?: string | null
    phone?: string | null
    external_id?: string | null
    values?: Array<{ key: string; value: string }>
  }) {
    const dialog = activeDialog.value
    if (!dialog) return false
    try {
      sidebar.value = mapSidebar(await updateClientFieldsRequest(Number(dialog.id), payload))
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить'
      return false
    }
  }

  async function saveAppealFields(appealId: number, values: Array<{ key: string; value: string }>) {
    try {
      sidebar.value = mapSidebar(await updateAppealFieldsRequest(appealId, { values }))
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить'
      return false
    }
  }

  async function openSidePanel() {
    const dialog = activeDialog.value
    if (!dialog) return
    sidePanelOpen.value = true
    await loadSidebar(dialog.id)
  }

  function closeSidePanel() {
    sidePanelOpen.value = false
  }

  async function editMessage(messageId: string, text: string) {
    const dialog = activeDialog.value
    if (!dialog) return false
    error.value = ''
    try {
      const msg = await editMessageRequest(Number(dialog.id), Number(messageId), text.trim())
      const mapped = mapMessage(msg)
      const idx = messages.value.findIndex((m) => m.id === mapped.id)
      if (idx >= 0) messages.value[idx] = mapped
      if (!mapped.isInternal) {
        dialog.lastMessage = mapped.text || dialog.lastMessage
        dialog.lastDirection = mapped.direction
        dialog.lastStatus = mapped.status
      }
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось изменить'
      return false
    }
  }

  async function removeMessage(messageId: string) {
    const dialog = activeDialog.value
    if (!dialog) return false
    error.value = ''
    try {
      const msg = await deleteMessageRequest(Number(dialog.id), Number(messageId))
      const mapped = mapMessage(msg)
      const idx = messages.value.findIndex((m) => m.id === mapped.id)
      if (idx >= 0) messages.value[idx] = mapped
      if (replyingTo.value?.id === messageId) replyingTo.value = null
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить'
      return false
    }
  }

  return {
    dialogs,
    messages,
    operators,
    activeDialogId,
    draft,
    pendingFiles,
    noteMode,
    replyingTo,
    dialogAppeals,
    viewingAppealId,
    viewingAppeal,
    isViewingPastAppeal,
    canCompose,
    filter,
    channelFilterId,
    searchQuery,
    unreadByTab,
    totalUnread,
    loadingDialogs,
    loadingMoreDialogs,
    hasMoreDialogs,
    loadingMessages,
    loadingOlder,
    hasMoreMessages,
    sending,
    error,
    wsStatus,
    typingDialogId,
    sidePanelOpen,
    sidebar,
    sidebarLoading,
    closing,
    activeDialog,
    filteredDialogs,
    activeMessages,
    connectRealtime,
    disconnectRealtime,
    fetchOperators,
    fetchDialogs,
    loadMoreDialogs,
    fetchUnreadSummary,
    loadOlderMessages,
    selectDialog,
    clearActiveDialog,
    openDialogById,
    selectAppeal,
    setReplyTo,
    clearReply,
    setNoteMode,
    setFilter,
    setChannelFilter,
    setSearchQuery,
    assignOperator,
    sendMessage,
    closeAppeal,
    openSidePanel,
    closeSidePanel,
    saveClientFields,
    saveAppealFields,
    editMessage,
    removeMessage,
    addFiles,
    removePendingFile,
    applyTemplate,
  }
})
