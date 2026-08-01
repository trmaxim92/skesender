<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Search, Trash2 } from 'lucide-vue-next'
import CreateAppealModal from '@/components/appeals/CreateAppealModal.vue'
import { useAppealsStore } from '@/stores/appeals'
import { useAuthStore } from '@/stores/auth'
import { useChannelsStore } from '@/stores/channels'
import { appealStatusLabel, transportLabel } from '@/types'

const appeals = useAppealsStore()
const channels = useChannelsStore()
const auth = useAuthStore()
const router = useRouter()

const createOpen = ref(false)
const deletingId = ref<number | null>(null)
const canCreate = computed(() => auth.can('section.chats') && auth.can('action.write'))
const canDelete = computed(() => auth.can('action.delete_appeals'))

onMounted(() => {
  void appeals.fetchAppeals()
})

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

function openAppeal(appealId: number) {
  void router.push({ name: 'appeal-detail', params: { appealId: String(appealId) } })
}

function onSubmit() {
  void appeals.search()
}

async function openCreate() {
  createOpen.value = true
  if (!channels.channels.length) {
    void channels.fetchChannels()
  }
}

function onCreated(dialogId: number) {
  createOpen.value = false
  void router.push({ name: 'chats', query: { dialog: String(dialogId) } })
}

async function onDelete(a: { id: number; number: number; contactName: string }, event: Event) {
  event.stopPropagation()
  if (!canDelete.value || deletingId.value != null) return
  const ok = window.confirm(
    `Удалить обращение #${a.number} (${a.contactName})?\nСообщения этого обращения будут удалены безвозвратно.`,
  )
  if (!ok) return
  deletingId.value = a.id
  try {
    await appeals.removeAppeal(a.id)
  } finally {
    deletingId.value = null
  }
}

const pageFrom = () => (appeals.total ? appeals.offset + 1 : 0)
const pageTo = () => Math.min(appeals.offset + appeals.items.length, appeals.total)
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <div class="border-b border-line bg-panel px-6 py-4">
      <div class="mb-4 flex items-center justify-between gap-3">
        <div>
          <h1 class="text-lg font-bold tracking-tight text-ink">Обращения</h1>
          <p class="text-xs text-muted">История тикетов и исходящий старт диалога</p>
        </div>
        <button
          v-if="canCreate"
          type="button"
          class="inline-flex size-10 items-center justify-center rounded-xl bg-brand text-white shadow-sm transition hover:opacity-90"
          title="Создать обращение"
          @click="openCreate"
        >
          <Plus class="size-5" />
        </button>
      </div>

      <form class="flex flex-wrap items-end gap-3" @submit.prevent="onSubmit">
        <label class="min-w-[220px] flex-1">
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
            Поиск
          </span>
          <div class="relative">
            <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input
              v-model="appeals.q"
              type="search"
              placeholder="Номер, имя, логин, текст сообщения…"
              class="w-full rounded-xl border border-line bg-surface py-2 pl-9 pr-3 text-sm outline-none ring-brand focus:ring-2"
            />
          </div>
        </label>

        <label>
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
            Статус
          </span>
          <select
            v-model="appeals.status"
            class="rounded-xl border border-line bg-surface px-3 py-2 text-sm"
            @change="appeals.search()"
          >
            <option value="all">Все</option>
            <option value="open">Открытые</option>
            <option value="closed">Закрытые</option>
          </select>
        </label>

        <label>
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
            Оператор
          </span>
          <select
            v-model="appeals.assignee"
            class="rounded-xl border border-line bg-surface px-3 py-2 text-sm"
            @change="appeals.search()"
          >
            <option value="all">Все</option>
            <option value="mine">Мои</option>
            <option value="unassigned">Свободные</option>
          </select>
        </label>

        <label>
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
            С
          </span>
          <input
            v-model="appeals.dateFrom"
            type="date"
            class="rounded-xl border border-line bg-surface px-3 py-2 text-sm"
            @change="appeals.search()"
          />
        </label>

        <label>
          <span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">
            По
          </span>
          <input
            v-model="appeals.dateTo"
            type="date"
            class="rounded-xl border border-line bg-surface px-3 py-2 text-sm"
            @change="appeals.search()"
          />
        </label>

        <button
          type="submit"
          class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="appeals.loading"
        >
          Найти
        </button>
      </form>
    </div>

    <div class="min-h-0 flex-1 overflow-auto p-6">
      <p v-if="appeals.error" class="mb-4 text-sm text-danger">{{ appeals.error }}</p>
      <p v-if="appeals.loading && !appeals.items.length" class="text-sm text-muted">Загрузка…</p>
      <p
        v-else-if="!appeals.loading && !appeals.items.length"
        class="text-sm text-muted"
      >
        Обращений не найдено
      </p>

      <div v-else class="overflow-hidden rounded-2xl border border-line bg-panel">
        <table class="w-full text-left text-sm">
          <thead class="border-b border-line bg-surface text-[11px] uppercase tracking-wide text-muted">
            <tr>
              <th class="px-4 py-3 font-semibold">#</th>
              <th class="px-4 py-3 font-semibold">Клиент</th>
              <th class="px-4 py-3 font-semibold">Статус</th>
              <th class="px-4 py-3 font-semibold">Канал</th>
              <th class="px-4 py-3 font-semibold">Оператор</th>
              <th class="px-4 py-3 font-semibold">Открыто</th>
              <th class="px-4 py-3 font-semibold">Последнее</th>
              <th v-if="canDelete" class="w-12 px-2 py-3" />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="a in appeals.items"
              :key="a.id"
              class="cursor-pointer border-b border-line last:border-0 transition hover:bg-brand-soft/40"
              @click="openAppeal(a.id)"
            >
              <td class="px-4 py-3 font-semibold">#{{ a.number }}</td>
              <td class="px-4 py-3">
                <div class="flex items-center gap-3">
                  <div
                    class="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface text-xs font-bold text-muted"
                  >
                    <img
                      v-if="a.contactAvatarUrl"
                      :src="a.contactAvatarUrl"
                      :alt="a.contactName"
                      class="size-full object-cover"
                      loading="lazy"
                      referrerpolicy="no-referrer"
                    />
                    <span v-else>{{ a.contactName.slice(0, 1) }}</span>
                  </div>
                  <div class="min-w-0">
                    <div class="truncate font-semibold">{{ a.contactName }}</div>
                    <div class="truncate text-xs text-muted">
                      {{ a.contactUsername ? `@${a.contactUsername}` : a.contactExternalId || '—' }}
                    </div>
                  </div>
                </div>
              </td>
              <td class="px-4 py-3">
                <span
                  class="rounded-full px-2 py-0.5 text-[10px] font-bold"
                  :class="a.status === 'open' ? 'bg-ok/15 text-ok' : 'bg-muted/15 text-muted'"
                >
                  {{ appealStatusLabel[a.status] }}
                </span>
              </td>
              <td class="px-4 py-3 text-xs text-muted">
                {{ a.channelName || '—' }}
                <span v-if="a.transport"> · {{ transportLabel[a.transport] }}</span>
              </td>
              <td class="px-4 py-3 text-xs">{{ a.assigneeName || 'Не назначен' }}</td>
              <td class="px-4 py-3 text-xs text-muted">{{ formatDate(a.openedAt) }}</td>
              <td class="max-w-[220px] truncate px-4 py-3 text-xs text-muted">
                {{ a.lastMessage || '—' }}
              </td>
              <td v-if="canDelete" class="px-2 py-3" @click.stop>
                <button
                  type="button"
                  class="rounded-lg p-1.5 text-muted transition hover:bg-danger/10 hover:text-danger disabled:opacity-40"
                  :disabled="deletingId === a.id"
                  title="Удалить обращение"
                  @click="onDelete(a, $event)"
                >
                  <Trash2 class="size-3.5" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div
        v-if="appeals.total"
        class="mt-4 flex items-center justify-between text-xs text-muted"
      >
        <span>
          {{ pageFrom() }}–{{ pageTo() }} из {{ appeals.total }}
        </span>
        <div class="flex gap-2">
          <button
            type="button"
            class="rounded-lg border border-line px-3 py-1.5 font-semibold disabled:opacity-40"
            :disabled="appeals.offset <= 0 || appeals.loading"
            @click="appeals.prevPage()"
          >
            Назад
          </button>
          <button
            type="button"
            class="rounded-lg border border-line px-3 py-1.5 font-semibold disabled:opacity-40"
            :disabled="appeals.offset + appeals.limit >= appeals.total || appeals.loading"
            @click="appeals.nextPage()"
          >
            Далее
          </button>
        </div>
      </div>
    </div>

    <CreateAppealModal
      :open="createOpen"
      :channels="channels.channels"
      :loading-channels="channels.loading"
      @close="createOpen = false"
      @created="onCreated"
    />
  </div>
</template>
