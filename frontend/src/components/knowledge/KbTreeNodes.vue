<script setup lang="ts">
import {
  ChevronDown,
  ChevronRight,
  FileText,
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
}>()
</script>

<template>
  <ul class="space-y-0.5" :style="{ paddingLeft: depth ? '0.65rem' : '0' }">
    <li v-for="node in nodes" :key="node.id">
      <div class="group relative flex items-center gap-0.5 rounded-lg hover:bg-surface">
        <button
          type="button"
          class="flex size-6 shrink-0 items-center justify-center rounded text-muted"
          @click="emit('toggle', node.id)"
        >
          <ChevronDown v-if="expanded.has(node.id)" class="size-3.5" />
          <ChevronRight v-else class="size-3.5" />
        </button>
        <button
          type="button"
          class="min-w-0 flex-1 truncate py-1.5 pr-1 text-left text-[13px] font-medium text-ink"
          @click="emit('toggle', node.id)"
        >
          {{ node.title }}
          <span class="ml-1 text-[10px] font-normal text-muted">{{ folderArticleCount(node) }}</span>
        </button>
        <div
          v-if="canWrite"
          class="relative shrink-0 pr-1 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100"
        >
          <button
            type="button"
            class="flex size-6 items-center justify-center rounded text-muted hover:bg-line/60"
            @click.stop="emit('menu', menuFolderId === node.id ? null : node.id)"
          >
            <MoreHorizontal class="size-3.5" />
          </button>
          <div
            v-if="menuFolderId === node.id"
            class="absolute right-0 top-full z-20 mt-1 w-44 overflow-hidden rounded-xl border border-line bg-panel py-1 shadow-lg"
          >
            <button
              type="button"
              class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-surface"
              @click="emit('new-article', node.id)"
            >
              <Plus class="size-3.5" /> Статья
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-surface"
              @click="emit('new-folder', node.id)"
            >
              <FolderPlus class="size-3.5" /> Подраздел
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-surface"
              @click="emit('rename', node)"
            >
              <Pencil class="size-3.5" /> Переименовать
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-danger hover:bg-danger-soft"
              @click="emit('delete', node)"
            >
              <Trash2 class="size-3.5" /> Удалить
            </button>
          </div>
        </div>
      </div>
      <template v-if="expanded.has(node.id)">
        <ul class="mb-1 ml-3 space-y-0.5 border-l border-line/80 pl-2">
          <li v-for="art in node.articles" :key="'a' + art.id">
            <button
              type="button"
              class="flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-[13px] transition"
              :class="
                activeId === art.id
                  ? 'bg-brand-soft font-medium text-brand'
                  : 'text-ink/80 hover:bg-surface'
              "
              @click="emit('open', art.id)"
            >
              <FileText class="size-3.5 shrink-0 opacity-50" />
              <span class="truncate">{{ art.title }}</span>
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
          :depth="(depth ?? 0) + 1"
          @toggle="emit('toggle', $event)"
          @open="emit('open', $event)"
          @menu="emit('menu', $event)"
          @new-folder="emit('new-folder', $event)"
          @new-article="emit('new-article', $event)"
          @rename="emit('rename', $event)"
          @delete="emit('delete', $event)"
        />
      </template>
    </li>
  </ul>
</template>

<script lang="ts">
export default {
  name: 'KbTreeNodes',
}
</script>
