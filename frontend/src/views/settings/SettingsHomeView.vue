<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { ChevronRight } from 'lucide-vue-next'
import { SETTINGS_NAV_GROUPS } from '@/navigation/settingsNav'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const groups = computed(() =>
  SETTINGS_NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => auth.can(item.permission)),
  })).filter((group) => group.items.length > 0),
)
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-8 p-6">
    <div>
      <h2 class="text-lg font-semibold tracking-tight">Настройки</h2>
      <p class="mt-1 text-sm text-muted">
        Разделы кабинета: интеграции и параметры обращений.
      </p>
    </div>

    <section v-for="group in groups" :key="group.id" class="space-y-3">
      <div>
        <h3 class="text-sm font-semibold text-ink">{{ group.title }}</h3>
        <p class="text-xs text-muted">{{ group.description }}</p>
      </div>
      <div class="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-panel">
        <RouterLink
          v-for="item in group.items"
          :key="item.to"
          :to="item.to"
          class="flex items-center gap-3 px-4 py-3.5 transition hover:bg-surface"
        >
          <span
            class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand"
          >
            <component :is="item.icon" class="size-4" />
          </span>
          <span class="min-w-0 flex-1">
            <span class="block text-sm font-medium text-ink">{{ item.label }}</span>
            <span class="block truncate text-xs text-muted">{{ item.description }}</span>
          </span>
          <ChevronRight class="size-4 shrink-0 text-muted" />
        </RouterLink>
      </div>
    </section>

    <p v-if="!groups.length" class="text-sm text-muted">
      Нет доступных разделов настроек для вашей роли.
    </p>
  </div>
</template>
