<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Download,
  FileImage,
  ImagePlus,
  Megaphone,
  Pause,
  Play,
  Plus,
  Radio,
  Upload,
  Users,
  X,
} from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useMailingStore } from '@/stores/mailing'
import { useChannelsStore } from '@/stores/channels'
import AddChannelModal from '@/components/channels/AddChannelModal.vue'
import { downloadRecipientsSample, parseRecipientsFile } from '@/utils/mailingRecipients'
import type { Channel, ChannelTransport } from '@/types'
import { transportLabel } from '@/types'

type Mode = 'list' | 'wizard' | 'detail'
type WizardStep = 1 | 2 | 3 | 4
type PlatformKey = 'max' | 'telegram'

const auth = useAuthStore()
const canWrite = computed(() => auth.can('action.write'))
const canManageChannels = computed(() => auth.can('action.manage_channels'))
const mailing = useMailingStore()
const channels = useChannelsStore()

const mode = ref<Mode>('list')
const step = ref<WizardStep>(1)

const selectedPlatform = ref<PlatformKey | null>(null)
const campName = ref('')
const campTemplateId = ref<number | null>(null)
const campChannelIds = ref<number[]>([])
const campDelay = ref(5)
const campRecipients = ref('')
const campSaving = ref(false)
const fileImporting = ref(false)
const fileImportError = ref('')
const importedFileName = ref('')

const creatingTemplate = ref(false)
const tplName = ref('')
const tplBody = ref('')
const tplMedia = ref<File | null>(null)
const tplPreview = ref<string | null>(null)
const tplSaving = ref(false)

let pollTimer: number | undefined

const steps = [
  { id: 1 as const, title: 'Платформа', hint: 'Куда слать' },
  { id: 2 as const, title: 'Получатели', hint: 'Логины и номера' },
  { id: 3 as const, title: 'Шаблон', hint: 'Текст и медиа' },
  { id: 4 as const, title: 'Аккаунты', hint: 'С кого слать' },
]

type TransportGroup = {
  key: PlatformKey
  label: string
  tone: string
  disabled: boolean
  addOptions: { transport: ChannelTransport; label: string; ready: boolean }[]
  accounts: Channel[]
}

const transportGroups = computed<TransportGroup[]>(() => {
  const all = channels.channels
  const by = (transports: ChannelTransport[]) =>
    all.filter((c) => transports.includes(c.transport) && c.status === 'online')

  return [
    {
      key: 'max',
      label: 'MAX',
      tone: 'bg-max text-white',
      disabled: false,
      addOptions: [
        { transport: 'maxbot', label: 'MAX · бот', ready: true },
        { transport: 'max', label: 'MAX · аккаунт', ready: true },
      ],
      accounts: by(['maxbot', 'max']),
    },
    {
      key: 'telegram',
      label: 'Telegram',
      tone: 'bg-tg text-white',
      disabled: false,
      addOptions: [
        { transport: 'telegram', label: 'Telegram · бот', ready: true },
        { transport: 'tgapi', label: 'Telegram · аккаунт', ready: true },
      ],
      accounts: by(['telegram', 'tgapi']),
    },
  ]
})

const selectedGroup = computed(
  () => transportGroups.value.find((g) => g.key === selectedPlatform.value) ?? null,
)

const platformAccounts = computed(() => selectedGroup.value?.accounts ?? [])

const selectedTemplate = computed(() =>
  mailing.templates.find((t) => t.id === campTemplateId.value) ?? null,
)

const selectedChannels = computed(() =>
  channels.channels.filter((c) => campChannelIds.value.includes(c.id)),
)

const recipientCount = computed(() => {
  const lines = campRecipients.value
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#'))
  return new Set(lines.map((l) => l.toLowerCase())).size
})

const stepValid = computed(() => {
  if (step.value === 1) return Boolean(selectedPlatform.value)
  if (step.value === 2) return recipientCount.value > 0 && campName.value.trim().length > 0
  if (step.value === 3) return Boolean(campTemplateId.value)
  if (step.value === 4) return campChannelIds.value.length > 0
  return false
})

const progressPct = computed(() => {
  const c = mailing.activeCampaign
  if (!c || !c.total) return 0
  return Math.min(100, Math.round(((c.sent + c.failed) / c.total) * 100))
})

const statusLabel: Record<string, string> = {
  draft: 'Черновик',
  running: 'Идёт',
  paused: 'Пауза',
  completed: 'Готово',
  failed: 'Ошибка',
  pending: 'Ожидает',
  sending: 'Отправка',
  sent: 'Отправлено',
  skipped: 'Пропуск',
}

onMounted(async () => {
  await Promise.all([mailing.fetchTemplates(), mailing.fetchCampaigns(), channels.fetchChannels()])
})

onUnmounted(() => {
  stopPoll()
  revokePreview()
})

watch(
  () => mailing.activeCampaign?.status,
  (status) => {
    stopPoll()
    if (status === 'running' && mailing.activeCampaign) {
      const id = mailing.activeCampaign.id
      pollTimer = window.setInterval(() => {
        void mailing.openCampaign(id)
        void mailing.fetchCampaigns()
      }, 3000)
    }
  },
)

watch(
  () => channels.connectOpen,
  async (open, wasOpen) => {
    if (wasOpen && !open) {
      await channels.fetchChannels()
    }
  },
)

watch(selectedPlatform, () => {
  campChannelIds.value = []
})

function stopPoll() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function revokePreview() {
  if (tplPreview.value) {
    URL.revokeObjectURL(tplPreview.value)
    tplPreview.value = null
  }
}

function startWizard() {
  mailing.error = ''
  step.value = 1
  selectedPlatform.value = null
  campName.value = `Рассылка ${new Date().toLocaleDateString('ru-RU')}`
  campTemplateId.value = mailing.templates[0]?.id ?? null
  campChannelIds.value = []
  campDelay.value = 5
  campRecipients.value = ''
  fileImportError.value = ''
  importedFileName.value = ''
  creatingTemplate.value = !mailing.templates.length
  resetTplForm()
  mode.value = 'wizard'
}

function backToList() {
  mode.value = 'list'
  mailing.activeCampaign = null
  stopPoll()
}

function resetTplForm() {
  tplName.value = ''
  tplBody.value = ''
  tplMedia.value = null
  revokePreview()
}

function onMediaChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  revokePreview()
  tplMedia.value = file
  if (file && file.type.startsWith('image/')) {
    tplPreview.value = URL.createObjectURL(file)
  }
}

async function addTemplate() {
  if (!tplName.value.trim()) return
  tplSaving.value = true
  const ok = await mailing.createTemplate(tplName.value.trim(), tplBody.value, tplMedia.value)
  tplSaving.value = false
  if (!ok) return
  const created = mailing.templates[0]
  if (created) campTemplateId.value = created.id
  creatingTemplate.value = false
  resetTplForm()
}

function selectPlatform(key: PlatformKey) {
  const group = transportGroups.value.find((g) => g.key === key)
  if (!group || group.disabled) return
  selectedPlatform.value = key
}

function toggleChannel(id: number) {
  const set = new Set(campChannelIds.value)
  if (set.has(id)) set.delete(id)
  else set.add(id)
  campChannelIds.value = [...set]
}

function selectAllPlatformAccounts() {
  const ids = platformAccounts.value.map((c) => c.id)
  const set = new Set(campChannelIds.value)
  const allSelected = ids.length > 0 && ids.every((id) => set.has(id))
  if (allSelected) {
    ids.forEach((id) => set.delete(id))
  } else {
    ids.forEach((id) => set.add(id))
  }
  campChannelIds.value = [...set]
}

function addAccount(transport: ChannelTransport) {
  channels.openConnect(transport)
}

async function onRecipientsFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  fileImporting.value = true
  fileImportError.value = ''
  try {
    const lines = await parseRecipientsFile(file)
    if (!lines.length) {
      fileImportError.value = 'В файле не найдено получателей'
      return
    }
    campRecipients.value = lines.join('\n')
    importedFileName.value = file.name
  } catch (err) {
    fileImportError.value = err instanceof Error ? err.message : 'Не удалось прочитать файл'
  } finally {
    fileImporting.value = false
  }
}

function downloadSample(format: 'csv' | 'xlsx') {
  downloadRecipientsSample(format)
}

function nextStep() {
  if (!stepValid.value || step.value >= 4) return
  step.value = (step.value + 1) as WizardStep
}

function prevStep() {
  if (step.value <= 1) {
    mode.value = 'list'
    return
  }
  step.value = (step.value - 1) as WizardStep
}

async function launchCampaign() {
  if (!campTemplateId.value || !campChannelIds.value.length || !campName.value.trim()) return
  campSaving.value = true
  const created = await mailing.createCampaign({
    name: campName.value.trim(),
    templateId: campTemplateId.value,
    channelIds: campChannelIds.value,
    delaySec: campDelay.value,
    recipientsText: campRecipients.value,
  })
  campSaving.value = false
  if (!created) return
  await mailing.openCampaign(created.id)
  await mailing.startCampaign(created.id)
  mode.value = 'detail'
}

async function openDetail(id: number) {
  await mailing.openCampaign(id)
  mode.value = 'detail'
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-surface">
    <!-- LIST -->
    <div v-if="mode === 'list'" class="flex min-h-0 flex-1 flex-col">
      <div class="relative overflow-hidden border-b border-line bg-panel px-4 py-5 md:px-6 md:py-6">
        <div
          class="pointer-events-none absolute -right-16 -top-20 size-56 rounded-full bg-brand/10 blur-2xl"
        />
        <div
          class="pointer-events-none absolute -bottom-24 left-1/3 size-40 rounded-full bg-tg/10 blur-2xl"
        />
        <div class="relative flex flex-wrap items-end justify-between gap-4">
          <div>
            <p class="text-[11px] font-bold uppercase tracking-[0.18em] text-brand">Рассылки</p>
            <h1 class="mt-1 text-2xl font-bold tracking-tight text-ink">Кампании</h1>
            <p class="mt-1 max-w-lg text-sm text-muted">
              Платформа → получатели → шаблон → аккаунты. Один поток, без лишнего шума.
            </p>
          </div>
          <button
            v-if="canWrite"
            type="button"
            class="inline-flex items-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:brightness-105 active:scale-[0.98]"
            @click="startWizard"
          >
            <Plus class="size-4" />
            Новая рассылка
          </button>
        </div>
      </div>

      <div class="min-h-0 flex-1 overflow-auto p-4 md:p-6">
        <p v-if="mailing.error" class="mb-4 text-sm text-danger">{{ mailing.error }}</p>

        <div v-if="!mailing.campaigns.length" class="flex flex-col items-center justify-center py-20 text-center">
          <div class="mb-4 flex size-14 items-center justify-center rounded-2xl bg-brand-soft text-brand">
            <Megaphone class="size-7" />
          </div>
          <h2 class="text-lg font-semibold">Пока пусто</h2>
          <p class="mt-1 max-w-sm text-sm text-muted">
            Создайте первую кампанию — мастер проведёт по шагам от платформы до старта.
          </p>
          <button
            v-if="canWrite"
            type="button"
            class="mt-5 rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white"
            @click="startWizard"
          >
            Начать
          </button>
        </div>

        <div v-else class="mx-auto grid max-w-5xl gap-3">
          <button
            v-for="c in mailing.campaigns"
            :key="c.id"
            type="button"
            class="group flex items-center gap-4 rounded-2xl border border-line bg-panel p-4 text-left transition hover:border-brand/40 hover:shadow-sm"
            @click="openDetail(c.id)"
          >
            <div
              class="flex size-11 shrink-0 items-center justify-center rounded-xl"
              :class="
                c.status === 'running'
                  ? 'bg-ok/15 text-ok'
                  : c.status === 'completed'
                    ? 'bg-brand-soft text-brand'
                    : 'bg-surface text-muted'
              "
            >
              <Megaphone class="size-5" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <span class="truncate font-semibold">{{ c.name }}</span>
                <span class="rounded-md bg-surface px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-muted">
                  {{ statusLabel[c.status] || c.status }}
                </span>
              </div>
              <p class="mt-0.5 truncate text-xs text-muted">
                {{ c.templateName || 'Без шаблона' }} · {{ c.sent }}/{{ c.total }}
                <span v-if="c.failed"> · ошибок {{ c.failed }}</span>
              </p>
              <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface">
                <div
                  class="h-full rounded-full bg-brand transition-all duration-500"
                  :style="{ width: `${c.total ? Math.round(((c.sent + c.failed) / c.total) * 100) : 0}%` }"
                />
              </div>
            </div>
            <div v-if="canWrite" class="flex shrink-0 gap-2" @click.stop>
              <button
                v-if="c.status === 'draft' || c.status === 'paused'"
                type="button"
                class="inline-flex items-center gap-1 rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-white"
                @click="mailing.startCampaign(c.id)"
              >
                <Play class="size-3.5" /> Старт
              </button>
              <button
                v-else-if="c.status === 'running'"
                type="button"
                class="inline-flex items-center gap-1 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold"
                @click="mailing.pauseCampaign(c.id)"
              >
                <Pause class="size-3.5" /> Пауза
              </button>
            </div>
          </button>
        </div>
      </div>
    </div>

    <!-- WIZARD -->
    <div v-else-if="mode === 'wizard'" class="flex min-h-0 flex-1 flex-col">
      <div class="border-b border-line bg-panel px-6 py-4">
        <div class="mx-auto flex max-w-3xl items-center gap-3">
          <button
            type="button"
            class="rounded-lg p-2 text-muted transition hover:bg-surface hover:text-ink"
            @click="prevStep"
          >
            <ArrowLeft class="size-4" />
          </button>
          <div class="min-w-0 flex-1">
            <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-muted">
              Шаг {{ step }} из 4
            </p>
            <h1 class="text-lg font-bold tracking-tight">{{ steps[step - 1].title }}</h1>
          </div>
        </div>
        <div class="mx-auto mt-4 flex max-w-3xl gap-2">
          <div
            v-for="s in steps"
            :key="s.id"
            class="h-1 flex-1 overflow-hidden rounded-full bg-surface"
          >
            <div
              class="h-full rounded-full bg-brand transition-all duration-400"
              :style="{ width: step >= s.id ? '100%' : '0%' }"
            />
          </div>
        </div>
        <div class="mx-auto mt-2 flex max-w-3xl justify-between text-[10px] font-semibold uppercase tracking-wide text-muted">
          <span v-for="s in steps" :key="s.id" :class="step === s.id ? 'text-brand' : ''">
            {{ s.title }}
          </span>
        </div>
      </div>

      <div class="min-h-0 flex-1 overflow-auto px-4 py-4 md:px-6 md:py-6">
        <p v-if="mailing.error" class="mx-auto mb-4 max-w-3xl text-sm text-danger">{{ mailing.error }}</p>

        <Transition name="wizard-fade" mode="out-in">
          <!-- Step 1: Platform -->
          <div v-if="step === 1" key="s1" class="mx-auto max-w-3xl">
            <p class="mb-5 text-sm text-muted">
              Выберите мессенджер для рассылки. Аккаунты подберём на последнем шаге.
            </p>

            <div class="grid gap-4 sm:grid-cols-3">
              <button
                v-for="group in transportGroups"
                :key="group.key"
                type="button"
                class="relative flex flex-col items-center gap-3 rounded-2xl border p-6 text-center transition"
                :class="[
                  group.disabled
                    ? 'cursor-not-allowed border-line bg-panel opacity-55'
                    : selectedPlatform === group.key
                      ? 'border-brand bg-brand-soft/50 shadow-sm'
                      : 'border-line bg-panel hover:border-brand/40 hover:shadow-sm',
                ]"
                :disabled="group.disabled"
                @click="selectPlatform(group.key)"
              >
                <span
                  v-if="group.disabled"
                  class="absolute right-3 top-3 rounded-md bg-surface px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-muted"
                >
                  скоро
                </span>
                <div
                  class="flex size-14 items-center justify-center rounded-2xl"
                  :class="group.tone"
                >
                  <Radio class="size-7" />
                </div>
                <div>
                  <div class="text-base font-bold tracking-tight">{{ group.label }}</div>
                  <p class="mt-1 text-xs text-muted">
                    {{ group.accounts.length }} online
                  </p>
                </div>
                <div
                  v-if="selectedPlatform === group.key"
                  class="flex size-6 items-center justify-center rounded-full bg-brand text-white"
                >
                  <Check class="size-3.5" />
                </div>
              </button>
            </div>
          </div>

          <!-- Step 2: Recipients -->
          <div v-else-if="step === 2" key="s2" class="mx-auto max-w-3xl">
            <label class="mb-4 block">
              <span class="mb-1 block text-xs font-semibold text-muted">Название кампании</span>
              <input
                v-model="campName"
                class="w-full rounded-xl border border-line bg-panel px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
              />
            </label>

            <div class="mb-3 rounded-2xl border border-line bg-panel p-4">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 class="text-sm font-semibold">База получателей</h3>
                  <p class="mt-1 text-xs text-muted">
                    Загрузите CSV / XLS или вставьте список вручную. Колонки:
                    <span class="font-mono">login</span>,
                    <span class="font-mono">phone</span>.
                    Телефоны работают через личные аккаунты (MAX · аккаунт / Telegram · аккаунт);
                    боты принимают user/chat id.
                  </p>
                </div>
                <div class="flex flex-wrap gap-2">
                  <button
                    type="button"
                    class="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold hover:border-brand hover:text-brand"
                    @click="downloadSample('csv')"
                  >
                    <Download class="size-3.5" />
                    Пример CSV
                  </button>
                  <button
                    type="button"
                    class="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold hover:border-brand hover:text-brand"
                    @click="downloadSample('xlsx')"
                  >
                    <Download class="size-3.5" />
                    Пример XLSX
                  </button>
                </div>
              </div>

              <label
                class="mt-4 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line bg-surface px-4 py-8 transition hover:border-brand hover:bg-brand-soft/30"
              >
                <Upload class="size-6 text-brand" />
                <span class="text-sm font-semibold">
                  {{ fileImporting ? 'Читаем файл…' : 'Загрузить CSV / XLS / XLSX' }}
                </span>
                <span class="text-xs text-muted">
                  {{ importedFileName || 'Одна колонка или login + phone' }}
                </span>
                <input
                  type="file"
                  accept=".csv,.txt,.xls,.xlsx,text/csv,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  class="hidden"
                  :disabled="fileImporting"
                  @change="onRecipientsFile"
                />
              </label>
              <p v-if="fileImportError" class="mt-2 text-xs text-danger">{{ fileImportError }}</p>
            </div>

            <div class="mb-2 flex items-center justify-between">
              <span class="text-xs font-semibold text-muted">Список (можно править)</span>
              <span class="rounded-md bg-brand-soft px-2 py-0.5 text-xs font-bold text-brand">
                {{ recipientCount }} шт.
              </span>
            </div>
            <textarea
              v-model="campRecipients"
              rows="10"
              placeholder="@username&#10;+79001234567&#10;another_user"
              class="w-full rounded-2xl border border-line bg-panel px-4 py-3 font-mono text-sm outline-none ring-brand focus:ring-2"
            />
            <p class="mt-2 text-xs text-muted">Один логин или телефон на строку. Строки с # игнорируются.</p>
          </div>

          <!-- Step 3: Template -->
          <div v-else-if="step === 3" key="s3" class="mx-auto max-w-3xl">
            <p class="mb-4 text-sm text-muted">Выберите готовый шаблон или создайте новый с текстом и медиа.</p>

            <div class="mb-4 flex gap-2">
              <button
                type="button"
                class="rounded-lg px-3 py-1.5 text-xs font-semibold"
                :class="!creatingTemplate ? 'bg-brand text-white' : 'bg-surface text-muted'"
                @click="creatingTemplate = false"
              >
                Выбрать
              </button>
              <button
                type="button"
                class="rounded-lg px-3 py-1.5 text-xs font-semibold"
                :class="creatingTemplate ? 'bg-brand text-white' : 'bg-surface text-muted'"
                @click="creatingTemplate = true"
              >
                Создать новый
              </button>
            </div>

            <form
              v-if="creatingTemplate"
              class="space-y-3 rounded-2xl border border-line bg-panel p-5"
              @submit.prevent="addTemplate"
            >
              <label class="block">
                <span class="mb-1 block text-xs font-semibold text-muted">Название</span>
                <input
                  v-model="tplName"
                  required
                  class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
                  placeholder="Летнее предложение"
                />
              </label>
              <label class="block">
                <span class="mb-1 block text-xs font-semibold text-muted">Текст сообщения</span>
                <textarea
                  v-model="tplBody"
                  rows="5"
                  class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
                  placeholder="Здравствуйте! …"
                />
              </label>
              <div>
                <span class="mb-1 block text-xs font-semibold text-muted">Изображение или видео</span>
                <label
                  class="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line bg-surface px-4 py-8 transition hover:border-brand hover:bg-brand-soft/40"
                >
                  <ImagePlus class="size-6 text-brand" />
                  <span class="text-sm font-semibold">{{ tplMedia ? tplMedia.name : 'Загрузить файл' }}</span>
                  <span class="text-xs text-muted">PNG, JPG, MP4…</span>
                  <input type="file" accept="image/*,video/*" class="hidden" @change="onMediaChange" />
                </label>
                <img
                  v-if="tplPreview"
                  :src="tplPreview"
                  alt=""
                  class="mt-3 max-h-40 rounded-xl object-cover"
                />
              </div>
              <div class="flex justify-end gap-2 pt-1">
                <button
                  v-if="mailing.templates.length"
                  type="button"
                  class="rounded-xl px-4 py-2 text-sm text-muted hover:bg-surface"
                  @click="creatingTemplate = false"
                >
                  Отмена
                </button>
                <button
                  type="submit"
                  class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                  :disabled="tplSaving"
                >
                  {{ tplSaving ? 'Сохраняем…' : 'Сохранить шаблон' }}
                </button>
              </div>
            </form>

            <div v-else class="grid gap-3 sm:grid-cols-2">
              <button
                v-for="t in mailing.templates"
                :key="t.id"
                type="button"
                class="rounded-2xl border p-4 text-left transition"
                :class="
                  campTemplateId === t.id
                    ? 'border-brand bg-brand-soft/50 shadow-sm'
                    : 'border-line bg-panel hover:border-brand/40'
                "
                @click="campTemplateId = t.id"
              >
                <div class="flex items-start justify-between gap-2">
                  <div class="min-w-0">
                    <div class="font-semibold">{{ t.name }}</div>
                    <p class="mt-1 line-clamp-3 text-xs text-muted whitespace-pre-wrap">
                      {{ t.body || 'Без текста' }}
                    </p>
                  </div>
                  <div
                    v-if="campTemplateId === t.id"
                    class="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand text-white"
                  >
                    <Check class="size-3.5" />
                  </div>
                </div>
                <div
                  v-if="t.hasMedia"
                  class="mt-3 inline-flex items-center gap-1 rounded-md bg-surface px-2 py-1 text-[10px] font-bold uppercase text-muted"
                >
                  <FileImage class="size-3" />
                  {{ t.mediaKind }}
                </div>
              </button>
              <p v-if="!mailing.templates.length" class="text-sm text-muted sm:col-span-2">
                Шаблонов нет — создайте первый.
              </p>
            </div>
          </div>

          <!-- Step 4: Accounts + short review -->
          <div v-else key="s4" class="mx-auto max-w-3xl space-y-4">
            <p class="text-sm text-muted">
              Выберите online-аккаунты
              <span v-if="selectedGroup" class="font-semibold text-ink">{{ selectedGroup.label }}</span>.
              Можно несколько — отправка пойдёт по кругу.
            </p>

            <section
              v-if="selectedGroup"
              class="overflow-hidden rounded-2xl border border-line bg-panel"
            >
              <div class="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
                <div class="flex items-center gap-2">
                  <span
                    class="rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide"
                    :class="selectedGroup.tone"
                  >
                    {{ selectedGroup.label }}
                  </span>
                  <span class="text-xs text-muted">
                    {{ platformAccounts.length }} online
                  </span>
                </div>
                <button
                  v-if="platformAccounts.length"
                  type="button"
                  class="text-xs font-semibold text-brand hover:underline"
                  @click="selectAllPlatformAccounts"
                >
                  {{
                    platformAccounts.every((c) => campChannelIds.includes(c.id))
                      ? 'Снять все'
                      : 'Выбрать все'
                  }}
                </button>
              </div>

              <div class="space-y-1 p-2">
                <button
                  v-for="ch in platformAccounts"
                  :key="ch.id"
                  type="button"
                  class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition"
                  :class="
                    campChannelIds.includes(ch.id)
                      ? 'bg-brand-soft/70'
                      : 'hover:bg-surface'
                  "
                  @click="toggleChannel(ch.id)"
                >
                  <div
                    class="flex size-9 shrink-0 items-center justify-center rounded-lg"
                    :class="selectedGroup.tone"
                  >
                    <Radio class="size-4" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="truncate text-sm font-semibold">{{ ch.name }}</div>
                    <div class="truncate text-xs text-muted">
                      {{ transportLabel[ch.transport] }} · {{ ch.identity }}
                    </div>
                  </div>
                  <div
                    class="flex size-5 shrink-0 items-center justify-center rounded-md border"
                    :class="
                      campChannelIds.includes(ch.id)
                        ? 'border-brand bg-brand text-white'
                        : 'border-line bg-panel'
                    "
                  >
                    <Check v-if="campChannelIds.includes(ch.id)" class="size-3" />
                  </div>
                </button>

                <p
                  v-if="!platformAccounts.length"
                  class="px-3 py-3 text-xs text-muted"
                >
                  Нет online-аккаунтов — добавьте ниже.
                </p>
              </div>

              <div
                v-if="canManageChannels"
                class="flex flex-wrap gap-2 border-t border-line bg-surface/60 px-3 py-2.5"
              >
                <button
                  v-for="opt in selectedGroup.addOptions"
                  :key="opt.transport"
                  type="button"
                  class="inline-flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-semibold transition hover:border-brand hover:text-brand disabled:cursor-not-allowed disabled:opacity-40"
                  :disabled="!opt.ready"
                  @click="addAccount(opt.transport)"
                >
                  <Plus class="size-3.5" />
                  {{ opt.ready ? `Добавить ${opt.label}` : `${opt.label} · скоро` }}
                </button>
              </div>
            </section>

            <div class="rounded-2xl border border-line bg-panel p-5">
              <h2 class="text-base font-bold">{{ campName || 'Без названия' }}</h2>
              <dl class="mt-4 grid gap-4 sm:grid-cols-2">
                <div>
                  <dt class="text-[11px] font-bold uppercase tracking-wide text-muted">Шаблон</dt>
                  <dd class="mt-1 text-sm font-semibold">{{ selectedTemplate?.name || '—' }}</dd>
                  <p class="mt-1 line-clamp-3 text-xs text-muted whitespace-pre-wrap">
                    {{ selectedTemplate?.body || '' }}
                  </p>
                </div>
                <div>
                  <dt class="text-[11px] font-bold uppercase tracking-wide text-muted">Параметры</dt>
                  <dd class="mt-1 space-y-1 text-sm">
                    <div class="flex items-center gap-2">
                      <Users class="size-3.5 text-muted" />
                      {{ recipientCount }} получателей
                    </div>
                    <div class="flex items-center gap-2">
                      <Radio class="size-3.5 text-muted" />
                      {{ selectedChannels.length }} аккаунтов
                    </div>
                    <label class="mt-2 flex items-center gap-2 text-xs text-muted">
                      Пауза
                      <input
                        v-model.number="campDelay"
                        type="number"
                        min="1"
                        max="300"
                        class="w-16 rounded-lg border border-line bg-surface px-2 py-1 text-sm text-ink"
                      />
                      сек
                    </label>
                  </dd>
                </div>
              </dl>
              <p class="mt-4 rounded-xl bg-surface px-3 py-2.5 text-xs text-muted">
                Каждый контакт получит одно сообщение с одного аккаунта — без дублей
              </p>
            </div>
          </div>
        </Transition>
      </div>

      <div class="border-t border-line bg-panel px-6 py-4">
        <div class="mx-auto flex max-w-3xl items-center justify-between gap-3">
          <button
            type="button"
            class="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-muted hover:bg-surface"
            @click="prevStep"
          >
            <ArrowLeft class="size-4" />
            Назад
          </button>
          <button
            v-if="step < 4"
            type="button"
            class="inline-flex items-center gap-2 rounded-xl bg-brand px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-45"
            :disabled="!stepValid"
            @click="nextStep"
          >
            Далее
            <ArrowRight class="size-4" />
          </button>
          <button
            v-else
            type="button"
            class="inline-flex items-center gap-2 rounded-xl bg-brand px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-45"
            :disabled="!stepValid || campSaving"
            @click="launchCampaign"
          >
            <Play class="size-4" />
            {{ campSaving ? 'Запускаем…' : 'Создать и запустить' }}
          </button>
        </div>
      </div>
    </div>

    <!-- DETAIL -->
    <div v-else-if="mode === 'detail' && mailing.activeCampaign" class="flex min-h-0 flex-1 flex-col">
      <div class="border-b border-line bg-panel px-6 py-4">
        <div class="mx-auto flex max-w-4xl items-start justify-between gap-4">
          <div class="flex items-start gap-3">
            <button
              type="button"
              class="mt-0.5 rounded-lg p-2 text-muted hover:bg-surface"
              @click="backToList"
            >
              <X class="size-4" />
            </button>
            <div>
              <h1 class="text-xl font-bold tracking-tight">{{ mailing.activeCampaign.name }}</h1>
              <p class="mt-0.5 text-sm text-muted">
                {{ statusLabel[mailing.activeCampaign.status] }} ·
                {{ mailing.activeCampaign.sent }}/{{ mailing.activeCampaign.total }}
                <span v-if="mailing.activeCampaign.failed">
                  · ошибок {{ mailing.activeCampaign.failed }}
                </span>
              </p>
              <div class="mt-3 h-2 w-56 overflow-hidden rounded-full bg-surface sm:w-72">
                <div
                  class="h-full rounded-full bg-brand transition-all duration-500"
                  :style="{ width: `${progressPct}%` }"
                />
              </div>
            </div>
          </div>
          <div class="flex gap-2">
            <button
              v-if="mailing.activeCampaign.status === 'draft' || mailing.activeCampaign.status === 'paused'"
              type="button"
              class="inline-flex items-center gap-1.5 rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white"
              @click="mailing.startCampaign(mailing.activeCampaign.id)"
            >
              <Play class="size-4" /> Старт
            </button>
            <button
              v-else-if="mailing.activeCampaign.status === 'running'"
              type="button"
              class="inline-flex items-center gap-1.5 rounded-xl border border-line px-4 py-2 text-sm font-semibold"
              @click="mailing.pauseCampaign(mailing.activeCampaign.id)"
            >
              <Pause class="size-4" /> Пауза
            </button>
          </div>
        </div>
      </div>

      <div class="min-h-0 flex-1 overflow-auto p-4 md:p-6">
        <div class="mx-auto max-w-4xl overflow-x-auto rounded-2xl border border-line bg-panel">
          <table class="w-full min-w-[480px] text-left text-sm">
            <thead class="border-b border-line bg-surface text-[11px] uppercase tracking-wide text-muted">
              <tr>
                <th class="px-4 py-3">Получатель</th>
                <th class="px-4 py-3">Тип</th>
                <th class="px-4 py-3">Статус</th>
                <th class="px-4 py-3">Ошибка</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in mailing.activeCampaign.recipients"
                :key="r.id"
                class="border-b border-line last:border-0"
              >
                <td class="px-4 py-2.5 font-mono text-xs">{{ r.normalized }}</td>
                <td class="px-4 py-2.5 text-xs text-muted">{{ r.kind }}</td>
                <td class="px-4 py-2.5 text-xs">{{ statusLabel[r.status] || r.status }}</td>
                <td class="max-w-[280px] truncate px-4 py-2.5 text-xs text-danger">
                  {{ r.error || '—' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <AddChannelModal v-if="channels.connectOpen && canManageChannels" />
  </div>
</template>

<style scoped>
.wizard-fade-enter-active,
.wizard-fade-leave-active {
  transition:
    opacity 0.2s ease,
    transform 0.2s ease;
}
.wizard-fade-enter-from {
  opacity: 0;
  transform: translateX(12px);
}
.wizard-fade-leave-to {
  opacity: 0;
  transform: translateX(-8px);
}
</style>
