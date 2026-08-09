<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Modal from '@/components/ui/Modal.vue'
import { sendContactMessageRequest } from '@/api/contacts'
import { ApiError } from '@/api/client'
import {
  transportBadge,
  transportBadgeClass,
  transportLabel,
  type Channel,
} from '@/types'

const props = defineProps<{
  open: boolean
  contactId: number
  contactName: string
  phone: string
  channels: Channel[]
  loadingChannels?: boolean
}>()

const emit = defineEmits<{
  close: []
  sent: [dialogId: number]
}>()

type Step = 'channel' | 'compose'

const START_TRANSPORTS = new Set(['maxbot', 'max', 'telegram', 'tgapi'])

const step = ref<Step>('channel')
const selectedId = ref<number | null>(null)
const text = ref('')
const busy = ref(false)
const error = ref('')

const eligible = computed(() =>
  props.channels.filter(
    (c) => c.status === 'online' && START_TRANSPORTS.has(c.transport) && c.hasCredentials !== false,
  ),
)

const selected = computed(() => eligible.value.find((c) => c.id === selectedId.value) ?? null)

const title = computed(() =>
  step.value === 'channel' ? 'Канал для сообщения' : `Сообщение · ${props.contactName || props.phone}`,
)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    step.value = 'channel'
    selectedId.value = null
    text.value = ''
    busy.value = false
    error.value = ''
  },
)

function pickChannel(id: number) {
  selectedId.value = id
  step.value = 'compose'
  error.value = ''
}

function back() {
  step.value = 'channel'
  error.value = ''
}

async function submit() {
  if (!selected.value || busy.value) return
  const body = text.value.trim()
  if (!body) {
    error.value = 'Введите текст сообщения'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const res = await sendContactMessageRequest(props.contactId, {
      channel_id: selected.value.id,
      text: body,
    })
    emit('sent', res.dialog.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось отправить'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Modal v-if="open" :title="title" @close="emit('close')">
    <div v-if="step === 'channel'" class="space-y-3">
      <p class="text-sm text-muted">
        Сообщение уйдёт на номер <span class="font-medium text-ink">{{ phone }}</span>
      </p>
      <p v-if="loadingChannels" class="text-sm text-muted">Загрузка каналов…</p>
      <p v-else-if="!eligible.length" class="rounded-xl bg-surface px-3 py-3 text-sm text-muted">
        Нет онлайн-каналов для исходящего старта (MAX / Telegram).
      </p>
      <ul v-else class="max-h-72 space-y-2 overflow-auto">
        <li v-for="ch in eligible" :key="ch.id">
          <button
            type="button"
            class="flex w-full items-center gap-3 rounded-xl border border-line bg-surface px-3 py-2.5 text-left transition hover:border-brand/40 hover:bg-panel"
            @click="pickChannel(ch.id)"
          >
            <span
              class="inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-[10px] font-bold"
              :class="transportBadgeClass[ch.transport]"
            >
              {{ transportBadge[ch.transport] }}
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-medium text-ink">{{ ch.name }}</span>
              <span class="block text-xs text-muted">{{ transportLabel[ch.transport] }}</span>
            </span>
          </button>
        </li>
      </ul>
    </div>

    <div v-else class="space-y-3">
      <button type="button" class="text-xs font-medium text-brand hover:underline" @click="back">
        ← Сменить канал
      </button>
      <p class="text-sm text-muted">
        Канал: <span class="font-medium text-ink">{{ selected?.name }}</span>
      </p>
      <textarea
        v-model="text"
        rows="5"
        class="w-full resize-y rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
        placeholder="Текст предложения…"
      />
      <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
      <div class="flex justify-end gap-2">
        <button
          type="button"
          class="rounded-xl px-3 py-2 text-sm text-muted hover:bg-surface"
          :disabled="busy"
          @click="emit('close')"
        >
          Отмена
        </button>
        <button
          type="button"
          class="rounded-xl bg-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          :disabled="busy"
          @click="submit"
        >
          {{ busy ? 'Отправка…' : 'Отправить' }}
        </button>
      </div>
    </div>
  </Modal>
</template>
