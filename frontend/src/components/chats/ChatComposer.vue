<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  FileText,
  Film,
  Image as ImageIcon,
  Mic,
  NotebookPen,
  Paperclip,
  SendHorizontal,
  TextQuote,
  X,
} from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import type { Template, TemplateGroup } from '@/types'

const props = defineProps<{
  modelValue: string
  files: File[]
  sending?: boolean
  noteMode?: boolean
  notesOnly?: boolean
  templates?: Template[]
  templateGroups?: TemplateGroup[]
  replyingTo?: {
    id: string
    text: string
    direction: 'in' | 'out'
    operatorName?: string | null
  } | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:noteMode': [value: boolean]
  addFiles: [files: FileList | File[]]
  removeFile: [index: number]
  applyTemplate: [template: Template]
  clearReply: []
  send: []
}>()

const attachOpen = ref(false)
const templatesOpen = ref(false)
const dragOver = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const textareaEl = ref<HTMLTextAreaElement | null>(null)
const accept = ref('image/*,video/*,audio/*,.pdf,.doc,.docx,.xls,.xlsx,.txt,.zip')
const dragDepth = ref(0)

const canSend = computed(
  () =>
    (props.modelValue.trim().length > 0 || (!props.noteMode && props.files.length > 0)) &&
    !props.sending,
)

const groupedTemplates = computed(() => {
  if (props.templateGroups?.length) return props.templateGroups
  if (!props.templates?.length) return []
  return [
    {
      categoryId: null,
      categoryName: 'Шаблоны',
      templates: props.templates,
    },
  ]
})

const hasTemplates = computed(() =>
  groupedTemplates.value.some((g) => g.templates.length > 0),
)

const attachTypes = [
  {
    id: 'image',
    title: 'Фото',
    hint: 'JPG, PNG, WEBP, GIF',
    accept: 'image/*',
    icon: ImageIcon,
  },
  {
    id: 'video',
    title: 'Видео',
    hint: 'MP4, MOV, WEBM',
    accept: 'video/*',
    icon: Film,
  },
  {
    id: 'document',
    title: 'Документ',
    hint: 'PDF, DOC, XLS, ZIP…',
    accept: '.pdf,.doc,.docx,.xls,.xlsx,.txt,.zip,application/*',
    icon: FileText,
  },
  {
    id: 'audio',
    title: 'Аудио',
    hint: 'MP3, WAV, M4A',
    accept: 'audio/*',
    icon: Mic,
  },
] as const

function openPicker(typeAccept: string) {
  accept.value = typeAccept
  attachOpen.value = false
  requestAnimationFrame(() => fileInput.value?.click())
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) emit('addFiles', input.files)
  input.value = ''
}

function onDragEnter(event: DragEvent) {
  if (props.noteMode) return
  event.preventDefault()
  dragDepth.value += 1
  dragOver.value = true
}

function onDragLeave(event: DragEvent) {
  if (props.noteMode) return
  event.preventDefault()
  dragDepth.value = Math.max(0, dragDepth.value - 1)
  if (dragDepth.value === 0) dragOver.value = false
}

function onDragOver(event: DragEvent) {
  if (props.noteMode) return
  event.preventDefault()
}

function onDrop(event: DragEvent) {
  if (props.noteMode) return
  event.preventDefault()
  dragDepth.value = 0
  dragOver.value = false
  const list = event.dataTransfer?.files
  if (list?.length) emit('addFiles', list)
}

function fileKindLabel(file: File) {
  if (file.type.startsWith('image/')) return 'Фото'
  if (file.type.startsWith('video/')) return 'Видео'
  if (file.type.startsWith('audio/')) return 'Аудио'
  return 'Файл'
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

function resizeTextarea() {
  const el = textareaEl.value
  if (!el) return
  el.style.height = 'auto'
  if (!props.modelValue) {
    el.style.height = ''
    return
  }
  el.style.height = `${Math.min(el.scrollHeight, 128)}px`
}

function onInput(event: Event) {
  const el = event.target as HTMLTextAreaElement
  emit('update:modelValue', el.value)
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 128)}px`
}

watch(
  () => props.modelValue,
  async (value) => {
    if (value) return
    await nextTick()
    resizeTextarea()
  },
)
</script>

<template>
  <div
    class="relative border-t border-line bg-panel px-4 py-3"
    @dragenter="onDragEnter"
    @dragleave="onDragLeave"
    @dragover="onDragOver"
    @drop="onDrop"
  >
    <div
      v-if="dragOver"
      class="pointer-events-none absolute inset-3 z-10 flex items-center justify-center rounded-2xl border-2 border-dashed border-brand bg-brand-soft/90"
    >
      <div class="text-center">
        <p class="text-sm font-semibold text-brand">Отпустите файлы здесь</p>
        <p class="mt-0.5 text-xs text-muted">фото, видео, документы — до 5 за раз</p>
      </div>
    </div>

    <div
      v-if="noteMode"
      class="mb-2.5 flex items-center gap-2 rounded-xl border border-bubble-note-border bg-bubble-note px-3 py-2 text-xs text-bubble-note-ink"
    >
      <NotebookPen class="size-3.5 shrink-0" />
      <span class="min-w-0 flex-1 font-medium">
        Заметка для менеджеров — клиент её не увидит
      </span>
      <button
        v-if="!notesOnly"
        type="button"
        class="rounded-md px-1.5 py-0.5 font-semibold transition hover:bg-black/5"
        @click="emit('update:noteMode', false)"
      >
        Отмена
      </button>
    </div>

    <div
      v-if="replyingTo"
      class="mb-2.5 flex items-start gap-2 rounded-xl border border-brand/30 bg-brand-soft/60 px-3 py-2"
    >
      <div class="min-w-0 flex-1 border-l-2 border-brand pl-2.5">
        <div class="text-[11px] font-semibold text-brand">
          Ответ ·
          {{
            replyingTo.direction === 'out'
              ? replyingTo.operatorName || 'Вы'
              : 'Клиент'
          }}
        </div>
        <div class="mt-0.5 line-clamp-2 text-xs text-muted">
          {{ replyingTo.text || 'Вложение' }}
        </div>
      </div>
      <button
        type="button"
        class="rounded-md p-1 text-muted transition hover:bg-panel hover:text-danger"
        title="Отменить ответ"
        @click="emit('clearReply')"
      >
        <X class="size-3.5" />
      </button>
    </div>

    <div v-if="files.length && !noteMode" class="mb-2.5 flex gap-2 overflow-x-auto pb-0.5">
      <div
        v-for="(file, idx) in files"
        :key="`${file.name}-${file.size}-${idx}`"
        class="group flex min-w-0 shrink-0 items-center gap-2 rounded-xl border border-line bg-surface px-2.5 py-1.5"
      >
        <div
          class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand"
        >
          <ImageIcon v-if="file.type.startsWith('image/')" class="size-3.5" />
          <Film v-else-if="file.type.startsWith('video/')" class="size-3.5" />
          <Mic v-else-if="file.type.startsWith('audio/')" class="size-3.5" />
          <FileText v-else class="size-3.5" />
        </div>
        <div class="min-w-0">
          <div class="max-w-[140px] truncate text-xs font-medium">{{ file.name }}</div>
          <div class="text-[10px] text-muted">
            {{ fileKindLabel(file) }} · {{ formatSize(file.size) }}
          </div>
        </div>
        <button
          type="button"
          class="rounded-md p-1 text-muted opacity-70 transition hover:bg-panel hover:text-danger hover:opacity-100"
          @click="emit('removeFile', idx)"
        >
          <X class="size-3.5" />
        </button>
      </div>
    </div>

    <form class="flex items-end gap-2" @submit.prevent="emit('send')">
      <input
        ref="fileInput"
        type="file"
        class="hidden"
        multiple
        :accept="accept"
        @change="onFileChange"
      />

      <button
        v-if="!notesOnly"
        type="button"
        class="flex size-11 shrink-0 items-center justify-center rounded-xl border transition"
        :class="
          noteMode
            ? 'border-bubble-note-border bg-bubble-note text-bubble-note-ink'
            : 'border-line bg-surface text-muted hover:border-brand/40 hover:bg-brand-soft hover:text-brand'
        "
        :title="noteMode ? 'Режим заметки' : 'Внутренняя заметка'"
        @click="emit('update:noteMode', !noteMode)"
      >
        <NotebookPen class="size-4" />
      </button>

      <button
        v-if="!notesOnly"
        type="button"
        class="flex size-11 shrink-0 items-center justify-center rounded-xl border border-line bg-surface text-muted transition hover:border-brand/40 hover:bg-brand-soft hover:text-brand disabled:cursor-not-allowed disabled:opacity-40"
        title="Шаблон"
        :disabled="noteMode"
        @click="templatesOpen = true"
      >
        <TextQuote class="size-4" />
      </button>

      <button
        v-if="!notesOnly"
        type="button"
        class="flex size-11 shrink-0 items-center justify-center rounded-xl border border-line bg-surface text-muted transition hover:border-brand/40 hover:bg-brand-soft hover:text-brand disabled:cursor-not-allowed disabled:opacity-40"
        title="Прикрепить"
        :disabled="noteMode"
        @click="attachOpen = true"
      >
        <Paperclip class="size-4" />
      </button>

      <div
        class="flex min-h-11 min-w-0 flex-1 items-end rounded-2xl border px-3.5 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.6)] transition focus-within:ring-2"
        :class="
          noteMode
            ? 'border-bubble-note-border bg-bubble-note focus-within:ring-bubble-note-border/40'
            : 'border-line bg-surface focus-within:border-brand/50 focus-within:ring-brand/20'
        "
      >
        <textarea
          ref="textareaEl"
          :value="modelValue"
          rows="1"
          :placeholder="noteMode ? 'Заметка для команды…' : 'Написать сообщение… или перетащите файл'"
          class="max-h-32 min-h-[28px] w-full resize-none bg-transparent py-1 text-sm leading-6 outline-none"
          :class="noteMode ? 'text-bubble-note-ink placeholder:text-bubble-note-ink/50' : 'text-ink placeholder:text-muted/80'"
          @input="onInput"
          @keydown.enter.exact.prevent="canSend && emit('send')"
        />
      </div>

      <button
        type="submit"
        class="flex size-11 shrink-0 items-center justify-center rounded-xl text-white transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-40"
        :class="noteMode ? 'bg-bubble-note-ink' : 'bg-brand'"
        :disabled="!canSend"
        :title="noteMode ? 'Сохранить заметку' : 'Отправить'"
      >
        <span v-if="sending" class="text-xs font-semibold">…</span>
        <NotebookPen v-else-if="noteMode" class="size-4" />
        <SendHorizontal v-else class="size-4" />
      </button>
    </form>

    <Modal v-if="templatesOpen" title="Шаблоны" @close="templatesOpen = false">
      <p v-if="!hasTemplates" class="text-sm text-muted">
        Нет шаблонов для этого канала. Создайте в разделе «Шаблоны».
      </p>
      <div v-else class="max-h-[60vh] space-y-4 overflow-y-auto">
        <section v-for="group in groupedTemplates" :key="group.categoryId ?? 'none'">
          <h3 class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
            {{ group.categoryName }}
          </h3>
          <div class="space-y-2">
            <button
              v-for="t in group.templates"
              :key="t.id"
              type="button"
              class="w-full rounded-xl border border-line bg-surface px-3.5 py-3 text-left transition hover:border-brand/40 hover:bg-brand-soft/50"
              @click="
                emit('applyTemplate', t);
                templatesOpen = false
              "
            >
              <div class="text-sm font-semibold">{{ t.name }}</div>
              <div class="mt-1 line-clamp-2 text-xs text-muted">{{ t.body }}</div>
            </button>
          </div>
        </section>
      </div>
    </Modal>

    <Modal v-if="attachOpen" title="Прикрепить файл" @close="attachOpen = false">
      <p class="mb-4 text-sm text-muted">Выберите тип вложения — откроется выбор файлов.</p>
      <div class="grid grid-cols-2 gap-3">
        <button
          v-for="item in attachTypes"
          :key="item.id"
          type="button"
          class="flex flex-col items-start gap-3 rounded-2xl border border-line bg-surface px-4 py-4 text-left transition hover:border-brand/50 hover:bg-brand-soft/60"
          @click="openPicker(item.accept)"
        >
          <div class="flex size-10 items-center justify-center rounded-xl bg-brand-soft text-brand">
            <component :is="item.icon" class="size-5" />
          </div>
          <div>
            <div class="text-sm font-semibold">{{ item.title }}</div>
            <div class="mt-0.5 text-xs text-muted">{{ item.hint }}</div>
          </div>
        </button>
      </div>
    </Modal>
  </div>
</template>
