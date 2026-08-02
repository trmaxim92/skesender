<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useTemplatesStore } from '@/stores/templates'
import type { ChannelTransport } from '@/types'

const templates = useTemplatesStore()

const name = ref('Обращение закрыто')
const body = ref('')
const transport = ref<ChannelTransport | 'all'>('all')

onMounted(async () => {
  await templates.fetchCloseTemplate()
  syncFromStore()
})

watch(
  () => templates.closeTemplate,
  () => syncFromStore(),
)

function syncFromStore() {
  const t = templates.closeTemplate
  if (!t) return
  name.value = t.name
  body.value = t.body
  transport.value = t.transport
}

async function save() {
  if (!body.value.trim()) return
  const ok = await templates.saveCloseTemplate({
    name: name.value.trim() || 'Обращение закрыто',
    body: body.value.trim(),
    transport: transport.value,
  })
  if (ok) syncFromStore()
}
</script>

<template>
  <div class="h-full overflow-auto p-6">
    <div class="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 class="text-lg font-bold tracking-tight">Шаблон закрытия обращения</h1>
        <p class="mt-1 text-sm text-muted">
          Системный текст клиенту при закрытии обращения. Личные быстрые ответы операторы правят в
          профиле → «Мои шаблоны».
        </p>
      </div>

      <p v-if="templates.error" class="text-sm text-danger">{{ templates.error }}</p>
      <p v-if="templates.loading" class="text-sm text-muted">Загрузка…</p>

      <label class="block">
        <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
          Название
        </span>
        <input
          v-model="name"
          type="text"
          class="w-full rounded-xl border border-line bg-panel px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
        />
      </label>

      <label class="block">
        <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
          Канал
        </span>
        <select
          v-model="transport"
          class="w-full rounded-xl border border-line bg-panel px-3.5 py-2.5 text-sm"
        >
          <option value="all">Все каналы</option>
          <option value="maxbot">MAX · бот</option>
          <option value="max">MAX · аккаунт</option>
          <option value="telegram">Telegram · бот</option>
          <option value="tgapi">Telegram · аккаунт</option>
        </select>
      </label>

      <label class="block">
        <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
          Текст
        </span>
        <textarea
          v-model="body"
          rows="6"
          class="w-full resize-y rounded-xl border border-line bg-panel px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
          placeholder="Текст сообщения клиенту"
        />
        <span class="mt-1.5 block text-[11px] text-muted">
          Плейсхолдеры:
          <code v-pre class="font-mono">{{operator}}</code>,
          <code v-pre class="font-mono">{{contact}}</code>,
          <code v-pre class="font-mono">{{appeal}}</code>
        </span>
      </label>

      <div class="flex justify-end">
        <button
          type="button"
          class="rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="templates.saving || !body.trim()"
          @click="save"
        >
          {{ templates.saving ? '…' : 'Сохранить' }}
        </button>
      </div>
    </div>
  </div>
</template>
