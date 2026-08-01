<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowLeft, Radio } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import { startChatRequest } from '@/api/chats'
import { ApiError } from '@/api/client'
import { transportBadge, transportBadgeClass, transportLabel, type Channel } from '@/types'

const props = defineProps<{
  open: boolean
  channels: Channel[]
  loadingChannels?: boolean
}>()

const emit = defineEmits<{
  close: []
  created: [dialogId: number]
}>()

type Step = 'channel' | 'compose'

const step = ref<Step>('channel')
const selectedId = ref<number | null>(null)
const recipient = ref('')
const text = ref('')
const busy = ref(false)
const error = ref('')

const START_TRANSPORTS = new Set(['maxbot', 'max', 'telegram', 'tgapi'])

const eligible = computed(() =>
  props.channels.filter(
    (c) => c.status === 'online' && START_TRANSPORTS.has(c.transport) && c.hasCredentials !== false,
  ),
)

const selected = computed(() => eligible.value.find((c) => c.id === selectedId.value) ?? null)

const recipientHint = computed(() => {
  const t = selected.value?.transport
  if (t === 'tgapi') return 'Одно из: телефон, @username или user id'
  if (t === 'telegram') return 'После /start можно @username; иначе user id. Для @ без диалога — Telegram · аккаунт'
  if (t === 'max') return 'Одно из: телефон или user id (найдём chat id автоматически)'
  if (t === 'maxbot') return 'Числовой user id (телефон — через MAX · аккаунт)'
  return 'Получатель'
})

const recipientPlaceholder = computed(() => {
  const t = selected.value?.transport
  if (t === 'tgapi') return '+7999… / @username / 123456789'
  if (t === 'max') return '+79991234567'
  if (t === 'telegram') return '@username или 123456789'
  return 'например 20745927'
})

const title = computed(() =>
  step.value === 'channel' ? 'Новое обращение' : 'Получатель и сообщение',
)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    step.value = 'channel'
    selectedId.value = null
    recipient.value = ''
    text.value = ''
    busy.value = false
    error.value = ''
  },
)

function pickChannel(id: number) {
  selectedId.value = id
  error.value = ''
  step.value = 'compose'
}

function back() {
  if (busy.value) return
  error.value = ''
  step.value = 'channel'
}

async function submit() {
  if (!selected.value || busy.value) return
  const to = recipient.value.trim()
  const body = text.value.trim()
  if (!to || !body) {
    error.value = 'Заполните получателя и текст'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const res = await startChatRequest({
      channel_id: selected.value.id,
      recipient: to,
      text: body,
    })
    emit('created', res.dialog.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось создать обращение'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Modal v-if="open" :title="title" @close="emit('close')">
    <div v-if="step === 'channel'" class="space-y-4">
      <p class="text-sm text-muted">Выберите канал, в который отправить первое сообщение.</p>

      <p v-if="loadingChannels" class="text-sm text-muted">Загрузка каналов…</p>
      <p v-else-if="!eligible.length" class="rounded-xl border border-line bg-surface px-3 py-3 text-sm text-muted">
        Нет онлайн-каналов MAX/Telegram. Подключите канал во вкладке «Каналы».
      </p>
      <div v-else class="max-h-80 space-y-1.5 overflow-auto">
        <button
          v-for="ch in eligible"
          :key="ch.id"
          type="button"
          class="flex w-full items-center gap-3 rounded-xl border border-line px-3 py-2.5 text-left transition hover:border-brand/40 hover:bg-surface"
          @click="pickChannel(ch.id)"
        >
          <div class="flex size-9 items-center justify-center rounded-full bg-brand-soft text-brand">
            <Radio class="size-4" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-semibold text-ink">{{ ch.name }}</div>
            <div class="truncate text-[11px] text-muted">
              {{ transportLabel[ch.transport] }}
              <span v-if="ch.identity"> · {{ ch.identity }}</span>
            </div>
          </div>
          <span
            class="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold tracking-wide"
            :class="transportBadgeClass[ch.transport]"
          >
            {{ transportBadge[ch.transport] }}
          </span>
        </button>
      </div>
    </div>

    <div v-else class="space-y-4">
      <button
        type="button"
        class="inline-flex items-center gap-1 text-xs font-semibold text-muted transition hover:text-brand"
        :disabled="busy"
        @click="back"
      >
        <ArrowLeft class="size-3.5" />
        Другой канал
      </button>

      <div
        v-if="selected"
        class="rounded-xl border border-line bg-surface px-3 py-2 text-sm"
      >
        <div class="font-semibold text-ink">{{ selected.name }}</div>
        <div class="text-[11px] text-muted">{{ transportLabel[selected.transport] }}</div>
      </div>

      <label class="block">
        <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
          Получатель
        </span>
        <input
          v-model="recipient"
          type="text"
          :placeholder="recipientPlaceholder"
          class="w-full rounded-xl border border-line bg-panel px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
          :disabled="busy"
        />
        <span class="mt-1 block text-[11px] text-muted">{{ recipientHint }}</span>
      </label>

      <label class="block">
        <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
          Сообщение
        </span>
        <textarea
          v-model="text"
          rows="4"
          placeholder="Текст исходящего сообщения"
          class="w-full resize-none rounded-xl border border-line bg-panel px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
          :disabled="busy"
          @keydown.ctrl.enter.prevent="submit"
        />
      </label>

      <p v-if="error" class="text-sm text-danger">{{ error }}</p>

      <div class="flex justify-end gap-2">
        <button
          type="button"
          class="rounded-xl px-3 py-2 text-sm font-semibold text-muted hover:bg-surface"
          :disabled="busy"
          @click="emit('close')"
        >
          Отмена
        </button>
        <button
          type="button"
          class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
          :disabled="busy || !recipient.trim() || !text.trim()"
          @click="submit"
        >
          {{ busy ? 'Отправка…' : 'Отправить' }}
        </button>
      </div>
    </div>
  </Modal>
</template>
