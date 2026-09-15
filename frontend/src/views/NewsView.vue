<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Newspaper } from 'lucide-vue-next'
import { ApiError } from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'
import type { AppNotification } from '@/api/notifications'

const route = useRoute()
const router = useRouter()
const notifications = useNotificationsStore()

const expandedId = ref<string | null>(null)
const itemRefs = ref<Record<string, HTMLElement | null>>({})

const focusQueryId = computed(() => {
  const raw = route.query.id
  const v = Array.isArray(raw) ? raw[0] : raw
  if (!v) return null
  return String(v).startsWith('news:') ? String(v) : `news:${v}`
})

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

function setItemRef(id: string, el: unknown) {
  itemRefs.value[id] = (el as HTMLElement | null) ?? null
}

async function openItem(n: AppNotification) {
  const next = expandedId.value === n.id ? null : n.id
  expandedId.value = next
  if (!n.read) {
    try {
      await notifications.markRead([n.id])
    } catch {
      // keep list usable
    }
  }
  const num = n.id.replace(/^news:/, '')
  if (next) {
    if (route.query.id !== num) {
      void router.replace({ name: 'news', query: { id: num } })
    }
  } else if (route.query.id) {
    void router.replace({ name: 'news' })
  }
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

async function focusFromQuery() {
  const id = focusQueryId.value
  if (!id) return
  expandedId.value = id
  const item = notifications.items.find((n) => n.id === id)
  if (item && !item.read) {
    try {
      await notifications.markRead([id])
    } catch {
      // ignore
    }
  }
  await nextTick()
  itemRefs.value[id]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

onMounted(async () => {
  await notifications.fetchList()
  await focusFromQuery()
})

watch(focusQueryId, () => {
  void focusFromQuery()
})
</script>

<template>
  <div class="mx-auto flex h-full max-w-2xl flex-col gap-6 p-4 md:p-6">
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

    <p v-if="notifications.loading && !notifications.items.length" class="py-16 text-center text-sm text-mute">
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
      <li
        v-for="n in notifications.items"
        :key="n.id"
        :ref="(el) => setItemRef(n.id, el)"
      >
        <button
          type="button"
          class="flex w-full gap-3 py-4 text-left transition hover:bg-surface/70"
          :class="!n.read ? 'bg-brand-soft/25' : ''"
          @click="openItem(n)"
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
            <p
              class="mt-1.5 text-sm leading-relaxed text-mute"
              :class="expandedId === n.id ? 'whitespace-pre-wrap' : 'line-clamp-2'"
            >
              {{ n.body }}
            </p>
            <p
              v-if="expandedId !== n.id && n.body.length > 140"
              class="mt-2 text-xs font-medium text-brand"
            >
              Читать полностью
            </p>
          </div>
        </button>
      </li>
    </ul>
  </div>
</template>
