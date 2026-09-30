<script setup lang="ts">
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderPlus,
  MoreHorizontal,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-vue-next'
import type { KbFolderNode } from '@/types'

defineProps<{
  nodes: KbFolderNode[]
  expanded: Set<number>
  activeId: number | null
  canWrite: boolean
  menuFolderId: number | null
  folderArticleCount: (n: KbFolderNode) => number
  canMoveUp: (id: number) => boolean
  canMoveDown: (id: number) => boolean
  depth?: number
}>()

const emit = defineEmits<{
  toggle: [id: number]
  open: [id: number]
  menu: [id: number | null]
  'new-folder': [parentId: number]
  'new-article': [folderId: number]
  rename: [folder: KbFolderNode]
  delete: [folder: KbFolderNode]
  'move-up': [id: number]
  'move-down': [id: number]
}>()
</script>

<template>
  <ul class="space-y-0.5" :style="{ paddingLeft: depth ? '0.5rem' : '0' }">
    <li v-for="node in nodes" :key="node.id">
      <div
        class="group relative flex items-center gap-1 rounded-xl px-1.5 py-0.5 hover:bg-surface"
        :class="menuFolderId === node.id ? 'bg-surface' : ''"
      >
        <button
          type="button"
          class="flex size-7 shrink-0 items-center justify-center rounded-lg text-muted"
          @click="emit('toggle', node.id)"
        >
          <ChevronDown v-if="expanded.has(node.id)" class="size-3.5" />
          <ChevronRight v-else class="size-3.5" />
        </button>
        <button
          type="button"
          class="flex min-w-0 flex-1 items-center gap-2 py-1.5 text-left"
          @click="emit('toggle', node.id)"
        >
          <Folder class="size-4 shrink-0 text-brand/80" />
          <span class="min-w-0 flex-1 truncate text-[13px] font-semibold text-ink">{{
            node.title
          }}</span>
          <span
            class="shrink-0 rounded-md bg-surface px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-muted"
            >{{ folderArticleCount(node) }}</span
          >
        </button>
        <div v-if="canWrite" class="relative shrink-0">
          <button
            type="button"
            class="flex size-7 items-center justify-center rounded-lg text-muted opacity-70 transition hover:bg-line/50 hover:opacity-100 md:opacity-0 md:group-hover:opacity-100"
            :class="menuFolderId === node.id ? 'bg-line/50 opacity-100 md:opacity-100' : ''"
            aria-label="Действия раздела"
            @click.stop="emit('menu', menuFolderId === node.id ? null : node.id)"
          >
            <MoreHorizontal class="size-3.5" />
          </button>
          <div
            v-if="menuFolderId === node.id"
            class="absolute right-0 top-full z-30 mt-1 w-48 overflow-hidden rounded-xl border border-line bg-panel py-1 shadow-lg"
            @click.stop
          >
            <button
              type="button"
              class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-surface"
              @click="emit('new-article', node.id)"
            >
              <Plus class="size-3.5" /> Новая статья
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-surface"
              @click="emit('new-folder', node.id)"
            >
              <FolderPlus class="size-3.5" /> Подраздел
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-surface"
              @click="emit('rename', node)"
            >
              <Pencil class="size-3.5" /> Переименовать
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-surface disabled:opacity-40"
              :disabled="!canMoveUp(node.id)"
              @click="emit('move-up', node.id)"
            >
              <ArrowUp class="size-3.5" /> Выше
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-surface disabled:opacity-40"
              :disabled="!canMoveDown(node.id)"
              @click="emit('move-down', node.id)"
            >
              <ArrowDown class="size-3.5" /> Ниже
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-danger hover:bg-danger-soft"
              @click="emit('delete', node)"
            >
              <Trash2 class="size-3.5" /> Удалить
            </button>
          </div>
        </div>
      </div>
      <template v-if="expanded.has(node.id)">
        <ul class="mb-1 ml-4 space-y-0.5 border-l border-line/70 pl-2">
          <li v-for="art in node.articles" :key="'a' + art.id">
            <button
              type="button"
              class="relative flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] transition"
              :class="
                activeId === art.id
                  ? 'bg-brand-soft font-semibold text-brand'
                  : 'text-ink/80 hover:bg-surface'
              "
              @click="emit('open', art.id)"
            >
              <span
                v-if="activeId === art.id"
                class="absolute bottom-1.5 left-0 top-1.5 w-[3px] rounded-r-full bg-brand"
              />
              <FileText class="size-3.5 shrink-0 opacity-55" />
              <span class="min-w-0 flex-1 truncate">{{ art.title }}</span>
              <span
                v-if="!art.isPublished"
                class="shrink-0 rounded bg-warn/15 px-1 py-0.5 text-[9px] font-semibold uppercase text-warn"
                >черн.</span
              >
            </button>
          </li>
        </ul>
        <KbTreeNodes
          v-if="node.children.length"
          :nodes="node.children"
          :expanded="expanded"
          :active-id="activeId"
          :can-write="canWrite"
          :menu-folder-id="menuFolderId"
          :folder-article-count="folderArticleCount"
          :can-move-up="canMoveUp"
          :can-move-down="canMoveDown"
          :depth="(depth ?? 0) + 1"
          @toggle="emit('toggle', $event)"
          @open="emit('open', $event)"
          @menu="emit('menu', $event)"
          @new-folder="emit('new-folder', $event)"
          @new-article="emit('new-article', $event)"
          @rename="emit('rename', $event)"
          @delete="emit('delete', $event)"
          @move-up="emit('move-up', $event)"
          @move-down="emit('move-down', $event)"
        />
      </template>
    </li>
  </ul>
</template>

<script lang="ts">
export default { name: 'KbTreeNodes' }
</script>
