<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Newspaper } from 'lucide-vue-next'
import { ApiError } from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'
import type { AppNotification } from '@/api/notifications'

const route = useRoute()
const router = useRouter()
const notifications = useNotificationsStore()

const focusQueryId = computed(() => {
  const raw = route.query.id
  const v = Array.isArray(raw) ? raw[0] : raw
  if (!v) return null
  return String(v).startsWith('news:') ? String(v) : `news:${v}`
})

const active = computed(() => {
  const id = focusQueryId.value
  if (!id) return null
  return notifications.items.find((n) => n.id === id) ?? null
})

const listMode = computed(() => !focusQueryId.value)

function formatAt(iso: string) {
  try {
    return new Date(iso).toLocaleString('ru-RU', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

async function markIfUnread(n: AppNotification | null) {
  if (!n || n.read) return
  try {
    await notifications.markRead([n.id])
  } catch {
    // ignore
  }
}

async function openArticle(n: AppNotification) {
  const num = n.id.replace(/^news:/, '')
  void router.push({ name: 'news', query: { id: num } })
}

function backToList() {
  void router.push({ name: 'news' })
}

async function markAll() {
  try {
    await notifications.markAllRead()
  } catch (e) {
    window.dispatchEvent(
      new CustomEvent('oe:in-app-toast', {
        detail: {
          kind: 'err',
          title: 'Новости',
          text: e instanceof ApiError ? e.detail : 'Не удалось отметить прочитанным',
        },
      }),
    )
  }
}

onMounted(async () => {
  await notifications.fetchList()
  await markIfUnread(active.value)
})

watch(focusQueryId, async () => {
  if (!notifications.items.length) {
    await notifications.fetchList()
  }
  await markIfUnread(active.value)
})
</script>

<template>
  <div class="mx-auto flex h-full max-w-2xl flex-col gap-6 p-4 md:p-6">
    <template v-if="!listMode">
      <button
        type="button"
        class="inline-flex w-fit items-center gap-1.5 text-sm font-medium text-mute transition hover:text-ink"
        @click="backToList"
      >
        <ArrowLeft class="size-4" />
        Все новости
      </button>

      <p v-if="notifications.loading && !active" class="py-16 text-center text-sm text-mute">
        Загрузка…
      </p>
      <p
        v-else-if="notifications.error"
        class="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
      >
        {{ notifications.error }}
      </p>
      <div v-else-if="!active" class="py-16 text-center text-sm text-mute">
        Новость не найдена или удалена
      </div>
      <article v-else class="space-y-4">
        <header class="space-y-2">
          <p class="text-[11px] font-medium uppercase tracking-wide text-mute">Новости системы</p>
          <h2 class="text-2xl font-semibold tracking-tight text-ink">{{ active.title }}</h2>
          <time class="block text-sm text-mute">{{ formatAt(active.createdAt) }}</time>
        </header>
        <div class="whitespace-pre-wrap text-[15px] leading-relaxed text-ink/90">{{ active.body }}</div>
      </article>
    </template>

    <template v-else>
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 class="text-lg font-semibold tracking-tight text-ink">Новости системы</h2>
          <p class="mt-1 text-sm text-mute">Все опубликованные обновления для команды</p>
        </div>
        <button
          v-if="notifications.hasUnread"
          type="button"
          class="text-sm font-medium text-brand transition hover:underline"
          @click="markAll"
        >
          Прочитать все
        </button>
      </div>

      <p
        v-if="notifications.loading && !notifications.items.length"
        class="py-16 text-center text-sm text-mute"
      >
        Загрузка…
      </p>
      <p
        v-else-if="notifications.error"
        class="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
      >
        {{ notifications.error }}
      </p>
      <div
        v-else-if="!notifications.items.length"
        class="flex flex-col items-center justify-center gap-3 py-20 text-center"
      >
        <Newspaper class="size-8 text-mute/60" />
        <p class="text-sm text-mute">Пока нет опубликованных новостей</p>
      </div>

      <ul v-else class="divide-y divide-line border-y border-line">
        <li v-for="n in notifications.items" :key="n.id">
          <button
            type="button"
            class="flex w-full gap-3 py-4 text-left transition hover:bg-surface/70"
            :class="!n.read ? 'bg-brand-soft/25' : ''"
            @click="openArticle(n)"
          >
            <span
              class="mt-2 size-2 shrink-0 rounded-full"
              :class="n.read ? 'bg-transparent' : 'bg-brand'"
              aria-hidden="true"
            />
            <div class="min-w-0 flex-1 pr-1">
              <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <h3 class="text-[15px] font-semibold leading-snug text-ink">{{ n.title }}</h3>
                <time class="shrink-0 text-xs text-mute">{{ formatAt(n.createdAt) }}</time>
              </div>
              <p class="mt-1.5 line-clamp-2 text-sm leading-relaxed text-mute">{{ n.body }}</p>
            </div>
          </button>
        </li>
      </ul>
    </template>
  </div>
</template>
