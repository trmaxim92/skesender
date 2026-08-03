<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'
import ContactAvatar from '@/components/chats/ContactAvatar.vue'
import type { DialogSidebar, FieldDefinition } from '@/types'
import { appealStatusLabel, transportLabel } from '@/types'
import { useAuthStore } from '@/stores/auth'
import { useChatsStore } from '@/stores/chats'

const props = defineProps<{
  open: boolean
  loading?: boolean
  data: DialogSidebar | null
}>()

defineEmits<{ close: [] }>()

const auth = useAuthStore()
const chats = useChatsStore()

const tab = ref<'client' | 'appeal'>('client')
const selectedAppealId = ref<number | null>(null)
const clientDraft = ref<Record<string, string>>({})
const appealDraft = ref<Record<string, string>>({})
const saving = ref(false)
const canWrite = computed(() => auth.can('action.write'))

const shownAppeal = computed(() => {
  if (!props.data) return null
  if (selectedAppealId.value != null) {
    return props.data.appeals.find((a) => a.id === selectedAppealId.value) ?? props.data.currentAppeal
  }
  return props.data.currentAppeal
})

watch(
  () => props.data,
  (data) => {
    if (!data) return
    clientDraft.value = { ...data.clientValues }
    appealDraft.value = { ...data.appealValues }
    selectedAppealId.value = chats.viewingAppealId ?? data.currentAppeal?.id ?? null
  },
  { immediate: true },
)

watch(
  () => chats.viewingAppealId,
  (id) => {
    if (id != null) selectedAppealId.value = id
  },
)

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

async function saveClient() {
  if (!canWrite.value) return
  saving.value = true
  const values = Object.entries(clientDraft.value)
    .filter(([key]) => !['full_name', 'phone', 'external_id'].includes(key))
    .map(([key, value]) => ({ key, value }))
  await chats.saveClientFields({
    full_name: clientDraft.value.full_name ?? '',
    phone: clientDraft.value.phone ?? '',
    external_id: clientDraft.value.external_id ?? '',
    values,
  })
  saving.value = false
}

async function saveAppeal() {
  if (!canWrite.value || !shownAppeal.value) return
  if (shownAppeal.value.id !== props.data?.currentAppeal?.id) return
  saving.value = true
  const values = Object.entries(appealDraft.value).map(([key, value]) => ({ key, value }))
  await chats.saveAppealFields(shownAppeal.value.id, values)
  saving.value = false
}

async function onSelectHistoryAppeal(appealId: number) {
  selectedAppealId.value = appealId
  await chats.selectAppeal(appealId)
  if (appealId === props.data?.currentAppeal?.id) {
    appealDraft.value = { ...(props.data?.appealValues ?? {}) }
  } else {
    // Past appeal: thread switched; fields stay tied to current appeal values API.
    appealDraft.value = {}
  }
}

function fieldInputType(f: FieldDefinition) {
  if (f.fieldType === 'number') return 'number'
  if (f.fieldType === 'phone') return 'tel'
  if (f.fieldType === 'date') return 'date'
  if (f.fieldType === 'link') return 'url'
  return 'text'
}

function linkHref(value: string | undefined) {
  const raw = (value || '').trim()
  if (!raw) return ''
  if (/^https?:\/\//i.test(raw)) return raw
  return `https://${raw}`
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-40 flex justify-end">
      <button
        type="button"
        class="absolute inset-0 bg-ink/30"
        aria-label="Закрыть панель"
        @click="$emit('close')"
      />
      <aside
        class="relative z-10 flex h-full w-full max-w-[360px] flex-col border-l border-line bg-panel shadow-xl"
      >
        <header class="flex items-center justify-between border-b border-line px-4 py-3">
          <div class="flex gap-1 rounded-lg bg-surface p-0.5">
            <button
              type="button"
              class="rounded-md px-3 py-1.5 text-xs font-semibold transition"
              :class="tab === 'client' ? 'bg-panel text-ink shadow-sm' : 'text-muted'"
              @click="tab = 'client'"
            >
              Клиент
            </button>
            <button
              type="button"
              class="rounded-md px-3 py-1.5 text-xs font-semibold transition"
              :class="tab === 'appeal' ? 'bg-panel text-ink shadow-sm' : 'text-muted'"
              @click="tab = 'appeal'"
            >
              Обращение
            </button>
          </div>
          <button
            type="button"
            class="rounded-lg p-1.5 text-muted hover:bg-surface hover:text-ink"
            @click="$emit('close')"
          >
            <X class="size-4" />
          </button>
        </header>

        <div class="min-h-0 flex-1 overflow-auto p-4">
          <p v-if="loading" class="text-sm text-muted">Загрузка…</p>
          <template v-else-if="data">
            <div v-if="tab === 'client'" class="space-y-4">
              <div class="flex items-center gap-3">
                <ContactAvatar
                  :name="data.client.contactName"
                  :url="data.client.contactAvatarUrl"
                  size="lg"
                />
                <div class="min-w-0">
                  <div class="truncate text-sm font-semibold">{{ data.client.contactName }}</div>
                  <div class="text-[11px] text-muted">
                    {{ data.client.channelName || '—' }}
                    <span v-if="data.client.transport">
                      · {{ transportLabel[data.client.transport] }}
                    </span>
                  </div>
                </div>
              </div>

              <div
                v-for="f in data.clientFields"
                :key="f.key"
                class="space-y-1"
              >
                <label class="text-[11px] font-semibold uppercase tracking-wide text-muted">
                  {{ f.label }}
                  <span v-if="f.isSystem" class="normal-case text-muted/70">(базовое)</span>
                </label>
                <textarea
                  v-if="f.fieldType === 'textarea'"
                  v-model="clientDraft[f.key]"
                  rows="3"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  :readonly="!canWrite"
                />
                <select
                  v-else-if="f.fieldType === 'select'"
                  v-model="clientDraft[f.key]"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  :disabled="!canWrite"
                >
                  <option value="">—</option>
                  <option v-for="opt in f.options" :key="opt" :value="opt">{{ opt }}</option>
                </select>
                <div v-else-if="f.fieldType === 'link'" class="space-y-1.5">
                  <input
                    v-model="clientDraft[f.key]"
                    type="url"
                    placeholder="https://"
                    class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                    :readonly="!canWrite"
                  />
                  <a
                    v-if="clientDraft[f.key]?.trim()"
                    :href="linkHref(clientDraft[f.key])"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="inline-block text-xs font-semibold text-brand hover:underline"
                  >
                    Открыть ссылку
                  </a>
                </div>
                <label
                  v-else-if="f.fieldType === 'bool'"
                  class="flex items-center gap-2 text-sm"
                >
                  <input
                    type="checkbox"
                    :checked="clientDraft[f.key] === 'true' || clientDraft[f.key] === '1'"
                    :disabled="!canWrite"
                    @change="
                      clientDraft[f.key] = ($event.target as HTMLInputElement).checked
                        ? 'true'
                        : 'false'
                    "
                  />
                  Да
                </label>
                <input
                  v-else
                  v-model="clientDraft[f.key]"
                  :type="fieldInputType(f)"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  :readonly="!canWrite"
                />
              </div>

              <div class="space-y-1 text-xs text-muted">
                <div>Username: {{ data.client.contactUsername || '—' }}</div>
                <div>Диалог с: {{ formatDate(data.client.dialogCreatedAt) }}</div>
                <div>Обращений: {{ data.client.appealsCount }}</div>
              </div>

              <button
                v-if="canWrite"
                type="button"
                class="w-full rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
                :disabled="saving"
                @click="saveClient"
              >
                {{ saving ? 'Сохранение…' : 'Сохранить клиента' }}
              </button>
            </div>

            <div v-else class="space-y-4">
              <div v-if="shownAppeal" class="rounded-2xl border border-line bg-surface p-3">
                <div class="flex items-center justify-between gap-2">
                  <div class="text-sm font-semibold">#{{ shownAppeal.number }}</div>
                  <span
                    class="rounded-full px-2 py-0.5 text-[10px] font-bold"
                    :class="
                      shownAppeal.status === 'open'
                        ? 'bg-ok/15 text-ok'
                        : 'bg-muted/15 text-muted'
                    "
                  >
                    {{ appealStatusLabel[shownAppeal.status] }}
                  </span>
                </div>
                <dl class="mt-3 space-y-2 text-xs">
                  <div class="flex justify-between gap-2">
                    <dt class="text-muted">Открыто</dt>
                    <dd>{{ formatDate(shownAppeal.openedAt) }}</dd>
                  </div>
                  <div class="flex justify-between gap-2">
                    <dt class="text-muted">Закрыто</dt>
                    <dd>{{ formatDate(shownAppeal.closedAt) }}</dd>
                  </div>
                  <div class="flex justify-between gap-2">
                    <dt class="text-muted">Оператор</dt>
                    <dd>{{ data.client.assigneeName || '—' }}</dd>
                  </div>
                </dl>
              </div>

              <div
                v-for="f in data.appealFields"
                v-show="shownAppeal?.id === data.currentAppeal?.id"
                :key="f.key"
                class="space-y-1"
              >
                <label class="text-[11px] font-semibold uppercase tracking-wide text-muted">
                  {{ f.label }}
                </label>
                <textarea
                  v-if="f.fieldType === 'textarea'"
                  v-model="appealDraft[f.key]"
                  rows="3"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  :readonly="!canWrite"
                />
                <select
                  v-else-if="f.fieldType === 'select'"
                  v-model="appealDraft[f.key]"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  :disabled="!canWrite"
                >
                  <option value="">—</option>
                  <option v-for="opt in f.options" :key="opt" :value="opt">{{ opt }}</option>
                </select>
                <div v-else-if="f.fieldType === 'link'" class="space-y-1.5">
                  <input
                    v-model="appealDraft[f.key]"
                    type="url"
                    placeholder="https://"
                    class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                    :readonly="!canWrite"
                  />
                  <a
                    v-if="appealDraft[f.key]?.trim()"
                    :href="linkHref(appealDraft[f.key])"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="inline-block text-xs font-semibold text-brand hover:underline"
                  >
                    Открыть ссылку
                  </a>
                </div>
                <label
                  v-else-if="f.fieldType === 'bool'"
                  class="flex items-center gap-2 text-sm"
                >
                  <input
                    type="checkbox"
                    :checked="appealDraft[f.key] === 'true' || appealDraft[f.key] === '1'"
                    :disabled="!canWrite"
                    @change="
                      appealDraft[f.key] = ($event.target as HTMLInputElement).checked
                        ? 'true'
                        : 'false'
                    "
                  />
                  Да
                </label>
                <input
                  v-else
                  v-model="appealDraft[f.key]"
                  :type="fieldInputType(f)"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  :readonly="!canWrite"
                />
              </div>

              <p
                v-if="shownAppeal && shownAppeal.id !== data.currentAppeal?.id"
                class="rounded-xl border border-line bg-surface px-3 py-2 text-xs text-muted"
              >
                Показана история обращения #{{ shownAppeal.number }}. Поля редактируются у
                текущего обращения.
              </p>

              <p v-else-if="!data.appealFields.length" class="text-xs text-muted">
                Для отдела этого чата пока нет кастомных полей обращения.
              </p>

              <button
                v-if="
                  canWrite &&
                  shownAppeal &&
                  shownAppeal.id === data.currentAppeal?.id &&
                  data.appealFields.length
                "
                type="button"
                class="w-full rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
                :disabled="saving"
                @click="saveAppeal"
              >
                {{ saving ? 'Сохранение…' : 'Сохранить обращение' }}
              </button>

              <div>
                <div class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
                  История обращений
                </div>
                <div class="space-y-1.5">
                  <button
                    v-for="a in data.appeals"
                    :key="a.id"
                    type="button"
                    class="flex w-full items-center justify-between rounded-xl border border-line px-3 py-2 text-left text-xs transition hover:border-brand/40 hover:bg-brand-soft/40"
                    :class="shownAppeal?.id === a.id ? 'border-brand/50 bg-brand-soft/50' : 'bg-panel'"
                    @click="onSelectHistoryAppeal(a.id)"
                  >
                    <span class="font-semibold">#{{ a.number }}</span>
                    <span class="text-muted">{{ appealStatusLabel[a.status] }}</span>
                  </button>
                </div>
              </div>
            </div>
          </template>
        </div>
      </aside>
    </div>
  </Teleport>
</template>
