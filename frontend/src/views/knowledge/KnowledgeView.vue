<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { BookOpen, FileText, FolderPlus, Pencil, Plus, Search, Trash2 } from 'lucide-vue-next'
import KbRichEditor from '@/components/knowledge/KbRichEditor.vue'
import KbTreeNodes from '@/components/knowledge/KbTreeNodes.vue'
import { useAuthStore } from '@/stores/auth'
import { useKnowledgeStore } from '@/stores/knowledge'
import type { KbFolderNode } from '@/types'

const auth = useAuthStore()
const store = useKnowledgeStore()
const route = useRoute()
const router = useRouter()

const canWrite = computed(() => auth.can('section.knowledge') && auth.can('action.write'))
const search = ref('')
const expanded = ref<Set<number>>(new Set())
const editing = ref(false)
const draftTitle = ref('')
const draftHtml = ref('')
const menuFolderId = ref<number | null>(null)
const treeBusy = ref(false)

const articleId = computed(() => {
  const raw = route.params.articleId
  if (!raw) return null
  const n = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isFinite(n) ? n : null
})

const breadcrumb = computed(() => {
  const art = store.current
  if (!art) return [{ title: 'База знаний' }]
  const path: { title: string }[] = []
  const find = (nodes: KbFolderNode[], trail: { title: string }[]): boolean => {
    for (const n of nodes) {
      const next = [...trail, { title: n.title }]
      if (n.articles.some((a) => a.id === art.id)) {
        path.push(...next)
        return true
      }
      if (find(n.children, next)) return true
    }
    return false
  }
  find(store.folders, [])
  return [{ title: 'База знаний' }, ...path, { title: art.title }]
})

const filteredFolders = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return store.folders
  return filterTree(store.folders, q)
})

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
  const needle = q.trim().toLowerCase()
  if (!needle) return
  const ids = new Set(expanded.value)
  const collect = (nodes: KbFolderNode[]) => {
    for (const node of nodes) {
      ids.add(node.id)
      collect(node.children)
    }
  }
  collect(filteredFolders.value)
  expanded.value = ids
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

function startEdit() {
  if (!store.current || !canWrite.value) return
  draftTitle.value = store.current.title
  draftHtml.value = store.current.bodyHtml || ''
  editing.value = true
}

function cancelEdit() {
  editing.value = false
  if (store.current) {
    draftTitle.value = store.current.title
    draftHtml.value = store.current.bodyHtml || ''
  }
}

async function saveEdit() {
  if (!store.current || !draftTitle.value.trim()) return
  const saved = await store.saveArticle(store.current.id, {
    title: draftTitle.value.trim(),
    bodyHtml: draftHtml.value,
  })
  if (saved) editing.value = false
}

async function promptNewFolder(parentId: number | null = null) {
  if (!canWrite.value) return
  const title = window.prompt('Название раздела')
  if (!title?.trim()) return
  treeBusy.value = true
  const ok = await store.createFolder(title.trim(), parentId)
  treeBusy.value = false
  if (ok && parentId != null) {
    expanded.value.add(parentId)
    expanded.value = new Set(expanded.value)
  }
  menuFolderId.value = null
}

async function promptRenameFolder(folder: KbFolderNode) {
  if (!canWrite.value) return
  const title = window.prompt('Новое название', folder.title)
  if (!title?.trim() || title.trim() === folder.title) {
    menuFolderId.value = null
    return
  }
  treeBusy.value = true
  await store.renameFolder(folder.id, title.trim())
  treeBusy.value = false
  menuFolderId.value = null
}

async function confirmDeleteFolder(folder: KbFolderNode) {
  if (!canWrite.value) return
  if (!window.confirm(`Удалить раздел «${folder.title}» и всё содержимое?`)) {
    menuFolderId.value = null
    return
  }
  treeBusy.value = true
  await store.removeFolder(folder.id)
  treeBusy.value = false
  menuFolderId.value = null
  if (articleId.value && !findArticleInTree(store.folders, articleId.value)) {
    void router.push({ name: 'knowledge' })
  }
}

function findArticleInTree(nodes: KbFolderNode[], id: number): boolean {
  for (const n of nodes) {
    if (n.articles.some((a) => a.id === id)) return true
    if (findArticleInTree(n.children, id)) return true
  }
  return false
}

async function promptNewArticle(folderId: number) {
  if (!canWrite.value) return
  const title = window.prompt('Название статьи')
  if (!title?.trim()) return
  treeBusy.value = true
  const article = await store.createArticle(folderId, title.trim(), '<p></p>')
  treeBusy.value = false
  menuFolderId.value = null
  if (article) {
    expanded.value.add(folderId)
    expanded.value = new Set(expanded.value)
    draftTitle.value = article.title
    draftHtml.value = article.bodyHtml || ''
    editing.value = true
    void router.push({ name: 'knowledge-article', params: { articleId: String(article.id) } })
  }
}

async function confirmDeleteArticle() {
  if (!store.current || !canWrite.value) return
  if (!window.confirm(`Удалить статью «${store.current.title}»?`)) return
  const ok = await store.removeArticle(store.current.id)
  if (ok) {
    editing.value = false
    void router.push({ name: 'knowledge' })
  }
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

watch(articleId, async (id) => {
  if (id == null) {
    store.clearArticle()
    editing.value = false
    return
  }
  const art = await store.loadArticle(id)
  if (art) {
    draftTitle.value = art.title
    draftHtml.value = art.bodyHtml || ''
    expandParentsOfArticle(id)
  }
})

onMounted(async () => {
  await store.fetchTree()
  if (articleId.value != null) {
    const art = await store.loadArticle(articleId.value)
    if (art) {
      draftTitle.value = art.title
      draftHtml.value = art.bodyHtml || ''
      expandParentsOfArticle(articleId.value)
    }
  } else if (store.folders.length) {
    for (const f of store.folders) expanded.value.add(f.id)
    expanded.value = new Set(expanded.value)
  }
})
</script>

<template>
  <div class="kb-shell flex h-full min-h-0 overflow-hidden bg-surface">
    <aside
      class="flex w-full max-w-full shrink-0 flex-col border-r border-line bg-panel md:w-[280px] lg:w-[300px]"
      :class="articleId ? 'max-md:hidden' : ''"
    >
      <div class="border-b border-line px-3 py-3">
        <div class="relative">
          <Search
            class="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted"
          />
          <input
            v-model="search"
            type="search"
            placeholder="Поиск по разделам…"
            class="w-full rounded-xl border border-line bg-surface py-2 pl-9 pr-3 text-sm outline-none focus:border-brand"
          />
        </div>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        <p v-if="store.loading" class="px-2 py-4 text-sm text-muted">Загрузка…</p>
        <p v-else-if="store.error && store.isEmpty" class="px-2 py-4 text-sm text-danger">
          {{ store.error }}
        </p>
        <KbTreeNodes
          v-else
          :nodes="filteredFolders"
          :expanded="expanded"
          :active-id="articleId"
          :can-write="canWrite"
          :menu-folder-id="menuFolderId"
          :folder-article-count="folderArticleCount"
          @toggle="toggleExpand"
          @open="openArticle"
          @menu="menuFolderId = $event"
          @new-folder="promptNewFolder"
          @new-article="promptNewArticle"
          @rename="promptRenameFolder"
          @delete="confirmDeleteFolder"
        />
      </div>

      <div v-if="canWrite" class="border-t border-line p-2">
        <button
          type="button"
          class="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-line px-3 py-2.5 text-sm font-medium text-ink transition hover:border-brand hover:bg-brand-soft hover:text-brand disabled:opacity-50"
          :disabled="treeBusy || store.saving"
          @click="promptNewFolder(null)"
        >
          <FolderPlus class="size-4" />
          Новый раздел
        </button>
      </div>
    </aside>

    <section
      class="relative flex min-w-0 flex-1 flex-col overflow-hidden"
      :class="!articleId && !store.isEmpty ? 'max-md:hidden' : ''"
    >
      <div
        v-if="store.isEmpty && !store.loading"
        class="relative flex flex-1 flex-col items-center justify-center overflow-hidden px-6 py-16 text-center"
      >
        <div
          class="pointer-events-none absolute inset-0 opacity-[0.55]"
          style="
            background:
              radial-gradient(
                ellipse 80% 60% at 20% 10%,
                color-mix(in srgb, var(--color-brand) 18%, transparent),
                transparent 55%
              ),
              radial-gradient(
                ellipse 70% 50% at 90% 80%,
                color-mix(in srgb, var(--color-sidebar) 12%, transparent),
                transparent 50%
              ),
              linear-gradient(160deg, var(--color-surface), var(--color-panel));
          "
        />
        <div class="relative max-w-md">
          <div
            class="mx-auto mb-5 flex size-14 items-center justify-center rounded-2xl bg-brand text-white shadow-lg shadow-brand/25"
          >
            <BookOpen class="size-7" />
          </div>
          <h1 class="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">База знаний</h1>
          <p class="mt-3 text-sm leading-relaxed text-muted">
            Разделы и статьи для операторов — инструкции, скрипты ответов, внутренние регламенты.
          </p>
          <button
            v-if="canWrite"
            type="button"
            class="mt-6 inline-flex items-center gap-2 rounded-xl bg-brand px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-95"
            @click="promptNewFolder(null)"
          >
            <Plus class="size-4" />
            Создать первый раздел
          </button>
          <p v-else class="mt-6 text-sm text-muted">Пока нет опубликованных материалов.</p>
        </div>
      </div>

      <div
        v-else-if="!articleId"
        class="flex flex-1 flex-col items-center justify-center px-6 text-center"
      >
        <FileText class="mb-3 size-10 text-muted/40" />
        <p class="text-sm font-medium text-ink">Выберите статью</p>
        <p class="mt-1 max-w-xs text-xs text-muted">
          {{ store.articleCount }}
          {{ store.articleCount === 1 ? 'статья' : store.articleCount < 5 ? 'статьи' : 'статей' }}
          в дереве слева
        </p>
      </div>

      <template v-else>
        <header class="shrink-0 border-b border-line bg-panel/90 px-4 py-3 backdrop-blur sm:px-6">
          <nav class="mb-2 flex flex-wrap items-center gap-1 text-[11px] text-muted">
            <template v-for="(c, i) in breadcrumb" :key="i">
              <span v-if="i > 0" class="opacity-40">/</span>
              <span :class="i === breadcrumb.length - 1 ? 'font-medium text-ink' : ''">{{
                c.title
              }}</span>
            </template>
          </nav>
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <input
                v-if="editing"
                v-model="draftTitle"
                class="w-full rounded-lg border border-line bg-surface px-3 py-1.5 text-xl font-semibold outline-none focus:border-brand"
              />
              <h1 v-else class="truncate text-xl font-semibold text-ink sm:text-2xl">
                {{ store.current?.title ?? '…' }}
              </h1>
              <p v-if="store.current && !editing" class="mt-1 text-xs text-muted">
                <span v-if="store.current.updatedByName">{{ store.current.updatedByName }} · </span>
                {{ formatDate(store.current.updatedAt) }}
                <span
                  v-if="!store.current.isPublished"
                  class="ml-2 rounded bg-warn/15 px-1.5 py-0.5 text-warn"
                  >черновик</span
                >
              </p>
            </div>
            <div v-if="canWrite" class="flex shrink-0 flex-wrap gap-2">
              <template v-if="editing">
                <button
                  type="button"
                  class="rounded-xl border border-line px-3 py-1.5 text-sm"
                  :disabled="store.saving"
                  @click="cancelEdit"
                >
                  Отмена
                </button>
                <button
                  type="button"
                  class="rounded-xl bg-brand px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
                  :disabled="store.saving || !draftTitle.trim()"
                  @click="saveEdit"
                >
                  {{ store.saving ? 'Сохранение…' : 'Сохранить' }}
                </button>
              </template>
              <template v-else>
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 rounded-xl border border-line px-3 py-1.5 text-sm"
                  @click="startEdit"
                >
                  <Pencil class="size-3.5" />
                  Изменить
                </button>
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 rounded-xl border border-line px-3 py-1.5 text-sm text-danger"
                  @click="confirmDeleteArticle"
                >
                  <Trash2 class="size-3.5" />
                  Удалить
                </button>
              </template>
            </div>
          </div>
          <p v-if="store.error" class="mt-2 text-xs text-danger">{{ store.error }}</p>
        </header>

        <div class="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-8 sm:py-6">
          <p v-if="store.loadingArticle" class="text-sm text-muted">Загрузка статьи…</p>
          <template v-else-if="store.current">
            <KbRichEditor v-if="editing" v-model="draftHtml" />
            <article
              v-else
              class="kb-prose mx-auto max-w-3xl"
              v-html="store.current.bodyHtml || '<p>Пустая статья</p>'"
            />
          </template>
        </div>
      </template>
    </section>
  </div>
</template>

<style>
.kb-prose {
  font-size: 0.975rem;
  line-height: 1.7;
  color: var(--color-ink);
}
.kb-prose h2 {
  margin: 1.4em 0 0.5em;
  font-size: 1.35rem;
  font-weight: 650;
  letter-spacing: -0.02em;
}
.kb-prose h3 {
  margin: 1.2em 0 0.4em;
  font-size: 1.1rem;
  font-weight: 600;
}
.kb-prose p {
  margin: 0.65em 0;
}
.kb-prose ul,
.kb-prose ol {
  margin: 0.65em 0;
  padding-left: 1.35rem;
}
.kb-prose ul {
  list-style: disc;
}
.kb-prose ol {
  list-style: decimal;
}
.kb-prose blockquote {
  margin: 0.9em 0;
  border-left: 3px solid var(--color-brand);
  padding-left: 0.9rem;
  color: var(--color-muted);
  font-style: italic;
}
.kb-prose a,
.kb-tiptap-body a.kb-link {
  color: var(--color-brand);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.kb-tiptap-body {
  font-size: 0.975rem;
  line-height: 1.7;
  color: var(--color-ink);
}
.kb-tiptap-body h2 {
  margin: 1.2em 0 0.45em;
  font-size: 1.3rem;
  font-weight: 650;
}
.kb-tiptap-body h3 {
  margin: 1em 0 0.35em;
  font-size: 1.08rem;
  font-weight: 600;
}
.kb-tiptap-body ul {
  list-style: disc;
  padding-left: 1.35rem;
}
.kb-tiptap-body ol {
  list-style: decimal;
  padding-left: 1.35rem;
}
.kb-tiptap-body blockquote {
  border-left: 3px solid var(--color-brand);
  padding-left: 0.85rem;
  color: var(--color-muted);
  font-style: italic;
}
</style>
