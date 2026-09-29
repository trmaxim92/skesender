<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ChevronDown,
  ChevronRight,
  Copy,
  LayoutGrid,
  Pencil,
  Search,
  X,
} from 'lucide-vue-next'
import type { Template, TemplateGroup } from '@/types'
import { resolveCategoryIcon } from '@/utils/templateCategoryIcons'

const props = defineProps<{
  groups: TemplateGroup[]
  createPath?: { name: string }
}>()

const emit = defineEmits<{
  close: []
  select: [template: Template]
}>()

type SortMode = 'popular' | 'name' | 'recent'
const ALL_KEY = 'all'

const router = useRouter()
const searchEl = ref<HTMLInputElement | null>(null)
const query = ref('')
const categoryKey = ref(ALL_KEY)
const selectedId = ref<string | null>(null)
const sortMode = ref<SortMode>('popular')
const sortOpen = ref(false)
/** Below `lg`: list and preview swap instead of stacking. */
const isNarrow = ref(
  typeof window !== 'undefined' ? window.matchMedia('(max-width: 1023px)').matches : false,
)
const mobilePane = ref<'list' | 'preview'>('list')

let narrowMq: MediaQueryList | null = null
function onNarrowChange(ev: MediaQueryListEvent) {
  isNarrow.value = ev.matches
  if (!ev.matches) mobilePane.value = 'list'
}

function groupKey(group: TemplateGroup) {
  return group.categoryId ?? `name:${group.categoryName}`
}

function isPopular(t: Template) {
  // No usage stats yet — highlight shared park templates with media as «популярные».
  return !t.isMine && t.mediaCount > 0
}

const totalCount = computed(() =>
  props.groups.reduce((n, g) => n + g.templates.length, 0),
)

const navItems = computed(() => {
  const items = [
    {
      key: ALL_KEY,
      name: 'Все шаблоны',
      icon: LayoutGrid,
      count: totalCount.value,
    },
  ]
  for (const g of props.groups) {
    items.push({
      key: groupKey(g),
      name: g.categoryName,
      icon: resolveCategoryIcon(g.categoryIcon, g.categoryName),
      count: g.templates.length,
    })
  }
  return items
})

function matchesQuery(t: Template, categoryName: string, q: string) {
  if (!q) return true
  return (
    t.name.toLowerCase().includes(q) ||
    (t.body || '').toLowerCase().includes(q) ||
    categoryName.toLowerCase().includes(q)
  )
}

function sortTemplates(list: Template[]) {
  const mode = sortMode.value
  return [...list].sort((a, b) => {
    if (mode === 'name') return a.name.localeCompare(b.name, 'ru')
    if (mode === 'recent') {
      return String(b.updatedAt || '').localeCompare(String(a.updatedAt || ''))
    }
    // popular
    const pa = Number(isPopular(a))
    const pb = Number(isPopular(b))
    if (pa !== pb) return pb - pa
    if (a.mediaCount !== b.mediaCount) return b.mediaCount - a.mediaCount
    return a.name.localeCompare(b.name, 'ru')
  })
}

const listSections = computed(() => {
  const q = query.value.trim().toLowerCase()
  const sections: {
    key: string
    name: string
    icon: string | null
    templates: Template[]
  }[] = []

  const source =
    categoryKey.value === ALL_KEY
      ? props.groups
      : props.groups.filter((g) => groupKey(g) === categoryKey.value)

  for (const g of source) {
    const templates = sortTemplates(
      g.templates.filter((t) => matchesQuery(t, g.categoryName, q)),
    )
    if (!templates.length) continue
    sections.push({
      key: groupKey(g),
      name: g.categoryName,
      icon: g.categoryIcon,
      templates,
    })
  }
  return sections
})

const flatTemplates = computed(() =>
  listSections.value.flatMap((s) => s.templates),
)

const selected = computed(
  () => flatTemplates.value.find((t) => t.id === selectedId.value) ?? null,
)

const selectedCategoryName = computed(() => {
  if (!selected.value) return ''
  for (const g of props.groups) {
    if (g.templates.some((t) => t.id === selected.value!.id)) return g.categoryName
  }
  return selected.value.categoryName || ''
})

const sortLabel = computed(() => {
  if (sortMode.value === 'name') return 'По названию'
  if (sortMode.value === 'recent') return 'Сначала новые'
  return 'Сначала популярные'
})

watch(
  flatTemplates,
  (list) => {
    if (!list.length) {
      selectedId.value = null
      return
    }
    if (!list.some((t) => t.id === selectedId.value)) {
      selectedId.value = list[0].id
    }
  },
  { immediate: true },
)

function pickCategory(key: string) {
  categoryKey.value = key
  sortOpen.value = false
  if (isNarrow.value) mobilePane.value = 'list'
}

function pickTemplate(t: Template) {
  selectedId.value = t.id
  if (isNarrow.value) mobilePane.value = 'preview'
}

function backToList() {
  mobilePane.value = 'list'
  sortOpen.value = false
}

function useSelected() {
  if (!selected.value) return
  emit('select', selected.value)
  emit('close')
}

function editSelected() {
  if (!selected.value) return
  emit('close')
  void router.push({
    name: props.createPath?.name || 'profile-templates',
    query: { edit: selected.value.id },
  })
}

function setSort(mode: SortMode) {
  sortMode.value = mode
  sortOpen.value = false
}

function onKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Escape') {
    if (sortOpen.value) {
      sortOpen.value = false
      return
    }
    if (isNarrow.value && mobilePane.value === 'preview') {
      ev.preventDefault()
      backToList()
      return
    }
    ev.preventDefault()
    emit('close')
    return
  }
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'k') {
    ev.preventDefault()
    if (isNarrow.value && mobilePane.value === 'preview') backToList()
    requestAnimationFrame(() => {
      searchEl.value?.focus()
      searchEl.value?.select()
    })
  }
}

onMounted(() => {
  narrowMq = window.matchMedia('(max-width: 1023px)')
  isNarrow.value = narrowMq.matches
  narrowMq.addEventListener('change', onNarrowChange)
  window.addEventListener('keydown', onKeydown)
  requestAnimationFrame(() => searchEl.value?.focus())
})

onUnmounted(() => {
  narrowMq?.removeEventListener('change', onNarrowChange)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-end justify-center bg-ink/45 backdrop-blur-[2px] sm:items-center sm:p-4 lg:p-5"
    @click.self="emit('close')"
  >
    <div
      class="flex h-[min(100dvh,100%)] w-full max-w-6xl flex-col overflow-hidden border border-line bg-panel shadow-2xl max-sm:rounded-t-2xl sm:h-[min(92dvh,900px)] sm:rounded-2xl"
      role="dialog"
      aria-modal="true"
      aria-label="Выбор шаблона"
      @click.stop
    >
      <!-- Header -->
      <div
        class="flex items-start justify-between gap-3 border-b border-line px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))] sm:gap-4 sm:px-6 sm:py-4"
      >
        <div class="min-w-0">
          <h2 class="text-lg font-bold tracking-tight text-ink sm:text-xl">Выбор шаблона</h2>
          <p class="mt-0.5 hidden text-sm text-muted sm:block">
            Используйте готовые шаблоны для быстрых ответов
          </p>
        </div>
        <button
          type="button"
          class="flex size-9 shrink-0 items-center justify-center rounded-xl text-muted transition hover:bg-surface hover:text-ink"
          aria-label="Закрыть"
          @click="emit('close')"
        >
          <X class="size-5" />
        </button>
      </div>

      <div class="flex min-h-0 flex-1 flex-col lg:flex-row">
        <!-- Left: categories (hidden on narrow preview step) -->
        <aside
          v-show="!isNarrow || mobilePane === 'list'"
          class="flex shrink-0 flex-col border-b border-line bg-surface/40 lg:w-[240px] lg:border-b-0 lg:border-r"
        >
          <nav
            class="min-h-0 overflow-x-auto overflow-y-auto p-2 [-ms-overflow-style:none] [scrollbar-width:none] lg:flex-1 lg:overflow-x-hidden [&::-webkit-scrollbar]:hidden"
          >
            <div class="flex gap-1 lg:flex-col lg:gap-0.5">
              <button
                v-for="item in navItems"
                :key="item.key"
                type="button"
                class="relative inline-flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-left transition sm:gap-2.5 sm:py-2.5 lg:w-full"
                :class="
                  categoryKey === item.key
                    ? 'bg-brand-soft/80 text-brand'
                    : 'text-ink hover:bg-panel'
                "
                @click="pickCategory(item.key)"
              >
                <span
                  v-if="categoryKey === item.key"
                  class="absolute bottom-2 left-0 top-2 hidden w-[3px] rounded-r-full bg-brand lg:block"
                />
                <component :is="item.icon" class="size-4 shrink-0 opacity-80" />
                <span class="min-w-0 flex-1 truncate text-sm font-medium">{{ item.name }}</span>
                <span
                  class="shrink-0 text-xs tabular-nums"
                  :class="categoryKey === item.key ? 'text-brand/70' : 'text-muted'"
                >
                  {{ item.count }}
                </span>
              </button>
            </div>
          </nav>
        </aside>

        <!-- Center: list -->
        <section
          v-show="!isNarrow || mobilePane === 'list'"
          class="flex min-h-0 min-w-0 flex-1 flex-col lg:border-r lg:border-line"
        >
          <div class="flex items-center gap-2 border-b border-line px-3 py-2.5 sm:flex-wrap sm:px-4 sm:py-3">
            <div class="relative min-w-0 flex-1 sm:min-w-[180px]">
              <Search
                class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted/70"
              />
              <input
                ref="searchEl"
                v-model="query"
                type="search"
                :placeholder="isNarrow ? 'Поиск…' : 'Поиск по шаблонам…'"
                class="w-full rounded-xl border-0 bg-surface py-2.5 pl-10 pr-3 text-sm text-ink outline-none ring-brand/25 placeholder:text-muted/70 focus:ring-2"
              />
            </div>
            <div class="relative shrink-0">
              <button
                type="button"
                class="inline-flex max-w-[9.5rem] items-center gap-1 rounded-xl border border-line bg-panel px-2.5 py-2.5 text-xs font-semibold text-ink transition hover:bg-surface sm:max-w-none sm:gap-1.5 sm:px-3"
                @click="sortOpen = !sortOpen"
              >
                <span class="truncate">{{ sortLabel }}</span>
                <ChevronDown class="size-3.5 shrink-0 text-muted" />
              </button>
              <div
                v-if="sortOpen"
                class="absolute right-0 z-10 mt-1 w-48 overflow-hidden rounded-xl border border-line bg-panel py-1 shadow-lg"
              >
                <button
                  type="button"
                  class="block w-full px-3 py-2 text-left text-xs font-medium hover:bg-surface"
                  :class="sortMode === 'popular' ? 'text-brand' : 'text-ink'"
                  @click="setSort('popular')"
                >
                  Сначала популярные
                </button>
                <button
                  type="button"
                  class="block w-full px-3 py-2 text-left text-xs font-medium hover:bg-surface"
                  :class="sortMode === 'recent' ? 'text-brand' : 'text-ink'"
                  @click="setSort('recent')"
                >
                  Сначала новые
                </button>
                <button
                  type="button"
                  class="block w-full px-3 py-2 text-left text-xs font-medium hover:bg-surface"
                  :class="sortMode === 'name' ? 'text-brand' : 'text-ink'"
                  @click="setSort('name')"
                >
                  По названию
                </button>
              </div>
            </div>
          </div>

          <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-3 sm:px-4">
            <template v-if="listSections.length">
              <div v-for="section in listSections" :key="section.key" class="mb-4 last:mb-0">
                <div class="mb-2 flex items-center justify-between px-1">
                  <h3 class="text-[11px] font-bold uppercase tracking-wide text-muted">
                    {{ section.name }}
                  </h3>
                  <span class="text-[11px] tabular-nums text-mute">{{
                    section.templates.length
                  }}</span>
                </div>
                <div class="space-y-2">
                  <button
                    v-for="t in section.templates"
                    :key="t.id"
                    type="button"
                    class="flex w-full items-center gap-3 rounded-2xl border px-3 py-3 text-left transition sm:px-3.5"
                    :class="
                      selectedId === t.id
                        ? 'border-brand bg-brand-soft/50 shadow-sm'
                        : 'border-line bg-panel hover:border-brand/30 hover:bg-surface/80'
                    "
                    @click="pickTemplate(t)"
                  >
                    <div
                      class="flex size-10 shrink-0 items-center justify-center rounded-xl"
                      :class="
                        selectedId === t.id ? 'bg-brand text-white' : 'bg-brand-soft text-brand'
                      "
                    >
                      <component
                        :is="resolveCategoryIcon(section.icon, section.name)"
                        class="size-4"
                      />
                    </div>
                    <div class="min-w-0 flex-1">
                      <div class="flex flex-wrap items-center gap-2">
                        <span class="truncate text-sm font-bold text-ink">{{ t.name }}</span>
                        <span
                          v-if="isPopular(t)"
                          class="rounded-md bg-brand px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white"
                        >
                          Популярный
                        </span>
                      </div>
                      <p class="mt-0.5 line-clamp-1 text-xs text-muted">
                        {{ t.body || (t.mediaCount ? 'Шаблон с вложением' : 'Без текста') }}
                      </p>
                    </div>
                    <ChevronRight class="size-4 shrink-0 text-muted" />
                  </button>
                </div>
              </div>
            </template>
            <p v-else class="px-2 py-10 text-center text-sm text-muted">
              {{ totalCount ? 'Ничего не найдено' : 'Нет шаблонов для этого канала' }}
            </p>
          </div>
        </section>

        <!-- Right: preview (full pane on narrow) -->
        <aside
          v-show="!isNarrow || mobilePane === 'preview'"
          class="flex min-h-0 w-full flex-1 flex-col lg:w-[320px] lg:flex-none xl:w-[360px]"
        >
          <div class="flex items-start gap-2 border-b border-line px-4 py-3 sm:px-5 sm:py-4">
            <button
              v-if="isNarrow"
              type="button"
              class="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg text-muted transition hover:bg-surface hover:text-ink"
              aria-label="Назад к списку"
              @click="backToList"
            >
              <ChevronRight class="size-5 rotate-180" />
            </button>
            <div class="min-w-0 flex-1">
              <h3 class="text-base font-bold text-ink">Предпросмотр шаблона</h3>
              <p v-if="selectedCategoryName" class="mt-0.5 text-xs text-muted">
                {{ selectedCategoryName }}
              </p>
            </div>
          </div>

          <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5">
            <template v-if="selected">
              <h4 class="mb-3 text-sm font-bold text-ink">{{ selected.name }}</h4>
              <div
                class="whitespace-pre-wrap break-words rounded-2xl bg-surface px-4 py-4 text-sm leading-relaxed text-ink"
              >
                {{ selected.body || 'Текст не задан — только вложение.' }}
              </div>
              <p v-if="selected.mediaCount" class="mt-3 text-xs text-muted">
                Вложений: {{ selected.mediaCount }}
                <span v-if="selected.mediaName"> · {{ selected.mediaName }}</span>
              </p>
            </template>
            <p v-else class="py-8 text-center text-sm text-muted">
              Выберите шаблон слева, чтобы увидеть текст
            </p>
          </div>

          <div
            class="space-y-2 border-t border-line p-4 pb-[max(1rem,env(safe-area-inset-bottom))]"
          >
            <button
              type="button"
              class="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:opacity-40"
              :disabled="!selected"
              @click="useSelected"
            >
              <Copy class="size-4" />
              Использовать шаблон
            </button>
            <button
              type="button"
              class="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-line bg-surface px-4 py-2.5 text-sm font-semibold text-ink transition hover:bg-panel disabled:opacity-40"
              :disabled="!selected"
              @click="editSelected"
            >
              <Pencil class="size-4 text-muted" />
              Редактировать шаблон
            </button>
          </div>
        </aside>
      </div>
    </div>
  </div>
</template>
