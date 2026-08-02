import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  connectMaxBotRequest,
  connectTelegramBotRequest,
  connectWebchatRequest,
  deleteChannelRequest,
  listChannelsRequest,
  mapChannel,
  maxQr2faRequest,
  maxQrStatusRequest,
  startMaxQrRequest,
  startTelegramQrRequest,
} from '@/api/auth'
import { updateChannelRequest } from '@/api/settings'
import { ApiError } from '@/api/client'
import type { Channel, ChannelTransport } from '@/types'

export type ConnectStep = 'pick' | 'details' | 'bot_token' | 'qr' | null

export const useChannelsStore = defineStore('channels', () => {
  const channels = ref<Channel[]>([])
  const loading = ref(false)
  const loadError = ref('')
  const connectOpen = ref(false)
  const connectStep = ref<ConnectStep>(null)
  const selectedTransport = ref<ChannelTransport | null>(null)
  const channelName = ref('')
  const departmentId = ref<number | null>(null)
  const botToken = ref('')
  const connecting = ref(false)
  const qrPendingId = ref<number | null>(null)
  const qrUrl = ref('')
  const qrStatus = ref('')
  const qrHint = ref('')
  const qrPassword = ref('')
  const connectError = ref('')
  let qrPollTimer: number | undefined

  const onlineCount = computed(() => channels.value.filter((c) => c.status === 'online').length)
  const need2fa = computed(() => qrStatus.value === 'need_2fa')

  async function fetchChannels() {
    loading.value = true
    loadError.value = ''
    try {
      const list = await listChannelsRequest()
      channels.value = list.map(mapChannel)
    } catch (e) {
      loadError.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить каналы'
    } finally {
      loading.value = false
    }
  }

  function stopQrPoll() {
    if (qrPollTimer) {
      window.clearInterval(qrPollTimer)
      qrPollTimer = undefined
    }
  }

  function openConnect(preferredTransport?: ChannelTransport) {
    connectOpen.value = true
    connectStep.value = 'pick'
    selectedTransport.value = null
    channelName.value = ''
    departmentId.value = null
    botToken.value = ''
    qrUrl.value = ''
    qrStatus.value = ''
    qrHint.value = ''
    qrPassword.value = ''
    connectError.value = ''
    qrPendingId.value = null
    stopQrPoll()
    if (preferredTransport) {
      pickTransport(preferredTransport)
    }
  }

  function closeConnect() {
    connectOpen.value = false
    connectStep.value = null
    stopQrPoll()
  }

  function pickTransport(transport: ChannelTransport) {
    selectedTransport.value = transport
    connectError.value = ''
    if (transport === 'vk') {
      connectError.value = 'Этот транспорт появится позже.'
      return
    }
    connectStep.value = 'details'
  }

  function continueFromDetails() {
    connectError.value = ''
    if (!channelName.value.trim()) {
      connectError.value = 'Укажите название канала'
      return
    }
    if (departmentId.value == null) {
      connectError.value = 'Выберите отдел'
      return
    }
    const transport = selectedTransport.value
    if (transport === 'maxbot' || transport === 'telegram') {
      connectStep.value = 'bot_token'
    } else if (transport === 'max' || transport === 'tgapi') {
      void startQr()
    } else if (transport === 'webchat') {
      void connectWebchat()
    }
  }

  async function connectWebchat() {
    connectError.value = ''
    connecting.value = true
    try {
      const name = channelName.value.trim()
      const dept = departmentId.value
      const result = await connectWebchatRequest(name, dept)
      const mapped = mapChannel(result.channel)
      channels.value.unshift(mapped)
      closeConnect()
    } catch (e) {
      connectError.value = e instanceof ApiError ? e.detail : 'Ошибка создания виджета'
    } finally {
      connecting.value = false
    }
  }

  async function connectBot() {
    connectError.value = ''
    if (!botToken.value.trim()) {
      connectError.value = 'Вставьте токен бота'
      return
    }
    connecting.value = true
    try {
      const name = channelName.value.trim()
      const dept = departmentId.value
      const result =
        selectedTransport.value === 'telegram'
          ? await connectTelegramBotRequest(botToken.value.trim(), name, dept)
          : await connectMaxBotRequest(botToken.value.trim(), name, dept)
      const mapped = mapChannel(result.channel)
      const idx = channels.value.findIndex((c) => c.id === mapped.id)
      if (idx >= 0) channels.value[idx] = mapped
      else channels.value.unshift(mapped)
      closeConnect()
    } catch (e) {
      connectError.value = e instanceof ApiError ? e.detail : 'Ошибка подключения'
    } finally {
      connecting.value = false
    }
  }

  async function startQr() {
    connectStep.value = 'qr'
    connecting.value = true
    connectError.value = ''
    try {
      const name = channelName.value.trim()
      const dept = departmentId.value
      const isTelegram = selectedTransport.value === 'tgapi'
      const result = isTelegram
        ? await startTelegramQrRequest(name || 'Telegram аккаунт', dept)
        : await startMaxQrRequest(name || 'MAX аккаунт', dept)
      const mapped = mapChannel(result.channel)
      channels.value.unshift(mapped)
      qrPendingId.value = mapped.id
      qrUrl.value = result.qr_url
      qrStatus.value = result.status
      stopQrPoll()
      qrPollTimer = window.setInterval(() => {
        void pollQrStatus()
      }, 2000)
    } catch (e) {
      connectError.value = e instanceof ApiError ? e.detail : 'Не удалось получить QR'
      connectStep.value = 'details'
    } finally {
      connecting.value = false
    }
  }

  async function pollQrStatus() {
    const id = qrPendingId.value
    if (!id) return
    try {
      const status = await maxQrStatusRequest(id)
      qrStatus.value = status.status
      if (status.qr_url) qrUrl.value = status.qr_url
      qrHint.value = status.hint || ''
      if (status.channel) {
        const mapped = mapChannel(status.channel)
        const idx = channels.value.findIndex((c) => c.id === id)
        if (idx >= 0) channels.value[idx] = mapped
      }
      if (status.status === 'online') {
        stopQrPoll()
        closeConnect()
        await fetchChannels()
      }
      if (status.status === 'error') {
        connectError.value = status.error || 'Ошибка подключения QR'
        stopQrPoll()
      }
    } catch (e) {
      connectError.value = e instanceof ApiError ? e.detail : 'Ошибка статуса QR'
    }
  }

  async function submit2fa() {
    const id = qrPendingId.value
    if (!id || !qrPassword.value.trim()) return
    connecting.value = true
    connectError.value = ''
    try {
      await maxQr2faRequest(id, qrPassword.value.trim())
      qrPassword.value = ''
      qrStatus.value = 'connecting'
    } catch (e) {
      connectError.value = e instanceof ApiError ? e.detail : 'Неверный пароль 2FA'
    } finally {
      connecting.value = false
    }
  }

  async function updateChannel(
    id: number,
    payload: { name?: string; departmentId?: number; status?: 'online' | 'offline' },
  ) {
    try {
      const updated = await updateChannelRequest(id, {
        name: payload.name,
        department_id: payload.departmentId,
        status: payload.status,
      })
      const idx = channels.value.findIndex((c) => c.id === id)
      if (idx >= 0) {
        channels.value[idx] = {
          ...channels.value[idx],
          name: updated.name,
          status: updated.status as Channel['status'],
          departmentId: updated.department_id,
          departmentName: updated.department_name,
          publicKey: updated.public_key ?? channels.value[idx].publicKey,
        }
      }
      return true
    } catch (e) {
      loadError.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить канал'
      return false
    }
  }

  async function removeChannel(id: number): Promise<boolean> {
    try {
      await deleteChannelRequest(id)
      channels.value = channels.value.filter((c) => c.id !== id)
      return true
    } catch (e) {
      loadError.value = e instanceof ApiError ? e.detail : 'Не удалось удалить канал'
      return false
    }
  }

  return {
    channels,
    loading,
    loadError,
    connectOpen,
    connectStep,
    selectedTransport,
    channelName,
    departmentId,
    botToken,
    connecting,
    qrUrl,
    qrPendingId,
    qrStatus,
    qrHint,
    qrPassword,
    need2fa,
    connectError,
    onlineCount,
    fetchChannels,
    openConnect,
    closeConnect,
    pickTransport,
    continueFromDetails,
    connectBot,
    submit2fa,
    updateChannel,
    removeChannel,
  }
})
