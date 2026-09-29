<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  BookOpen,
  Clock,
  FileText,
  FolderInput,
  FolderPlus,
  Pencil,
  Plus,
  Search,
  Trash2,
} from 'lucide-vue-next'
import KbArticleBody from '@/components/knowledge/KbArticleBody.vue'
import KbRichEditor from '@/components/knowledge/KbRichEditor.vue'
import KbTreeNodes from '@/components/knowledge/KbTreeNodes.vue'
import Modal from '@/components/ui/Modal.vue'
import {
  searchKnowledgeArticles,
  type KbSearchHit,
} from '@/api/knowledge'
import { useAuthStore } from '@/stores/auth'
import { useKnowledgeStore } from '@/stores/knowledge'
import type { KbFolderNode } from '@/types'
import {
  loadKbRecent,
  pushKbRecent,
  serializeKbHtml,
  type KbRecentItem,
  type KbTocItem,
} from '@/utils/knowledgeUi'

type DialogKind =
  | 'folder-create'
  | 'folder-rename'
  | 'folder-delete'
  | 'article-create'
  | 'article-delete'
  | 'article-move'
  | null

type Crumb =
  | { kind: 'root'; title: string }
  | { kind: 'folder'; id: number; title: string }
  | { kind: 'article'; title: string }

const auth = useAuthStore()
const store = useKnowledgeStore()
const route = useRoute()
const router = useRouter()

const canWrite = computed(() => auth.can('section.knowledge') && auth.can('action.write'))
const search = ref('')
const searchHits = ref<KbSearchHit[]>([])
const searchLoading = ref(false)
const recent = ref<KbRecentItem[]>(loadKbRecent())
const toc = ref<KbTocItem[]>([])
const articleBodyRef = ref<InstanceType<typeof KbArticleBody> | null>(null)
let searchTimer: ReturnType<typeof setTimeout> | undefined
const expanded = ref<Set<number>>(new Set())
const editing = ref(false)
const draftTitle = ref('')
const draftHtml = ref('')
const draftPublished = ref(true)
const menuFolderId = ref<number | null>(null)
const treeBusy = ref(false)

const dialog = ref<DialogKind>(null)
const dialogTitle = ref('')
const dialogFolderParentId = ref<number | null>(null)
const dialogFolder = ref<KbFolderNode | null>(null)
const dialogFolderIdForArticle = ref<number | null>(null)
const dialogInput = ref('')
const dialogPublished = ref(true)
const dialogMoveFolderId = ref<number | null>(null)
const dialogError = ref('')

const articleId = computed(() => {
  const raw = route.params.articleId
  if (!raw) return null
  const n = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isFinite(n) ? n : null
})

const breadcrumb = computed((): Crumb[] => {
  const art = store.current
  if (!art) return [{ kind: 'root', title: 'База знаний' }]
  const path: Extract<Crumb, { kind: 'folder' }>[] = []
  const find = (
    nodes: KbFolderNode[],
    trail: Extract<Crumb, { kind: 'folder' }>[],
  ): boolean => {
    for (const n of nodes) {
      const next = [...trail, { kind: 'folder' as const, id: n.id, title: n.title }]
      if (n.articles.some((a) => a.id === art.id)) {
        path.push(...next)
        return true
      }
      if (find(n.children, next)) return true
    }
    return false
  }
  find(store.folders, [])
  return [
    { kind: 'root', title: 'База знаний' },
    ...path,
    { kind: 'article', title: art.title },
  ]
})

const filteredFolders = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return store.folders
  return filterTree(store.folders, q)
})

const showSearchPanel = computed(() => search.value.trim().length >= 2)

function filterTree(nodes: KbFolderNode[], q: string): KbFolderNode[] {
  const out: KbFolderNode[] = []
  for (const node of nodes) {
    const children = filterTree(node.children, q)
    const articles = node.articles.filter((a) => a.title.toLowerCase().includes(q))
    const selfMatch = node.title.toLowerCase().includes(q)
    if (selfMatch || articles.length || children.length) {
      out.push({
        ...node,
        articles: selfMatch ? node.articles : articles,
        children,
      })
    }
  }
  return out
}

watch(search, (q) => {
  const needle = q.trim()
  if (searchTimer) clearTimeout(searchTimer)
  if (needle.length < 2) {
    searchHits.value = []
    searchLoading.value = false
    return
  }
  searchLoading.value = true
  searchTimer = setTimeout(async () => {
    try {
      searchHits.value = await searchKnowledgeArticles(needle)
    } catch {
      searchHits.value = []
    } finally {
      searchLoading.value = false
    }
  }, 280)
})

function folderArticleCount(node: KbFolderNode): number {
  return node.articles.length + node.children.reduce((sum, c) => sum + folderArticleCount(c), 0)
}

function toggleExpand(id: number) {
  if (expanded.value.has(id)) expanded.value.delete(id)
  else expanded.value.add(id)
  expanded.value = new Set(expanded.value)
}

function openArticle(id: number) {
  editing.value = false
  menuFolderId.value = null
  void router.push({ name: 'knowledge-article', params: { articleId: String(id) } })
}

function backToTree() {
  editing.value = false
  menuFolderId.value = null
  void router.push({ name: 'knowledge' })
}

function onCrumb(c: Crumb) {
  if (c.kind === 'root') {
    backToTree()
    return
  }
  if (c.kind === 'folder') {
    expanded.value.add(c.id)
    expanded.value = new Set(expanded.value)
    if (articleId.value) backToTree()
  }
}

function startEdit() {
  if (!store.current || !canWrite.value) return
  draftTitle.value = store.current.title
  draftHtml.value = store.current.bodyHtml || ''
  draftPublished.value = store.current.isPublished
  editing.value = true
}

function cancelEdit() {
  editing.value = false
  if (store.current) {
    draftTitle.value = store.current.title
    draftHtml.value = store.current.bodyHtml || ''
    draftPublished.value = store.current.isPublished
  }
}

async function saveEdit() {
  if (!store.current || !draftTitle.value.trim()) return
  const saved = await store.saveArticle(store.current.id, {
    title: draftTitle.value.trim(),
    bodyHtml: serializeKbHtml(draftHtml.value),
    isPublished: draftPublished.value,
  })
  if (saved) {
    editing.value = false
    toc.value = []
    pushKbRecent(saved.id, saved.title)
    recent.value = loadKbRecent()
  }
}

function closeDialog() {
  dialog.value = null
  dialogError.value = ''
  dialogFolder.value = null
  dialogFolderIdForArticle.value = null
  dialogInput.value = ''
}

function openCreateFolder(parentId: number | null = null) {
  if (!canWrite.value) return
  menuFolderId.value = null
  dialogFolderParentId.value = parentId
  dialogInput.value = ''
  dialogError.value = ''
  dialog.value = 'folder-create'
  dialogTitle.value = parentId == null ? 'Новый раздел' : 'Новый подраздел'
}

function openRenameFolder(folder: KbFolderNode) {
  if (!canWrite.value) return
  menuFolderId.value = null
  dialogFolder.value = folder
  dialogInput.value = folder.title
  dialogError.value = ''
  dialog.value = 'folder-rename'
  dialogTitle.value = 'Переименовать раздел'
}

function openDeleteFolder(folder: KbFolderNode) {
  if (!canWrite.value) return
  menuFolderId.value = null
  dialogFolder.value = folder
  dialogError.value = ''
  dialog.value = 'folder-delete'
  dialogTitle.value = 'Удалить раздел'
}

function openCreateArticle(folderId: number) {
  if (!canWrite.value) return
  menuFolderId.value = null
  dialogFolderIdForArticle.value = folderId
  dialogInput.value = ''
  dialogPublished.value = true
  dialogError.value = ''
  dialog.value = 'article-create'
  dialogTitle.value = 'Новая статья'
}

function openDeleteArticle() {
  if (!store.current || !canWrite.value) return
  dialogError.value = ''
  dialog.value = 'article-delete'
  dialogTitle.value = 'Удалить статью'
}

function openMoveArticle() {
  if (!store.current || !canWrite.value) return
  dialogMoveFolderId.value = store.current.folderId
  dialogError.value = ''
  dialog.value = 'article-move'
  dialogTitle.value = 'Перенести статью'
}

async function submitDialog() {
  dialogError.value = ''
  treeBusy.value = true
  try {
    if (dialog.value === 'folder-create') {
      const title = dialogInput.value.trim()
      if (!title) {
        dialogError.value = 'Введите название'
        return
      }
      const parentId = dialogFolderParentId.value
      const ok = await store.createFolder(title, parentId)
      if (!ok) {
        dialogError.value = store.error || 'Ошибка'
        return
      }
      if (parentId != null) {
        expanded.value.add(parentId)
        expanded.value = new Set(expanded.value)
      }
      closeDialog()
      return
    }
    if (dialog.value === 'folder-rename' && dialogFolder.value) {
      const title = dialogInput.value.trim()
      if (!title) {
        dialogError.value = 'Введите название'
        return
      }
      const ok = await store.renameFolder(dialogFolder.value.id, title)
      if (!ok) {
        dialogError.value = store.error || 'Ошибка'
        return
      }
      closeDialog()
      return
    }
    if (dialog.value === 'folder-delete' && dialogFolder.value) {
      const id = dialogFolder.value.id
      const ok = await store.removeFolder(id)
      if (!ok) {
        dialogError.value = store.error || 'Ошибка'
        return
      }
      closeDialog()
      if (articleId.value && !findArticleInTree(store.folders, articleId.value)) {
        void router.push({ name: 'knowledge' })
      }
      return
    }
    if (dialog.value === 'article-create' && dialogFolderIdForArticle.value != null) {
      const title = dialogInput.value.trim()
      if (!title) {
        dialogError.value = 'Введите название'
        return
      }
      const folderId = dialogFolderIdForArticle.value
      const article = await store.createArticle(
        folderId,
        title,
        '<p></p>',
        dialogPublished.value,
      )
      if (!article) {
        dialogError.value = store.error || 'Ошибка'
        return
      }
      expanded.value.add(folderId)
      expanded.value = new Set(expanded.value)
      closeDialog()
      draftTitle.value = article.title
      draftHtml.value = article.bodyHtml || ''
      draftPublished.value = article.isPublished
      editing.value = true
      void router.push({
        name: 'knowledge-article',
        params: { articleId: String(article.id) },
      })
      return
    }
    if (dialog.value === 'article-delete' && store.current) {
      const ok = await store.removeArticle(store.current.id)
      if (!ok) {
        dialogError.value = store.error || 'Ошибка'
        return
      }
      closeDialog()
      editing.value = false
      void router.push({ name: 'knowledge' })
      return
    }
    if (dialog.value === 'article-move' && store.current && dialogMoveFolderId.value != null) {
      if (dialogMoveFolderId.value === store.current.folderId) {
        closeDialog()
        return
      }
      const saved = await store.saveArticle(store.current.id, {
        folderId: dialogMoveFolderId.value,
      })
      if (!saved) {
        dialogError.value = store.error || 'Ошибка'
        return
      }
      expanded.value.add(dialogMoveFolderId.value)
      expanded.value = new Set(expanded.value)
      closeDialog()
    }
  } finally {
    treeBusy.value = false
  }
}

async function onMoveFolder(id: number, direction: 'up' | 'down') {
  menuFolderId.value = null
  treeBusy.value = true
  await store.moveFolder(id, direction)
  treeBusy.value = false
}

function findArticleInTree(nodes: KbFolderNode[], id: number): boolean {
  for (const n of nodes) {
    if (n.articles.some((a) => a.id === id)) return true
    if (findArticleInTree(n.children, id)) return true
  }
  return false
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleString('ru-RU', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function expandParentsOfArticle(id: number) {
  const walk = (nodes: KbFolderNode[], trail: number[]): boolean => {
    for (const n of nodes) {
      const next = [...trail, n.id]
      if (n.articles.some((a) => a.id === id)) {
        for (const fid of next) expanded.value.add(fid)
        expanded.value = new Set(expanded.value)
        return true
      }
      if (walk(n.children, next)) return true
    }
    return false
  }
  walk(store.folders, [])
}

function onDocClick() {
  menuFolderId.value = null
}

watch(articleId, async (id) => {
  if (id == null) {
    store.clearArticle()
    editing.value = false
    toc.value = []
    return
  }
  const art = await store.loadArticle(id)
  if (art) {
    draftTitle.value = art.title
    draftHtml.value = art.bodyHtml || ''
    draftPublished.value = art.isPublished
    expandParentsOfArticle(id)
    pushKbRecent(art.id, art.title)
    recent.value = loadKbRecent()
  }
})

onMounted(async () => {
  document.addEventListener('click', onDocClick)
  recent.value = loadKbRecent()
  await store.fetchTree()
  if (articleId.value != null) {
    const art = await store.loadArticle(articleId.value)
    if (art) {
      draftTitle.value = art.title
      draftHtml.value = art.bodyHtml || ''
      draftPublished.value = art.isPublished
      expandParentsOfArticle(articleId.value)
      pushKbRecent(art.id, art.title)
      recent.value = loadKbRecent()
    }
  } else if (store.folders.length) {
    for (const f of store.folders) expanded.value.add(f.id)
    expanded.value = new Set(expanded.value)
  }
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<template>
  <div class="kb-shell flex h-full min-h-0 overflow-hidden bg-[#eef1f6]">
    <!-- Tree -->
    <aside
      class="flex w-full shrink-0 flex-col border-r border-line/80 bg-panel md:w-[300px] lg:w-[320px]"
      :class="articleId ? 'hidden md:flex' : 'flex'"
    >
      <div class="border-b border-line px-4 py-4">
        <div class="mb-3 flex items-center gap-2">
          <div class="flex size-8 items-center justify-center rounded-xl bg-brand text-white">
            <BookOpen class="size-4" />
          </div>
          <div>
            <div class="text-sm font-bold tracking-tight text-ink">База знаний</div>
            <div class="text-[11px] text-muted">Инструкции для смены</div>
          </div>
        </div>
        <div class="relative">
          <Search
            class="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted"
          />
          <input
            v-model="search"
            type="search"
            placeholder="Найти статью…"
            class="w-full rounded-xl border border-line bg-surface py-2.5 pl-9 pr-3 text-sm outline-none focus:border-brand"
          />
        </div>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-3" @click.stop>
        <p v-if="store.loading" class="px-2 py-4 text-sm text-muted">Загрузка…</p>
        <p v-else-if="store.error && store.isEmpty" class="px-2 py-4 text-sm text-danger">
          {{ store.error }}
        </p>
        <template v-else-if="showSearchPanel">
          <p v-if="searchLoading" class="px-2 py-3 text-xs text-muted">Ищем…</p>
          <p v-else-if="!searchHits.length" class="px-2 py-3 text-xs text-muted">Ничего не найдено</p>
          <ul v-else class="space-y-1">
            <li v-for="hit in searchHits" :key="hit.id">
              <button
                type="button"
                class="w-full rounded-xl px-2.5 py-2.5 text-left transition hover:bg-surface"
                :class="articleId === hit.id ? 'bg-brand-soft' : ''"
                @click="openArticle(hit.id)"
              >
                <div class="truncate text-[13px] font-semibold text-ink">{{ hit.title }}</div>
                <p v-if="hit.snippet" class="mt-0.5 line-clamp-2 text-[11px] text-muted">
                  {{ hit.snippet }}
                </p>
              </button>
            </li>
          </ul>
        </template>
        <template v-else>
          <div v-if="recent.length && !search.trim()" class="mb-4">
            <div
              class="mb-1.5 flex items-center gap-1.5 px-2 text-[10px] font-bold uppercase tracking-[0.08em] text-muted"
            >
              <Clock class="size-3" />
              Недавние
            </div>
            <button
              v-for="r in recent"
              :key="'r' + r.id"
              type="button"
              class="mb-0.5 flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] text-ink/85 transition hover:bg-surface"
              @click="openArticle(r.id)"
            >
              <FileText class="size-3.5 shrink-0 text-brand/70" />
              <span class="truncate">{{ r.title }}</span>
            </button>
          </div>
          <KbTreeNodes
            :nodes="filteredFolders"
            :expanded="expanded"
            :active-id="articleId"
            :can-write="canWrite"
            :menu-folder-id="menuFolderId"
            :folder-article-count="folderArticleCount"
            :can-move-up="(id) => store.canMoveFolder(id, 'up')"
            :can-move-down="(id) => store.canMoveFolder(id, 'down')"
            @toggle="toggleExpand"
            @open="openArticle"
            @menu="menuFolderId = $event"
            @new-folder="openCreateFolder"
            @new-article="openCreateArticle"
            @rename="openRenameFolder"
            @delete="openDeleteFolder"
            @move-up="onMoveFolder($event, 'up')"
            @move-down="onMoveFolder($event, 'down')"
          />
        </template>
      </div>

      <div v-if="canWrite" class="border-t border-line p-3">
        <button
          type="button"
          class="flex w-full items-center justify-center gap-2 rounded-xl bg-ink px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-ink/90 disabled:opacity-50"
          :disabled="treeBusy || store.saving"
          @click="openCreateFolder(null)"
        >
          <FolderPlus class="size-4" />
          Новый раздел
        </button>
      </div>
    </aside>

    <!-- Reader / editor -->
    <section
      class="relative flex min-w-0 flex-1 flex-col overflow-hidden"
      :class="!articleId && !store.isEmpty ? 'hidden md:flex' : 'flex'"
    >
      <div
        v-if="store.isEmpty && !store.loading"
        class="flex flex-1 flex-col items-center justify-center px-6 py-12 text-center"
      >
        <div class="mb-5 flex size-16 items-center justify-center rounded-3xl bg-brand text-white shadow-lg shadow-brand/20">
          <BookOpen class="size-8" />
        </div>
        <h1 class="text-3xl font-bold tracking-tight text-ink">База знаний</h1>
        <p class="mt-2 max-w-md text-sm leading-relaxed text-muted">
          Живые инструкции для операторов — скрипты, регламенты и ответы на частые вопросы.
        </p>
        <button
          v-if="canWrite"
          type="button"
          class="mt-6 inline-flex items-center gap-2 rounded-xl bg-brand px-5 py-2.5 text-sm font-semibold text-white"
          @click="openCreateFolder(null)"
        >
          <Plus class="size-4" />
          Создать первый раздел
        </button>
      </div>

      <div
        v-else-if="!articleId"
        class="flex flex-1 flex-col items-center justify-center px-6 text-center"
      >
        <div class="mb-4 flex size-14 items-center justify-center rounded-2xl bg-panel text-muted shadow-sm">
          <FileText class="size-6" />
        </div>
        <p class="text-base font-semibold text-ink">Выберите статью слева</p>
        <p class="mt-1 text-sm text-muted">
          {{ store.articleCount }} материалов в базе
        </p>
        <div v-if="recent.length" class="mt-8 w-full max-w-sm text-left">
          <div class="mb-2 text-[11px] font-bold uppercase tracking-wide text-muted">Продолжить</div>
          <button
            v-for="r in recent"
            :key="'rr' + r.id"
            type="button"
            class="mb-2 flex w-full items-center gap-3 rounded-2xl border border-line bg-panel px-4 py-3 text-left shadow-sm transition hover:border-brand/35"
            @click="openArticle(r.id)"
          >
            <Clock class="size-4 shrink-0 text-brand" />
            <span class="truncate text-sm font-medium">{{ r.title }}</span>
          </button>
        </div>
      </div>

      <template v-else>
        <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <div class="mx-auto max-w-3xl px-4 py-5 sm:px-8 sm:py-8">
            <div class="mb-4 flex items-center gap-2">
              <button
                type="button"
                class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-panel text-muted shadow-sm md:hidden"
                aria-label="К дереву"
                @click="backToTree"
              >
                <ArrowLeft class="size-4" />
              </button>
              <nav class="flex min-w-0 flex-wrap items-center gap-1 text-[11px] text-muted">
                <template v-for="(c, i) in breadcrumb" :key="i">
                  <span v-if="i > 0" class="opacity-40">/</span>
                  <button
                    v-if="c.kind !== 'article'"
                    type="button"
                    class="truncate transition hover:text-brand"
                    @click="onCrumb(c)"
                  >
                    {{ c.title }}
                  </button>
                  <span v-else class="truncate font-medium text-ink">{{ c.title }}</span>
                </template>
              </nav>
            </div>

            <!-- Document card -->
            <article class="overflow-hidden rounded-2xl border border-line bg-panel shadow-[0_8px_30px_rgba(21,32,51,0.06)]">
              <header class="border-b border-line px-5 py-5 sm:px-8 sm:py-6">
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div class="min-w-0 flex-1">
                    <input
                      v-if="editing"
                      v-model="draftTitle"
                      class="w-full border-0 bg-transparent text-2xl font-bold tracking-tight text-ink outline-none placeholder:text-muted/50 sm:text-3xl"
                      placeholder="Название статьи"
                    />
                    <h1 v-else class="text-2xl font-bold tracking-tight text-ink sm:text-3xl">
                      {{ store.current?.title ?? '…' }}
                    </h1>
                    <div v-if="!editing && store.current" class="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
                      <span v-if="store.current.updatedByName">{{ store.current.updatedByName }}</span>
                      <span v-if="store.current.updatedByName">·</span>
                      <span>{{ formatDate(store.current.updatedAt) }}</span>
                      <span
                        v-if="!store.current.isPublished"
                        class="rounded-full bg-warn/15 px-2 py-0.5 font-semibold text-warn"
                        >черновик</span
                      >
                    </div>
                    <div v-else-if="editing" class="mt-4 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        class="inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold"
                        :class="
                          draftPublished
                            ? 'border-ok/25 bg-ok/10 text-ok'
                            : 'border-warn/25 bg-warn/10 text-warn'
                        "
                        @click="draftPublished = !draftPublished"
                      >
                        <span
                          class="size-2 rounded-full"
                          :class="draftPublished ? 'bg-ok' : 'bg-warn'"
                        />
                        {{ draftPublished ? 'Опубликовано' : 'Черновик' }}
                      </button>
                    </div>
                  </div>

                  <div v-if="canWrite" class="flex shrink-0 flex-wrap gap-2">
                    <template v-if="editing">
                      <button
                        type="button"
                        class="rounded-xl border border-line px-3.5 py-2 text-sm font-medium"
                        :disabled="store.saving"
                        @click="cancelEdit"
                      >
                        Отмена
                      </button>
                      <button
                        type="button"
                        class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                        :disabled="store.saving || !draftTitle.trim()"
                        @click="saveEdit"
                      >
                        {{ store.saving ? 'Сохранение…' : 'Сохранить' }}
                      </button>
                    </template>
                    <template v-else>
                      <button
                        type="button"
                        class="inline-flex items-center gap-1.5 rounded-xl bg-ink px-3.5 py-2 text-sm font-semibold text-white"
                        @click="startEdit"
                      >
                        <Pencil class="size-3.5" />
                        Редактировать
                      </button>
                      <button
                        type="button"
                        class="inline-flex items-center gap-1.5 rounded-xl border border-line px-3 py-2 text-sm"
                        @click="openMoveArticle"
                      >
                        <FolderInput class="size-3.5" />
                      </button>
                      <button
                        type="button"
                        class="inline-flex items-center gap-1.5 rounded-xl border border-line px-3 py-2 text-sm text-danger"
                        @click="openDeleteArticle"
                      >
                        <Trash2 class="size-3.5" />
                      </button>
                    </template>
                  </div>
                </div>
                <p v-if="store.error" class="mt-2 text-xs text-danger">{{ store.error }}</p>
              </header>

              <div class="px-0 py-0 sm:px-0">
                <p v-if="store.loadingArticle" class="px-8 py-10 text-sm text-muted">Загрузка…</p>
                <template v-else-if="store.current">
                  <div v-if="editing" class="p-3 sm:p-4">
                    <KbRichEditor :key="store.current.id" v-model="draftHtml" />
                  </div>
                  <div v-else class="px-5 py-6 sm:px-8 sm:py-8">
                    <div class="flex gap-8">
                      <KbArticleBody
                        ref="articleBodyRef"
                        class="min-w-0 flex-1"
                        :html="store.current.bodyHtml || '<p>Пустая статья — нажмите «Редактировать».</p>'"
                        @toc="toc = $event"
                      />
                      <aside v-if="toc.length > 1" class="hidden w-44 shrink-0 xl:block">
                        <div class="sticky top-6">
                          <div class="mb-2 text-[10px] font-bold uppercase tracking-[0.08em] text-muted">
                            На этой странице
                          </div>
                          <nav class="space-y-1.5 border-l border-line pl-3">
                            <button
                              v-for="item in toc"
                              :key="item.id"
                              type="button"
                              class="block w-full truncate text-left text-[12px] text-muted transition hover:text-brand"
                              :class="item.level === 3 ? 'pl-2' : 'font-semibold text-ink/80'"
                              @click="articleBodyRef?.scrollToHeading(item.id)"
                            >
                              {{ item.text }}
                            </button>
                          </nav>
                        </div>
                      </aside>
                    </div>
                  </div>
                </template>
              </div>
            </article>
          </div>
        </div>
      </template>
    </section>

    <!-- Dialogs -->
    <Modal
      v-if="dialog === 'folder-create' || dialog === 'folder-rename'"
      :title="dialogTitle"
      @close="closeDialog"
    >
      <label class="mb-1 block text-xs font-semibold text-muted">Название</label>
      <input
        v-model="dialogInput"
        type="text"
        class="mb-3 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm outline-none focus:border-brand"
        maxlength="255"
        @keydown.enter.prevent="submitDialog"
      />
      <p v-if="dialogError" class="mb-3 text-xs text-danger">{{ dialogError }}</p>
      <div class="flex justify-end gap-2">
        <button type="button" class="rounded-xl border border-line px-3 py-2 text-sm" @click="closeDialog">
          Отмена
        </button>
        <button
          type="button"
          class="rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="treeBusy || store.saving"
          @click="submitDialog"
        >
          {{ dialog === 'folder-rename' ? 'Сохранить' : 'Создать' }}
        </button>
      </div>
    </Modal>

    <Modal v-if="dialog === 'article-create'" :title="dialogTitle" @close="closeDialog">
      <label class="mb-1 block text-xs font-semibold text-muted">Название</label>
      <input
        v-model="dialogInput"
        type="text"
        class="mb-3 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm outline-none focus:border-brand"
        maxlength="255"
        @keydown.enter.prevent="submitDialog"
      />
      <label class="mb-4 flex items-center gap-2 text-sm">
        <input v-model="dialogPublished" type="checkbox" />
        Сразу опубликовать
      </label>
      <p v-if="dialogError" class="mb-3 text-xs text-danger">{{ dialogError }}</p>
      <div class="flex justify-end gap-2">
        <button type="button" class="rounded-xl border border-line px-3 py-2 text-sm" @click="closeDialog">
          Отмена
        </button>
        <button
          type="button"
          class="rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="treeBusy || store.saving"
          @click="submitDialog"
        >
          Создать
        </button>
      </div>
    </Modal>

    <Modal v-if="dialog === 'folder-delete'" :title="dialogTitle" @close="closeDialog">
      <p class="mb-4 text-sm text-ink">
        Удалить раздел
        <span class="font-semibold">«{{ dialogFolder?.title }}»</span>
        вместе со всеми подразделами и статьями? Это нельзя отменить.
      </p>
      <p v-if="dialogError" class="mb-3 text-xs text-danger">{{ dialogError }}</p>
      <div class="flex justify-end gap-2">
        <button type="button" class="rounded-xl border border-line px-3 py-2 text-sm" @click="closeDialog">
          Отмена
        </button>
        <button
          type="button"
          class="rounded-xl bg-danger px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="treeBusy || store.saving"
          @click="submitDialog"
        >
          Удалить
        </button>
      </div>
    </Modal>

    <Modal v-if="dialog === 'article-delete'" :title="dialogTitle" @close="closeDialog">
      <p class="mb-4 text-sm text-ink">
        Удалить статью
        <span class="font-semibold">«{{ store.current?.title }}»</span>?
      </p>
      <p v-if="dialogError" class="mb-3 text-xs text-danger">{{ dialogError }}</p>
      <div class="flex justify-end gap-2">
        <button type="button" class="rounded-xl border border-line px-3 py-2 text-sm" @click="closeDialog">
          Отмена
        </button>
        <button
          type="button"
          class="rounded-xl bg-danger px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="treeBusy || store.saving"
          @click="submitDialog"
        >
          Удалить
        </button>
      </div>
    </Modal>

    <Modal v-if="dialog === 'article-move'" :title="dialogTitle" @close="closeDialog">
      <label class="mb-1 block text-xs font-semibold text-muted">Раздел</label>
      <select
        v-model.number="dialogMoveFolderId"
        class="mb-4 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm outline-none focus:border-brand"
      >
        <option
          v-for="f in store.flatFolderOptions"
          :key="f.id"
          :value="f.id"
        >
          {{ '—'.repeat(f.depth) }}{{ f.depth ? ' ' : '' }}{{ f.title }}
        </option>
      </select>
      <p v-if="dialogError" class="mb-3 text-xs text-danger">{{ dialogError }}</p>
      <div class="flex justify-end gap-2">
        <button type="button" class="rounded-xl border border-line px-3 py-2 text-sm" @click="closeDialog">
          Отмена
        </button>
        <button
          type="button"
          class="rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="treeBusy || store.saving || dialogMoveFolderId == null"
          @click="submitDialog"
        >
          Перенести
        </button>
      </div>
    </Modal>
  </div>
</template>
