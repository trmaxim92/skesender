<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Clock,
  Copy,
  Eye,
  FileText,
  Folder,
  FolderInput,
  FolderPlus,
  Home,
  Lightbulb,
  MessageCircle,
  MoreHorizontal,
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
  flattenKbArticles,
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
const activeTocId = ref<string | null>(null)
let searchTimer: ReturnType<typeof setTimeout> | undefined
const expanded = ref<Set<number>>(new Set())
const editing = ref(false)
const previewing = ref(false)
const draftTitle = ref('')
const draftHtml = ref('')
const draftPublished = ref(true)
const menuFolderId = ref<number | null>(null)
const articleMenuOpen = ref(false)
const treeBusy = ref(false)
const copyDone = ref(false)

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

const flatArticles = computed(() => flattenKbArticles(store.folders))

const popularArticles = computed(() => {
  const fromRecent = recent.value
    .map((r) => flatArticles.value.find((a) => a.id === r.id))
    .filter((a): a is NonNullable<typeof a> => !!a)
  const rest = flatArticles.value.filter((a) => !fromRecent.some((r) => r.id === a.id))
  return [...fromRecent, ...rest].slice(0, 3)
})

const relatedArticles = computed(() => {
  const cur = store.current
  if (!cur) return []
  return flatArticles.value
    .filter((a) => a.folderId === cur.folderId && a.id !== cur.id)
    .slice(0, 4)
})

const currentFolderTitle = computed(() => {
  const cur = store.current
  if (!cur) return ''
  return flatArticles.value.find((a) => a.id === cur.id)?.folderTitle ?? ''
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
  previewing.value = false
  menuFolderId.value = null
  articleMenuOpen.value = false
  void router.push({ name: 'knowledge-article', params: { articleId: String(id) } })
}

function backToTree() {
  editing.value = false
  previewing.value = false
  menuFolderId.value = null
  articleMenuOpen.value = false
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
  previewing.value = false
  editing.value = true
  articleMenuOpen.value = false
}

function cancelEdit() {
  editing.value = false
  previewing.value = false
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
    previewing.value = false
    toc.value = []
    pushKbRecent(saved.id, saved.title)
    recent.value = loadKbRecent()
  }
}

async function copyLink() {
  try {
    await navigator.clipboard.writeText(window.location.href)
    copyDone.value = true
    setTimeout(() => {
      copyDone.value = false
    }, 1600)
  } catch {
    /* ignore */
  }
}

function goSupport() {
  void router.push({ name: 'chats' })
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
  articleMenuOpen.value = false
  dialogError.value = ''
  dialog.value = 'article-delete'
  dialogTitle.value = 'Удалить статью'
}

function openMoveArticle() {
  if (!store.current || !canWrite.value) return
  articleMenuOpen.value = false
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
      previewing.value = false
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
      previewing.value = false
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

function onTocClick(id: string) {
  activeTocId.value = id
  articleBodyRef.value?.scrollToHeading(id)
}

function onDocClick() {
  menuFolderId.value = null
  articleMenuOpen.value = false
}

watch(articleId, async (id) => {
  if (id == null) {
    store.clearArticle()
    editing.value = false
    previewing.value = false
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
  <div class="kb-shell flex h-full min-h-0 overflow-hidden bg-[#f0f2f7]">
    <!-- Tree sidebar -->
    <aside
      class="flex w-full shrink-0 flex-col border-r border-line/70 bg-panel md:w-[292px] lg:w-[310px]"
      :class="articleId ? 'hidden md:flex' : 'flex'"
    >
      <div class="border-b border-line/80 px-4 pb-3.5 pt-4">
        <div class="mb-3.5 flex items-center gap-2.5">
          <div class="flex size-9 items-center justify-center rounded-xl bg-brand text-white shadow-sm shadow-brand/25">
            <BookOpen class="size-4" />
          </div>
          <div class="min-w-0">
            <div class="text-[14px] font-bold leading-tight tracking-tight text-ink">База знаний</div>
            <div class="text-[11px] text-muted">Инструкции для смены</div>
          </div>
        </div>
        <div class="relative">
          <Search
            class="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted"
          />
          <input
            v-model="search"
            type="search"
            placeholder="Найти статью…"
            class="w-full rounded-xl border-0 bg-[#eef1f6] py-2.5 pl-9 pr-3 text-[13px] outline-none ring-1 ring-transparent transition placeholder:text-muted/70 focus:bg-panel focus:ring-brand/30"
          />
        </div>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2.5 py-3" @click.stop>
        <p v-if="store.loading" class="px-2 py-4 text-sm text-muted">Загрузка…</p>
        <p v-else-if="store.error && store.isEmpty" class="px-2 py-4 text-sm text-danger">
          {{ store.error }}
        </p>
        <template v-else-if="showSearchPanel">
          <p v-if="searchLoading" class="px-2 py-3 text-xs text-muted">Ищем…</p>
          <p v-else-if="!searchHits.length" class="px-2 py-3 text-xs text-muted">Ничего не найдено</p>
          <ul v-else class="space-y-0.5">
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
          <!-- Все статьи -->
          <button
            type="button"
            class="mb-0.5 flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2.5 text-left transition"
            :class="
              !articleId
                ? 'bg-brand-soft font-semibold text-brand'
                : 'text-ink/85 hover:bg-surface'
            "
            @click="backToTree"
          >
            <FileText class="size-3.5 shrink-0 opacity-70" />
            <span class="min-w-0 flex-1 truncate text-[13px]">Все статьи</span>
            <span
              class="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold tabular-nums"
              :class="!articleId ? 'bg-brand text-white' : 'bg-surface text-muted'"
              >{{ store.articleCount }}</span
            >
          </button>

          <!-- Недавние -->
          <div v-if="recent.length" class="mb-2 mt-3">
            <div
              class="mb-1 flex items-center gap-1.5 px-2.5 text-[10px] font-bold uppercase tracking-[0.08em] text-muted"
            >
              <Clock class="size-3" />
              Недавние
            </div>
            <button
              v-for="r in recent.slice(0, 4)"
              :key="'r' + r.id"
              type="button"
              class="mb-0.5 flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] transition"
              :class="
                articleId === r.id
                  ? 'bg-brand-soft font-semibold text-brand'
                  : 'text-ink/80 hover:bg-surface'
              "
              @click="openArticle(r.id)"
            >
              <FileText class="size-3.5 shrink-0 opacity-50" />
              <span class="truncate">{{ r.title }}</span>
            </button>
          </div>

          <div
            class="mb-1 mt-3 px-2.5 text-[10px] font-bold uppercase tracking-[0.08em] text-muted"
          >
            Разделы
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

      <div v-if="canWrite" class="border-t border-line/80 p-3">
        <button
          type="button"
          class="flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-3 py-2.5 text-sm font-semibold text-white shadow-sm shadow-brand/20 transition hover:brightness-95 disabled:opacity-50"
          :disabled="treeBusy || store.saving"
          @click="openCreateFolder(null)"
        >
          <Plus class="size-4" />
          Новый раздел
        </button>
      </div>
    </aside>

    <!-- Main -->
    <section
      class="relative flex min-w-0 flex-1 flex-col overflow-hidden"
      :class="!articleId && !store.isEmpty ? 'hidden md:flex' : 'flex'"
    >
      <!-- Empty KB -->
      <div
        v-if="store.isEmpty && !store.loading"
        class="flex flex-1 flex-col items-center justify-center px-6 py-12 text-center"
      >
        <div
          class="mb-5 flex size-16 items-center justify-center rounded-3xl bg-brand text-white shadow-lg shadow-brand/25"
        >
          <BookOpen class="size-8" />
        </div>
        <h1 class="text-2xl font-bold tracking-tight text-ink sm:text-3xl">База знаний</h1>
        <p class="mt-2 max-w-md text-sm leading-relaxed text-muted">
          Живые инструкции для операторов — скрипты, регламенты и ответы на частые вопросы.
        </p>
        <button
          v-if="canWrite"
          type="button"
          class="mt-6 inline-flex items-center gap-2 rounded-xl bg-brand px-5 py-2.5 text-sm font-semibold text-white"
          @click="openCreateFolder(null)"
        >
          <FolderPlus class="size-4" />
          Создать первый раздел
        </button>
      </div>

      <!-- Home / no article -->
      <div
        v-else-if="!articleId"
        class="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain"
      >
        <div class="mx-auto flex w-full max-w-4xl flex-1 flex-col px-5 py-6 sm:px-8 sm:py-8">
          <button
            type="button"
            class="mb-8 inline-flex items-center gap-1.5 self-start text-[13px] text-muted transition hover:text-brand"
            @click="backToTree"
          >
            <ArrowLeft class="size-3.5" />
            База знаний
          </button>

          <div class="flex flex-1 flex-col items-center justify-center text-center">
            <div class="kb-home-glow relative mb-5">
              <div
                class="relative z-[1] flex size-[4.5rem] items-center justify-center rounded-2xl bg-brand-soft text-brand"
              >
                <FileText class="size-8" stroke-width="1.6" />
              </div>
            </div>
            <h1 class="text-2xl font-bold tracking-tight text-ink sm:text-[1.75rem]">
              Выберите статью слева
            </h1>
            <p class="mt-2 max-w-sm text-[14px] leading-relaxed text-muted">
              Здесь собраны все инструкции и материалы для удобной работы
            </p>
          </div>

          <div v-if="popularArticles.length" class="mt-10 pb-2">
            <div class="mb-3 flex items-center justify-between gap-3">
              <h2 class="text-[15px] font-bold text-ink">Популярные материалы</h2>
              <span class="text-[12px] font-medium text-muted"
                >{{ store.articleCount }} статей →</span
              >
            </div>
            <div class="grid gap-3 sm:grid-cols-3">
              <button
                v-for="(card, idx) in popularArticles"
                :key="card.id"
                type="button"
                class="group flex flex-col rounded-2xl border border-line/80 bg-panel p-4 text-left shadow-[0_1px_3px_rgba(21,32,51,0.04)] transition hover:border-brand/30 hover:shadow-[0_8px_24px_rgba(21,32,51,0.07)]"
                @click="openArticle(card.id)"
              >
                <div
                  class="mb-3 flex size-9 items-center justify-center rounded-xl"
                  :class="
                    idx === 0
                      ? 'bg-brand-soft text-brand'
                      : idx === 1
                        ? 'bg-[#eef2ff] text-[#4f6bed]'
                        : 'bg-[#ecfdf5] text-[#0d9f6e]'
                  "
                >
                  <FileText v-if="idx === 0" class="size-4" />
                  <Clock v-else-if="idx === 1" class="size-4" />
                  <BookOpen v-else class="size-4" />
                </div>
                <div class="mb-1 line-clamp-2 text-[14px] font-bold leading-snug text-ink">
                  {{ card.title }}
                </div>
                <p class="mb-3 line-clamp-2 flex-1 text-[12px] leading-relaxed text-muted">
                  {{ card.folderTitle }}
                </p>
                <div
                  class="ml-auto flex size-7 items-center justify-center rounded-lg bg-surface text-muted transition group-hover:bg-brand group-hover:text-white"
                >
                  <ArrowRight class="size-3.5" />
                </div>
              </button>
            </div>
          </div>

          <div
            class="mt-6 flex flex-col items-start gap-3 rounded-2xl border border-[#cfe0f5] bg-[#eaf3fc] px-4 py-4 sm:flex-row sm:items-center sm:px-5"
          >
            <div class="flex min-w-0 flex-1 items-start gap-3">
              <div
                class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-white text-[#3b82c4] shadow-sm"
              >
                <Lightbulb class="size-4" />
              </div>
              <div class="min-w-0">
                <div class="text-[13px] font-bold text-ink">Нужна помощь?</div>
                <p class="mt-0.5 text-[12px] leading-relaxed text-muted">
                  Если не нашли нужную информацию, обратитесь к администратору или напишите в
                  поддержку.
                </p>
              </div>
            </div>
            <button
              type="button"
              class="inline-flex shrink-0 items-center gap-2 rounded-xl bg-panel px-3.5 py-2 text-[13px] font-semibold text-ink shadow-sm ring-1 ring-line/80 transition hover:ring-brand/30"
              @click="goSupport"
            >
              <MessageCircle class="size-3.5 text-brand" />
              Написать в поддержку
            </button>
          </div>
        </div>
      </div>

      <!-- Article: read / edit -->
      <template v-else>
        <div class="flex min-h-0 flex-1 overflow-hidden">
          <div class="min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain">
            <div
              class="mx-auto px-4 py-5 sm:px-7 sm:py-7"
              :class="editing ? 'max-w-4xl' : 'max-w-3xl xl:max-w-[52rem]'"
            >
              <!-- Breadcrumb -->
              <div class="mb-5 flex items-center gap-2">
                <button
                  type="button"
                  class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-panel text-muted shadow-sm ring-1 ring-line/60 md:hidden"
                  aria-label="К дереву"
                  @click="backToTree"
                >
                  <ArrowLeft class="size-4" />
                </button>
                <nav class="flex min-w-0 flex-wrap items-center gap-1 text-[12px] text-muted">
                  <button
                    type="button"
                    class="flex size-6 items-center justify-center rounded-md transition hover:bg-panel hover:text-brand"
                    @click="backToTree"
                  >
                    <Home class="size-3.5" />
                  </button>
                  <template v-for="(c, i) in breadcrumb" :key="i">
                    <span class="opacity-35">›</span>
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

              <!-- Header -->
              <header class="mb-6">
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div class="min-w-0 flex-1">
                    <div v-if="!editing" class="mb-2.5">
                      <span
                        class="inline-flex items-center gap-1 rounded-md bg-brand px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white"
                      >
                        Инструкция
                      </span>
                    </div>

                    <div v-if="editing" class="flex items-center gap-2">
                      <input
                        v-model="draftTitle"
                        class="w-full border-0 bg-transparent text-[1.65rem] font-bold tracking-tight text-ink outline-none placeholder:text-muted/45 sm:text-[1.85rem]"
                        placeholder="Название статьи"
                      />
                      <Pencil class="size-4 shrink-0 text-muted" />
                    </div>
                    <h1
                      v-else
                      class="text-[1.65rem] font-bold leading-tight tracking-tight text-ink sm:text-[1.85rem]"
                    >
                      {{ store.current?.title ?? '…' }}
                    </h1>

                    <!-- Read meta -->
                    <div
                      v-if="!editing && store.current"
                      class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-muted"
                    >
                      <span class="inline-flex items-center gap-1.5">
                        <Clock class="size-3.5 opacity-70" />
                        {{ formatDate(store.current.updatedAt) }}
                      </span>
                      <span v-if="store.current.updatedByName" class="inline-flex items-center gap-1.5">
                        <span
                          class="flex size-5 items-center justify-center rounded-full bg-ink/90 text-[9px] font-bold text-white"
                          >{{ store.current.updatedByName.slice(0, 1).toUpperCase() }}</span
                        >
                        {{ store.current.updatedByName }}
                      </span>
                      <span
                        v-if="currentFolderTitle"
                        class="inline-flex items-center gap-1.5"
                      >
                        <Folder class="size-3.5 opacity-70" />
                        {{ currentFolderTitle }}
                      </span>
                      <span
                        v-if="!store.current.isPublished"
                        class="rounded-full bg-warn/15 px-2 py-0.5 text-[10px] font-semibold text-warn"
                        >черновик</span
                      >
                    </div>

                    <!-- Edit status -->
                    <div v-else-if="editing" class="mt-3">
                      <button
                        type="button"
                        class="inline-flex items-center gap-2 rounded-full px-3 py-1 text-[12px] font-semibold"
                        :class="
                          draftPublished
                            ? 'bg-ok/12 text-ok'
                            : 'bg-warn/12 text-warn'
                        "
                        @click="draftPublished = !draftPublished"
                      >
                        <span
                          class="size-1.5 rounded-full"
                          :class="draftPublished ? 'bg-ok' : 'bg-warn'"
                        />
                        {{ draftPublished ? 'Опубликовано' : 'Черновик' }}
                      </button>
                    </div>
                  </div>

                  <!-- Actions -->
                  <div v-if="canWrite || !editing" class="flex shrink-0 flex-wrap items-center gap-2">
                    <template v-if="editing">
                      <button
                        type="button"
                        class="inline-flex items-center gap-1.5 rounded-xl border border-line bg-panel px-3 py-2 text-[13px] font-medium transition hover:border-brand/30"
                        :class="previewing ? 'border-brand/40 bg-brand-soft text-brand' : ''"
                        @click="previewing = !previewing"
                      >
                        <Eye class="size-3.5" />
                        Предпросмотр
                      </button>
                      <button
                        type="button"
                        class="rounded-xl border border-line bg-panel px-3.5 py-2 text-[13px] font-medium"
                        :disabled="store.saving"
                        @click="cancelEdit"
                      >
                        Отмена
                      </button>
                      <button
                        type="button"
                        class="rounded-xl bg-brand px-4 py-2 text-[13px] font-semibold text-white shadow-sm shadow-brand/20 disabled:opacity-50"
                        :disabled="store.saving || !draftTitle.trim()"
                        @click="saveEdit"
                      >
                        {{ store.saving ? 'Сохранение…' : 'Сохранить' }}
                      </button>
                      <div class="relative" @click.stop>
                        <button
                          type="button"
                          class="flex size-9 items-center justify-center rounded-xl border border-line bg-panel text-muted"
                          @click="articleMenuOpen = !articleMenuOpen"
                        >
                          <MoreHorizontal class="size-4" />
                        </button>
                        <div
                          v-if="articleMenuOpen"
                          class="absolute right-0 top-full z-20 mt-1 w-44 overflow-hidden rounded-xl border border-line bg-panel py-1 shadow-lg"
                        >
                          <button
                            type="button"
                            class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-surface"
                            @click="openMoveArticle"
                          >
                            <FolderInput class="size-3.5" /> Перенести
                          </button>
                          <button
                            type="button"
                            class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-danger hover:bg-danger-soft"
                            @click="openDeleteArticle"
                          >
                            <Trash2 class="size-3.5" /> Удалить
                          </button>
                        </div>
                      </div>
                    </template>
                    <template v-else>
                      <button
                        v-if="canWrite"
                        type="button"
                        class="inline-flex items-center gap-1.5 rounded-xl bg-ink px-3.5 py-2 text-[13px] font-semibold text-white"
                        @click="startEdit"
                      >
                        <Pencil class="size-3.5" />
                        Редактировать
                      </button>
                      <button
                        type="button"
                        class="flex size-9 items-center justify-center rounded-xl border border-line bg-panel text-muted transition hover:text-brand"
                        :title="copyDone ? 'Скопировано' : 'Скопировать ссылку'"
                        @click="copyLink"
                      >
                        <Copy class="size-3.5" />
                      </button>
                      <div v-if="canWrite" class="relative" @click.stop>
                        <button
                          type="button"
                          class="flex size-9 items-center justify-center rounded-xl border border-line bg-panel text-muted"
                          @click="articleMenuOpen = !articleMenuOpen"
                        >
                          <MoreHorizontal class="size-4" />
                        </button>
                        <div
                          v-if="articleMenuOpen"
                          class="absolute right-0 top-full z-20 mt-1 w-44 overflow-hidden rounded-xl border border-line bg-panel py-1 shadow-lg"
                        >
                          <button
                            type="button"
                            class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-surface"
                            @click="openMoveArticle"
                          >
                            <FolderInput class="size-3.5" /> Перенести
                          </button>
                          <button
                            type="button"
                            class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-danger hover:bg-danger-soft"
                            @click="openDeleteArticle"
                          >
                            <Trash2 class="size-3.5" /> Удалить
                          </button>
                        </div>
                      </div>
                    </template>
                  </div>
                </div>
                <p v-if="store.error" class="mt-2 text-xs text-danger">{{ store.error }}</p>
              </header>

              <!-- Body -->
              <p v-if="store.loadingArticle" class="py-10 text-sm text-muted">Загрузка…</p>
              <template v-else-if="store.current">
                <div v-if="editing && !previewing">
                  <KbRichEditor :key="store.current.id" v-model="draftHtml" />
                </div>
                <div v-else class="kb-read-card rounded-2xl bg-panel px-5 py-6 shadow-[0_1px_2px_rgba(21,32,51,0.04)] sm:px-8 sm:py-8">
                  <KbArticleBody
                    ref="articleBodyRef"
                    :html="
                      editing
                        ? draftHtml || '<p></p>'
                        : store.current.bodyHtml ||
                          '<p>Пустая статья — нажмите «Редактировать».</p>'
                    "
                    @toc="toc = $event"
                  />
                </div>
              </template>
            </div>
          </div>

          <!-- Right rail (read mode only) -->
          <aside
            v-if="!editing && store.current"
            class="hidden w-[240px] shrink-0 flex-col gap-4 overflow-y-auto border-l border-line/70 bg-panel/60 px-4 py-6 xl:flex"
          >
            <div v-if="toc.length">
              <div class="mb-2.5 text-[11px] font-bold uppercase tracking-[0.07em] text-muted">
                Содержание
              </div>
              <nav class="space-y-0.5">
                <button
                  v-for="(item, idx) in toc"
                  :key="item.id"
                  type="button"
                  class="relative flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] transition hover:bg-surface"
                  :class="[
                    item.level >= 3 ? 'pl-5 text-muted' : 'font-medium text-ink/85',
                    activeTocId === item.id ? 'bg-brand-soft text-brand' : '',
                  ]"
                  @click="onTocClick(item.id)"
                >
                  <span
                    v-if="activeTocId === item.id || (!activeTocId && idx === 0)"
                    class="absolute bottom-1.5 left-0 top-1.5 w-[2.5px] rounded-r-full bg-brand"
                  />
                  <span class="line-clamp-2">{{ item.text }}</span>
                </button>
              </nav>
            </div>

            <div
              v-if="relatedArticles.length"
              class="rounded-2xl border border-line/80 bg-panel p-3.5 shadow-sm"
            >
              <div class="mb-2.5 text-[11px] font-bold uppercase tracking-[0.07em] text-muted">
                Полезные материалы
              </div>
              <ul class="space-y-1">
                <li v-for="r in relatedArticles" :key="'rel' + r.id">
                  <button
                    type="button"
                    class="flex w-full items-center gap-2 rounded-lg px-1.5 py-1.5 text-left text-[12px] text-ink/85 transition hover:bg-surface hover:text-brand"
                    @click="openArticle(r.id)"
                  >
                    <FileText class="size-3.5 shrink-0 opacity-50" />
                    <span class="min-w-0 flex-1 truncate">{{ r.title }}</span>
                    <ArrowRight class="size-3 shrink-0 opacity-40" />
                  </button>
                </li>
              </ul>
            </div>

            <div class="rounded-2xl border border-[#cfe0f5] bg-[#eaf3fc] p-3.5">
              <div class="mb-1 flex items-center gap-2">
                <Lightbulb class="size-3.5 text-[#3b82c4]" />
                <span class="text-[13px] font-bold text-ink">Нужна помощь?</span>
              </div>
              <p class="mb-3 text-[11px] leading-relaxed text-muted">
                Не нашли ответ — напишите в поддержку.
              </p>
              <button
                type="button"
                class="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-panel px-3 py-2 text-[12px] font-semibold text-ink shadow-sm ring-1 ring-line/70"
                @click="goSupport"
              >
                <MessageCircle class="size-3.5 text-brand" />
                Написать
              </button>
            </div>
          </aside>
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
        <option v-for="f in store.flatFolderOptions" :key="f.id" :value="f.id">
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
