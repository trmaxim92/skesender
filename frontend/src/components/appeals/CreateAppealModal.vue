<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowLeft, ChevronDown, ChevronRight, Radio, TextQuote } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import { startChatRequest } from '@/api/chats'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useMyTemplatesStore } from '@/stores/myTemplates'
import {
  transportBadge,
  transportBadgeClass,
  transportLabel,
  type Channel,
  type Template,
  type TemplateGroup,
} from '@/types'

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

const auth = useAuthStore()
const myTemplates = useMyTemplatesStore()

const step = ref<Step>('channel')
const selectedId = ref<number | null>(null)
const recipient = ref('')
const text = ref('')
const busy = ref(false)
const error = ref('')
const templatesOpen = ref(false)
const collapsedCategories = ref<Record<string, boolean>>({})

const START_TRANSPORTS = new Set(['maxbot', 'max', 'telegram', 'tgapi'])

const eligible = computed(() =>
  props.channels.filter(
    (c) => c.status === 'online' && START_TRANSPORTS.has(c.transport) && c.hasCredentials !== false,
  ),
)

const selected = computed(() => eligible.value.find((c) => c.id === selectedId.value) ?? null)

const templateGroups = computed((): TemplateGroup[] => {
  return [...myTemplates.forTransportGrouped(selected.value?.transport)]
})

const hasTemplates = computed(() =>
  templateGroups.value.some((g) => g.templates.length > 0),
)

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
    templatesOpen.value = false
    collapsedCategories.value = {}
    void myTemplates.fetchAll()
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
  templatesOpen.value = false
  step.value = 'channel'
}

function categoryKey(group: TemplateGroup) {
  return group.categoryId ?? 'none'
}

function isCategoryOpen(group: TemplateGroup) {
  return !collapsedCategories.value[categoryKey(group)]
}

function toggleCategory(group: TemplateGroup) {
  const key = categoryKey(group)
  collapsedCategories.value = {
    ...collapsedCategories.value,
    [key]: !collapsedCategories.value[key],
  }
}

function applyTemplate(template: Template) {
  const contact = recipient.value.trim() || 'Клиент'
  text.value = (template.body || '')
    .replaceAll('{{operator}}', auth.user?.name || 'Оператор')
    .replaceAll('{{contact}}', contact)
  templatesOpen.value = false
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

      <div class="block">
        <div class="mb-1 flex items-center justify-between gap-2">
          <span class="text-[11px] font-semibold uppercase tracking-wide text-muted">
            Сообщение
          </span>
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-semibold text-brand transition hover:bg-brand-soft disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="busy"
            title="Вставить шаблон"
            @click="templatesOpen = true"
          >
            <TextQuote class="size-3.5" />
            Шаблон
          </button>
        </div>
        <textarea
          v-model="text"
          rows="4"
          placeholder="Текст исходящего сообщения"
          class="w-full resize-none rounded-xl border border-line bg-panel px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
          :disabled="busy"
          @keydown.ctrl.enter.prevent="submit"
        />
      </div>

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

  <Modal v-if="open && templatesOpen" title="Шаблоны" @close="templatesOpen = false">
    <p v-if="!hasTemplates" class="text-sm text-muted">
      Нет шаблонов для этого канала. Создайте в разделе «Мои шаблоны».
    </p>
    <div v-else class="max-h-[60vh] space-y-2 overflow-y-auto">
      <section
        v-for="group in templateGroups"
        :key="group.categoryId ?? 'none'"
        class="overflow-hidden rounded-xl border border-line"
      >
        <button
          type="button"
          class="flex w-full items-center gap-2 bg-surface px-3 py-2.5 text-left transition hover:bg-brand-soft/40"
          @click="toggleCategory(group)"
        >
          <ChevronDown v-if="isCategoryOpen(group)" class="size-4 shrink-0 text-muted" />
          <ChevronRight v-else class="size-4 shrink-0 text-muted" />
          <span class="min-w-0 flex-1 truncate text-xs font-semibold uppercase tracking-wide text-muted">
            {{ group.categoryName }}
          </span>
          <span class="shrink-0 text-[11px] text-muted">{{ group.templates.length }}</span>
        </button>
        <div v-if="isCategoryOpen(group)" class="space-y-2 border-t border-line p-2">
          <button
            v-for="t in group.templates"
            :key="t.id"
            type="button"
            class="w-full rounded-xl border border-line bg-panel px-3.5 py-3 text-left transition hover:border-brand/40 hover:bg-brand-soft/50"
            @click="applyTemplate(t)"
          >
            <div class="text-sm font-semibold">{{ t.name }}</div>
            <div class="mt-1 line-clamp-2 text-xs text-muted">{{ t.body || 'Без текста' }}</div>
          </button>
        </div>
      </section>
    </div>
  </Modal>
</template>
