<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import QRCode from 'qrcode'
import Modal from '@/components/ui/Modal.vue'
import { useChannelsStore } from '@/stores/channels'
import { listDepartmentsRequest, mapDepartment } from '@/api/settings'
import type { ChannelTransport, Department } from '@/types'
import { transportLabel } from '@/types'

const channels = useChannelsStore()
const qrDataUrl = ref('')
const departments = ref<Department[]>([])

const options: { transport: ChannelTransport; hint: string; ready: boolean }[] = [
  { transport: 'maxbot', hint: 'Токен бота из кабинета MAX', ready: true },
  { transport: 'max', hint: 'Личный аккаунт по QR (PyMax)', ready: true },
  { transport: 'telegram', hint: 'Токен от @BotFather', ready: true },
  { transport: 'tgapi', hint: 'Личный аккаунт по QR (Telethon)', ready: true },
]

const title = computed(() => {
  if (channels.connectStep === 'details') return 'Название и отдел'
  if (channels.connectStep === 'bot_token') return 'Токен бота'
  if (channels.connectStep === 'qr') return 'Сканируйте QR'
  return 'Добавить канал'
})

const namePlaceholder = computed(() => {
  const t = channels.selectedTransport
  if (!t) return 'Например: Продажи · MAX бот'
  return `Например: Продажи · ${transportLabel[t]}`
})

async function renderQr(url: string) {
  if (!url) {
    qrDataUrl.value = ''
    return
  }
  try {
    qrDataUrl.value = await QRCode.toDataURL(url, {
      width: 240,
      margin: 2,
      color: { dark: '#152033', light: '#ffffff' },
    })
  } catch {
    qrDataUrl.value = ''
    channels.connectError = 'Не удалось отрисовать QR'
  }
}

watch(
  () => channels.qrUrl,
  (url) => {
    void renderQr(url)
  },
)

onMounted(async () => {
  void renderQr(channels.qrUrl)
  try {
    departments.value = (await listDepartmentsRequest()).map(mapDepartment)
    if (channels.departmentId == null && departments.value.length) {
      channels.departmentId = departments.value[0].id
    }
  } catch {
    departments.value = []
  }
})

watch(
  () => channels.selectedTransport,
  (t) => {
    if (!t || channels.channelName.trim()) return
    const dept = departments.value.find((d) => d.id === channels.departmentId)
    const deptPart = dept?.name || 'Общий'
    channels.channelName = `${deptPart} · ${transportLabel[t]}`
  },
)

watch(
  () => channels.departmentId,
  (id) => {
    if (!channels.selectedTransport || !id) return
    const dept = departments.value.find((d) => d.id === id)
    if (!dept) return
    // refresh suggested name if it still looks auto-generated
    const suffix = transportLabel[channels.selectedTransport]
    if (!channels.channelName.trim() || channels.channelName.includes(' · ')) {
      channels.channelName = `${dept.name} · ${suffix}`
    }
  },
)
</script>

<template>
  <Modal :title="title" @close="channels.closeConnect()">
    <div v-if="channels.connectStep === 'pick'" class="grid gap-2">
      <button
        v-for="opt in options"
        :key="opt.transport"
        type="button"
        class="flex items-center justify-between rounded-xl border border-line px-4 py-3 text-left transition hover:border-brand hover:bg-brand-soft disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-line disabled:hover:bg-transparent"
        :disabled="!opt.ready || channels.connecting"
        @click="channels.pickTransport(opt.transport)"
      >
        <div>
          <div class="text-sm font-semibold">{{ transportLabel[opt.transport] }}</div>
          <div class="text-xs text-muted">{{ opt.hint }}</div>
        </div>
        <span v-if="!opt.ready" class="text-[10px] font-bold uppercase text-muted">soon</span>
      </button>
      <p v-if="channels.connectError" class="mt-2 text-sm text-danger">{{ channels.connectError }}</p>
    </div>

    <div v-else-if="channels.connectStep === 'details'" class="space-y-4">
      <p class="text-sm text-muted">
        Дайте каналу понятное имя (отдел + мессенджер) и привяжите к отделу — так будет ясно, кому назначать чаты.
      </p>
      <label class="block">
        <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
          Название
        </span>
        <input
          v-model="channels.channelName"
          type="text"
          :placeholder="namePlaceholder"
          class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
        />
      </label>
      <label class="block">
        <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
          Отдел
        </span>
        <select
          v-model.number="channels.departmentId"
          class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm outline-none"
        >
          <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>
      <p v-if="channels.connectError" class="text-sm text-danger">{{ channels.connectError }}</p>
      <div class="flex justify-end gap-2">
        <button
          type="button"
          class="rounded-xl px-4 py-2 text-sm text-muted hover:bg-surface"
          @click="channels.connectStep = 'pick'"
        >
          Назад
        </button>
        <button
          type="button"
          class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white"
          @click="channels.continueFromDetails()"
        >
          Далее
        </button>
      </div>
    </div>

    <div v-else-if="channels.connectStep === 'bot_token'" class="space-y-4">
      <p class="text-sm text-muted">
        <template v-if="channels.selectedTransport === 'telegram'">
          Вставьте токен бота от
          <span class="font-mono text-xs">@BotFather</span>.
        </template>
        <template v-else>
          Вставьте access token бота MAX.
        </template>
        Канал: <strong>{{ channels.channelName }}</strong>
      </p>
      <label class="block">
        <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">Токен</span>
        <input
          v-model="channels.botToken"
          type="text"
          placeholder="token..."
          class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 font-mono text-sm outline-none ring-brand focus:ring-2"
        />
      </label>
      <p v-if="channels.connectError" class="text-sm text-danger">{{ channels.connectError }}</p>
      <div class="flex justify-end gap-2">
        <button
          type="button"
          class="rounded-xl px-4 py-2 text-sm text-muted hover:bg-surface"
          @click="channels.connectStep = 'details'"
        >
          Назад
        </button>
        <button
          type="button"
          class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          :disabled="channels.connecting"
          @click="channels.connectBot()"
        >
          {{ channels.connecting ? 'Подключаем…' : 'Подключить' }}
        </button>
      </div>
    </div>

    <div v-else-if="channels.connectStep === 'qr'" class="space-y-4 text-center">
      <p class="text-sm text-muted">
        Канал: <strong>{{ channels.channelName }}</strong>
        · статус:
        <span class="font-mono">{{ channels.qrStatus || '…' }}</span>
      </p>
      <div class="mx-auto flex size-60 items-center justify-center rounded-2xl border border-line bg-white p-3">
        <img v-if="qrDataUrl" :src="qrDataUrl" alt="QR для входа" class="size-full" />
        <span v-else class="text-sm text-muted">{{ channels.connecting ? 'Получаем QR…' : 'Нет QR' }}</span>
      </div>

      <div v-if="channels.need2fa" class="space-y-3 text-left">
        <p class="text-sm text-muted">
          Нужен пароль 2FA
          <span v-if="channels.qrHint">({{ channels.qrHint }})</span>
        </p>
        <input
          v-model="channels.qrPassword"
          type="password"
          class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
          placeholder="Пароль"
        />
        <button
          type="button"
          class="w-full rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
          :disabled="channels.connecting || !channels.qrPassword.trim()"
          @click="channels.submit2fa()"
        >
          Отправить пароль
        </button>
      </div>

      <p v-if="channels.connectError" class="text-sm text-danger">{{ channels.connectError }}</p>
    </div>
  </Modal>
</template>
