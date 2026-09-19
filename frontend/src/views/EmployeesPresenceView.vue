<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  listPresenceEmployeesRequest,
  mapPresenceEmployee,
} from '@/api/presence'
import { ApiError } from '@/api/client'
import type { PresenceEmployee, PresenceStatus } from '@/types'

const employees = ref<PresenceEmployee[]>([])
const loading = ref(false)
const error = ref('')
const filter = ref<'all' | 'on_duty' | 'offline'>('all')
let refreshTimer: number | undefined

async function load() {
  loading.value = true
  error.value = ''
  try {
    employees.value = (await listPresenceEmployeesRequest()).map(mapPresenceEmployee)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

async function refreshQuiet() {
  try {
    employees.value = (await listPresenceEmployeesRequest()).map(mapPresenceEmployee)
    error.value = ''
  } catch {
    /* keep previous list */
  }
}

function onVisibility() {
  if (document.visibilityState === 'visible') void refreshQuiet()
}

onMounted(() => {
  void load()
  refreshTimer = window.setInterval(() => void refreshQuiet(), 30_000)
  document.addEventListener('visibilitychange', onVisibility)
})

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
  document.removeEventListener('visibilitychange', onVisibility)
})

const filtered = computed(() => {
  if (filter.value === 'on_duty') {
    return employees.value.filter((e) => e.presenceStatus?.onDuty)
  }
  if (filter.value === 'offline') {
    return employees.value.filter(
      (e) => !e.presenceStatus || e.presenceStatus.slug === 'offline' || !e.presenceStatus.onDuty,
    )
  }
  return employees.value
})

const grouped = computed(() => {
  const map = new Map<string, { status: PresenceEmployee['presenceStatus']; people: PresenceEmployee[] }>()
  for (const e of filtered.value) {
    const key = e.presenceStatus ? String(e.presenceStatus.id) : 'none'
    if (!map.has(key)) {
      map.set(key, { status: e.presenceStatus, people: [] })
    }
    map.get(key)!.people.push(e)
  }
  return [...map.values()].sort((a, b) => {
    const ao = a.status?.sortOrder ?? 999
    const bo = b.status?.sortOrder ?? 999
    return ao - bo
  })
})

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return `${parts[0]![0] ?? ''}${parts[1]![0] ?? ''}`.toUpperCase()
  return (parts[0] || '?').slice(0, 2).toUpperCase()
}

function statusColor(status: PresenceStatus | null | undefined) {
  return status?.color || '#9ca3af'
}
</script>

<template>
  <div class="h-full overflow-auto p-6">
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <p class="text-sm text-muted">Кто сейчас в каком статусе присутствия.</p>
      <div class="flex gap-1 rounded-xl border border-line bg-panel p-1 text-sm">
        <button
          type="button"
          class="rounded-lg px-3 py-1.5"
          :class="filter === 'all' ? 'bg-brand-soft text-brand font-medium' : 'text-mute'"
          @click="filter = 'all'"
        >
          Все
        </button>
        <button
          type="button"
          class="rounded-lg px-3 py-1.5"
          :class="filter === 'on_duty' ? 'bg-brand-soft text-brand font-medium' : 'text-mute'"
          @click="filter = 'on_duty'"
        >
          На смене
        </button>
        <button
          type="button"
          class="rounded-lg px-3 py-1.5"
          :class="filter === 'offline' ? 'bg-brand-soft text-brand font-medium' : 'text-mute'"
          @click="filter = 'offline'"
        >
          Не на смене
        </button>
      </div>
    </div>

    <p v-if="error" class="mb-3 text-sm text-danger">{{ error }}</p>
    <p v-if="loading && !employees.length" class="text-sm text-muted">Загрузка…</p>

    <div v-else class="space-y-6">
      <section v-for="group in grouped" :key="group.status?.id ?? 'none'">
        <h2 class="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
          <span
            class="size-2.5 rounded-full"
            :style="{ background: statusColor(group.status) }"
          />
          {{ group.status?.name || 'Без статуса' }}
          <span class="font-normal text-mute">({{ group.people.length }})</span>
        </h2>
        <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <article
            v-for="p in group.people"
            :key="p.id"
            class="flex items-center gap-3 rounded-xl border border-line bg-panel px-3 py-2.5"
          >
            <span
              class="relative flex size-10 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white shadow-sm ring-2 ring-white"
              :style="{ background: statusColor(p.presenceStatus) }"
              :title="p.presenceStatus?.name || 'Без статуса'"
            >
              {{ initials(p.name) }}
            </span>
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-medium text-ink">{{ p.name }}</p>
              <p class="truncate text-xs text-mute">{{ p.roleName || '—' }}</p>
              <p class="mt-0.5 flex items-center gap-1.5 truncate text-[11px] font-semibold">
                <span
                  class="size-1.5 shrink-0 rounded-full"
                  :style="{ background: statusColor(p.presenceStatus) }"
                />
                <span :style="{ color: statusColor(p.presenceStatus) }">
                  {{ p.presenceStatus?.name || 'Без статуса' }}
                </span>
              </p>
            </div>
          </article>
        </div>
      </section>
      <p v-if="!grouped.length" class="text-sm text-muted">Никого не найдено.</p>
    </div>
  </div>
</template>
